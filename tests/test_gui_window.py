import os
from time import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bms_can_monitor.gui.controller import GuiController
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
    )
    assert all(widget.width() > 0 and widget.height() > 0 for widget in metric_widgets)
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

    window.close()
    app.processEvents()
