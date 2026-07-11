import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bms_can_monitor.data import SessionSummary
from bms_can_monitor.gui.replay_dialog import ReplaySessionDialog


def qapp():
    return QApplication.instance() or QApplication([])


def test_replay_session_dialog_lists_sessions_and_defaults_to_latest():
    qapp()
    sessions = (
        SessionSummary(1, 1.0, 2.0, 0, 0, 250_000, 0, "V2.1", "first"),
        SessionSummary(
            2,
            3.0,
            5.0,
            0,
            1,
            250_000,
            0,
            "V2.1",
            "second",
            storage_mode="raw_only",
            detected_addresses=(0, 1, 2),
            frame_count=100,
            first_frame_timestamp=3.0,
            last_frame_timestamp=5.0,
        ),
    )

    dialog = ReplaySessionDialog(sessions)

    assert dialog.table.rowCount() == 2
    assert dialog.selected_session_id == 2
    assert dialog.table.item(1, 3).text() == "100"
    assert dialog.table.item(1, 5).text() == "0, 1, 2"
    dialog.close()
