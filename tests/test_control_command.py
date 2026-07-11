import pytest

from bms_can_monitor.protocol import (
    CTRL_INFO_FRAME_ID,
    ControlCommand,
    ControlMask,
    ControlProtocolError,
)


def test_pdf_ctrl_info_example_encodes_exact_frame():
    command = ControlCommand(
        mask=ControlMask.CHARGE | ControlMask.BALANCE,
        charge_on=True,
        discharge_on=True,
        balance_on=True,
    )
    frame = command.to_frame(channel=1, timestamp=10.0)
    assert frame.can_id == CTRL_INFO_FRAME_ID == 0x18F0F428
    assert frame.data == bytes.fromhex("05 01 01 01 00 00 00 00")
    assert frame.is_extended is True
    assert frame.channel == 1
    assert frame.source == "control"
    assert command.selected_changes == (("charge", True), ("balance", True))


def test_control_command_rejects_reserved_mask_bits():
    with pytest.raises(ControlProtocolError, match="reserved bits"):
        ControlCommand(mask=0x08)


def test_control_command_does_not_coerce_unsafe_input_types():
    with pytest.raises(ControlProtocolError, match="charge_on must be a boolean"):
        ControlCommand(mask=ControlMask.CHARGE, charge_on="yes")
    with pytest.raises(ControlProtocolError, match="address must be an integer"):
        ControlCommand(mask=ControlMask.CHARGE, device_address=1.5)


def test_control_send_requires_mask_and_verified_default_address():
    with pytest.raises(ControlProtocolError, match="at least one"):
        ControlCommand().validate_for_send()
    with pytest.raises(ControlProtocolError, match="locked to device address 0"):
        ControlCommand(mask=ControlMask.CHARGE, device_address=2).validate_for_send()
