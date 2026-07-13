"""Background SQLite recorder for raw CAN frames and operational events."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
from time import monotonic, time
from typing import Iterable, Mapping

from bms_can_monitor.canio.events import CanEvent
from bms_can_monitor.protocol.models import CanFrame, DecodedMessage

SCHEMA_VERSION = 2
STORAGE_MODE_RAW_ONLY = "raw_only"
STORAGE_MODE_LEGACY_SIGNALS = "legacy_signals"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    ended_at REAL,
    device_type INTEGER NOT NULL,
    device_index INTEGER NOT NULL,
    channel INTEGER NOT NULL,
    bitrate INTEGER NOT NULL,
    device_address INTEGER NOT NULL,
    protocol_version TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    storage_mode TEXT NOT NULL DEFAULT 'raw_only',
    detected_addresses_json TEXT NOT NULL DEFAULT '[]',
    dbc_sha256 TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS raw_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp REAL NOT NULL,
    can_id INTEGER NOT NULL,
    is_extended INTEGER NOT NULL,
    is_remote INTEGER NOT NULL,
    dlc INTEGER NOT NULL,
    data BLOB NOT NULL,
    channel INTEGER NOT NULL,
    hardware_timestamp INTEGER,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp REAL NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_raw_frames_session_time
    ON raw_frames(session_id, timestamp, id);
CREATE INDEX IF NOT EXISTS idx_events_session_time
    ON events(session_id, timestamp, id);
"""


class RecorderError(RuntimeError):
    """Base class for recorder failures."""


class RecorderQueueFull(RecorderError):
    """Raised when recording cannot keep up with incoming data."""


class RecorderWriteError(RecorderError):
    """Raised when the background SQLite writer failed."""


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    started_at: float = 0.0
    device_type: int = 4
    device_index: int = 0
    channel: int = 0
    bitrate: int = 250_000
    device_address: int = 0
    protocol_version: str = "Jikong BMS CAN V2.1"
    note: str = ""
    storage_mode: str = STORAGE_MODE_RAW_ONLY
    detected_addresses: tuple[int, ...] = ()
    dbc_sha256: str = ""

    def __post_init__(self) -> None:
        if self.storage_mode != STORAGE_MODE_RAW_ONLY:
            raise ValueError("new recorder sessions must use raw_only storage")
        addresses = tuple(sorted({int(value) for value in self.detected_addresses}))
        if any(not 0 <= value <= 0x0B for value in addresses):
            raise ValueError("detected BMS addresses must be 0..11")
        object.__setattr__(self, "detected_addresses", addresses)
        if self.dbc_sha256 and (
            len(self.dbc_sha256) != 64
            or any(
                character not in "0123456789abcdefABCDEF"
                for character in self.dbc_sha256
            )
        ):
            raise ValueError("DBC SHA-256 must contain 64 hexadecimal characters")

    def with_start_time(self) -> SessionMetadata:
        if self.started_at > 0:
            return self
        return SessionMetadata(
            started_at=time(),
            device_type=self.device_type,
            device_index=self.device_index,
            channel=self.channel,
            bitrate=self.bitrate,
            device_address=self.device_address,
            protocol_version=self.protocol_version,
            note=self.note,
            storage_mode=self.storage_mode,
            detected_addresses=self.detected_addresses,
            dbc_sha256=self.dbc_sha256,
        )


@dataclass(frozen=True, slots=True)
class RecorderStats:
    frames_written: int
    signals_written: int
    events_written: int
    dropped_items: int
    queued_items: int


@dataclass(frozen=True, slots=True)
class WalCheckpointResult:
    busy: int = 0
    log_pages: int = 0
    checkpointed_pages: int = 0
    error: str = ""

    @property
    def complete(self) -> bool:
        return not self.error and self.busy == 0


@dataclass(frozen=True, slots=True)
class RecorderStopResult:
    session_id: int
    ended_at: float
    stats: RecorderStats
    checkpoint: WalCheckpointResult

    @property
    def portable(self) -> bool:
        """Whether the main SQLite file contains the complete stopped session."""

        return self.checkpoint.complete


@dataclass(frozen=True, slots=True)
class _FrameItem:
    values: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _EventItem:
    values: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _FlushItem:
    completed: Event


@dataclass(frozen=True, slots=True)
class _StopItem:
    completed: Event


RecordItem = _FrameItem | _EventItem | _FlushItem | _StopItem


