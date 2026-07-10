"""Bounds-checked byte readers used by protocol-specific logic."""

from __future__ import annotations


def _slice(data: bytes | bytearray, offset: int, size: int) -> bytes:
    if offset < 0:
        raise ValueError("byte offset must be non-negative")
    value = bytes(data[offset : offset + size])
    if len(value) != size:
        raise ValueError(f"need {size} byte(s) at offset {offset}, got {len(value)}")
    return value


def u8(data: bytes | bytearray, offset: int = 0) -> int:
    return _slice(data, offset, 1)[0]


def u16_le(data: bytes | bytearray, offset: int = 0) -> int:
    return int.from_bytes(_slice(data, offset, 2), "little", signed=False)


def u16_be(data: bytes | bytearray, offset: int = 0) -> int:
    return int.from_bytes(_slice(data, offset, 2), "big", signed=False)


def u32_le(data: bytes | bytearray, offset: int = 0) -> int:
    return int.from_bytes(_slice(data, offset, 4), "little", signed=False)
