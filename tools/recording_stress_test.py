from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from time import monotonic

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from bms_can_monitor.data import SessionMetadata, SessionRecorder  # noqa: E402
from bms_can_monitor.protocol import CanFrame  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark background raw-frame recording.")
    parser.add_argument("--database", type=Path, default=Path("records/stress.sqlite3"))
    parser.add_argument("--frames", type=int, default=100_000)
    parser.add_argument("--bms-count", type=int, default=5, choices=range(1, 13))
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("--frames must be positive")

    recorder = SessionRecorder(
        args.database,
        batch_size=1000,
        queue_capacity=max(100_000, args.frames),
    )
    session_id = recorder.start(SessionMetadata(note="recording stress test"))
    started = monotonic()
    for index in range(args.frames):
        address = index % args.bms_count
        recorder.record_frame(
            CanFrame(
                0x02F4 + address,
                bytes.fromhex("13 01 D7 11 33"),
                timestamp=1_700_000_000.0 + index / (107 * args.bms_count),
                source="stress_test",
            )
        )
    recorder.flush(timeout=60.0)
    recorder.stop(
        detected_addresses=range(args.bms_count),
        timeout=60.0,
    )
    elapsed = monotonic() - started
    with sqlite3.connect(args.database) as connection:
        stored = connection.execute(
            "SELECT COUNT(*) FROM raw_frames WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        signal_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_samples'"
        ).fetchone()
    database_bytes = args.database.stat().st_size
    print(
        f"stored={stored} elapsed={elapsed:.3f}s rate={stored / elapsed:.0f} frames/s "
        f"bms={args.bms_count} bytes={database_bytes} "
        f"bytes_per_frame={database_bytes / stored:.1f} database={args.database}"
    )
    return 0 if stored == args.frames and signal_table is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
