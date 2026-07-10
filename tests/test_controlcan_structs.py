import ctypes

from bms_can_monitor.canio import controlcan_types as types


def test_controlcan_struct_sizes_match_sdk_layout():
    for name, expected in types.EXPECTED_SIZES.items():
        struct_type = getattr(types, name)
        assert ctypes.sizeof(struct_type) == expected


def test_make_init_config_for_bms_defaults():
    config = types.make_init_config(timing0=0x01, timing1=0x1C)
    assert config.AccCode == 0x00000000
    assert config.AccMask == 0xFFFFFFFF
    assert config.Filter == 1
    assert config.Timing0 == 0x01
    assert config.Timing1 == 0x1C
    assert config.Mode == 0


def test_make_can_obj_pads_data_and_marks_extended():
    frame = types.make_can_obj(can_id=0x18F128F4, data=bytes([1, 2, 3]), extended=True)
    assert frame.ID == 0x18F128F4
    assert frame.DataLen == 3
    assert frame.ExternFlag == 1
    assert frame.RemoteFlag == 0
    assert list(frame.Data) == [1, 2, 3, 0, 0, 0, 0, 0]

