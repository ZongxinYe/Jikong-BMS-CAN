"""Reusable operational widgets for the desktop monitor."""

from __future__ import annotations

from collections.abc import Iterable

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bms_can_monitor.data import BmsSignalKey, SignalRingBuffer


SIGNAL_LABELS = {
    "BattVolt": "电池总压",
    "BattCurr": "电池电流",
    "SOC": "SOC",
    "SOH": "SOH",
    "MaxCellVolt": "最高单体电压",
    "MinCellVolt": "最低单体电压",
    "MaxCellTemp": "最高单体温度",
    "MinCellTemp": "最低单体温度",
    "AvrgCellTemp": "平均单体温度",
    "CapRemain": "剩余容量",
}

SIGNAL_UNITS = {
    "BattVolt": "V",
    "BattCurr": "A",
    "SOC": "%",
    "SOH": "%",
    "MaxCellVolt": "mV",
    "MinCellVolt": "mV",
    "MaxCellTemp": "°C",
    "MinCellTemp": "°C",
    "AvrgCellTemp": "°C",
    "CapRemain": "Ah",
}

BMS_COLORS = (
    "#157f78",
    "#2563a6",
    "#c2413b",
    "#7a5a18",
    "#6f4a8e",
    "#2d6a4f",
    "#a63d70",
    "#347c98",
    "#9c5b20",
    "#5267a3",
    "#71802c",
    "#8b4f45",
)


class MetricDisplay(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricDisplay")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(92)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel("--")
        self.value_label.setObjectName("metricValue")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: object | None, unit: str = "") -> None:
        if value is None:
            text = "--"
        elif isinstance(value, float):
            text = f"{value:.2f}".rstrip("0").rstrip(".")
        else:
            text = str(value)
        self.value_label.setText(f"{text} {unit}".rstrip())


