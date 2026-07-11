import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from bms_can_monitor.data import BmsSignalKey, SignalRingBuffer
from bms_can_monitor.gui.widgets import BMS_COLORS, WaveformPanel


def qapp():
    return QApplication.instance() or QApplication([])


def address_item(panel: WaveformPanel, address: int):
    for index in range(panel.bms_list.count()):
        item = panel.bms_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == address:
            return item
    raise AssertionError(f"BMS {address} item not found")


def test_five_bms_share_signal_plots_with_isolated_series_and_legends():
    qapp()
    buffer = SignalRingBuffer()
    panel = WaveformPanel(buffer)
    panel.set_available_addresses(range(5))

    for address in range(5):
        buffer.append("BattVolt", 10.0, 50 + address, device_address=address)
        buffer.append("BattVolt", 12.0, 51 + address, device_address=address)
    panel.refresh()

    assert panel.selected_addresses == (0, 1, 2, 3, 4)
    assert panel.selected_signals == ("BattVolt", "BattCurr", "SOC")
    assert len(panel._curves) == 15
    assert panel.trace_count_label.text() == "5 BMS · 3 信号 · 15 曲线"
    for address in range(5):
        key = BmsSignalKey(address, "BattVolt")
        x, y = panel._curves[key].getData()
        assert list(x) == [-2.0, 0.0]
        assert list(y) == [50.0 + address, 51.0 + address]
        assert panel._curves[key].opts["pen"].color().name() == BMS_COLORS[address]

    legend_names = {
        label.text for _sample, label in panel._plots["BattVolt"].legend.items
    }
    assert legend_names == {f"BMS {address}" for address in range(5)}


def test_address_selection_survives_new_discovery_and_reset():
    qapp()
    panel = WaveformPanel(SignalRingBuffer())
    panel.set_available_addresses((0, 1, 2))
    address_item(panel, 1).setCheckState(Qt.CheckState.Unchecked)

    panel.set_available_addresses((0, 1, 2, 3))
    assert panel.selected_addresses == (0, 2, 3)
    assert BmsSignalKey(1, "BattVolt") not in panel._curves
    assert BmsSignalKey(3, "BattVolt") in panel._curves
    assert (
        panel._curves[BmsSignalKey(0, "BattVolt")].opts["pen"].color().name()
        == BMS_COLORS[0]
    )

    panel.set_available_addresses(())
    assert panel.selected_addresses == ()
    assert panel.bms_list.count() == 0
    assert panel._curves == {}
    assert panel.trace_count_label.text() == "0 BMS · 3 信号 · 0 曲线"
