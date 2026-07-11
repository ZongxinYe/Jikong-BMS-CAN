import sqlite3

from bms_can_monitor.data import (
    DataPipeline,
    SessionMetadata,
    SessionRecorder,
    SignalRingBuffer,
)
from bms_can_monitor.protocol import CanFrame


def count_rows(database, table):
    with sqlite3.connect(database) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def table_exists(database, table):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None


def test_pipeline_updates_state_waveform_and_recorder(tmp_path):
    database = tmp_path / "pipeline.sqlite3"
    recorder = SessionRecorder(database, flush_interval=0.01)
    recorder.start(SessionMetadata(started_at=1.0))
    pipeline = DataPipeline(
        recorder=recorder,
        ring_buffer=SignalRingBuffer(["BattVolt", "SOC"]),
    )
    message = pipeline.process_frame(
        CanFrame(
            0x02F4,
            bytes.fromhex("13 01 D7 11 33"),
            timestamp=2.0,
            source="replay",
        )
    )
    assert message.name == "BATT_ST1"
    assert pipeline.state_store.get_value("BattVolt") == 27.5
    assert pipeline.ring_buffer.series("SOC")[0].value == 51.0
    pipeline.flush()
    recorder.stop()
    assert count_rows(database, "raw_frames") == 1
    assert table_exists(database, "signal_samples") is False


def test_pipeline_records_unknown_frame_without_interrupting(tmp_path):
    database = tmp_path / "unknown.sqlite3"
    recorder = SessionRecorder(database)
    recorder.start(SessionMetadata(started_at=1.0))
    pipeline = DataPipeline(recorder=recorder)
    assert pipeline.process_frame(CanFrame(0x123, b"\x01", timestamp=2.0)) is None
    assert pipeline.decode_errors == 1
    recorder.stop()
    assert count_rows(database, "raw_frames") == 1
    assert table_exists(database, "signal_samples") is False


def test_pipeline_assembles_cell_voltage_state(tmp_path):
    pipeline = DataPipeline()
    pipeline.process_frame(
        CanFrame(
            0x18E028F4,
            bytes.fromhex("AD 0E AB 0E A3 0E A6 0E"),
            timestamp=3.0,
            is_extended=True,
        )
    )
    assert pipeline.state_store.snapshot().cell_voltages_mv == {
        1: 3757,
        2: 3755,
        3: 3747,
        4: 3750,
    }
