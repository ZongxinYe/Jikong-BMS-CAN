from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from bms_can_monitor.data import export_session, list_sessions  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a recorded SQLite session to CSV.")
    parser.add_argument("database", type=Path)
    parser.add_argument("--session", type=int, help="Session ID")
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
                f"bitrate={session.bitrate} note={session.note!r}"
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
    files = export_session(
        args.database,
        args.output,
        session_id,
        signal_names=signal_names,
    )
    print(f"Raw frames: {files.raw_frames}")
    print(f"Signals: {files.signals_wide}")
    print(f"Events: {files.events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
