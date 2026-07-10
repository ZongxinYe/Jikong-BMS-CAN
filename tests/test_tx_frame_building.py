import pytest

from bms_can_monitor.canio.controlcan_types import make_can_obj


def test_standard_tx_frame_building():
    frame = make_can_obj(can_id=0x2F4, data=b"\x13\x01\xd7\x11\x33")
    assert frame.ID == 0x2F4
    assert frame.SendType == 1
    assert frame.DataLen == 5
    assert frame.ExternFlag == 0
    assert list(frame.Data[:5]) == [0x13, 0x01, 0xD7, 0x11, 0x33]


def test_remote_frame_flag_is_set():
    frame = make_can_obj(can_id=0x123, remote=True)
    assert frame.RemoteFlag == 1
    assert frame.DataLen == 0


def test_too_much_data_raises():
    with pytest.raises(ValueError):
        make_can_obj(can_id=0x123, data=bytes(range(9)))

