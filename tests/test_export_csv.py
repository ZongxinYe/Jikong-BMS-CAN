import csv

import pytest

from bms_can_monitor.canio import load_replay_csv
from bms_can_monitor.data import (
    ExportError,
    SessionMetadata,
    SessionRecorder,
    export_events,
    export_raw_frames,
    export_session,
    export_signals_wide,
    list_sessions,
)
from bms_can_monitor.protocol import CanFrame


def create_recording(tmp_path):
    database = tmp_path / "recording.sqlite3"
    recorder = SessionRecorder(database, flush_interval=0.01)
    session_id = recorder.start(
        SessionMetadata(started_at=10.0, note="导出测试")
    )
    status_frame = CanFrame(
        0x02F4,
        bytes.fromhex("13 01 D7 11 33"),
        timestamp=11.0,
        source="replay",
    )
    temp_frame = CanFrame(
        0x05F4,
        bytes.fromhex("48 06 2F 01 3F"),
        timestamp=12.0,
        source="replay",
    )
    for frame in (status_frame, temp_frame):
        recorder.record_frame(frame)
    recorder.record_event_data(
        "alarm",
        "温度告警",
        timestamp=12.5,
        details={"level": 2},
    )
    recorder.stop(ended_at=20.0)
    return database, session_id


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_raw_export_can_be_loaded_by_phase2_replay(tmp_path):
    database, session_id = create_recording(tmp_path)
    output = export_raw_frames(database, tmp_path / "raw.csv", session_id)
    replay = load_replay_csv(output)
    assert [frame.can_id for frame in replay] == [0x02F4, 0x05F4]
    assert replay[0].data == bytes.fromhex("13 01 D7 11 33")
    assert replay[1].timestamp == 12.0


def test_signal_wide_export_forward_fills_latest_values(tmp_path):
    database, session_id = create_recording(tmp_path)
    output = export_signals_wide(
        database,
        tmp_path / "signals.csv",
        session_id,
        signal_names=("BattVolt", "SOC", "MaxCellTemp"),
    )
    rows = read_csv(output)
    assert len(rows) == 2
    assert rows[0] == {
        "timestamp": "11.000000000",
        "BattVolt": "27.5",
        "SOC": "51",
        "MaxCellTemp": "",
    }
    assert rows[1] == {
        "timestamp": "12.000000000",
        "BattVolt": "27.5",
        "SOC": "51",
        "MaxCellTemp": "22",
    }


def test_signal_export_decodes_only_requested_bms_address(tmp_path):
    database = tmp_path / "multi.sqlite3"
    recorder = SessionRecorder(database)
    session_id = recorder.start(SessionMetadata(started_at=1.0))
    recorder.record_frame(
        CanFrame(0x02F4, bytes.fromhex("13 01 D7 11 33"), timestamp=2.0)
    )
    recorder.record_frame(
        CanFrame(0x02F5, bytes.fromhex("64 00 A0 0F 22"), timestamp=3.0)
    )
    recorder.stop(detected_addresses=(0, 1))

    output = export_signals_wide(
        database,
        tmp_path / "bms1.csv",
        session_id,
        signal_names=("BattVolt", "SOC"),
        device_address=1,
    )

    assert read_csv(output) == [
        {"timestamp": "3.000000000", "BattVolt": "10", "SOC": "34"}
    ]


def test_event_and_session_exports_preserve_unicode(tmp_path):
    database, session_id = create_recording(tmp_path)
    events = export_events(database, tmp_path / "events.csv", session_id)
    assert read_csv(events)[0]["message"] == "温度告警"
    summaries = list_sessions(database)
    assert summaries[0].note == "导出测试"
    assert summaries[0].ended_at == 20.0

    exported = export_session(database, tmp_path / "all", session_id)
    assert exported.raw_frames.is_file()
    assert exported.signals_wide.is_file()
    assert exported.events.is_file()


def test_export_rejects_missing_database_and_session(tmp_path):
    with pytest.raises(ExportError, match="not found"):
        list_sessions(tmp_path / "missing.sqlite3")

    database, _ = create_recording(tmp_path)
    with pytest.raises(ExportError, match="does not exist"):
        export_raw_frames(database, tmp_path / "none.csv", 999)


def test_event_export_neutralizes_excel_formula_prefix(tmp_path):
    database = tmp_path / "formula.sqlite3"
    recorder = SessionRecorder(database)
    session_id = recorder.start(SessionMetadata(started_at=1.0))
    recorder.record_event_data("note", "=1+1", timestamp=2.0)
    recorder.stop()
    output = export_events(database, tmp_path / "formula.csv", session_id)
    assert read_csv(output)[0]["message"] == "'=1+1"
