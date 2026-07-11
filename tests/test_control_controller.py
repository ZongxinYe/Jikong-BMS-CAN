import json
import os
import sqlite3
from threading import Event
from time import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bms_can_monitor.canio import (
    CONTROL_CONFIRMATION_PHRASE,
    BusConfig,
    CanEventType,
    ControlSafetyError,
)
from bms_can_monitor.gui.controller import GuiController, SourceState
from bms_can_monitor.protocol import CanFrame, ControlCommand, ControlMask


class ControlAdapter:
    is_started = True

    def __init__(self, result=1):
        self.result = result
        self.sent = []
        self.sent_event = Event()

    def send(self, frame):
        self.sent.append(frame)
        self.sent_event.set()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self, *, suppress_errors=False):
        self.is_started = False


def qapp():
    return QApplication.instance() or QApplication([])


def command():
    return ControlCommand(mask=ControlMask.CHARGE, charge_on=True)


def make_live(controller, adapter, *, mode=0):
    controller._current_config = BusConfig(mode=mode)
    controller._adapter = adapter
    controller._set_source_state(SourceState("live", "connected", active=True))
    controller.pipeline.process_frame(
        CanFrame(0x02F4, bytes.fromhex("13 01 D7 11 33"), timestamp=time())
    )


def audit_stages(path):
    return [
        json.loads(line)["stage"]
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_unconnected_or_unconfirmed_control_cannot_send(tmp_path):
    controller = GuiController(
        start_timers=False,
        control_audit_path=tmp_path / "audit.jsonl",
    )
    with pytest.raises(ControlSafetyError, match="live CAN"):
        controller.send_control(command(), None)
    assert audit_stages(tmp_path / "audit.jsonl") == ["rejected"]
    controller.shutdown()


def test_listen_only_mode_rejects_control(tmp_path):
    controller = GuiController(
        start_timers=False,
        control_audit_path=tmp_path / "audit.jsonl",
    )
    adapter = ControlAdapter()
    make_live(controller, adapter, mode=1)
    with pytest.raises(ControlSafetyError, match="listen-only"):
        controller.authorize_control(command(), CONTROL_CONFIRMATION_PHRASE)
    assert adapter.sent == []
    controller.shutdown()


def test_confirmed_live_control_is_sent_and_audited(tmp_path):
    app = qapp()
    path = tmp_path / "audit.jsonl"
    controller = GuiController(start_timers=False, control_audit_path=path)
    adapter = ControlAdapter()
    make_live(controller, adapter)
    results = []
    event_batches = []
    controller.control_send_finished.connect(results.append)
    controller.events_received.connect(event_batches.append)

    authorization = controller.authorize_control(
        command(), CONTROL_CONFIRMATION_PHRASE
    )
    controller.send_control(command(), authorization)
    assert adapter.sent_event.wait(1)
    controller._control_thread.join(1)
    controller.drain_once()
    app.processEvents()

    assert len(adapter.sent) == 1
    assert adapter.sent[0].data == bytes.fromhex("01 01 00 00 00 00 00 00")
    assert results[-1].success is True
    event_types = [event.event_type for batch in event_batches for event in batch]
    assert event_types == [
        CanEventType.CONTROL_AUTHORIZED,
        CanEventType.CONTROL_SEND_REQUESTED,
        CanEventType.TX_SUCCEEDED,
    ]
    assert audit_stages(path) == ["authorized", "send_requested", "succeeded"]
    controller.shutdown()


def test_stale_bms_state_rejects_control(tmp_path):
    controller = GuiController(
        start_timers=False,
        control_audit_path=tmp_path / "audit.jsonl",
    )
    adapter = ControlAdapter()
    controller._current_config = BusConfig()
    controller._adapter = adapter
    controller._set_source_state(SourceState("live", "connected", active=True))
    controller.pipeline.process_frame(
        CanFrame(0x02F4, bytes.fromhex("13 01 D7 11 33"), timestamp=time() - 10)
    )
    with pytest.raises(ControlSafetyError, match="no recent BMS frame"):
        controller.authorize_control(command(), CONTROL_CONFIRMATION_PHRASE)
    assert adapter.sent == []
    controller.shutdown()


def test_other_bms_recent_frame_does_not_authorize_address_zero(tmp_path):
    controller = GuiController(
        start_timers=False,
        control_audit_path=tmp_path / "audit.jsonl",
    )
    adapter = ControlAdapter()
    controller._current_config = BusConfig(device_address=0)
    controller._adapter = adapter
    controller._set_source_state(SourceState("live", "connected", active=True))
    controller.pipeline.process_frame(
        CanFrame(0x02F5, bytes.fromhex("13 01 D7 11 33"), timestamp=time())
    )

    with pytest.raises(ControlSafetyError, match="no recent BMS frame"):
        controller.authorize_control(command(), CONTROL_CONFIRMATION_PHRASE)

    assert controller.pipeline.detected_addresses == (1,)
    assert adapter.sent == []
    controller.shutdown()


def test_audit_failure_blocks_adapter_send(tmp_path):
    audit_directory = tmp_path / "audit-is-a-directory"
    audit_directory.mkdir()
    controller = GuiController(
        start_timers=False,
        control_audit_path=audit_directory,
    )
    adapter = ControlAdapter()
    make_live(controller, adapter)
    with pytest.raises(ControlSafetyError, match="failed to write control audit"):
        controller.authorize_control(command(), CONTROL_CONFIRMATION_PHRASE)
    assert adapter.sent == []
    controller.shutdown()


def test_control_event_chain_is_recorded_in_sqlite(tmp_path):
    controller = GuiController(
        start_timers=False,
        control_audit_path=tmp_path / "audit.jsonl",
    )
    adapter = ControlAdapter()
    make_live(controller, adapter)
    database = tmp_path / "control-session.sqlite3"
    controller.start_recording(database)

    authorization = controller.authorize_control(
        command(), CONTROL_CONFIRMATION_PHRASE
    )
    controller.send_control(command(), authorization)
    controller._control_thread.join(1)
    controller.drain_once()
    controller.stop_recording()

    with sqlite3.connect(database) as connection:
        event_types = [
            row[0]
            for row in connection.execute(
                "SELECT event_type FROM events ORDER BY id"
            ).fetchall()
        ]
    assert event_types == [
        "control_authorized",
        "control_send_requested",
        "tx_succeeded",
    ]
    controller.shutdown()
