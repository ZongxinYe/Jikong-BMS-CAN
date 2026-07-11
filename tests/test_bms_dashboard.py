import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bms_can_monitor.gui.bms_dashboard import BmsDashboard
from bms_can_monitor.protocol import BmsSnapshot, DecodedSignal


def qapp():
    return QApplication.instance() or QApplication([])


def signal(name, value, unit=""):
    return DecodedSignal(name, value, value, unit, 1.0, 0x100)


def test_dashboard_shows_protocol_voltage_extremes_and_temperature():
    qapp()
    dashboard = BmsDashboard(4)
    dashboard.update_snapshot(
        BmsSnapshot(
            timestamp=1.0,
            signals={
                "MaxCellVolt": signal("MaxCellVolt", 3412, "mV"),
                "MinCellVolt": signal("MinCellVolt", 3378, "mV"),
                "AvrgCellTemp": signal("AvrgCellTemp", 26, "degC"),
                "MaxCellTemp": signal("MaxCellTemp", 31, "degC"),
                "MaxCtNO": signal("MaxCtNO", 3),
                "MinCellTemp": signal("MinCellTemp", 22, "degC"),
                "MinCtNO": signal("MinCtNO", 1),
            },
        )
    )

    assert dashboard.delta_metric.value_label.text() == "34 mV"
    assert dashboard.delta_metric.high_value_label.text() == "最高 3412 mV"
    assert dashboard.delta_metric.low_value_label.text() == "最低 3378 mV"
    assert dashboard.temperature_metric.value_label.text() == "26 °C"
    assert dashboard.temperature_metric.high_value_label.text() == "最高 31 °C (探头 3)"
    assert dashboard.temperature_metric.low_value_label.text() == "最低 22 °C (探头 1)"


def test_dashboard_voltage_range_falls_back_to_assembled_cells():
    qapp()
    dashboard = BmsDashboard(0)
    assert dashboard.temperature_metric.value_label.text() == "--"
    assert dashboard.temperature_metric.high_value_label.text() == "最高 --"
    assert dashboard.temperature_metric.low_value_label.text() == "最低 --"
    dashboard.update_snapshot(
        BmsSnapshot(timestamp=1.0, cell_voltages_mv={1: 3300, 2: 3350})
    )
    assert dashboard.delta_metric.value_label.text() == "50 mV"
    assert dashboard.delta_metric.high_value_label.text() == "最高 3350 mV"
    assert dashboard.delta_metric.low_value_label.text() == "最低 3300 mV"

    dashboard.update_snapshot(
        BmsSnapshot(timestamp=2.0, cell_voltages_mv={1: 3300})
    )
    assert dashboard.delta_metric.value_label.text() == "--"
