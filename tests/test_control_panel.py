import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bms_can_monitor.gui.control_panel import ControlPanel
from bms_can_monitor.protocol import ControlMask


def qapp():
    return QApplication.instance() or QApplication([])


def test_control_panel_is_locked_and_unmasked_by_default():
    qapp()
    panel = ControlPanel()
    assert panel.is_unlocked is False
    assert panel.command().mask == ControlMask.NONE
    assert panel.send_button.isEnabled() is False


def test_control_panel_builds_masked_command_and_preview():
    qapp()
    panel = ControlPanel()
    panel.set_unlocked(True)
    panel.charge_mask.setChecked(True)
    panel.charge_target.setChecked(True)
    panel.balance_mask.setChecked(True)

    command = panel.command()
    assert command.mask == ControlMask.CHARGE | ControlMask.BALANCE
    assert command.charge_on is True
    assert command.balance_on is False
    assert panel.data_edit.text() == "05 01 00 00 00 00 00 00"
    assert panel.send_button.isEnabled() is True
    assert "充电开关：开启" in panel.summary_text()
    assert "放电开关" not in panel.summary_text()


def test_non_default_address_disables_panel_send():
    qapp()
    panel = ControlPanel()
    panel.set_unlocked(True)
    panel.charge_mask.setChecked(True)
    panel.set_device_address(2)
    assert panel.frame_id_edit.text() == "不可发送"
    assert panel.send_button.isEnabled() is False
