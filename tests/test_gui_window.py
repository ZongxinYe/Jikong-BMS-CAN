import os
from time import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bms_can_monitor.gui.controller import GuiController
from bms_can_monitor.gui.demo import build_demo_frames
from bms_can_monitor.gui.app import configure_application
from bms_can_monitor.gui.main_window import MainWindow


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
    assert window.tabs.isTabEnabled(window.control_tab_index) is False
    assert window.control_action.isChecked() is False
    assert window.signal_model.rowCount() > 0
    assert window.cell_model.rowCount() == 16
    assert window.frame_model.rowCount() > 0
    assert window.voltage_metric.value_label.text().endswith(" V")
    assert window.size().width() >= window.minimumWidth()

    window.close()
    app.processEvents()
