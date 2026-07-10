import pytest

from bms_can_monitor.canio.bus_config import BusConfig
from bms_can_monitor.canio.canalyst2_adapter import (
    AdapterState,
    Canalyst2Adapter,
    Canalyst2Error,
)
from bms_can_monitor.canio.diagnostics import collect_diagnostics
from bms_can_monitor.canio.events import CanEventType
from bms_can_monitor.protocol import CanFrame


def test_connect_uses_bms_defaults_and_closes(fake_controlcan_dll):
    events = []
    adapter = Canalyst2Adapter(dll=fake_controlcan_dll, event_sink=events.append)
    adapter.connect()
    assert adapter.state is AdapterState.STARTED
    assert ("VCI_InitCAN", (4, 0, 0, 0x01, 0x1C, 0)) in fake_controlcan_dll.calls
    assert adapter.pending_count() == 7
    assert adapter.board_info().serial_number == "SN0000"
    adapter.close()
    assert adapter.state is AdapterState.CLOSED
    assert [event.event_type for event in events] == [
        CanEventType.CONNECTING,
        CanEventType.CONNECTED,
        CanEventType.DISCONNECTED,
    ]


def test_connect_failure_closes_open_device(fake_controlcan_dll):
    fake_controlcan_dll.status["VCI_InitCAN"] = 0
    adapter = Canalyst2Adapter(dll=fake_controlcan_dll)
    with pytest.raises(Canalyst2Error, match="VCI_InitCAN"):
        adapter.connect()
    assert adapter.state is AdapterState.ERROR
    assert any(name == "VCI_CloseDevice" for name, _ in fake_controlcan_dll.calls)
    adapter.close(suppress_errors=True)
    assert adapter.state is AdapterState.CLOSED


def test_transmit_preserves_frame_flags_and_remote_dlc(fake_controlcan_dll):
    adapter = Canalyst2Adapter(BusConfig(channel=1), dll=fake_controlcan_dll)
    adapter.connect()
    adapter.send(
        CanFrame(
            0x18F0F428,
            bytes.fromhex("05 01 01 01"),
            is_extended=True,
            channel=1,
        )
    )
    adapter.send(
        CanFrame(0x321, b"", is_remote=True, dlc=8, channel=1)
    )
    assert fake_controlcan_dll.transmitted[0] == {
        "can_id": 0x18F0F428,
        "dlc": 4,
        "data": bytes.fromhex("05 01 01 01"),
        "extended": True,
        "remote": False,
        "send_type": 1,
        "channel": 1,
    }
    assert fake_controlcan_dll.transmitted[1]["remote"] is True
    assert fake_controlcan_dll.transmitted[1]["dlc"] == 8
    assert fake_controlcan_dll.transmitted[1]["data"] == b"\x00" * 8


def test_batch_receive_converts_sdk_frames(fake_controlcan_dll):
    fake_controlcan_dll.receive_batches.append(
        [
            {
                "can_id": 0x02F4,
                "data": bytes.fromhex("13 01 D7 11 33"),
                "hardware_timestamp": 1234,
            },
            {
                "can_id": 0x18F128F4,
                "data": bytes.fromhex("2C 01 90 01 E8 03 00 64"),
                "extended": True,
            },
            {"can_id": 0x321, "remote": True, "dlc": 6},
        ]
    )
    adapter = Canalyst2Adapter(dll=fake_controlcan_dll)
    adapter.connect()
    frames = adapter.receive(10, 5)
    assert len(frames) == 3
    assert frames[0].data == bytes.fromhex("13 01 D7 11 33")
    assert frames[0].hardware_timestamp == 1234
    assert frames[0].source == "canalyst2"
    assert frames[1].is_extended is True
    assert frames[2].is_remote is True
    assert frames[2].dlc == 6
    assert frames[2].data == b""


def test_receive_error_is_not_treated_as_frame_count(fake_controlcan_dll):
    fake_controlcan_dll.status["VCI_Receive"] = 0xFFFFFFFF
    adapter = Canalyst2Adapter(dll=fake_controlcan_dll)
    adapter.connect()
    with pytest.raises(Canalyst2Error, match="VCI_Receive"):
        adapter.receive(100)
    assert adapter.state is AdapterState.ERROR


def test_transmit_failure_keeps_started_channel_available(fake_controlcan_dll):
    fake_controlcan_dll.status["VCI_Transmit"] = 0
    adapter = Canalyst2Adapter(dll=fake_controlcan_dll)
    adapter.connect()
    with pytest.raises(Canalyst2Error, match="VCI_Transmit"):
        adapter.send(CanFrame(0x123, b"\x01"))
    assert adapter.state is AdapterState.STARTED


def test_reset_restart_and_diagnostics(fake_controlcan_dll):
    adapter = Canalyst2Adapter(dll=fake_controlcan_dll)
    adapter.connect()
    adapter.restart()
    assert adapter.state is AdapterState.STARTED
    diagnostics = collect_diagnostics(adapter)
    assert diagnostics.pending_frames == 7
    assert diagnostics.error_info.error_code == 0x20
    assert diagnostics.error_info.passive_error_data == (1, 2, 3)
    assert diagnostics.controller_status.receive_error_counter == 7
    assert diagnostics.controller_status.transmit_error_counter == 8