class SessionRecorder:
    def __init__(
        self,
        database_path: str | Path,
        *,
        batch_size: int = 500,
        flush_interval: float = 0.25,
        queue_capacity: int = 100_000,
    ) -> None:
        if batch_size < 1:
            raise ValueError("recorder batch size must be positive")
        if flush_interval <= 0:
            raise ValueError("recorder flush interval must be positive")
        if queue_capacity < 1:
            raise ValueError("recorder queue capacity must be positive")
        self.database_path = Path(database_path)
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue_capacity = queue_capacity
        self._queue: Queue[RecordItem] = Queue(maxsize=queue_capacity)
        self._thread: Thread | None = None
        self._startup = Event()
        self._state_lock = RLock()
        self._running = False
        self._session_id: int | None = None
        self._writer_error: BaseException | None = None
        self._frames_written = 0
        self._events_written = 0
        self._dropped_items = 0
        self._last_stop_result: RecorderStopResult | None = None

    @property
    def session_id(self) -> int | None:
        return self._session_id

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def stats(self) -> RecorderStats:
        with self._state_lock:
            return RecorderStats(
                frames_written=self._frames_written,
                signals_written=0,
                events_written=self._events_written,
                dropped_items=self._dropped_items,
                queued_items=self._queue.qsize(),
            )

    @property
    def last_stop_result(self) -> RecorderStopResult | None:
        return self._last_stop_result

    def start(self, metadata: SessionMetadata | None = None) -> int:
        with self._state_lock:
            if self._running or self._session_id is not None:
                raise RecorderError("this recorder already owns a session")
            session = (metadata or SessionMetadata()).with_start_time()
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                initialize_schema(connection)
                cursor = connection.execute(
                    """
                    INSERT INTO sessions (
                        started_at, device_type, device_index, channel, bitrate,
                        device_address, protocol_version, note, storage_mode,
                        detected_addresses_json, dbc_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.started_at,
                        session.device_type,
                        session.device_index,
                        session.channel,
                        session.bitrate,
                        session.device_address,
                        session.protocol_version,
                        session.note,
                        session.storage_mode,
                        json.dumps(session.detected_addresses),
                        session.dbc_sha256.lower(),
                    ),
                )
                connection.commit()
                self._session_id = int(cursor.lastrowid)

            self._running = True
            self._startup.clear()
            self._thread = Thread(
                target=self._writer_loop,
                name="sqlite-session-recorder",
                daemon=True,
            )
            self._thread.start()

        if not self._startup.wait(5.0):
            raise RecorderWriteError("SQLite writer did not start within 5 seconds")
        self._raise_writer_error()
        return self._require_session_id()

    def record_frame(self, frame: CanFrame) -> None:
        session_id = self._require_ready()
        self._enqueue(
            _FrameItem(
                (
                    session_id,
                    frame.timestamp,
                    frame.can_id,
                    int(frame.is_extended),
                    int(frame.is_remote),
                    frame.dlc,
                    sqlite3.Binary(frame.data),
                    frame.channel,
                    frame.hardware_timestamp,
                    frame.source,
                )
            )
        )

    def record_message(self, message: DecodedMessage) -> None:
        """Compatibility no-op; schema v2 derives signals from raw frames."""

        del message
        self._require_ready()

    def record_event(self, event: CanEvent) -> None:
        event_type = (
            event.event_type.value
            if isinstance(event.event_type, Enum)
            else str(event.event_type)
        )
        self.record_event_data(
            event_type,
            event.message,
            timestamp=event.timestamp,
            details=event.details,
        )

    def record_event_data(
        self,
        event_type: str,
        message: str,
        *,
        timestamp: float | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        session_id = self._require_ready()
        details_json = json.dumps(
            details or {},
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        )
        self._enqueue(
            _EventItem(
                (
                    session_id,
                    time() if timestamp is None else timestamp,
                    str(event_type),
                    str(message),
                    details_json,
                )
            )
        )

    def _enqueue(self, item: RecordItem) -> None:
        self._raise_writer_error()
        try:
            self._queue.put_nowait(item)
        except Full as exc:
            with self._state_lock:
                self._dropped_items += 1
            raise RecorderQueueFull(
                f"recorder queue reached capacity {self.queue_capacity}"
            ) from exc

    def flush(self, timeout: float = 5.0) -> None:
        self._require_ready()
        completed = Event()
        try:
            self._queue.put(_FlushItem(completed), timeout=timeout)
        except Full as exc:
            raise RecorderQueueFull("could not enqueue recorder flush") from exc
        if not completed.wait(timeout):
            self._raise_writer_error()
            raise RecorderWriteError("recorder flush timed out")
        self._raise_writer_error()

    def stop(
        self,
        *,
        ended_at: float | None = None,
        detected_addresses: Iterable[int] | None = None,
        timeout: float = 10.0,
    ) -> RecorderStopResult | None:
        addresses_json: str | None = None
        if detected_addresses is not None:
            addresses = tuple(sorted({int(value) for value in detected_addresses}))
            if any(not 0 <= value <= 0x0B for value in addresses):
                raise ValueError("detected BMS addresses must be 0..11")
            addresses_json = json.dumps(addresses)
        with self._state_lock:
            if not self._running:
                self._raise_writer_error()
                return self._last_stop_result
            thread = self._thread

        if thread is not None and thread.is_alive():
            completed = Event()
            try:
                self._queue.put(_StopItem(completed), timeout=timeout)
            except Full as exc:
                raise RecorderQueueFull("could not enqueue recorder stop") from exc
            if not completed.wait(timeout):
                self._raise_writer_error()
                raise RecorderWriteError("recorder stop timed out")
            thread.join(timeout)

        session_id = self._require_session_id()
        ended_at_value = time() if ended_at is None else ended_at
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET ended_at = ?,
                    detected_addresses_json = COALESCE(?, detected_addresses_json)
                WHERE id = ?
                """,
                (
                    ended_at_value,
                    addresses_json,
                    session_id,
                ),
            )
            connection.commit()
            checkpoint = self._checkpoint_wal(connection)
        with self._state_lock:
            self._running = False
            self._last_stop_result = RecorderStopResult(
                session_id=session_id,
                ended_at=ended_at_value,
                stats=self.stats,
                checkpoint=checkpoint,
            )
        self._raise_writer_error()
        return self._last_stop_result

    close = stop

    def _writer_loop(self) -> None:
        connection: sqlite3.Connection | None = None
        pending_rows = 0
        deadline = monotonic() + self.flush_interval
        try:
            connection = self._connect()
            self._startup.set()
            while True:
                try:
                    item = self._queue.get(timeout=max(0.0, deadline - monotonic()))
                except Empty:
                    if pending_rows:
                        connection.commit()
                        pending_rows = 0
                    deadline = monotonic() + self.flush_interval
                    continue

                if isinstance(item, _FlushItem):
                    connection.commit()
                    pending_rows = 0
                    deadline = monotonic() + self.flush_interval
                    item.completed.set()
                    continue
                if isinstance(item, _StopItem):
                    connection.commit()
                    item.completed.set()
                    return

                written = self._write_item(connection, item)
                pending_rows += written
                if pending_rows >= self.batch_size:
                    connection.commit()
                    pending_rows = 0
                    deadline = monotonic() + self.flush_interval
        except BaseException as exc:
            with self._state_lock:
                self._writer_error = exc
            self._release_waiters()
            self._startup.set()
        finally:
            if connection is not None:
                try:
                    connection.commit()
                finally:
                    connection.close()

    def _write_item(self, connection: sqlite3.Connection, item: RecordItem) -> int:
        if isinstance(item, _FrameItem):
            connection.execute(
                """
                INSERT INTO raw_frames (
                    session_id, timestamp, can_id, is_extended, is_remote, dlc,
                    data, channel, hardware_timestamp, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                item.values,
            )
            with self._state_lock:
                self._frames_written += 1
            return 1
        if isinstance(item, _EventItem):
            connection.execute(
                """
                INSERT INTO events (
                    session_id, timestamp, event_type, message, details_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                item.values,
            )
            with self._state_lock:
                self._events_written += 1
            return 1
        raise TypeError(f"unsupported recorder item: {type(item).__name__}")

    def _release_waiters(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                return
            if isinstance(item, (_FlushItem, _StopItem)):
                item.completed.set()

    def _require_ready(self) -> int:
        self._raise_writer_error()
        if not self.is_running:
            raise RecorderError("recorder session is not running")
        return self._require_session_id()

    def _require_session_id(self) -> int:
        if self._session_id is None:
            raise RecorderError("recorder session has not been started")
        return self._session_id

    def _raise_writer_error(self) -> None:
        if self._writer_error is not None:
            raise RecorderWriteError(
                f"SQLite writer failed: {self._writer_error}"
            ) from self._writer_error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @staticmethod
    def _checkpoint_wal(connection: sqlite3.Connection) -> WalCheckpointResult:
        try:
            row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.Error as exc:
            return WalCheckpointResult(error=str(exc))
        if row is None or len(row) != 3:
            return WalCheckpointResult(error="SQLite returned no checkpoint result")
        return WalCheckpointResult(
            busy=int(row[0]),
            log_pages=int(row[1]),
            checkpointed_pages=int(row[2]),
        )

    def __enter__(self) -> SessionRecorder:
        if not self.is_running:
            raise RecorderError("start the recorder before entering its context")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()


def initialize_schema(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RecorderError(
            f"recording schema version {version} is newer than supported version "
            f"{SCHEMA_VERSION}"
        )
    legacy_signals = version < SCHEMA_VERSION and _table_exists(
        connection, "signal_samples"
    )
    connection.executescript(SCHEMA_SQL)
    existing_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(sessions)")
    }
    additions = {
        "storage_mode": "TEXT NOT NULL DEFAULT 'raw_only'",
        "detected_addresses_json": "TEXT NOT NULL DEFAULT '[]'",
        "dbc_sha256": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing_columns:
            connection.execute(
                f"ALTER TABLE sessions ADD COLUMN {name} {definition}"
            )
    if legacy_signals:
        connection.execute(
            "UPDATE sessions SET storage_mode = ?",
            (STORAGE_MODE_LEGACY_SIGNALS,),
        )
        rows = connection.execute(
            "SELECT id, device_address FROM sessions"
        ).fetchall()
        connection.executemany(
            "UPDATE sessions SET detected_addresses_json = ? WHERE id = ?",
            (
                (json.dumps([int(address)]), int(session_id))
                for session_id, address in rows
            ),
        )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _json_default(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return repr(value)
