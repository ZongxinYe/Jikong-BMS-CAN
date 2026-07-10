"""CAN baud-rate timing table for CANalyst-II."""

from __future__ import annotations

BITRATE_TIMING: dict[int, tuple[int, int]] = {
    5_000: (0xBF, 0xFF),
    10_000: (0x31, 0x1C),
    20_000: (0x18, 0x1C),
    33_330: (0x09, 0x6F),
    40_000: (0x87, 0xFF),
    50_000: (0x09, 0x1C),
    66_660: (0x04, 0x6F),
    80_000: (0x83, 0xFF),
    83_330: (0x03, 0x6F),
    100_000: (0x04, 0x1C),
    125_000: (0x03, 0x1C),
    200_000: (0x81, 0xFA),
    250_000: (0x01, 0x1C),
    400_000: (0x80, 0xFA),
    500_000: (0x00, 0x1C),
    666_000: (0x80, 0xB6),
    800_000: (0x00, 0x16),
    1_000_000: (0x00, 0x14),
}

DEFAULT_BMS_BITRATE = 250_000


def timing_for_bitrate(bitrate: int) -> tuple[int, int]:
    """Return ControlCAN Timing0/Timing1 values for a standard bitrate."""

    try:
        return BITRATE_TIMING[int(bitrate)]
    except KeyError as exc:
        raise ValueError(f"Unsupported CAN bitrate: {bitrate}") from exc

