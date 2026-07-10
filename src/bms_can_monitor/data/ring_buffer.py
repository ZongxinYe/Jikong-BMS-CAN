"""Bounded, thread-safe time-series buffers for selected waveform signals."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite
from threading import RLock
from typing import Iterable, Mapping

from bms_can_monitor.protocol.models import BmsSnapshot, DecodedMessage, SignalValue


@dataclass(frozen=True, slots=True)
class SignalPoint:
    timestamp: float
    value: float


class SignalRingBuffer:
    def __init__(
        self,
        signals: Iterable[str] = (),
        *,
        window_seconds: float = 300.0,
        max_points_per_signal: int = 100_000,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("waveform window must be positive")
        if max_points_per_signal < 1:
            raise ValueError("max points per signal must be positive")
        self.window_seconds = float(window_seconds)
        self.max_points_per_signal = int(max_points_per_signal)
        self._lock = RLock()
        self._selected: set[str] = set()
        self._buffers: dict[str, deque[SignalPoint]] = {}
        self.select(signals)

    @property
    def selected_signals(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._selected))

    def select(self, signals: Iterable[str], *, retain_existing: bool = False) -> None:
        selected = {str(name) for name in signals if str(name)}
        with self._lock:
            if not retain_existing:
                for name in set(self._buffers) - selected:
                    del self._buffers[name]
            self._selected = selected
            for name in selected:
                self._buffers.setdefault(
                    name, deque(maxlen=self.max_points_per_signal)
                )

    def add_signal(self, name: str) -> None:
        if not name:
            raise ValueError("signal name cannot be empty")
        with self._lock:
            self._selected.add(name)
            self._buffers.setdefault(
                name, deque(maxlen=self.max_points_per_signal)
            )

    def remove_signal(self, name: str, *, retain_data: bool = False) -> None:
        with self._lock:
            self._selected.discard(name)
            if not retain_data:
                self._buffers.pop(name, None)

    def append(self, name: str, timestamp: float, value: SignalValue) -> bool:
        numeric = self._numeric_value(value)
        if numeric is None:
            return False
        with self._lock:
            if name not in self._selected:
                return False
            buffer = self._buffers[name]
            if buffer and timestamp < buffer[-1].timestamp:
                return False
            buffer.append(SignalPoint(float(timestamp), numeric))
            self._prune_buffer(buffer, float(timestamp))
            return True

    @staticmethod
    def _numeric_value(value: SignalValue) -> float | None:
        if value is None or isinstance(value, str):
            return None
        numeric = float(value)
        return numeric if isfinite(numeric) else None

    def append_message(self, message: DecodedMessage) -> tuple[str, ...]:
        appended = [
            signal.name
            for signal in message.signals
            if self.append(signal.name, signal.timestamp, signal.value)
        ]
        return tuple(appended)

    def append_snapshot(self, snapshot: BmsSnapshot) -> tuple[str, ...]:
        appended = [
            signal.name
            for signal in snapshot.signals.values()
            if self.append(signal.name, signal.timestamp, signal.value)
        ]
        return tuple(appended)

    def _prune_buffer(self, buffer: deque[SignalPoint], timestamp: float) -> None:
        cutoff = timestamp - self.window_seconds
        while buffer and buffer[0].timestamp < cutoff:
            buffer.popleft()

    def prune(self, timestamp: float) -> None:
        with self._lock:
            for buffer in self._buffers.values():
                self._prune_buffer(buffer, float(timestamp))

    def series(
        self, name: str, *, since: float | None = None
    ) -> tuple[SignalPoint, ...]:
        with self._lock:
            points = tuple(self._buffers.get(name, ()))
        if since is None:
            return points
        return tuple(point for point in points if point.timestamp >= since)

    def snapshot(self) -> Mapping[str, tuple[SignalPoint, ...]]:
        with self._lock:
            return {
                name: tuple(self._buffers.get(name, ()))
                for name in sorted(self._selected)
            }

    def clear(self, name: str | None = None) -> None:
        with self._lock:
            if name is None:
                for buffer in self._buffers.values():
                    buffer.clear()
            elif name in self._buffers:
                self._buffers[name].clear()
