"""Read-only, chunked access to SQLite recording sessions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from bms_can_monitor.protocol.models import CanFrame

from .recorder import SCHEMA_VERSION, STORAGE_MODE_LEGACY_SIGNALS


class RecordingReadError(RuntimeError):
    """Raised when a recording cannot be safely read."""


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session_id: int
    started_at: float
    ended_at: float | None
    device_index: int
    channel: int
    bitrate: int
    device_address: int
    protocol_version: str
    note: str
    storage_mode: str = STORAGE_MODE_LEGACY_SIGNALS
    detected_addresses: tuple[int, ...] = ()
    dbc_sha256: str = ""
    frame_count: int = 0
    first_frame_timestamp: float | None = None
    last_frame_timestamp: float | None = None

    @property
    def duration(self) -> float:
        if self.first_frame_timestamp is None or self.last_frame_timestamp is None:
            return 0.0
        return max(0.0, self.last_frame_timestamp - self.first_frame_timestamp)


class RecordingReader:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        if not self.database_path.is_file():
            raise RecordingReadError(
                f"recording database not found: {self.database_path}"
            )

    def _connect(self) -> sqlite3.Connection:
        uri = f"{self.database_path.as_uri()}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        except sqlite3.Error as exc:
            raise RecordingReadError(
                f"failed to open recording database: {exc}"
            ) from exc
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _validate(connection: sqlite3.Connection) -> int:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RecordingReadError(
                f"recording schema version {version} is newer than supported "
                f"version {SCHEMA_VERSION}"
            )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = {"sessions", "raw_frames"} - tables
        if missing:
            raise RecordingReadError(
                f"recording database is missing tables: {', '.join(sorted(missing))}"
            )
        return version

    @staticmethod
    def _session_columns(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row[1]) for row in connection.execute("PRAGMA table_info(sessions)")
        }

    def list_sessions(self) -> tuple[SessionSummary, ...]:
        with self._connect() as connection:
            version = self._validate(connection)
            columns = self._session_columns(connection)
            storage_sql = (
                "s.storage_mode"
                if "storage_mode" in columns
                else f"'{STORAGE_MODE_LEGACY_SIGNALS}'"
            )
            addresses_sql = (
                "s.detected_addresses_json"
                if "detected_addresses_json" in columns
                else "NULL"
            )
            dbc_hash_sql = "s.dbc_sha256" if "dbc_sha256" in columns else "''"
            rows = connection.execute(
                f"""
                SELECT s.id, s.started_at, s.ended_at, s.device_index, s.channel,
                       s.bitrate, s.device_address, s.protocol_version, s.note,
                       {storage_sql} AS storage_mode,
                       {addresses_sql} AS detected_addresses_json,
                       {dbc_hash_sql} AS dbc_sha256,
                       COUNT(r.id) AS frame_count,
                       MIN(r.timestamp) AS first_frame_timestamp,
                       MAX(r.timestamp) AS last_frame_timestamp
                FROM sessions AS s
                LEFT JOIN raw_frames AS r ON r.session_id = s.id
                GROUP BY s.id
                ORDER BY s.id
                """
            ).fetchall()
        return tuple(self._summary(row, version) for row in rows)

    @staticmethod
    def _summary(row: sqlite3.Row, schema_version: int) -> SessionSummary:
        fallback_address = int(row["device_address"])
        raw_addresses = row["detected_addresses_json"]
        if raw_addresses is None:
            addresses = (fallback_address,)
        else:
            try:
                parsed = json.loads(str(raw_addresses))
                addresses = tuple(sorted({int(value) for value in parsed}))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RecordingReadError(
                    f"session {row['id']} has invalid detected address metadata"
                ) from exc
        if any(not 0 <= value <= 0x0B for value in addresses):
            raise RecordingReadError(
                f"session {row['id']} contains an invalid BMS address"
            )
        storage_mode = str(row["storage_mode"])
        if schema_version < 2:
            storage_mode = STORAGE_MODE_LEGACY_SIGNALS
        return SessionSummary(
            session_id=int(row["id"]),
            started_at=float(row["started_at"]),
            ended_at=(
                None if row["ended_at"] is None else float(row["ended_at"])
            ),
            device_index=int(row["device_index"]),
            channel=int(row["channel"]),
            bitrate=int(row["bitrate"]),
            device_address=fallback_address,
            protocol_version=str(row["protocol_version"]),
            note=str(row["note"]),
            storage_mode=storage_mode,
            detected_addresses=addresses,
            dbc_sha256=str(row["dbc_sha256"] or "").lower(),
            frame_count=int(row["frame_count"]),
            first_frame_timestamp=(
                None
                if row["first_frame_timestamp"] is None
                else float(row["first_frame_timestamp"])
            ),
            last_frame_timestamp=(
                None
                if row["last_frame_timestamp"] is None
                else float(row["last_frame_timestamp"])
            ),
        )

    def session(self, session_id: int) -> SessionSummary:
        for summary in self.list_sessions():
            if summary.session_id == int(session_id):
                return summary
        raise RecordingReadError(f"session {session_id} does not exist")

    def iter_frames(
        self,
        session_id: int,
        *,
        batch_size: int = 2_000,
    ) -> Iterator[CanFrame]:
        if batch_size < 1:
            raise ValueError("recording read batch size must be positive")
        connection = self._connect()
        try:
            self._validate(connection)
            exists = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (int(session_id),)
            ).fetchone()
            if exists is None:
                raise RecordingReadError(f"session {session_id} does not exist")
            cursor = connection.execute(
                """
                SELECT timestamp, can_id, is_extended, is_remote, dlc, data,
                       channel, hardware_timestamp, source
                FROM raw_frames
                WHERE session_id = ?
                ORDER BY timestamp, id
                """,
                (int(session_id),),
            )
            while True:
                rows = cursor.fetchmany(batch_size)
                if not rows:
                    return
                for row in rows:
                    yield CanFrame(
                        can_id=int(row["can_id"]),
                        data=bytes(row["data"]),
                        timestamp=float(row["timestamp"]),
                        is_extended=bool(row["is_extended"]),
                        is_remote=bool(row["is_remote"]),
                        dlc=int(row["dlc"]),
                        channel=int(row["channel"]),
                        hardware_timestamp=(
                            None
                            if row["hardware_timestamp"] is None
                            else int(row["hardware_timestamp"])
                        ),
                        source=str(row["source"]),
                    )
        finally:
            connection.close()


class SqliteReplaySource:
    """Repeatable replay source backed by chunked read-only SQLite queries."""

    def __init__(
        self,
        database_path: str | Path,
        session_id: int,
        *,
        batch_size: int = 2_000,
    ) -> None:
        self.reader = RecordingReader(database_path)
        self.summary = self.reader.session(session_id)
        self.session_id = self.summary.session_id
        self.batch_size = int(batch_size)
        if self.batch_size < 1:
            raise ValueError("recording read batch size must be positive")

    @property
    def frame_count(self) -> int:
        return self.summary.frame_count

    def iter_frames(self) -> Iterator[CanFrame]:
        return self.reader.iter_frames(
            self.session_id,
            batch_size=self.batch_size,
        )
