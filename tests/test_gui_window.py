import os
import sqlite3
from time import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from bms_can_monitor.canio.events import CanEvent, CanEventType
from bms_can_monitor.data import BmsSignalKey, SessionMetadata, SessionRecorder
from bms_can_monitor.gui.controller import GuiController, SourceState
from bms_can_monitor.gui.demo import build_demo_frames
from bms_can_monitor.gui.app import configure_application
from bms_can_monitor.gui.main_window import MainWindow
from bms_can_monitor.protocol import CanFrame


def test_main_window_builds_and_refreshes_offscreen():
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    controller = GuiController(start_timers=False)
    window = MainWindow(controller)
    window.show()
    controller.inject_frames(build_demo_frames(time(), 3))
    controller.drain_once(time_budget_ms=100)
    app.processEvents()

    assert window.tabs.count() == 5
    assert window.bms_overview_tabs.count() == 3
    assert tuple(window.bms_dashboards) == (0, 1, 2)
    assert window.waveform_panel.selected_addresses == (0, 1, 2)
    assert len(window.waveform_panel._curves) == 9
    assert [
        window.bms_overview_tabs.tabText(index)
        for index in range(window.bms_overview_tabs.count())
    ] == ["BMS 0", "BMS 1", "BMS 2"]
    assert window.tabs.isTabEnabled(window.control_tab_index) is False
    assert window.control_action.isChecked() is False
    assert window.signal_model.rowCount() > 0
    assert window.cell_model.rowCount() == 16
    assert window.frame_model.rowCount() > 0
    assert window.voltage_metric.value_label.text().endswith(" V")
    assert window.temperature_metric.value_label.text().endswith(" °C")
    assert window.remaining_capacity_metric.value_label.text().endswith(" Ah")
    assert window.full_charge_capacity_metric.value_label.text().endswith(" Ah")
    assert window.cycle_capacity_metric.value_label.text().endswith(" Ah")
    assert window.cycle_count_metric.value_label.text().endswith(" 次")
    assert "#b42318" in window.delta_metric.high_value_label.styleSheet()
    assert "#13705a" in window.delta_metric.low_value_label.styleSheet()
    assert (
        window.bms_dashboards[0].voltage_metric.value_label.text()
        != window.bms_dashboards[1].voltage_metric.value_label.text()
    )
    assert (
        window.bms_dashboards[0].temperature_metric.value_label.text()
        != window.bms_dashboards[2].temperature_metric.value_label.text()
    )
    assert window.size().width() >= window.minimumWidth()

    dashboard = window.bms_dashboards[0]
    metric_widgets = (
        dashboard.voltage_metric,
        dashboard.current_metric,
        dashboard.soc_metric,
        dashboard.soh_metric,
        dashboard.delta_metric,
        dashboard.temperature_metric,
        dashboard.remaining_capacity_metric,
        dashboard.full_charge_capacity_metric,
        dashboard.cycle_capacity_metric,
        dashboard.cycle_count_metric,
    )
    for width, height in ((1024, 680), (1440, 900)):
        window.resize(width, height)
        app.processEvents()
        assert all(
            widget.width() > 0 and widget.height() > 0 for widget in metric_widgets
        )
        assert all(
            not first.geometry().intersects(second.geometry())
            for index, first in enumerate(metric_widgets)
            for second in metric_widgets[index + 1 :]
        )

    window.close()
    app.processEvents()


def test_main_window_creates_and_clears_five_bms_dashboards():
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    controller = GuiController(start_timers=False)
    window = MainWindow(controller)
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

    assert tuple(window.bms_dashboards) == (0, 1, 2, 3, 4)
    assert window.bms_overview_tabs.count() == 5

    window._clear_data()
    app.processEvents()
    assert tuple(window.bms_dashboards) == (0,)
    assert window.bms_dashboards[0].signal_model.rowCount() == 0
    assert window.waveform_panel.selected_addresses == ()
    assert window.waveform_panel._curves == {}

    window.close()
    app.processEvents()


def test_replay_finish_keeps_last_waveform_visible():
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    controller = GuiController(start_timers=False)
    window = MainWindow(controller)
    try:
        controller._set_source_state(
            SourceState("replay", "离线回放中", active=True)
        )
        controller.inject_frames(
            [
                CanFrame(
                    0x02F4,
                    bytes.fromhex("99 01 A0 0F 00"),
                    timestamp=10.0,
                )
            ]
        )
        controller.drain_once(time_budget_ms=100)
        app.processEvents()
        window.waveform_panel.refresh()
        key = BmsSignalKey(0, "BattVolt")
        before_x, before_y = window.waveform_panel._curves[key].getData()

        controller._enqueue_event(
            CanEvent(CanEventType.REPLAY_FINISHED, "CAN replay finished")
        )
        controller.drain_once(time_budget_ms=100)
        app.processEvents()

        assert controller.source_state.mode == "idle"
        assert window.waveform_panel.selected_addresses == (0,)
        assert key in window.waveform_panel._curves
        after_x, after_y = window.waveform_panel._curves[key].getData()
        assert list(after_x) == list(before_x)
        assert list(after_y) == list(before_y)
        assert list(after_y) == pytest.approx([40.9])
    finally:
        window.close()
        app.processEvents()


def test_unfinalized_recording_requires_confirmation_before_replay(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    database = tmp_path / "unfinalized.sqlite3"
    recorder = SessionRecorder(database)
    session_id = recorder.start(SessionMetadata(started_at=1.0))
    recorder.record_frame(
        CanFrame(0x02F4, bytes.fromhex("13 01 D7 11 33"), timestamp=2.0)
    )
    recorder.stop(ended_at=3.0)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE sessions SET ended_at = NULL WHERE id = ?", (session_id,)
        )

    controller = GuiController(start_timers=False)
    window = MainWindow(controller)
    warnings = []
    started = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(database), ""),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: (
            warnings.append((args, kwargs)) or QMessageBox.StandardButton.No
        ),
    )
    monkeypatch.setattr(
        controller,
        "start_replay",
        lambda *args, **kwargs: started.append((args, kwargs)),
    )
    try:
        window._open_replay()

        assert len(warnings) == 1
        assert "-wal/-shm" in warnings[0][0][2]
        assert started == []
    finally:
        window.close()
        app.processEvents()
