"""SQLite recording session selection dialog."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bms_can_monitor.data import SessionSummary


class ReplaySessionDialog(QDialog):
    def __init__(
        self,
        sessions: tuple[SessionSummary, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not sessions:
            raise ValueError("at least one recording session is required")
        self._sessions = sessions
        self.setWindowTitle("选择记录会话")
        self.resize(820, 360)

        root = QVBoxLayout(self)
        self.table = QTableWidget(len(sessions), 7)
        self.table.setHorizontalHeaderLabels(
            ("会话", "开始时间", "时长", "帧数", "CAN", "BMS 地址", "状态")
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        for row, session in enumerate(sessions):
            values = (
                str(session.session_id),
                datetime.fromtimestamp(session.started_at).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                _duration_text(session.duration),
                f"{session.frame_count:,}",
                f"CAN{session.channel + 1} / {session.bitrate // 1000} kbps",
                ", ".join(str(value) for value in session.detected_addresses)
                or "--",
                "已完成" if session.is_finalized else "未收尾",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {0, 2, 3, 4, 5, 6}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.selectRow(len(sessions) - 1)
        self.table.doubleClicked.connect(lambda _index: self.accept())
        root.addWidget(self.table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @property
    def selected_session_id(self) -> int:
        row = self.table.currentRow()
        if row < 0:
            row = len(self._sessions) - 1
        return self._sessions[row].session_id


def _duration_text(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
