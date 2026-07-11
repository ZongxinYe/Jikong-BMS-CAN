"""Bounded Qt item models used by the realtime desktop views."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from bms_can_monitor.canio import CanEvent, CanEventType
from bms_can_monitor.protocol import BmsSnapshot, CanFrame, DecodedSignal


def _time_text(timestamp: float) -> str:
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]


class FrameTableModel(QAbstractTableModel):
    HEADERS = (
        "时间",
        "通道",
        "CAN ID",
        "帧格式",
        "类型",
        "DLC",
        "数据",
        "报文",
        "BMS",
        "来源",
    )

    def __init__(self, parent=None, *, max_rows: int = 20_000) -> None:
        super().__init__(parent)
        if max_rows < 1:
            raise ValueError("max_rows must be positive")
        self.max_rows = max_rows
        self._rows: list[tuple[CanFrame, str, int | None]] = []
        self.paused = False

    @property
    def rows(self) -> tuple[tuple[CanFrame, str, int | None], ...]:
        return tuple(self._rows)

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        frame, message_name, device_address = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                _time_text(frame.timestamp),
                f"CAN{frame.channel + 1}",
                f"0x{frame.can_id:08X}" if frame.is_extended else f"0x{frame.can_id:03X}",
                "扩展帧" if frame.is_extended else "标准帧",
                "远程帧" if frame.is_remote else "数据帧",
                str(frame.dlc),
                frame.data.hex(" ").upper(),
                message_name or "未解析",
                "--" if device_address is None else str(device_address),
                frame.source,
            )
            return values[column]
        if role == Qt.ItemDataRole.TextAlignmentRole and column in {1, 2, 5, 8}:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ForegroundRole and not message_name:
            return QColor("#8a5a00")
        if role == Qt.ItemDataRole.UserRole:
            return frame
        return None

    def append_batch(
        self,
        rows: list[
            tuple[CanFrame, str] | tuple[CanFrame, str, int | None]
        ],
    ) -> None:
        if self.paused or not rows:
            return
        normalized = [
            (row[0], row[1], None) if len(row) == 2 else row
            for row in rows
        ]
        combined = self._rows + normalized
        if len(combined) > self.max_rows:
            self.beginResetModel()
            self._rows = combined[-self.max_rows :]
            self.endResetModel()
            return
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(rows) - 1)
        self._rows.extend(normalized)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()


class FrameFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._query = ""
        self.setDynamicSortFilter(True)

    def set_query(self, query: str) -> None:
        self._query = query.strip().lower()
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        if not self._query:
            return True
        model = self.sourceModel()
        return any(
            self._query
            in str(
                model.data(
                    model.index(source_row, column, source_parent),
                    Qt.ItemDataRole.DisplayRole,
                )
            ).lower()
            for column in range(model.columnCount(source_parent))
        )


class SignalTableModel(QAbstractTableModel):
    HEADERS = ("信号", "当前值", "单位", "更新时间")
    PREFERRED = (
        "BattVolt",
        "BattCurr",
        "SOC",
        "SOH",
        "MaxCellVolt",
        "MinCellVolt",
        "MaxCellTemp",
        "MinCellTemp",
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[DecodedSignal] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        signal = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            value = "--" if signal.value is None else signal.value
            if isinstance(value, float):
                value = f"{value:.3f}".rstrip("0").rstrip(".")
            return (signal.name, str(value), signal.unit or "", _time_text(signal.timestamp))[
                index.column()
            ]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {1, 2}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def update_snapshot(self, snapshot: BmsSnapshot) -> None:
        preferred = {name: index for index, name in enumerate(self.PREFERRED)}
        rows = sorted(
            snapshot.signals.values(),
            key=lambda signal: (preferred.get(signal.name, len(preferred)), signal.name),
        )
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class CellTableModel(QAbstractTableModel):
    HEADERS = ("单体", "电压", "相对平均值")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[int, int, float]] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        cell, voltage_mv, delta_mv = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                f"Cell {cell:02d}",
                f"{voltage_mv / 1000:.3f} V",
                f"{delta_mv:+.1f} mV",
            )[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 2:
            if abs(delta_mv) >= 50:
                return QColor("#b42318")
            if abs(delta_mv) >= 25:
                return QColor("#8a5a00")
        return None

    def update_snapshot(self, snapshot: BmsSnapshot) -> None:
        values = snapshot.cell_voltages_mv
        average = sum(values.values()) / len(values) if values else 0.0
        self.beginResetModel()
        self._rows = [
            (cell, voltage, voltage - average) for cell, voltage in sorted(values.items())
        ]
        self.endResetModel()


class EventTableModel(QAbstractTableModel):
    HEADERS = ("时间", "级别", "事件", "说明")

    def __init__(self, parent=None, *, max_rows: int = 2_000) -> None:
        super().__init__(parent)
        self.max_rows = max_rows
        self._rows: list[CanEvent] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        event = self._rows[index.row()]
        is_error = event.event_type in {
            CanEventType.ADAPTER_ERROR,
            CanEventType.CONTROL_REJECTED,
            CanEventType.REPLAY_ERROR,
            CanEventType.RX_QUEUE_OVERFLOW,
            CanEventType.TX_FAILED,
        }
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                _time_text(event.timestamp),
                "错误" if is_error else "信息",
                event.event_type.value,
                event.message,
            )[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and is_error:
            return QColor("#b42318")
        return None

    def append_batch(self, events: list[CanEvent]) -> None:
        if not events:
            return
        self.beginResetModel()
        self._rows = (self._rows + events)[-self.max_rows :]
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()
