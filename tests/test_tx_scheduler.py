from __future__ import annotations

from threading import Event
from time import monotonic, sleep

import pytest

from bms_can_monitor.canio.events import CanEventType
from bms_can_monitor.canio.tx_scheduler import TxScheduler
from bms_can_monitor.protocol import CanFrame


class SendAdapter:
    is_started = True

    def __init__(self, results=None):
        self.results = list(results or [])
        self.sent = []
        self.sent_event = Event()

    def receive(self, max_frames: int, wait_ms: int = 0):
        return []

    def send(self, frame: CanFrame) -> int:
        self.sent.append(frame)
        if len(self.sent) >= 3:
            self.sent_event.set()
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return 1


def wait_until(predicate, timeout=1.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return True
        sleep(0.001)
    return False


def test_send_once_emits_success_and_failure_events():
    adapter = SendAdapter([1, RuntimeError("offline")])
    events = []
    scheduler = TxScheduler(adapter, event_sink=events.append)
    assert scheduler.send_once(CanFrame(0x123, b"\x01")) == 1
    with pytest.raises(RuntimeError, match="offline"):
        scheduler.send_once(CanFrame(0x124, b"\x02"))
    assert [event.event_type for event in events] == [
        CanEventType.TX_SUCCEEDED,
        CanEventType.TX_FAILED,
    ]


def test_periodic_scheduler_tracks_three_successes():
    adapter = SendAdapter()
    scheduler = TxScheduler(adapter)
    task_id = scheduler.add_periodic(CanFrame(0x321, b"\x01"), interval_ms=5, count=3)
    scheduler.start()
    assert adapter.sent_event.wait(1)
    assert wait_until(lambda: scheduler.tasks[0].active is False)
    scheduler.stop()
    scheduler.join(1)
    task = next(task for task in scheduler.tasks if task.task_id == task_id)
    assert task.attempts == 3
    assert task.successes == 3
    assert task.failures == 0
    assert task.remaining == 0


def test_periodic_scheduler_records_failure_and_continues():
    adapter = SendAdapter([RuntimeError("first failed"), 1])
    scheduler = TxScheduler(adapter)
    task_id = scheduler.add_periodic(CanFrame(0x456), interval_ms=2, count=2)
    scheduler.start()
    assert wait_until(
        lambda: any(task.task_id == task_id and not task.active for task in scheduler.tasks)
    )
    scheduler.stop()
    scheduler.join(1)
    task = next(task for task in scheduler.tasks if task.task_id == task_id)
    assert task.attempts == 2
    assert task.successes == 1
    assert task.failures == 1


def test_scheduler_requires_started_adapter():
    adapter = SendAdapter()
    adapter.is_started = False
    scheduler = TxScheduler(adapter)
    with pytest.raises(RuntimeError, match="started"):
        scheduler.start()
