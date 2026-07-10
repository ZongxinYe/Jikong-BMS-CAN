from __future__ import annotations

from queue import Queue
from threading import Event
from time import sleep

from bms_can_monitor.canio.can_worker import CanReceiveWorker
from bms_can_monitor.canio.events import CanEventType
from bms_can_monitor.protocol import CanFrame


class ReceiveAdapter:
    is_started = True

    def __init__(self, batches):
        self.batches = list(batches)

    def receive(self, max_frames: int, wait_ms: int = 0):
        if self.batches:
            batch = self.batches.pop(0)
            if isinstance(batch, Exception):
                raise batch
            return batch
        sleep(max(wait_ms, 1) / 1000)
        return []

    def send(self, frame: CanFrame) -> int:
        return 1


def test_receive_worker_batches_frames_into_queue():
    frames = [CanFrame(0x100, b"\x01"), CanFrame(0x101, b"\x02")]
    output = Queue()
    worker = CanReceiveWorker(
        ReceiveAdapter([frames]), output, batch_size=10, wait_ms=1, timeout_seconds=None
    )
    worker.start()
    assert output.get(timeout=1).can_id == 0x100
    assert output.get(timeout=1).can_id == 0x101
    worker.stop()
    worker.join(1)
    assert worker.is_running is False
    assert worker.stats.batches == 1
    assert worker.stats.frames_received == 2
    assert worker.stats.frames_dropped == 0


def test_receive_worker_reports_queue_overflow():
    overflow = Event()
    events = []

    def event_sink(event):
        events.append(event)
        if event.event_type is CanEventType.RX_QUEUE_OVERFLOW:
            overflow.set()

    output = Queue(maxsize=1)
    worker = CanReceiveWorker(
        ReceiveAdapter([[CanFrame(0x100), CanFrame(0x101)]]),
        output,
        wait_ms=1,
        timeout_seconds=None,
        event_sink=event_sink,
    )
    worker.start()
    assert overflow.wait(1)
    worker.stop()
    worker.join(1)
    assert worker.stats.frames_received == 2
    assert worker.stats.frames_dropped == 1
    assert any(event.event_type is CanEventType.WORKER_STOPPED for event in events)


def test_receive_worker_emits_one_timeout_until_data_resumes():
    timeout = Event()
    events = []

    def event_sink(event):
        events.append(event)
        if event.event_type is CanEventType.RX_TIMEOUT:
            timeout.set()

    worker = CanReceiveWorker(
        ReceiveAdapter([]),
        Queue(),
        wait_ms=1,
        timeout_seconds=0.01,
        event_sink=event_sink,
    )
    worker.start()
    assert timeout.wait(1)
    worker.stop()
    worker.join(1)
    assert sum(event.event_type is CanEventType.RX_TIMEOUT for event in events) == 1


def test_receive_worker_stops_after_adapter_error():
    stopped = Event()
    events = []

    def event_sink(event):
        events.append(event)
        if event.event_type is CanEventType.WORKER_STOPPED:
            stopped.set()

    worker = CanReceiveWorker(
        ReceiveAdapter([RuntimeError("device removed")]),
        Queue(),
        event_sink=event_sink,
    )
    worker.start()
    assert stopped.wait(1)
    worker.join(1)
    assert worker.stats.errors == 1
    assert any(event.event_type is CanEventType.ADAPTER_ERROR for event in events)
