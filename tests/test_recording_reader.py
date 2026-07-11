import sqlite3

import pytest

from bms_can_monitor.data import (
    RecordingReadError,
    RecordingReader,
    SessionMetadata,
    SessionRecorder,
    SqliteReplaySource,
)
from bms_can_monitor.protocol import CanFrame


def create_recording(tmp_path):
    database = tmp_path / "reader.sqlite3"
    recorder = SessionRecorder(database)
    session_id = recorder.start(
        SessionMetadata(
            started_at=10.0,
            dbc_sha256="b" * 64,
        )
    )
    recorder.record_frame(
        CanFrame(
            0x02F4,
            bytes.fromhex("13 01 D7 11 33"),
            timestamp=11.0,
            channel=1,
            hardware_timestamp=123,
            source="canalyst2",
        )
    )
    recorder.record_frame(
        CanFrame(
            0x18F428F5,
            bytes.fromhex("C8 00 00 00 28 0A 64"),
            timestamp=12.0,
            is_extended=True,
            channel=1,
            source="canalyst2",
        )
    )
    recorder.stop(ended_at=20.0, detected_addresses=(0, 1))
    return database, session_id


def test_reader_lists_v2_session_metadata_and_frame_bounds(tmp_path):
    database, session_id = create_recording(tmp_path)
    summary = RecordingReader(database).session(session_id)

    assert summary.storage_mode == "raw_only"
    assert summary.detected_addresses == (0, 1)
    assert summary.dbc_sha256 == "b" * 64
    assert summary.frame_count == 2
    assert summary.first_frame_timestamp == 11.0
    assert summary.last_frame_timestamp == 12.0
    assert summary.duration == 1.0


def test_reader_streams_frames_in_repeatable_chunks_and_is_read_only(tmp_path):
    database, session_id = create_recording(tmp_path)
    reader = RecordingReader(database)

    first = list(reader.iter_frames(session_id, batch_size=1))
    second = list(reader.iter_frames(session_id, batch_size=2))
    assert [(frame.can_id, frame.timestamp) for frame in first] == [
        (0x02F4, 11.0),
        (0x18F428F5, 12.0),
    ]
    assert [(frame.can_id, frame.data) for frame in second] == [
        (frame.can_id, frame.data) for frame in first
    ]
    assert first[0].hardware_timestamp == 123

    with reader._connect() as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM raw_frames")


def test_sqlite_replay_source_can_be_iterated_more_than_once(tmp_path):
    database, session_id = create_recording(tmp_path)
    source = SqliteReplaySource(database, session_id, batch_size=1)

    assert source.frame_count == 2
    assert [frame.can_id for frame in source.iter_frames()] == [
        0x02F4,
        0x18F428F5,
    ]
    assert [frame.can_id for frame in source.iter_frames()] == [
        0x02F4,
        0x18F428F5,
    ]


def test_reader_supports_unmodified_v1_database(tmp_path):
    database = tmp_path / "v1.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY,
                started_at REAL NOT NULL,
                ended_at REAL,
                device_type INTEGER NOT NULL,
                device_index INTEGER NOT NULL,
                channel INTEGER NOT NULL,
                bitrate INTEGER NOT NULL,
                device_address INTEGER NOT NULL,
                protocol_version TEXT NOT NULL,
                note TEXT NOT NULL
            );
            CREATE TABLE raw_frames (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                can_id INTEGER NOT NULL,
                is_extended INTEGER NOT NULL,
                is_remote INTEGER NOT NULL,
                dlc INTEGER NOT NULL,
                data BLOB NOT NULL,
                channel INTEGER NOT NULL,
                hardware_timestamp INTEGER,
                source TEXT NOT NULL
            );
            INSERT INTO sessions VALUES
                (1, 1, 2, 4, 0, 0, 250000, 3, 'V2.1', 'legacy');
            INSERT INTO raw_frames VALUES
                (1, 1, 1.5, 759, 0, 0, 1, X'00', 0, NULL, 'live');
            PRAGMA user_version = 1;
            """
        )

    summary = RecordingReader(database).session(1)
    assert summary.storage_mode == "legacy_signals"
    assert summary.detected_addresses == (3,)
    assert summary.frame_count == 1


def test_reader_rejects_missing_and_future_schema(tmp_path):
    with pytest.raises(RecordingReadError, match="not found"):
        RecordingReader(tmp_path / "missing.sqlite3")

    database = tmp_path / "future.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sessions(id INTEGER)")
        connection.execute("CREATE TABLE raw_frames(id INTEGER)")
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(RecordingReadError, match="newer than supported"):
        RecordingReader(database).list_sessions()
