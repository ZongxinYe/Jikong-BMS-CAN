import os
import sqlite3
from time import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bms_can_monitor.gui.controller import GuiController
from bms_can_monitor.gui.demo import build_demo_frames
from bms_can_monitor.protocol import CanFrame


def qapp():
    return QApplication.instance() or QApplication([])


def count_rows(database, table):
    with sqlite3.connect(database) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_controller_drains_demo_frames_through_pipeline():
    app = qapp()
    controller = GuiController(start_timers=False)
    snapshots = []
    batches = []
    controller.snapshot_updated.connect(snapshots.append)
    controller.frames_processed.connect(batches.append)

    frames = build_demo_frames(time(), 0)
    assert controller.inject_frames(frames) == len(frames)
    assert controller.drain_once(time_budget_ms=100) == len(frames)
    app.processEvents()

    snapshot = controller.pipeline.state_store.snapshot()
    assert snapshot.signals["BattVolt"].value is not None
    assert len(snapshot.cell_voltages_mv) == 16
    assert len(batches[0]) == len(frames)
    assert snapshots[-1].timestamp == snapshot.timestamp
    controller.shutdown()


def test_controller_honors_drain_frame_limit():
    controller = GuiController(start_timers=False)
    frames = build_demo_frames(time(), 1)
    controller.inject_frames(frames)
    assert controller.drain_once(frame_limit=3, time_budget_ms=100) == 3
    assert controller.frame_queue.qsize() == len(frames) - 3
    controller.shutdown()


def test_controller_emits_one_snapshot_per_changed_bms_address():
    app = qapp()
    controller = GuiController(start_timers=False)
    updates = []
    address_sets = []
    legacy = []
    controller.bms_snapshot_updated.connect(
        lambda address, snapshot: updates.append((address, snapshot))
    )
    controller.detected_addresses_changed.connect(address_sets.append)
    controller.snapshot_updated.connect(legacy.append)
    frames = [
        CanFrame(
            0x02F4 + address,
            bytes.fromhex("13 01 D7 11 33"),
            timestamp=time(),
        )
        for address in range(5)
    ]

    controller.inject_frames(frames)
    controller.drain_once(time_budget_ms=100)
    app.processEvents()

    assert [address for address, _ in updates] == [0, 1, 2, 3, 4]
    assert address_sets[-1] == (0, 1, 2, 3, 4)
    assert len(legacy) == 1
    assert legacy[0].timestamp == updates[0][1].timestamp
    controller.shutdown()


def test_controller_records_gui_pipeline_session(tmp_path):
    controller = GuiController(start_timers=False)
    database = tmp_path / "gui-session.sqlite3"
    session_id = controller.start_recording(database, note="GUI test")
    frames = build_demo_frames(time(), 2)
    controller.inject_frames(frames)
    controller.drain_once(time_budget_ms=100)
    controller.stop_recording()

    assert session_id == 1
    assert count_rows(database, "raw_frames") == len(frames)
    assert count_rows(database, "signal_samples") > 0
    controller.shutdown()


def test_demo_source_can_start_and_stop():
    controller = GuiController(start_timers=False)
    controller.start_demo()
    assert controller.source_state.mode == "demo"
    assert controller.source_state.active is True
    controller.disconnect_source()
    assert controller.source_state.mode == "idle"
    controller.shutdown()
