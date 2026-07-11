"""One address-scoped BMS overview page."""

from __future__ import annotations

from numbers import Real

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from bms_can_monitor.protocol import BmsSnapshot

from .models import CellTableModel, SignalTableModel
from .widgets import MetricDisplay, RangeMetricDisplay


class BmsDashboard(QWidget):
    """Independent dashboard models and widgets for one BMS address."""

    def __init__(self, device_address: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.device_address = device_address

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        metrics = QGridLayout()
        metrics.setSpacing(7)
        metrics.setColumnStretch(0, 1)
        metrics.setColumnStretch(1, 1)
        metrics.setColumnStretch(2, 1)

        self.voltage_metric = MetricDisplay("电池总压")
        self.current_metric = MetricDisplay("电池电流")
        self.soc_metric = MetricDisplay("SOC")
        self.soh_metric = MetricDisplay("SOH")
        self.delta_metric = RangeMetricDisplay("单体压差")
        self.temperature_metric = RangeMetricDisplay("单体温度")
        for index, metric in enumerate(
            (
                self.voltage_metric,
                self.current_metric,
                self.soc_metric,
                self.soh_metric,
                self.delta_metric,
                self.temperature_metric,
            )
        ):
            metrics.addWidget(metric, index // 3, index % 3)
        root.addLayout(metrics)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        signal_panel = QWidget()
        signal_layout = QVBoxLayout(signal_panel)
        signal_layout.setContentsMargins(0, 0, 0, 0)
        signal_layout.addWidget(self._section_label("实时信号"))
        self.signal_model = SignalTableModel(self)
        self.signal_table = self._table(self.signal_model)
        self.signal_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        signal_layout.addWidget(self.signal_table)

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        cell_panel = QWidget()
        cell_layout = QVBoxLayout(cell_panel)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.addWidget(self._section_label("单体电压"))
        self.cell_model = CellTableModel(self)
        self.cell_table = self._table(self.cell_model)
        self.cell_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        cell_layout.addWidget(self.cell_table)

        issue_panel = QWidget()
        issue_layout = QVBoxLayout(issue_panel)
        issue_layout.setContentsMargins(0, 0, 0, 0)
        issue_layout.addWidget(self._section_label("活动告警与故障"))
        self.issue_list = QListWidget()
        issue_layout.addWidget(self.issue_list)
        right_splitter.addWidget(cell_panel)
        right_splitter.addWidget(issue_panel)
        right_splitter.setStretchFactor(0, 2)
        right_splitter.setStretchFactor(1, 1)
        splitter.addWidget(signal_panel)
        splitter.addWidget(right_splitter)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)
        self.update_snapshot(BmsSnapshot(timestamp=0.0))

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    @staticmethod
    def _table(model) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(False)
        return table

    @staticmethod
    def _signal_value(snapshot: BmsSnapshot, name: str) -> Real | None:
        signal = snapshot.signals.get(name)
        value = None if signal is None else signal.value
        return value if isinstance(value, Real) and not isinstance(value, bool) else None

    def update_snapshot(self, snapshot: BmsSnapshot) -> None:
        self.signal_model.update_snapshot(snapshot)
        self.cell_model.update_snapshot(snapshot)
        self.voltage_metric.set_value(self._signal_value(snapshot, "BattVolt"), "V")
        self.current_metric.set_value(self._signal_value(snapshot, "BattCurr"), "A")
        self.soc_metric.set_value(self._signal_value(snapshot, "SOC"), "%")
        self.soh_metric.set_value(self._signal_value(snapshot, "SOH"), "%")
        self._update_voltage_range(snapshot)
        self._update_temperature(snapshot)
        self._update_issues(snapshot)

    def _update_voltage_range(self, snapshot: BmsSnapshot) -> None:
        maximum = self._signal_value(snapshot, "MaxCellVolt")
        minimum = self._signal_value(snapshot, "MinCellVolt")
        if maximum is None or minimum is None:
            cells = tuple(snapshot.cell_voltages_mv.values())
            if len(cells) >= 2:
                maximum = max(cells)
                minimum = min(cells)
        if maximum is None or minimum is None:
            self.delta_metric.set_values(None, "mV")
            return
        self.delta_metric.set_values(
            maximum - minimum,
            "mV",
            high_text=f"最高 {maximum:g} mV",
            low_text=f"最低 {minimum:g} mV",
            high_color="#b42318",
            low_color="#13705a",
        )

    def _update_temperature(self, snapshot: BmsSnapshot) -> None:
        average = self._signal_value(snapshot, "AvrgCellTemp")
        maximum = self._signal_value(snapshot, "MaxCellTemp")
        minimum = self._signal_value(snapshot, "MinCellTemp")
        maximum_no = self._signal_value(snapshot, "MaxCtNO")
        minimum_no = self._signal_value(snapshot, "MinCtNO")
        high_text = "最高 --"
        low_text = "最低 --"
        if maximum is not None:
            suffix = f" (探头 {int(maximum_no)})" if maximum_no is not None else ""
            high_text = f"最高 {maximum:g} °C{suffix}"
        if minimum is not None:
            suffix = f" (探头 {int(minimum_no)})" if minimum_no is not None else ""
            low_text = f"最低 {minimum:g} °C{suffix}"
        self.temperature_metric.set_values(
            average,
            "°C",
            high_text=high_text,
            low_text=low_text,
        )

    def _update_issues(self, snapshot: BmsSnapshot) -> None:
        self.issue_list.clear()
        issues = (*snapshot.active_alarms, *snapshot.active_faults)
        if not issues:
            item = QListWidgetItem("无活动告警或故障")
            item.setForeground(Qt.GlobalColor.darkGreen)
            self.issue_list.addItem(item)
            return
        for issue in issues:
            item = QListWidgetItem(issue)
            item.setForeground(Qt.GlobalColor.darkRed)
            self.issue_list.addItem(item)
