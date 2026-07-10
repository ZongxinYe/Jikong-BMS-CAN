import pytest

from bms_can_monitor.canio.device_discovery import (
    DeviceDiscoveryError,
    discover_devices,
    format_sdk_version,
)


def test_discovers_board_identity_from_sdk(fake_controlcan_dll):
    devices = discover_devices(dll=fake_controlcan_dll)
    assert [device.index for device in devices] == [0, 1]
    assert devices[0].serial_number == "SN0000"
    assert devices[0].hardware_type == "CANalyst-II"
    assert devices[0].can_channels == 2
    assert devices[0].hardware_version_text == "1.02"
    assert format_sdk_version(0x1234) == "12.34"


def test_discovery_rejects_sdk_error_and_buffer_overrun(fake_controlcan_dll):
    fake_controlcan_dll.status["VCI_FindUsbDevice2"] = 0xFFFFFFFF
    with pytest.raises(DeviceDiscoveryError, match="0xFFFFFFFF"):
        discover_devices(dll=fake_controlcan_dll)

    fake_controlcan_dll.status["VCI_FindUsbDevice2"] = 3
    with pytest.raises(DeviceDiscoveryError, match="larger than buffer"):
        discover_devices(dll=fake_controlcan_dll, capacity=2)
