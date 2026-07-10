"""Structured events emitted by adapters, workers, schedulers, and replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Callable, Mapping, TypeAlias


class CanEventType(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ADAPTER_ERROR = "adapter_error"
    WORKER_STARTED = "worker_started"
    WORKER_STOPPED = "worker_stopped"
    RX_TIMEOUT = "rx_timeout"
    RX_QUEUE_OVERFLOW = "rx_queue_overflow"
    TX_SUCCEEDED = "tx_succeeded"
    TX_FAILED = "tx_failed"
    REPLAY_STARTED = "replay_started"
    REPLAY_FINISHED = "replay_finished"
    REPLAY_STOPPED = "replay_stopped"
    REPLAY_ERROR = "replay_error"


@dataclass(frozen=True, slots=True)
class CanEvent:
    event_type: CanEventType
    message: str
    timestamp: float = field(default_factory=time)
    details: Mapping[str, object] = field(default_factory=dict)


EventSink: TypeAlias = Callable[[CanEvent], None]


def emit_event(
    sink: EventSink | None,
    event_type: CanEventType,
    message: str,
    **details: object,
) -> CanEvent:
    event = CanEvent(event_type=event_type, message=message, details=details)
    if sink is not None:
        sink(event)
    return event
