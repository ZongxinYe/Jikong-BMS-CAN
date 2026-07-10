"""CSV frame loading and timing-aware offline replay."""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Full, Queue
from threading import Event, Thread
from time import monotonic, time
from typing import Iterable

from bms_can_monitor.protocol.models import CanFrame

from .events import CanEventType, EventSink, emit_event

REPLAY_CSV_FIELDS = (
    "timestamp",
    "can_id",
    "is_extended",
    "is_remote",
    "dlc",
    "data",
    "channel",
)


class ReplayFormatError(ValueError):
    """Raised when a replay CSV row cannot be converted to a CAN frame."""


@dataclass(frozen=True, slots=True)
class ReplayStats:
    emitted: int
    dropped: int
    loops_completed: int
    errors: int


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ReplayFormatError(f"invalid boolean value: {value!r}")


def _parse_can_id(value: str | None) -> int:
    text = (value or "").strip()
    if not text:
        raise ReplayFormatError("CAN ID is empty")
    is_prefixed_hex = text.lower().startswith("0x")
    has_hex_letters = any(character in "abcdefABCDEF" for character in text)
    base = 16 if is_prefixed_hex or has_hex_letters else 10
    try:
        return int(text, base)
    except ValueError as exc:
        raise ReplayFormatError(f"invalid CAN ID: {value!r}") from exc


def _parse_data(value: str | None) -> bytes:
    compact = (value or "").replace(" ", "").replace("-", "")
    if compact.lower().startswith("0x"):
        compact = compact[2:]
    if len(compact) % 2:
        raise ReplayFormatError(f"hex payload must contain whole bytes: {value!r}")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ReplayFormatError(f"invalid hex payload: {value!r}") from exc


def load_replay_csv(path: str | Path) -> list[CanFrame]:
    replay_path = Path(path)
    frames: list[CanFrame] = []
    with replay_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "can_id", "data"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ReplayFormatError(
                f"replay CSV is missing columns: {', '.join(sorted(missing))}"
            )
        for line_number, row in enumerate(reader, start=2):
            try:
                payload = _parse_data(row.get("data"))
                is_remote = _parse_bool(row.get("is_remote"))
                dlc_text = (row.get("dlc") or "").strip()
                dlc = int(dlc_text) if dlc_text else len(payload)
                frames.append(
                    CanFrame(
                        can_id=_parse_can_id(row["can_id"]),
                        data=payload,
                        timestamp=float(row["timestamp"]),
                        is_extended=_parse_bool(row.get("is_extended")),
                        is_remote=is_remote,
                        dlc=dlc,
                        channel=int((row.get("channel") or "0").strip()),
                        source="replay_file",
                    )
                )
            except (TypeError, ValueError) as exc:
                if isinstance(exc, ReplayFormatError):
                    error = exc
                else:
                    error = ReplayFormatError(str(exc))
                raise ReplayFormatError(f"line {line_number}: {error}") from exc
    _validate_timestamps(frames)
    return frames


def write_replay_csv(path: str | Path, frames: Iterable[CanFrame]) -> Path:
    replay_path = Path(path)
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    with replay_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPLAY_CSV_FIELDS)
        writer.writeheader()
        for frame in frames:
            writer.writerow(
                {
                    "timestamp": f"{frame.timestamp:.9f}",
                    "can_id": f"0x{frame.can_id:X}",
                    "is_extended": int(frame.is_extended),
                    "is_remote": int(frame.is_remote),
                    "dlc": frame.dlc,
                    "data": frame.data.hex(" ").upper(),
                    "channel": frame.channel,
                }
            )
    return replay_path


def _validate_timestamps(frames: list[CanFrame]) -> None:
    for previous, current in zip(frames, frames[1:]):
        if current.timestamp < previous.timestamp:
            raise ReplayFormatError("replay frame timestamps must be non-decreasing")


class ReplayWorker:
    def __init__(
        self,
        frames: Iterable[CanFrame],
        output_queue: Queue[CanFrame],
        *,
        speed: float = 1.0,
        loop: bool = False,
        event_sink: EventSink | None = None,
        daemon: bool = True,
    ) -> None:
        if speed <= 0:
            raise ValueError("replay speed must be positive")
        self.frames = list(frames)
        _validate_timestamps(self.frames)
        self.output_queue = output_queue
        self.speed = speed
        self.loop = loop
        self._event_sink = event_sink
        self._daemon = daemon
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._emitted = 0
        self._dropped = 0
        self._loops_completed = 0
        self._errors = 0

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        output_queue: Queue[CanFrame],
        **kwargs: object,
    ) -> ReplayWorker:
        return cls(load_replay_csv(path), output_queue, **kwargs)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def stats(self) -> ReplayStats:
        return ReplayStats(
            emitted=self._emitted,
            dropped=self._dropped,
            loops_completed=self._loops_completed,
            errors=self._errors,
        )

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            name="can-replay-worker",
            daemon=self._daemon,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        emit_event(
            self._event_sink,
            CanEventType.REPLAY_STARTED,
            "CAN replay started",
            frame_count=len(self.frames),
            speed=self.speed,
            loop=self.loop,
        )
        try:
            if not self.frames:
                emit_event(
                    self._event_sink,
                    CanEventType.REPLAY_FINISHED,
                    "CAN replay finished",
                    stats=self.stats,
                )
                return
            while not self._stop_event.is_set():
                if not self._play_once():
                    return
                self._loops_completed += 1
                if not self.loop:
                    emit_event(
                        self._event_sink,
                        CanEventType.REPLAY_FINISHED,
                        "CAN replay finished",
                        stats=self.stats,
                    )
                    return
        except Exception as exc:
            self._errors += 1
            emit_event(
                self._event_sink,
                CanEventType.REPLAY_ERROR,
                f"CAN replay failed: {exc}",
                error=repr(exc),
            )
        finally:
            if self._stop_event.is_set():
                emit_event(
                    self._event_sink,
                    CanEventType.REPLAY_STOPPED,
                    "CAN replay stopped",
                    stats=self.stats,
                )

    def _play_once(self) -> bool:
        first_timestamp = self.frames[0].timestamp
        started_monotonic = monotonic()
        started_timestamp = time()
        for source_frame in self.frames:
            offset = (source_frame.timestamp - first_timestamp) / self.speed
            delay = started_monotonic + offset - monotonic()
            if delay > 0 and self._stop_event.wait(delay):
                return False
            if self._stop_event.is_set():
                return False
            frame = replace(
                source_frame,
                timestamp=started_timestamp + offset,
                source="replay",
            )
            try:
                self.output_queue.put_nowait(frame)
                self._emitted += 1
            except Full:
                self._dropped += 1
                emit_event(
                    self._event_sink,
                    CanEventType.RX_QUEUE_OVERFLOW,
                    "Dropped replay CAN frame because output queue is full",
                    can_id=frame.can_id,
                )
        return True
