import json
import sqlite3

import pytest

from bms_can_monitor.canio.events import CanEvent, CanEventType
from bms_can_monitor.data import RecorderError, SessionMetadata, SessionRecorder
from bms_can_monitor.protocol import CanFrame, JikongBmsDecoder


def query_one(database, sql, parameters=()):
    with sqlite3.connect(database) as connection:
        return connection.execute(sql, parameters).fetchone()


def test_recorder_creates_schema_and_persists_complete_session(tmp_path):
    database = tmp_path / "session.sqlite3"
    recorder = SessionRecorder(database, batch_size=10, flush_interval=0.01)
    session_id = recorder.start(
        SessionMetadata(
            started_at=100.0,
            device_index=1,
            channel=1,
            bitrate=250_000,
            device_address=2,
            note="台架测试",
        )
    )

    frame = CanFrame(
        0x02F6,
        bytes.fromhex("13 01 D7 11 33"),
        timestamp=101.0,
        channel=1,
        hardware_timestamp=1234,
        source="canalyst2",
    )
    message = JikongBmsDecoder().decode(frame, device_address=2)
    recorder.record_frame(frame)
    recorder.record_message(message)
    recorder.record_event(
        CanEvent(
            CanEventType.CONNECTED,
            "设备已连接",
            timestamp=100.5,
            details={"channel": 1, "bitrate": 250_000},
        )
    )
    recorder.flush()

    assert query_one(database, "PRAGMA user_version") == (1,)
    assert query_one(
        database,
        "SELECT COUNT(*) FROM raw_frames WHERE session_id = ?",
        (session_id,),
    ) == (1,)
    assert query_one(
        database,
        "SELECT COUNT(*) FROM signal_samples WHERE session_id = ?",
        (session_id,),
    ) == (3,)
    raw = query_one(
        database,
        "SELECT can_id, dlc, data, channel, hardware_timestamp FROM raw_frames",
    )
    assert raw == (0x02F6, 5, bytes.fromhex("13 01 D7 11 33"), 1, 1234)
    event = query_one(database, "SELECT event_type, message, details_json FROM events")
    assert event[:2] == ("connected", "设备已连接")
    assert json.loads(event[2]) == {"bitrate": 250_000, "channel": 1}

    recorder.stop(ended_at=110.0)
    session = query_one(
        database,
        """
        SELECT started_at, ended_at, device_index, channel, device_address, note
        FROM sessions WHERE id = ?
        """,
        (session_id,),
    )
    assert session == (100.0, 110.0, 1, 1, 2, "台架测试")
    assert recorder.stats.frames_written == 1
    assert recorder.stats.signals_written == 3
    assert recorder.stats.events_written == 1


def test_recorder_requires_running_session(tmp_path):
    recorder = SessionRecorder(tmp_path / "not-started.sqlite3")
    with pytest.raises(RecorderError, match="not running"):
        recorder.record_frame(CanFrame(0x123))
    recorder.start()
    with pytest.raises(RecorderError, match="already owns"):
        recorder.start()
    recorder.stop()


def test_recorder_context_stops_session(tmp_path):
    database = tmp_path / "context.sqlite3"
    recorder = SessionRecorder(database)
    recorder.start(SessionMetadata(started_at=1.0))
    with recorder:
        recorder.record_event_data("note", "context event", timestamp=2.0)
    assert query_one(database, "SELECT ended_at IS NOT NULL FROM sessions") == (1,)
    assert query_one(database, "SELECT COUNT(*) FROM events") == (1,)


def test_recorder_batches_high_frame_volume_without_loss(tmp_path):
    database = tmp_path / "volume.sqlite3"
    recorder = SessionRecorder(
        database,
        batch_size=250,
        flush_interval=0.01,
        queue_capacity=10_000,
    )
    recorder.start(SessionMetadata(started_at=1.0))
    for index in range(5_000):
        recorder.record_frame(
            CanFrame(
                0x02F4,
                bytes.fromhex("13 01 D7 11 33"),
                timestamp=1.0 + index * 0.02,
            )
        )
    recorder.flush(timeout=10.0)
    recorder.stop(timeout=10.0)
    assert query_one(database, "SELECT COUNT(*) FROM raw_frames") == (5_000,)
    assert recorder.stats.frames_written == 5_000
    assert recorder.stats.dropped_items == 0
