"""Locked-by-default editor for the Jikong Ctrl_INFO command."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from bms_can_monitor.protocol import (
    CTRL_INFO_FRAME_ID,
    BmsSnapshot,
    ControlCommand,
    ControlMask,
)


CONTROL_NAMES = {
    "charge": "充电开关",
    "discharge": "放电开关",
    "balance": "均衡开关",
}


class ControlPanel(QWidget):
    send_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._device_address = 0
        self._unlocked = False
        self._pending = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)
        warning = QLabel(
            "该页面直接改变 BMS 充电、放电和均衡开关。每次仅发送一帧，不提供周期控制。"
        )
        warning.setObjectName("controlWarning")
        warning.setWordWrap(True)
        root.addWidget(warning)

        target_form = QFormLayout()
        self.target_address_label = QLabel("0（默认地址）")
        self.frame_id_edit = QLineEdit(f"0x{CTRL_INFO_FRAME_ID:08X}")
        self.frame_id_edit.setReadOnly(True)
        self.data_edit = QLineEdit()
        self.data_edit.setReadOnly(True)
        target_form.addRow("目标 BMS 地址", self.target_address_label)
        target_form.addRow("扩展帧 ID", self.frame_id_edit)
        target_form.addRow("发送 DATA", self.data_edit)
        root.addLayout(target_form)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(9)
        grid.addWidget(QLabel("控制项"), 0, 0)
        grid.addWidget(QLabel("MaskCode"), 0, 1)
        grid.addWidget(QLabel("目标状态"), 0, 2)
        grid.addWidget(QLabel("BMS 当前状态"), 0, 3)

        self.charge_mask = QCheckBox("允许控制")
        self.discharge_mask = QCheckBox("允许控制")
        self.balance_mask = QCheckBox("允许控制")
        self.charge_target = QCheckBox("关闭")
        self.discharge_target = QCheckBox("关闭")
        self.balance_target = QCheckBox("关闭")
        self.charge_current = QLabel("未知")
        self.discharge_current = QLabel("未知")
        self.balance_current = QLabel("未知")
        rows = (
            (
                "充电开关",
                self.charge_mask,
                self.charge_target,
                self.charge_current,
            ),
            (
                "放电开关",
                self.discharge_mask,
                self.discharge_target,
                self.discharge_current,
            ),
            (
                "均衡开关",
                self.balance_mask,
                self.balance_target,
                self.balance_current,
            ),
        )
        for row, (name, mask, target, current) in enumerate(rows, start=1):
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(mask, row, 1)
            grid.addWidget(target, row, 2)
            grid.addWidget(current, row, 3)
            mask.toggled.connect(self._refresh)
            target.toggled.connect(self._refresh)
        grid.setColumnStretch(3, 1)
        root.addLayout(grid)

        footer = QHBoxLayout()
        self.status_label = QLabel("控制功能已锁定")
        self.status_label.setObjectName("mutedLabel")
        self.send_button = QPushButton(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward),
            "确认并发送",
        )
        self.send_button.clicked.connect(self._request_send)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.send_button)
        root.addLayout(footer)
        root.addStretch(1)
        self._refresh()

    @property
    def is_unlocked(self) -> bool:
        return self._unlocked

    def command(self) -> ControlCommand:
        mask = ControlMask.NONE
        if self.charge_mask.isChecked():
            mask |= ControlMask.CHARGE
        if self.discharge_mask.isChecked():
            mask |= ControlMask.DISCHARGE
        if self.balance_mask.isChecked():
            mask |= ControlMask.BALANCE
        return ControlCommand(
            mask=mask,
            charge_on=self.charge_target.isChecked(),
            discharge_on=self.discharge_target.isChecked(),
            balance_on=self.balance_target.isChecked(),
            device_address=self._device_address,
        )

    def set_device_address(self, address: int) -> None:
        self._device_address = int(address)
        if self._device_address == 0:
            self.target_address_label.setText("0（默认地址）")
            self.frame_id_edit.setText(f"0x{CTRL_INFO_FRAME_ID:08X}")
        else:
            self.target_address_label.setText(f"{self._device_address}（控制未验证）")
            self.frame_id_edit.setText("不可发送")
        self._refresh()

    def set_unlocked(self, unlocked: bool) -> None:
        self._unlocked = bool(unlocked)
        if not self._unlocked:
            self.clear_masks()
            self.status_label.setText("控制功能已锁定")
        else:
            self.status_label.setText("请选择 MaskCode 和目标状态")
        self._refresh()

    def set_pending(self, pending: bool) -> None:
        self._pending = bool(pending)
        if pending:
            self.status_label.setText("控制帧发送中")
        self._refresh()

    def set_result(self, success: bool, message: str) -> None:
        self._pending = False
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: #13705a; font-weight: 600;"
            if success
            else "color: #b42318; font-weight: 600;"
        )
        if success:
            self.clear_masks()
        self._refresh()

    def clear_masks(self) -> None:
        self.charge_mask.setChecked(False)
        self.discharge_mask.setChecked(False)
        self.balance_mask.setChecked(False)

    def update_snapshot(self, snapshot: BmsSnapshot) -> None:
        self._set_current(self.charge_current, snapshot, "ChgMosSta")
        self._set_current(self.discharge_current, snapshot, "DchgMosSta")
        self._set_current(self.balance_current, snapshot, "BalanSta")

    @staticmethod
    def _set_current(label: QLabel, snapshot: BmsSnapshot, signal_name: str) -> None:
        signal = snapshot.signals.get(signal_name)
        if signal is None or signal.value is None:
            label.setText("未知")
        else:
            label.setText("开启" if bool(signal.value) else "关闭")

    def summary_text(self) -> str:
        command = self.command()
        changes = "\n".join(
            f"- {CONTROL_NAMES[name]}：{'开启' if enabled else '关闭'}"
            for name, enabled in command.selected_changes
        )
        return (
            f"扩展帧 ID：0x{CTRL_INFO_FRAME_ID:08X}\n"
            f"DATA：{command.payload.hex(' ').upper()}\n\n"
            f"本次生效项：\n{changes or '- 未选择'}"
        )

    def _request_send(self) -> None:
        self.send_requested.emit(self.command())

    def _refresh(self) -> None:
        command = self.command()
        self.data_edit.setText(command.payload.hex(" ").upper())
        controls_enabled = self._unlocked and not self._pending
        for mask, target in (
            (self.charge_mask, self.charge_target),
            (self.discharge_mask, self.discharge_target),
            (self.balance_mask, self.balance_target),
        ):
            mask.setEnabled(controls_enabled)
            target.setEnabled(controls_enabled and mask.isChecked())
            target.setText("开启" if target.isChecked() else "关闭")
        self.send_button.setEnabled(
            controls_enabled
            and self._device_address == 0
            and command.mask != ControlMask.NONE
        )
