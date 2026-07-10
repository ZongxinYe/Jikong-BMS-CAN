"""Single-frame sending and application-managed periodic transmission."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Condition, Thread
from time import monotonic
from uuid import uuid4

from bms_can_monitor.protocol.models import CanFrame

from .events import CanEventType, EventSink, emit_event
from .interfaces import CanAdapter


@dataclass(slots=True)
class _PeriodicTask:
    task_id: str
    frame: CanFrame
    interval_seconds: float
    remaining: int | None
    next_due: float
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    active: bool = True


@dataclass(frozen=True, slots=True)
class TxTaskSnapshot:
    task_id: str
    frame: CanFrame
    interval_seconds: float
    remaining: int | None
    attempts: int
    successes: int
    failures: int
    active: bool


class TxScheduler:
    def __init__(
        self,
        adapter: CanAdapter,
        *,
        event_sink: EventSink | None = None,
        daemon: bool = True,
    ) -> None:
        self.adapter = adapter
        self._event_sink = event_sink
        self._daemon = daemon
        self._condition = Condition()
        self._tasks: dict[str, _PeriodicTask] = {}
        self._stop_requested = False
        self._thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def tasks(self) -> tuple[TxTaskSnapshot, ...]:
        with self._condition:
            return tuple(self._snapshot(task) for task in self._tasks.values())

    @staticmethod
    def _snapshot(task: _PeriodicTask) -> TxTaskSnapshot:
        return TxTaskSnapshot(
            task_id=task.task_id,
            frame=task.frame,
            interval_seconds=task.interval_seconds,
            remaining=task.remaining,
            attempts=task.attempts,
            successes=task.successes,
            failures=task.failures,
            active=task.active,
        )

    def start(self) -> None:
        if self.is_running:
            return
        if not self.adapter.is_started:
            raise RuntimeError("CAN adapter must be started before the TX scheduler")
        self._stop_requested = False
        self._thread = Thread(
            target=self._run,
            name="can-tx-scheduler",
            daemon=self._daemon,
        )
        self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def send_once(self, frame: CanFrame) -> int:
        try:
            result = self.adapter.send(frame)
        except Exception as exc:
            emit_event(
                self._event_sink,
                CanEventType.TX_FAILED,
                f"CAN frame 0x{frame.can_id:X} send failed: {exc}",
                can_id=frame.can_id,
                error=repr(exc),
            )
            raise
        emit_event(
            self._event_sink,
            CanEventType.TX_SUCCEEDED,
            f"CAN frame 0x{frame.can_id:X} sent",
            can_id=frame.can_id,
            result=result,
        )
        return result

    def add_periodic(
        self,
        frame: CanFrame,
        *,
        interval_ms: int,
        count: int | None = None,
        start_immediately: bool = True,
    ) -> str:
        if interval_ms < 1:
            raise ValueError("periodic interval must be at least 1 ms")
        if count is not None and count < 1:
            raise ValueError("periodic send count must be positive or None")
        task_id = uuid4().hex
        interval_seconds = interval_ms / 1000.0
        first_delay = 0.0 if start_immediately else interval_seconds
        task = _PeriodicTask(
            task_id=task_id,
            frame=frame,
            interval_seconds=interval_seconds,
            remaining=count,
            next_due=monotonic() + first_delay,
        )
        with self._condition:
            self._tasks[task_id] = task
            self._condition.notify_all()
        return task_id

    def cancel(self, task_id: str) -> bool:
        with self._condition:
            task = self._tasks.get(task_id)
            if task is None or not task.active:
                return False
            task.active = False
            self._condition.notify_all()
            return True

    def remove_finished(self) -> int:
        with self._condition:
            finished = [task_id for task_id, task in self._tasks.items() if not task.active]
            for task_id in finished:
                del self._tasks[task_id]
            return len(finished)

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._stop_requested:
                    return
                active = [task for task in self._tasks.values() if task.active]
                if not active:
                    self._condition.wait()
                    continue
                task = min(active, key=lambda item: item.next_due)
                delay = task.next_due - monotonic()
                if delay > 0:
                    self._condition.wait(delay)
                    continue

            success = False
            error: Exception | None = None
            result = 0
            try:
                result = self.adapter.send(task.frame)
                success = result == 1
                if not success:
                    error = RuntimeError(f"adapter returned {result}")
            except Exception as exc:
                error = exc

            with self._condition:
                task.attempts += 1
                if success:
                    task.successes += 1
                else:
                    task.failures += 1
                if task.remaining is not None:
                    task.remaining -= 1
                    if task.remaining == 0:
                        task.active = False
                if task.active:
                    task.next_due = max(
                        task.next_due + task.interval_seconds,
                        monotonic(),
                    )
                snapshot = self._snapshot(task)

            if success:
                emit_event(
                    self._event_sink,
                    CanEventType.TX_SUCCEEDED,
                    f"Periodic CAN frame 0x{task.frame.can_id:X} sent",
                    task_id=task.task_id,
                    can_id=task.frame.can_id,
                    result=result,
                    task=snapshot,
                )
            else:
                emit_event(
                    self._event_sink,
                    CanEventType.TX_FAILED,
                    f"Periodic CAN frame 0x{task.frame.can_id:X} send failed: {error}",
                    task_id=task.task_id,
                    can_id=task.frame.can_id,
                    error=repr(error),
                    task=snapshot,
                )
