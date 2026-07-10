"""Deterministic moving BMS frames for GUI smoke tests and demonstrations."""

from __future__ import annotations

from math import sin
from struct import pack

from bms_can_monitor.protocol import CanFrame


def build_demo_frames(timestamp: float, step: int) -> tuple[CanFrame, ...]:
    phase = step / 15.0
    pack_voltage = 52.8 + 0.35 * sin(phase)
    pack_current = 18.0 * sin(phase * 0.65)
    soc = max(0, min(100, 78 - step // 1800))

    status = pack(
        "<HHB",
        round(pack_voltage * 10),
        round((pack_current + 400.0) * 10),
        soc,
    )
    base_cell_mv = round(pack_voltage * 1000 / 16)
    cells = [base_cell_mv + round(9 * sin(phase + index * 0.7)) for index in range(16)]
    max_cell = max(cells)
    min_cell = min(cells)
    max_cell_no = cells.index(max_cell) + 1
    min_cell_no = cells.index(min_cell) + 1

    frames: list[CanFrame] = [
        CanFrame(0x02F4, status, timestamp=timestamp, source="demo"),
        CanFrame(
            0x04F4,
            pack("<HBHB", max_cell, max_cell_no, min_cell, min_cell_no),
            timestamp=timestamp,
            source="demo",
        ),
        CanFrame(
            0x05F4,
            bytes((83, 3, 72, 1, 77)),
            timestamp=timestamp,
            source="demo",
        ),
        CanFrame(
            0x18F428F4,
            pack("<IHB", 86_400 + step, 0, 98),
            timestamp=timestamp,
            is_extended=True,
            source="demo",
        ),
        CanFrame(
            0x18F528F4,
            b"\x07",
            timestamp=timestamp,
            is_extended=True,
            source="demo",
        ),
    ]
    for chunk in range(4):
        payload = pack("<HHHH", *cells[chunk * 4 : chunk * 4 + 4])
        frames.append(
            CanFrame(
                0x18E028F4 + chunk * 0x00010000,
                payload,
                timestamp=timestamp,
                is_extended=True,
                source="demo",
            )
        )
    if step % 10 == 0:
        frames.extend(
            (
                CanFrame(0x07F4, b"\x00\x00\x00\x00", timestamp=timestamp, source="demo"),
                CanFrame(
                    0x18F328F4,
                    b"\x00\x00\x00",
                    timestamp=timestamp,
                    is_extended=True,
                    source="demo",
                ),
            )
        )
    return tuple(frames)
