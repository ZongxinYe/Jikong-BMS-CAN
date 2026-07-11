"""Deterministic moving BMS frames for GUI smoke tests and demonstrations."""

from __future__ import annotations

from collections.abc import Iterable
from math import sin
from struct import pack

from bms_can_monitor.protocol import CanFrame


def build_demo_frames(
    timestamp: float,
    step: int,
    addresses: Iterable[int] = (0, 1, 2),
) -> tuple[CanFrame, ...]:
    frames: list[CanFrame] = []
    for address in addresses:
        frames.extend(_build_address_frames(timestamp, step, address))
    return tuple(frames)


def _build_address_frames(
    timestamp: float, step: int, address: int
) -> tuple[CanFrame, ...]:
    if not 0 <= address <= 11:
        raise ValueError("demo BMS address must be 0..11")
    phase = step / 15.0
    pack_voltage = 52.8 + address * 0.8 + 0.35 * sin(phase + address * 0.3)
    pack_current = 18.0 * sin(phase * 0.65 + address * 0.4)
    soc = max(0, min(100, 78 - address * 7 - step // 1800))

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

    maximum_temperature = 33 + address * 2
    minimum_temperature = 22 + address
    average_temperature = round((maximum_temperature + minimum_temperature) / 2)

    frames: list[CanFrame] = [
        CanFrame(0x02F4 + address, status, timestamp=timestamp, source="demo"),
        CanFrame(
            0x04F4 + address,
            pack("<HBHB", max_cell, max_cell_no, min_cell, min_cell_no),
            timestamp=timestamp,
            source="demo",
        ),
        CanFrame(
            0x05F4 + address,
            bytes(
                (
                    maximum_temperature + 50,
                    3,
                    minimum_temperature + 50,
                    1,
                    average_temperature + 50,
                )
            ),
            timestamp=timestamp,
            source="demo",
        ),
        CanFrame(
            0x18F428F4 + address,
            pack("<IHB", 86_400 + step + address * 1_000, 0, 98 - address),
            timestamp=timestamp,
            is_extended=True,
            source="demo",
        ),
        CanFrame(
            0x18F528F4 + address,
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
                0x18E028F4 + chunk * 0x00010000 + address,
                payload,
                timestamp=timestamp,
                is_extended=True,
                source="demo",
            )
        )
    if step % 10 == 0:
        frames.extend(
            (
                CanFrame(
                    0x07F4 + address,
                    b"\x00\x00\x00\x00",
                    timestamp=timestamp,
                    source="demo",
                ),
                CanFrame(
                    0x18F328F4 + address,
                    b"\x00\x00\x00",
                    timestamp=timestamp,
                    is_extended=True,
                    source="demo",
                ),
            )
        )
    return tuple(frames)
