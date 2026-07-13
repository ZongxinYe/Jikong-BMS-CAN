import json
import sqlite3

import pytest

from bms_can_monitor.canio.events import CanEvent, CanEventType
from bms_can_monitor.data import (
    RecorderError,
    SessionMetadata,
    SessionRecorder,
    WalCheckpointResult,
)
from bms_can_monitor.protocol import CanFrame, JikongBmsDecoder


def query_one(database, sql, parameters=()):
    with sqlite3.connect(database) as connection:
        return connection.execute(sql, parameters).fetchone()


def table_exists(database, name):
    return query_one(
        database,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ) is not None


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
            dbc_sha256="a" * 64,
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

    assert query_one(database, "PRAGMA user_version") == (2,)
    assert query_one(
        database,
        "SELECT COUNT(*) FROM raw_frames WHERE session_id = ?",
        (session_id,),
    ) == (1,)
    assert table_exists(database, "signal_samples") is False
    raw = query_one(
        database,
        "SELECT can_id, dlc, data, channel, hardware_timestamp FROM raw_frames",
    )
    assert raw == (0x02F6, 5, bytes.fromhex("13 01 D7 11 33"), 1, 1234)
    event = query_one(database, "SELECT event_type, message, details_json FROM events")
    assert event[:2] == ("connected", "设备已连接")
    assert json.loads(event[2]) == {"bitrate": 250_000, "channel": 1}

    result = recorder.stop(ended_at=110.0, detected_addresses=(2, 4))
    assert result is not None
    assert result.session_id == session_id
    assert result.ended_at == 110.0
    assert result.stats.frames_written == 1
    assert result.checkpoint.complete is True
    assert result.portable is True
    session = query_one(
        database,
        """
        SELECT started_at, ended_at, device_index, channel, device_address, note,
               storage_mode, detected_addresses_json, dbc_sha256
        FROM sessions WHERE id = ?
        """,
        (session_id,),
    )
    assert session == (
        100.0,
        110.0,
        1,
        1,
        2,
        "台架测试",
        "raw_only",
        "[2, 4]",
        "a" * 64,
    )
    assert recorder.stats.frames_written == 1
    assert recorder.stats.signals_written == 0
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


def test_clean_stop_is_complete_in_immutable_main_database(tmp_path):
    database = tmp_path / "portable.sqlite3"
    recorder = SessionRecorder(database, flush_interval=0.01)
    session_id = recorder.start(SessionMetadata(started_at=1.0))
    for index in range(20):
        recorder.record_frame(
            CanFrame(
                0x02F4,
                bytes.fromhex("13 01 D7 11 33"),
                timestamp=2.0 + index * 0.1,
            )
        )

    result = recorder.stop(ended_at=5.0)

    assert result is not None
    assert result.portable is True
    immutable_uri = f"{database.resolve().as_uri()}?mode=ro&immutable=1"
    with sqlite3.connect(immutable_uri, uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM raw_frames").fetchone() == (20,)
        assert connection.execute(
            "SELECT ended_at FROM sessions WHERE id = ?", (session_id,)
        ).fetchone() == (5.0,)


def test_checkpoint_busy_is_reported_without_claiming_portability(tmp_path, monkeypatch):
    database = tmp_path / "checkpoint-busy.sqlite3"
    recorder = SessionRecorder(database)
    recorder.start(SessionMetadata(started_at=1.0))
    recorder.record_frame(CanFrame(0x123, b"\x01", timestamp=2.0))
    monkeypatch.setattr(
        recorder,
        "_checkpoint_wal",
        lambda _connection: WalCheckpointResult(
            busy=1,
            log_pages=2,
            checkpointed_pages=1,
        ),
    )

    result = recorder.stop(ended_at=3.0)

    assert result is not None
    assert result.checkpoint.busy == 1
    assert result.portable is False
    assert query_one(database, "SELECT COUNT(*) FROM raw_frames") == (1,)


def test_v1_schema_is_upgraded_without_deleting_legacy_signals(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at REAL NOT NULL,
                ended_at REAL,
                device_type INTEGER NOT NULL,
                device_index INTEGER NOT NULL,
                channel INTEGER NOT NULL,
                bitrate INTEGER NOT NULL,
                device_address INTEGER NOT NULL,
                protocol_version TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE signal_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                message_name TEXT NOT NULL,
                signal_name TEXT NOT NULL,
                value_real REAL,
                value_text TEXT,
                raw_value_real REAL,
                unit TEXT,
                source_frame_id INTEGER NOT NULL
            );
            INSERT INTO sessions (
                started_at, device_type, device_index, channel, bitrate,
                device_address, protocol_version, note
            ) VALUES (1, 4, 0, 0, 250000, 2, 'V2.1', 'legacy');
            INSERT INTO signal_samples (
                session_id, timestamp, message_name, signal_name,
                value_real, raw_value_real, unit, source_frame_id
            ) VALUES (1, 2, 'BATT_ST1', 'SOC', 51, 51, '%', 756);
            PRAGMA user_version = 1;
            """
        )

    recorder = SessionRecorder(database)
    new_session = recorder.start(SessionMetadata(started_at=3.0))
    recorder.stop(ended_at=4.0)

    assert new_session == 2
    assert query_one(database, "PRAGMA user_version") == (2,)
    assert query_one(database, "SELECT COUNT(*) FROM signal_samples") == (1,)
    assert query_one(
        database,
        "SELECT storage_mode, detected_addresses_json FROM sessions WHERE id=1",
    ) == ("legacy_signals", "[2]")
    assert query_one(
        database,
        "SELECT storage_mode FROM sessions WHERE id=2",
    ) == ("raw_only",)


def test_recorder_rejects_future_schema_version(tmp_path):
    database = tmp_path / "future.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(RecorderError, match="newer than supported"):
        SessionRecorder(database).start()
