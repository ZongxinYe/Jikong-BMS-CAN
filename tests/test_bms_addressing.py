from types import SimpleNamespace

import pytest

from bms_can_monitor.protocol import (
    BmsAddressConflictError,
    BmsAddressResolver,
    CanFrame,
)


@pytest.mark.parametrize(
    ("frame", "address", "message_name", "normalized_id"),
    [
        (CanFrame(0x02F8, b"\x00" * 5), 4, "BATT_ST1", 0x02F4),
        (
            CanFrame(0x18F428F6, b"\x00" * 7, is_extended=True),
            2,
            "BMS_INFO",
            0x18F428F4,
        ),
        (
            CanFrame(0x18E328F9, b"\x00" * 8, is_extended=True),
            5,
            "CELL_VOL_13_16",
            0x18E328F4,
        ),
    ],
)
def test_resolver_identifies_standard_extended_and_cell_frames(
    frame, address, message_name, normalized_id
):
    resolved = BmsAddressResolver().resolve(frame)
    assert resolved is not None
    assert resolved.device_address == address
    assert resolved.message_name == message_name
    assert resolved.normalized_frame_id == normalized_id


def test_current_dbc_address_map_has_no_conflicts_and_ignores_downlink():
    resolver = BmsAddressResolver()
    assert resolver.conflicts == {}
    assert resolver.resolve(CanFrame(0x123, b"\x01")) is None
    assert resolver.resolve(
        CanFrame(0x18F0F428, b"\x00" * 8, is_extended=True)
    ) is None
    assert resolver.resolve(
        CanFrame(0x02F4, b"\x00" * 5, is_extended=True)
    ) is None


def test_resolver_reports_ambiguous_offset_map():
    messages = (
        SimpleNamespace(
            frame_id=0x100,
            name="FIRST",
            senders=["BMS"],
            is_extended_frame=False,
        ),
        SimpleNamespace(
            frame_id=0x101,
            name="SECOND",
            senders=["BMS"],
            is_extended_frame=False,
        ),
    )
    resolver = BmsAddressResolver(SimpleNamespace(messages=messages))
    frame = CanFrame(0x101, b"\x00")

    with pytest.raises(BmsAddressConflictError) as captured:
        resolver.resolve(frame)

    assert {
        (item.device_address, item.message_name)
        for item in captured.value.candidates
    } == {(1, "FIRST"), (0, "SECOND")}
