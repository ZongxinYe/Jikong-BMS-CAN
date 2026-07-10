import pytest

from bms_can_monitor.protocol.byte_utils import u8, u16_be, u16_le, u32_le


def test_byte_readers_cover_protocol_endianness():
    data = bytes.fromhex("03 48 00 C8")
    assert u8(data) == 3
    assert u16_be(data) == 840
    assert u16_le(bytes.fromhex("13 01")) == 275
    assert u32_le(bytes.fromhex("C8 00 00 00")) == 200


def test_byte_readers_check_bounds():
    with pytest.raises(ValueError):
        u16_le(b"\x01")
    with pytest.raises(ValueError):
        u8(b"\x01", -1)
