from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from bms_can_monitor.data import (  # noqa: E402
    export_events,
    export_raw_frames,
    export_session,
    export_signals_wide,
    list_sessions,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a recorded SQLite session to CSV.")
    parser.add_argument("database", type=Path)
    parser.add_argument("--session", type=int, help="Session ID")
    parser.add_argument(
        "--address",
        type=int,
        choices=range(12),
        metavar="0..11",
        help="BMS address to decode; default exports one signal CSV per detected BMS",
    )
    parser.add_argument("--output", type=Path, default=Path("exports"))
    parser.add_argument(
        "--signals",
        help="Comma-separated signal names for the wide CSV; default exports all",
    )
    parser.add_argument("--list", action="store_true", help="List sessions and exit")
    args = parser.parse_args()

    sessions = list_sessions(args.database)
    if args.list:
        for session in sessions:
            print(
                f"id={session.session_id} start={session.started_at:.3f} "
                f"end={session.ended_at} channel={session.channel} "
                f"bitrate={session.bitrate} frames={session.frame_count} "
                f"addresses={session.detected_addresses} "
                f"storage={session.storage_mode} note={session.note!r}"
            )
        return 0

    session_id = args.session
    if session_id is None:
        if len(sessions) != 1:
            parser.error("--session is required when the database does not contain exactly one session")
        session_id = sessions[0].session_id
    signal_names = None
    if args.signals:
        signal_names = tuple(
            name.strip() for name in args.signals.split(",") if name.strip()
        )
    if args.address is not None:
        files = export_session(
            args.database,
            args.output,
            session_id,
            signal_names=signal_names,
            device_address=args.address,
        )
        print(f"Raw frames: {files.raw_frames}")
        print(f"Signals: {files.signals_wide}")
        print(f"Events: {files.events}")
        return 0

    session = next(item for item in sessions if item.session_id == session_id)
    prefix = f"session_{session_id}"
    raw = export_raw_frames(
        args.database, args.output / f"{prefix}_raw_frames.csv", session_id
    )
    events = export_events(
        args.database, args.output / f"{prefix}_events.csv", session_id
    )
    addresses = session.detected_addresses or (session.device_address,)
    print(f"Raw frames: {raw}")
    for address in addresses:
        signals = export_signals_wide(
            args.database,
            args.output / f"{prefix}_bms_{address:02d}_signals_wide.csv",
            session_id,
            signal_names=signal_names,
            device_address=address,
        )
        print(f"Signals BMS {address}: {signals}")
    print(f"Events: {events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
