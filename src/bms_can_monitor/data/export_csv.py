"""Excel-friendly CSV exports from recorded SQLite sessions."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .pipeline import DataPipeline
from .recording_reader import (
    RecordingReadError,
    RecordingReader,
    SessionSummary,
)


class ExportError(RuntimeError):
    """Raised when a database or session cannot be exported."""


@dataclass(frozen=True, slots=True)
class ExportedSessionFiles:
    raw_frames: Path
    signals_wide: Path
    events: Path


def list_sessions(database_path: str | Path) -> tuple[SessionSummary, ...]:
    try:
        return RecordingReader(database_path).list_sessions()
    except RecordingReadError as exc:
        raise ExportError(str(exc)) from exc


def export_raw_frames(
    database_path: str | Path,
    output_path: str | Path,
    session_id: int,
) -> Path:
    try:
        reader = RecordingReader(database_path)
        reader.session(session_id)
    except RecordingReadError as exc:
        raise ExportError(str(exc)) from exc

    output = _prepare_output(output_path)
    fieldnames = (
        "timestamp",
        "can_id",
        "is_extended",
        "is_remote",
        "dlc",
        "data",
        "channel",
        "hardware_timestamp",
        "source",
    )
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for frame in reader.iter_frames(session_id):
            writer.writerow(
                {
                    "timestamp": f"{frame.timestamp:.9f}",
                    "can_id": f"0x{frame.can_id:X}",
                    "is_extended": int(frame.is_extended),
                    "is_remote": int(frame.is_remote),
                    "dlc": frame.dlc,
                    "data": frame.data.hex(" ").upper(),
                    "channel": frame.channel,
                    "hardware_timestamp": (
                        ""
                        if frame.hardware_timestamp is None
                        else frame.hardware_timestamp
                    ),
                    "source": _excel_safe(frame.source),
                }
            )
    return output


def export_signals_wide(
    database_path: str | Path,
    output_path: str | Path,
    session_id: int,
    *,
    signal_names: Iterable[str] | None = None,
    forward_fill: bool = True,
    device_address: int = 0,
) -> Path:
    requested = None if signal_names is None else tuple(dict.fromkeys(signal_names))
    try:
        reader = RecordingReader(database_path)
        reader.session(session_id)
    except RecordingReadError as exc:
        raise ExportError(str(exc)) from exc
    names = (
        _discover_signal_names(reader, session_id, device_address)
        if requested is None
        else requested
    )
    selected = set(names)

    output = _prepare_output(output_path)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("timestamp", *names))
        writer.writeheader()
        latest: dict[str, object] = {}
        pending_timestamp: float | None = None
        pending_values: dict[str, object] = {}
        pipeline = DataPipeline()

        def flush_pending() -> None:
            nonlocal latest, pending_timestamp, pending_values
            if pending_timestamp is None or not pending_values:
                return
            current = dict(latest) if forward_fill else {}
            current.update(pending_values)
            writer.writerow(
                {
                    "timestamp": f"{pending_timestamp:.9f}",
                    **{name: current.get(name, "") for name in names},
                }
            )
            if forward_fill:
                latest = current
            pending_values = {}

        for frame in reader.iter_frames(session_id):
            message = pipeline.process_frame(frame)
            if message is None or message.device_address != device_address:
                continue
            updates = {
                signal.name: _export_value(signal.value)
                for signal in message.signals
                if signal.name in selected
            }
            if not updates:
                continue
            if pending_timestamp is not None and frame.timestamp != pending_timestamp:
                flush_pending()
            pending_timestamp = frame.timestamp
            pending_values.update(updates)
        flush_pending()
    return output


def _discover_signal_names(
    reader: RecordingReader,
    session_id: int,
    device_address: int,
) -> tuple[str, ...]:
    pipeline = DataPipeline()
    names: set[str] = set()
    for frame in reader.iter_frames(session_id):
        message = pipeline.process_frame(frame)
        if message is not None and message.device_address == device_address:
            names.update(signal.name for signal in message.signals)
    return tuple(sorted(names))


def _export_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, str):
        return _excel_safe(value)
    if isinstance(value, bool):
        return int(value)
    return _clean_number(float(value))


def export_events(
    database_path: str | Path,
    output_path: str | Path,
    session_id: int,
) -> Path:
    with _connect(database_path) as connection:
        _ensure_session(connection, session_id)
        rows = connection.execute(
            """
            SELECT timestamp, event_type, message, details_json
            FROM events WHERE session_id = ? ORDER BY timestamp, id
            """,
            (session_id,),
        ).fetchall()

    output = _prepare_output(output_path)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("timestamp", "event_type", "message", "details_json"))
        for row in rows:
            writer.writerow(
                (
                    f"{float(row['timestamp']):.9f}",
                    _excel_safe(str(row["event_type"])),
                    _excel_safe(str(row["message"])),
                    _excel_safe(str(row["details_json"])),
                )
            )
    return output


def export_session(
    database_path: str | Path,
    output_directory: str | Path,
    session_id: int,
    *,
    signal_names: Iterable[str] | None = None,
    device_address: int = 0,
) -> ExportedSessionFiles:
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    prefix = f"session_{session_id}"
    return ExportedSessionFiles(
        raw_frames=export_raw_frames(
            database_path, output_directory / f"{prefix}_raw_frames.csv", session_id
        ),
        signals_wide=export_signals_wide(
            database_path,
            output_directory / f"{prefix}_signals_wide.csv",
            session_id,
            signal_names=signal_names,
            device_address=device_address,
        ),
        events=export_events(
            database_path, output_directory / f"{prefix}_events.csv", session_id
        ),
    )


def _connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    if not path.is_file():
        raise ExportError(f"recording database not found: {path}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_session(connection: sqlite3.Connection, session_id: int) -> None:
    exists = connection.execute(
        "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if exists is None:
        raise ExportError(f"session {session_id} does not exist")


def _prepare_output(output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _excel_safe(value: str) -> str:
    if value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
