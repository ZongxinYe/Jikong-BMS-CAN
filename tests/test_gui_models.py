import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from bms_can_monitor.gui.models import (
    CellTableModel,
    FrameFilterProxyModel,
    FrameTableModel,
    SignalTableModel,
)
from bms_can_monitor.protocol import BmsSnapshot, CanFrame, DecodedSignal


def qapp():
    return QApplication.instance() or QApplication([])


def test_frame_model_is_bounded_and_formats_can_ids():
    qapp()
    model = FrameTableModel(max_rows=2)
    rows = [
        (CanFrame(0x123, b"\x01", timestamp=1.0), "A"),
        (CanFrame(0x124, b"\x02", timestamp=2.0), "B"),
        (
            CanFrame(0x18F428F4, b"\x03", timestamp=3.0, is_extended=True),
            "C",
        ),
    ]
    model.append_batch(rows)
    assert model.rowCount() == 2
    assert model.data(model.index(0, 2)) == "0x124"
    assert model.data(model.index(1, 2)) == "0x18F428F4"


def test_frame_filter_searches_across_visible_columns():
    qapp()
    model = FrameTableModel()
    model.append_batch(
        [
            (CanFrame(0x123, bytes.fromhex("AA BB"), timestamp=1.0), "STATUS"),
            (CanFrame(0x456, bytes.fromhex("01 02"), timestamp=2.0), "OTHER"),
        ]
    )
    proxy = FrameFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.set_query("aa bb")
    assert proxy.rowCount() == 1
    proxy.set_query("other")
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 7)) == "OTHER"


def test_signal_and_cell_models_refresh_from_snapshot():
    qapp()
    snapshot = BmsSnapshot(
        timestamp=2.0,
        signals={
            "SOC": DecodedSignal("SOC", 51, 51, "%", 2.0, 0x2F4),
            "BattVolt": DecodedSignal("BattVolt", 27.5, 275, "V", 2.0, 0x2F4),
        },
        cell_voltages_mv={1: 3750, 2: 3800},
    )
    signals = SignalTableModel()
    signals.update_snapshot(snapshot)
    assert signals.rowCount() == 2
    assert signals.data(signals.index(0, 0)) == "BattVolt"

    cells = CellTableModel()
    cells.update_snapshot(snapshot)
    assert cells.rowCount() == 2
    assert cells.data(cells.index(0, 1)) == "3.750 V"
    assert cells.data(cells.index(0, 2), Qt.ItemDataRole.DisplayRole) == "-25.0 mV"
