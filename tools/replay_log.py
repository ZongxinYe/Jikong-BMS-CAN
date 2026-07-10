from __future__ import annotations

import argparse
import sys
from pathlib import Path
from queue import Empty, Queue

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from bms_can_monitor.canio import ReplayWorker, load_replay_csv  # noqa: E402
from bms_can_monitor.protocol import CanFrame  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay raw CAN frames from CSV.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()

    frames = load_replay_csv(args.csv_path)
    output: Queue[CanFrame] = Queue()
    worker = ReplayWorker(frames, output, speed=args.speed)
    worker.start()
    while worker.is_running or not output.empty():
        try:
            frame = output.get(timeout=0.1)
        except Empty:
            continue
        frame_type = "EXT" if frame.is_extended else "STD"
        print(
            f"{frame.timestamp:.6f} CH{frame.channel + 1} {frame_type} "
            f"0x{frame.can_id:X} [{frame.dlc}] {frame.data.hex(' ').upper()}"
        )
    worker.join()
    print(f"Replay complete: {worker.stats}")
    return 0 if worker.stats.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
