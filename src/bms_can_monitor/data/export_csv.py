"""Excel-friendly CSV exports from recorded SQLite sessions."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Iterable


class ExportError(RuntimeError):
    """Raised when a database or session cannot be exported."""


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


@dataclass(frozen=True, slots=True)
class ExportedSessionFiles:
    raw_frames: Path
    signals_wide: Path
    events: Path


def list_sessions(database_path: str | Path) -> tuple[SessionSummary, ...]:
    with _connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, started_at, ended_at, device_index, channel, bitrate,
                   device_address, protocol_version, note
            FROM sessions ORDER BY id
            """
        ).fetchall()
    return tuple(
        SessionSummary(
            session_id=int(row["id"]),
            started_at=float(row["started_at"]),
            ended_at=(float(row["ended_at"]) if row["ended_at"] is not None else None),
            device_index=int(row["device_index"]),
            channel=int(row["channel"]),
            bitrate=int(row["bitrate"]),
            device_address=int(row["device_address"]),
            protocol_version=str(row["protocol_version"]),
            note=str(row["note"]),
        )
        for row in rows
    )


def export_raw_frames(
    database_path: str | Path,
    output_path: str | Path,
    session_id: int,
) -> Path:
    with _connect(database_path) as connection:
        _ensure_session(connection, session_id)
        rows = connection.execute(
            """
            SELECT timestamp, can_id, is_extended, is_remote, dlc, data,
                   channel, hardware_timestamp, source
            FROM raw_frames
            WHERE session_id = ?
            ORDER BY timestamp, id
            """,
            (session_id,),
        ).fetchall()

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
        for row in rows:
            writer.writerow(
                {
                    "timestamp": f"{float(row['timestamp']):.9f}",
                    "can_id": f"0x{int(row['can_id']):X}",
                    "is_extended": int(row["is_extended"]),
                    "is_remote": int(row["is_remote"]),
                    "dlc": int(row["dlc"]),
                    "data": bytes(row["data"]).hex(" ").upper(),
                    "channel": int(row["channel"]),
                    "hardware_timestamp": (
                        ""
                        if row["hardware_timestamp"] is None
                        else int(row["hardware_timestamp"])
                    ),
                    "source": _excel_safe(str(row["source"])),
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
) -> Path:
    requested = None if signal_names is None else tuple(dict.fromkeys(signal_names))
    with _connect(database_path) as connection:
        _ensure_session(connection, session_id)
        if requested is None:
            names = tuple(
                row[0]
                for row in connection.execute(
                    """
                    SELECT DISTINCT signal_name FROM signal_samples
                    WHERE session_id = ? ORDER BY signal_name
                    """,
                    (session_id,),
                )
            )
        else:
            names = requested

        sql = """
            SELECT timestamp, signal_name, value_real, value_text
            FROM signal_samples
            WHERE session_id = ?
        """
        parameters: list[object] = [session_id]
        if names:
            placeholders = ",".join("?" for _ in names)
            sql += f" AND signal_name IN ({placeholders})"
            parameters.extend(names)
        elif requested is not None:
            sql += " AND 0"
        sql += " ORDER BY timestamp, id"
        rows = connection.execute(sql, parameters).fetchall()

    output = _prepare_output(output_path)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("timestamp", *names))
        writer.writeheader()
        latest: dict[str, object] = {}
        for timestamp, grouped in groupby(rows, key=lambda row: float(row["timestamp"])):
            current = latest if forward_fill else {}
            for row in grouped:
                value: object
                if row["value_real"] is not None:
                    value = _clean_number(float(row["value_real"]))
                elif row["value_text"] is not None:
                    value = _excel_safe(str(row["value_text"]))
                else:
                    value = ""
                current[str(row["signal_name"])] = value
            writer.writerow(
                {
                    "timestamp": f"{timestamp:.9f}",
                    **{name: current.get(name, "") for name in names},
                }
            )
            if forward_fill:
                latest = current
    return output


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
