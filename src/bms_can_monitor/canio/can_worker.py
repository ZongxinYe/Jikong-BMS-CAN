"""Background batch receiver that writes unified frames to a safe queue."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Full, Queue
from threading import Lock, Event, Thread
from time import monotonic

from bms_can_monitor.protocol.models import CanFrame

from .events import CanEventType, EventSink, emit_event
from .interfaces import CanAdapter


@dataclass(frozen=True, slots=True)
class ReceiveWorkerStats:
    batches: int
    frames_received: int
    frames_dropped: int
    errors: int


class CanReceiveWorker:
    def __init__(
        self,
        adapter: CanAdapter,
        output_queue: Queue[CanFrame],
        *,
        batch_size: int = 2500,
        wait_ms: int = 20,
        timeout_seconds: float | None = 2.0,
        event_sink: EventSink | None = None,
        daemon: bool = True,
    ) -> None:
        if not 1 <= batch_size <= 2500:
            raise ValueError("batch size must be 1..2500")
        if not 0 <= wait_ms <= 1000:
            raise ValueError("receive wait must be 0..1000 ms")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout must be positive or None")
        self.adapter = adapter
        self.output_queue = output_queue
        self.batch_size = batch_size
        self.wait_ms = wait_ms
        self.timeout_seconds = timeout_seconds
        self._event_sink = event_sink
        self._daemon = daemon
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._stats_lock = Lock()
        self._batches = 0
        self._frames_received = 0
        self._frames_dropped = 0
        self._errors = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def stats(self) -> ReceiveWorkerStats:
        with self._stats_lock:
            return ReceiveWorkerStats(
                batches=self._batches,
                frames_received=self._frames_received,
                frames_dropped=self._frames_dropped,
                errors=self._errors,
            )

    def start(self) -> None:
        if self.is_running:
            return
        if not self.adapter.is_started:
            raise RuntimeError("CAN adapter must be started before the receive worker")
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            name="can-receive-worker",
            daemon=self._daemon,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        emit_event(
            self._event_sink,
            CanEventType.WORKER_STARTED,
            "CAN receive worker started",
        )
        last_frame_at = monotonic()
        timeout_reported = False
        try:
            while not self._stop_event.is_set():
                try:
                    frames = self.adapter.receive(self.batch_size, self.wait_ms)
                except Exception as exc:
                    with self._stats_lock:
                        self._errors += 1
                    emit_event(
                        self._event_sink,
                        CanEventType.ADAPTER_ERROR,
                        f"CAN receive worker stopped after error: {exc}",
                        component="receive_worker",
                        error=repr(exc),
                    )
                    break

                if frames:
                    with self._stats_lock:
                        self._batches += 1
                        self._frames_received += len(frames)
                    last_frame_at = monotonic()
                    timeout_reported = False
                    dropped_in_batch = 0
                    for frame in frames:
                        try:
                            self.output_queue.put_nowait(frame)
                        except Full:
                            dropped_in_batch += 1
                    if dropped_in_batch:
                        with self._stats_lock:
                            self._frames_dropped += dropped_in_batch
                        emit_event(
                            self._event_sink,
                            CanEventType.RX_QUEUE_OVERFLOW,
                            f"Dropped {dropped_in_batch} received CAN frame(s)",
                            dropped=dropped_in_batch,
                        )
                    continue

                if self.wait_ms == 0:
                    self._stop_event.wait(0.001)

                if (
                    self.timeout_seconds is not None
                    and not timeout_reported
                    and monotonic() - last_frame_at >= self.timeout_seconds
                ):
                    timeout_reported = True
                    emit_event(
                        self._event_sink,
                        CanEventType.RX_TIMEOUT,
                        "No CAN frames received within timeout",
                        timeout_seconds=self.timeout_seconds,
                    )
        finally:
            emit_event(
                self._event_sink,
                CanEventType.WORKER_STOPPED,
                "CAN receive worker stopped",
                stats=self.stats,
            )
