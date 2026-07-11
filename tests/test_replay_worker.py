from queue import Queue
from threading import Event
from time import monotonic, sleep

import pytest

from bms_can_monitor.canio.events import CanEventType
from bms_can_monitor.canio.replay_worker import (
    ReplayFormatError,
    ReplayWorker,
    load_replay_csv,
    write_replay_csv,
)
from bms_can_monitor.protocol import CanFrame


def test_replay_csv_round_trip_including_remote_frame(tmp_path):
    source = [
        CanFrame(0x02F4, bytes.fromhex("13 01 D7 11 33"), timestamp=1.0),
        CanFrame(
            0x18F128F4,
            bytes.fromhex("2C 01 90 01 E8 03 00 64"),
            timestamp=1.1,
            is_extended=True,
        ),
        CanFrame(0x321, b"", timestamp=1.2, is_remote=True, dlc=6),
    ]
    path = write_replay_csv(tmp_path / "frames.csv", source)
    loaded = load_replay_csv(path)
    assert [(frame.can_id, frame.data) for frame in loaded] == [
        (frame.can_id, frame.data) for frame in source
    ]
    assert loaded[1].is_extended is True
    assert loaded[2].is_remote is True
    assert loaded[2].dlc == 6
    assert all(frame.source == "replay_file" for frame in loaded)


def test_replay_csv_rejects_missing_columns_and_reverse_time(tmp_path):
    missing = tmp_path / "missing.csv"
    missing.write_text("timestamp,can_id\n1,0x123\n", encoding="utf-8")
    with pytest.raises(ReplayFormatError, match="missing columns"):
        load_replay_csv(missing)

    reverse = tmp_path / "reverse.csv"
    reverse.write_text(
        "timestamp,can_id,data\n2,0x123,01\n1,0x124,02\n",
        encoding="utf-8",
    )
    with pytest.raises(ReplayFormatError, match="non-decreasing"):
        load_replay_csv(reverse)


def test_replay_csv_accepts_unprefixed_hex_can_id(tmp_path):
    path = tmp_path / "hex-id.csv"
    path.write_text("timestamp,can_id,data\n1,02F4,01\n", encoding="utf-8")
    assert load_replay_csv(path)[0].can_id == 0x02F4


def test_replay_worker_rebases_time_and_finishes():
    output = Queue()
    finished = Event()
    events = []

    def event_sink(event):
        events.append(event)
        if event.event_type is CanEventType.REPLAY_FINISHED:
            finished.set()

    worker = ReplayWorker(
        [
            CanFrame(0x100, b"\x01", timestamp=10.0),
            CanFrame(0x101, b"\x02", timestamp=10.1),
        ],
        output,
        speed=100.0,
        event_sink=event_sink,
    )
    worker.start()
    assert finished.wait(1)
    worker.join(1)
    first = output.get_nowait()
    second = output.get_nowait()
    assert first.source == "replay"
    assert second.timestamp > first.timestamp
    assert worker.stats.emitted == 2
    assert worker.stats.loops_completed == 1
    assert [event.event_type for event in events] == [
        CanEventType.REPLAY_STARTED,
        CanEventType.REPLAY_FINISHED,
    ]


def test_replay_worker_reports_queue_overflow():
    overflow = Event()

    def event_sink(event):
        if event.event_type is CanEventType.RX_QUEUE_OVERFLOW:
            overflow.set()

    worker = ReplayWorker(
        [CanFrame(0x100, timestamp=0.0), CanFrame(0x101, timestamp=0.0)],
        Queue(maxsize=1),
        speed=100.0,
        event_sink=event_sink,
    )
    worker.start()
    assert overflow.wait(1)
    worker.join(1)
    assert worker.stats.emitted == 1
    assert worker.stats.dropped == 1


def test_replay_worker_stop_interrupts_long_delay():
    output = Queue()
    worker = ReplayWorker(
        [CanFrame(0x100, timestamp=0.0), CanFrame(0x101, timestamp=60.0)],
        output,
    )
    worker.start()
    assert output.get(timeout=1).can_id == 0x100
    worker.stop()
    worker.join(1)
    assert worker.is_running is False


def test_empty_replay_finishes_cleanly():
    finished = Event()

    def event_sink(event):
        if event.event_type is CanEventType.REPLAY_FINISHED:
            finished.set()

    worker = ReplayWorker([], Queue(), event_sink=event_sink)
    worker.start()
    assert finished.wait(1)
    worker.join(1)
    assert worker.stats.emitted == 0


class RepeatableStreamingSource:
    frame_count = 2

    def __init__(self):
        self.iterations = 0

    def iter_frames(self):
        self.iterations += 1
        yield CanFrame(0x100, b"\x01", timestamp=10.0)
        yield CanFrame(0x101, b"\x02", timestamp=10.001)


def test_replay_worker_accepts_non_iterable_streaming_source():
    source = RepeatableStreamingSource()
    output = Queue()
    worker = ReplayWorker(source, output, speed=100.0)

    worker.start()
    worker.join(1)

    assert source.iterations == 1
    assert [output.get_nowait().can_id for _ in range(2)] == [0x100, 0x101]


def test_looping_streaming_replay_reopens_source():
    source = RepeatableStreamingSource()
    worker = ReplayWorker(source, Queue(maxsize=100), speed=100.0, loop=True)
    worker.start()
    deadline = monotonic() + 1.0
    while source.iterations < 2 and monotonic() < deadline:
        sleep(0.005)
    worker.stop()
    worker.join(1)

    assert source.iterations >= 2
    assert worker.is_running is False
