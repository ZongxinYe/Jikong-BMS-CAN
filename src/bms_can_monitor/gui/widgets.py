"""Reusable operational widgets for the desktop monitor."""

from __future__ import annotations

from collections.abc import Mapping

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

from bms_can_monitor.data import SignalPoint, SignalRingBuffer


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

PLOT_COLORS = (
    "#157f78",
    "#2563a6",
    "#c2413b",
    "#7a5a18",
    "#6f4a8e",
    "#2d6a4f",
)


class MetricDisplay(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricDisplay")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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


class WaveformPanel(QWidget):
    selection_changed = pg.QtCore.Signal(object)

    def __init__(
        self,
        ring_buffer: SignalRingBuffer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ring_buffer = ring_buffer
        self._plots: dict[str, pg.PlotItem] = {}
        self._curves: dict[str, pg.PlotDataItem] = {}

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
        self.signal_list = QListWidget()
        self.signal_list.setMinimumWidth(175)
        self.signal_list.setMaximumWidth(260)
        self.signal_list.setToolTip("选择最多 6 条实时曲线")
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
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground("#ffffff")
        splitter.addWidget(self.signal_list)
        splitter.addWidget(self.graphics)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self.signal_list.itemChanged.connect(self._on_selection_changed)
        self._apply_selection()

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

    def _apply_selection(self) -> None:
        selected = self.selected_signals
        self.ring_buffer.select(selected, retain_existing=True)
        self.trace_count_label.setText(f"{len(selected)} 条曲线")
        self._rebuild_plots(selected)
        self.selection_changed.emit(selected)

    def _rebuild_plots(self, selected: tuple[str, ...]) -> None:
        self.graphics.clear()
        self._plots.clear()
        self._curves.clear()
        for row, name in enumerate(selected):
            plot = self.graphics.addPlot(row=row, col=0)
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.setLabel("left", SIGNAL_LABELS.get(name, name), units=SIGNAL_UNITS.get(name))
            plot.setLabel("bottom", "相对时间", units="s")
            plot.setMouseEnabled(x=True, y=True)
            plot.setClipToView(True)
            if row < len(selected) - 1:
                plot.hideAxis("bottom")
            curve = plot.plot(
                pen=pg.mkPen(PLOT_COLORS[row % len(PLOT_COLORS)], width=1.6),
                connect="finite",
            )
            self._plots[name] = plot
            self._curves[name] = curve

    def refresh(self) -> None:
        selected = self.selected_signals
        if not selected:
            return
        all_series: Mapping[str, tuple[SignalPoint, ...]] = self.ring_buffer.snapshot()
        latest = max(
            (points[-1].timestamp for points in all_series.values() if points),
            default=0.0,
        )
        window = float(self.window_combo.currentData())
        for name in selected:
            points = all_series.get(name, ())
            if latest:
                points = tuple(point for point in points if point.timestamp >= latest - window)
            x = [point.timestamp - latest for point in points]
            y = [point.value for point in points]
            self._curves[name].setData(x, y)
            self._plots[name].setXRange(-window, 0, padding=0)
