"""Small protocols that keep workers independent of CANalyst-II."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from bms_can_monitor.protocol.models import CanFrame


@runtime_checkable
class CanAdapter(Protocol):
    @property
    def is_started(self) -> bool: ...

    def receive(self, max_frames: int, wait_ms: int = 0) -> list[CanFrame]: ...

    def send(self, frame: CanFrame) -> int: ...
