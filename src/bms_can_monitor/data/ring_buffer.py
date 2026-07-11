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


@dataclass(frozen=True, order=True, slots=True)
class BmsSignalKey:
    device_address: int
    signal_name: str

    def __post_init__(self) -> None:
        if not 0 <= self.device_address <= 0x0B:
            raise ValueError("BMS device address must be 0..11")
        if not self.signal_name:
            raise ValueError("signal name cannot be empty")


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
        self._default_device_address = 0
        self._selected: set[str] = set()
        self._buffers: dict[BmsSignalKey, deque[SignalPoint]] = {}
        self.select(signals)

    @property
    def selected_signals(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._selected))

    @property
    def default_device_address(self) -> int:
        with self._lock:
            return self._default_device_address

    @default_device_address.setter
    def default_device_address(self, value: int) -> None:
        address = int(value)
        if not 0 <= address <= 0x0B:
            raise ValueError("BMS device address must be 0..11")
        with self._lock:
            self._default_device_address = address

    def select(self, signals: Iterable[str], *, retain_existing: bool = False) -> None:
        selected = {str(name) for name in signals if str(name)}
        with self._lock:
            if not retain_existing:
                for key in tuple(self._buffers):
                    if key.signal_name not in selected:
                        del self._buffers[key]
            self._selected = selected

    def add_signal(self, name: str) -> None:
        if not name:
            raise ValueError("signal name cannot be empty")
        with self._lock:
            self._selected.add(name)

    def remove_signal(self, name: str, *, retain_data: bool = False) -> None:
        with self._lock:
            self._selected.discard(name)
            if not retain_data:
                for key in tuple(self._buffers):
                    if key.signal_name == name:
                        del self._buffers[key]

    def _key(
        self,
        name: str | BmsSignalKey,
        device_address: int | None,
    ) -> BmsSignalKey:
        if isinstance(name, BmsSignalKey):
            return name
        address = (
            self.default_device_address
            if device_address is None
            else int(device_address)
        )
        return BmsSignalKey(address, str(name))

    def append(
        self,
        name: str | BmsSignalKey,
        timestamp: float,
        value: SignalValue,
        *,
        device_address: int | None = None,
    ) -> bool:
        numeric = self._numeric_value(value)
        if numeric is None:
            return False
        key = self._key(name, device_address)
        with self._lock:
            if key.signal_name not in self._selected:
                return False
            buffer = self._buffers.setdefault(
                key, deque(maxlen=self.max_points_per_signal)
            )
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
            if self.append(
                signal.name,
                signal.timestamp,
                signal.value,
                device_address=message.device_address,
            )
        ]
        return tuple(appended)

    def append_snapshot(
        self,
        snapshot: BmsSnapshot,
        *,
        device_address: int = 0,
    ) -> tuple[str, ...]:
        appended = [
            signal.name
            for signal in snapshot.signals.values()
            if self.append(
                signal.name,
                signal.timestamp,
                signal.value,
                device_address=device_address,
            )
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
        self,
        name: str | BmsSignalKey,
        *,
        device_address: int | None = None,
        since: float | None = None,
    ) -> tuple[SignalPoint, ...]:
        key = self._key(name, device_address)
        with self._lock:
            points = tuple(self._buffers.get(key, ()))
        if since is None:
            return points
        return tuple(point for point in points if point.timestamp >= since)

    def snapshot(
        self,
        *,
        device_address: int | None = None,
    ) -> Mapping[str, tuple[SignalPoint, ...]]:
        """Return the legacy signal-name view for one BMS address."""

        address = (
            self.default_device_address
            if device_address is None
            else int(device_address)
        )
        with self._lock:
            return {
                name: tuple(
                    self._buffers.get(BmsSignalKey(address, name), ())
                )
                for name in sorted(self._selected)
            }

    def snapshot_all(self) -> Mapping[BmsSignalKey, tuple[SignalPoint, ...]]:
        with self._lock:
            return {
                key: tuple(points)
                for key, points in sorted(self._buffers.items())
                if key.signal_name in self._selected
            }

    @property
    def series_keys(self) -> tuple[BmsSignalKey, ...]:
        with self._lock:
            return tuple(sorted(self._buffers))

    def clear(
        self,
        name: str | BmsSignalKey | None = None,
        *,
        device_address: int | None = None,
    ) -> None:
        with self._lock:
            if isinstance(name, BmsSignalKey):
                buffer = self._buffers.get(name)
                if buffer is not None:
                    buffer.clear()
                return
            if name is None and device_address is None:
                for buffer in self._buffers.values():
                    buffer.clear()
                return
            for key, buffer in self._buffers.items():
                if name is not None and key.signal_name != name:
                    continue
                if device_address is not None and key.device_address != device_address:
                    continue
                buffer.clear()