class RangeMetricDisplay(QFrame):
    """Metric card with a primary value and compact high/low details."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricDisplay")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(92)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel("--")
        self.value_label.setObjectName("metricValue")
        details = QHBoxLayout()
        details.setSpacing(12)
        self.high_value_label = QLabel("最高 --")
        self.high_value_label.setObjectName("metricDetail")
        self.low_value_label = QLabel("最低 --")
        self.low_value_label.setObjectName("metricDetail")
        details.addWidget(self.high_value_label)
        details.addWidget(self.low_value_label)
        details.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addLayout(details)

    def set_values(
        self,
        primary: object | None,
        primary_unit: str,
        *,
        high_text: str = "最高 --",
        low_text: str = "最低 --",
        high_color: str | None = None,
        low_color: str | None = None,
    ) -> None:
        self.value_label.setText(_metric_text(primary, primary_unit))
        self.high_value_label.setText(high_text)
        self.low_value_label.setText(low_text)
        self.high_value_label.setStyleSheet(
            f"color: {high_color}; font-weight: 600;" if high_color else ""
        )
        self.low_value_label.setStyleSheet(
            f"color: {low_color}; font-weight: 600;" if low_color else ""
        )


def _metric_text(value: object | None, unit: str = "") -> str:
    if value is None:
        return "--"
    elif isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text} {unit}".rstrip()


class WaveformPanel(QWidget):
    selection_changed = pg.QtCore.Signal(object)
    address_selection_changed = pg.QtCore.Signal(object)

    def __init__(
        self,
        ring_buffer: SignalRingBuffer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ring_buffer = ring_buffer
        self._plots: dict[str, pg.PlotItem] = {}
        self._curves: dict[BmsSignalKey, pg.PlotDataItem] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("时间窗"))
        self.window_combo = QComboBox()
        self.window_combo.addItem("30 秒", 30.0)
        self.window_combo.addItem("1 分钟", 60.0)
        self.window_combo.addItem("5 分钟", 300.0)
        self.window_combo.setCurrentIndex(1)
        self.window_combo.setMaximumWidth(110)
        controls.addWidget(self.window_combo)
        controls.addStretch(1)
        self.trace_count_label = QLabel()
        self.trace_count_label.setObjectName("mutedLabel")
        controls.addWidget(self.trace_count_label)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        selection_panel = QWidget()
        selection_layout = QVBoxLayout(selection_panel)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        selection_layout.setSpacing(5)
        selection_layout.addWidget(QLabel("BMS"))
        self.bms_list = QListWidget()
        self.bms_list.setMinimumHeight(90)
        self.bms_list.setMaximumHeight(180)
        self.bms_list.setToolTip("选择需要在同一信号图中对比的 BMS")
        selection_layout.addWidget(self.bms_list)
        selection_layout.addWidget(QLabel("信号"))
        self.signal_list = QListWidget()
        self.signal_list.setToolTip("选择最多 6 个实时信号")
        for name in SIGNAL_LABELS:
            item = QListWidgetItem(SIGNAL_LABELS[name])
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if name in {"BattVolt", "BattCurr", "SOC"}
                else Qt.CheckState.Unchecked
            )
            self.signal_list.addItem(item)
        selection_layout.addWidget(self.signal_list, 1)
        selection_panel.setMinimumWidth(175)
        selection_panel.setMaximumWidth(260)
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground("#ffffff")
        splitter.addWidget(selection_panel)
        splitter.addWidget(self.graphics)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self.bms_list.itemChanged.connect(self._on_address_selection_changed)
        self.signal_list.itemChanged.connect(self._on_selection_changed)
        self._apply_selection()

    @property
    def selected_addresses(self) -> tuple[int, ...]:
        addresses: list[int] = []
        for index in range(self.bms_list.count()):
            item = self.bms_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                addresses.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return tuple(addresses)

    @property
    def selected_signals(self) -> tuple[str, ...]:
        names: list[str] = []
        for index in range(self.signal_list.count()):
            item = self.signal_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                names.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return tuple(names)

    def _on_selection_changed(self, changed_item: QListWidgetItem) -> None:
        selected = self.selected_signals
        if len(selected) > 6:
            self.signal_list.blockSignals(True)
            changed_item.setCheckState(Qt.CheckState.Unchecked)
            self.signal_list.blockSignals(False)
        self._apply_selection()

    def _on_address_selection_changed(self, _changed_item: QListWidgetItem) -> None:
        self._rebuild_plots(self.selected_signals, self.selected_addresses)
        self._update_trace_count()
        self.address_selection_changed.emit(self.selected_addresses)

    def set_available_addresses(self, addresses: Iterable[int]) -> None:
        normalized = tuple(sorted({int(address) for address in addresses}))
        if any(not 0 <= address <= 11 for address in normalized):
            raise ValueError("BMS device address must be 0..11")
        previous = {
            int(self.bms_list.item(index).data(Qt.ItemDataRole.UserRole)):
            self.bms_list.item(index).checkState()
            for index in range(self.bms_list.count())
        }
        self.bms_list.blockSignals(True)
        self.bms_list.clear()
        for address in normalized:
            item = QListWidgetItem(f"BMS {address}")
            item.setData(Qt.ItemDataRole.UserRole, address)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(previous.get(address, Qt.CheckState.Checked))
            self.bms_list.addItem(item)
        self.bms_list.blockSignals(False)
        self._rebuild_plots(self.selected_signals, self.selected_addresses)
        self._update_trace_count()

    def _apply_selection(self) -> None:
        selected = self.selected_signals
        self.ring_buffer.select(selected, retain_existing=True)
        self._rebuild_plots(selected, self.selected_addresses)
        self._update_trace_count()
        self.selection_changed.emit(selected)

    def _update_trace_count(self) -> None:
        address_count = len(self.selected_addresses)
        signal_count = len(self.selected_signals)
        self.trace_count_label.setText(
            f"{address_count} BMS · {signal_count} 信号 · "
            f"{address_count * signal_count} 曲线"
        )

    def _rebuild_plots(
        self,
        selected: tuple[str, ...],
        addresses: tuple[int, ...],
    ) -> None:
        self.graphics.clear()
        self._plots.clear()
        self._curves.clear()
        for row, name in enumerate(selected):
            plot = self.graphics.addPlot(row=row, col=0)
            legend = plot.addLegend(
                offset=(8, 8),
                colCount=max(1, min(6, len(addresses))),
            )
            legend.setBrush(pg.mkBrush(255, 255, 255, 220))
            legend.setPen(pg.mkPen("#d8dde5"))
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.setLabel("left", SIGNAL_LABELS.get(name, name), units=SIGNAL_UNITS.get(name))
            plot.setLabel("bottom", "相对时间", units="s")
            plot.setMouseEnabled(x=True, y=True)
            plot.setClipToView(True)
            if row < len(selected) - 1:
                plot.hideAxis("bottom")
            self._plots[name] = plot
            for address in addresses:
                key = BmsSignalKey(address, name)
                self._curves[key] = plot.plot(
                    name=f"BMS {address}",
                    pen=pg.mkPen(BMS_COLORS[address], width=1.6),
                    connect="finite",
                )

    def refresh(self) -> None:
        selected = self.selected_signals
        if not selected:
            return
        addresses = self.selected_addresses
        all_series = self.ring_buffer.snapshot_all()
        selected_keys = tuple(
            BmsSignalKey(address, name)
            for name in selected
            for address in addresses
        )
        latest = max(
            (
                all_series[key][-1].timestamp
                for key in selected_keys
                if all_series.get(key)
            ),
            default=0.0,
        )
        window = float(self.window_combo.currentData())
        for name in selected:
            for address in addresses:
                key = BmsSignalKey(address, name)
                points = all_series.get(key, ())
                if latest:
                    points = tuple(
                        point
                        for point in points
                        if point.timestamp >= latest - window
                    )
                x = [point.timestamp - latest for point in points]
                y = [point.value for point in points]
                self._curves[key].setData(x, y)
            self._plots[name].setXRange(-window, 0, padding=0)
