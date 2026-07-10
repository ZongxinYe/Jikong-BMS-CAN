from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import monotonic

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from bms_can_monitor.canio import (  # noqa: E402
    BusConfig,
    Canalyst2Adapter,
    collect_diagnostics,
    discover_devices,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover CANalyst-II devices and optionally perform a receive-only smoke test."
    )
    parser.add_argument("--dll", type=Path, help="Path to ControlCAN.dll")
    parser.add_argument("--device", type=int, default=0, help="Device index")
    parser.add_argument("--channel", type=int, choices=(0, 1), default=0)
    parser.add_argument("--bitrate", type=int, default=250_000)
    parser.add_argument(
        "--receive-seconds",
        type=float,
        default=0.0,
        help="Open the channel and receive for N seconds; default only discovers devices",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    devices = discover_devices(dll_path=args.dll)
    if not devices:
        print("No CANalyst-II devices found.")
    for device in devices:
        print(
            f"[{device.index}] {device.hardware_type} serial={device.serial_number} "
            f"channels={device.can_channels} hw={device.hardware_version_text} "
            f"fw={device.firmware_version_text}"
        )

    if args.receive_seconds <= 0:
        return 0
    if not devices:
        return 2

    config = BusConfig(
        device_index=args.device,
        channel=args.channel,
        bitrate=args.bitrate,
        dll_path=args.dll,
    )
    frame_count = 0
    with Canalyst2Adapter(config) as adapter:
        board = adapter.board_info()
        print(
            f"Receiving only from {board.hardware_type} channel={args.channel} "
            f"bitrate={args.bitrate}..."
        )
        deadline = monotonic() + args.receive_seconds
        while monotonic() < deadline:
            frames = adapter.receive(config.receive_batch_size, config.receive_wait_ms)
            frame_count += len(frames)
            for frame in frames[:20]:
                frame_type = "EXT" if frame.is_extended else "STD"
                print(
                    f"{frame.timestamp:.6f} CH{frame.channel + 1} {frame_type} "
                    f"0x{frame.can_id:X} [{frame.dlc}] {frame.data.hex(' ').upper()}"
                )
        diagnostics = collect_diagnostics(adapter)
        print(
            f"Received {frame_count} frame(s); pending={diagnostics.pending_frames}; "
            f"diagnostics_unavailable={list(diagnostics.unavailable)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
