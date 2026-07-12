"""Thread-safe latest-value state for dashboard consumers."""

from __future__ import annotations

from threading import RLock
from typing import Mapping

from bms_can_monitor.protocol.models import (
    BmsSnapshot,
    DecodedMessage,
    DecodedSignal,
    SignalValue,
)


class BmsStateStore:
    """Merge decoded messages without allowing stale samples to overwrite new data."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._timestamp = 0.0
        self._signals: dict[str, DecodedSignal] = {}
        self._cell_voltages_mv: dict[int, int] = {}
        self._cell_timestamps: dict[int, float] = {}
        self._cell_voltage_sum_v: float | None = None
        self._summed_cell_count = 0
        self._cell_voltage_sum_timestamp = 0.0
        self._active_alarms: tuple[str, ...] = ()
        self._active_faults: tuple[str, ...] = ()
        self._alarm_timestamp = 0.0
        self._fault_timestamp = 0.0
        self._message_timestamps: dict[str, float] = {}

    @property
    def timestamp(self) -> float:
        with self._lock:
            return self._timestamp

    @property
    def message_timestamps(self) -> dict[str, float]:
        with self._lock:
            return dict(self._message_timestamps)

    def update_message(
        self,
        message: DecodedMessage,
        *,
        cell_voltages_mv: Mapping[int, int] | None = None,
        cell_voltage_sum_v: float | None = None,
        summed_cell_count: int = 0,
        cell_voltage_sum_timestamp: float | None = None,
        active_alarms: tuple[str, ...] | None = None,
        active_faults: tuple[str, ...] | None = None,
    ) -> BmsSnapshot:
        timestamp = message.frame.timestamp
        with self._lock:
            for signal in message.signals:
                current = self._signals.get(signal.name)
                if current is None or signal.timestamp >= current.timestamp:
                    self._signals[signal.name] = signal

            previous_message_time = self._message_timestamps.get(message.name, 0.0)
            if timestamp >= previous_message_time:
                self._message_timestamps[message.name] = timestamp

            if cell_voltages_mv is not None:
                self._update_cells_locked(cell_voltages_mv, timestamp)
            if cell_voltage_sum_v is not None:
                sum_timestamp = (
                    timestamp
                    if cell_voltage_sum_timestamp is None
                    else float(cell_voltage_sum_timestamp)
                )
                if sum_timestamp >= self._cell_voltage_sum_timestamp:
                    self._cell_voltage_sum_v = float(cell_voltage_sum_v)
                    self._summed_cell_count = int(summed_cell_count)
                    self._cell_voltage_sum_timestamp = sum_timestamp
            if active_alarms is not None and timestamp >= self._alarm_timestamp:
                self._active_alarms = tuple(active_alarms)
                self._alarm_timestamp = timestamp
            if active_faults is not None and timestamp >= self._fault_timestamp:
                self._active_faults = tuple(active_faults)
                self._fault_timestamp = timestamp
            self._timestamp = max(self._timestamp, timestamp)
            return self._snapshot_locked()

    def update_cells(
        self,
        values_mv: Mapping[int, int],
        *,
        timestamp: float,
    ) -> BmsSnapshot:
        with self._lock:
            self._update_cells_locked(values_mv, timestamp)
            self._timestamp = max(self._timestamp, timestamp)
            return self._snapshot_locked()

    def _update_cells_locked(
        self, values_mv: Mapping[int, int], timestamp: float
    ) -> None:
        for cell, voltage_mv in values_mv.items():
            if not 1 <= int(cell) <= 250:
                raise ValueError(f"cell number must be 1..250, got {cell}")
            if int(voltage_mv) < 0:
                raise ValueError("cell voltage cannot be negative")
            if timestamp >= self._cell_timestamps.get(int(cell), 0.0):
                self._cell_voltages_mv[int(cell)] = int(voltage_mv)
                self._cell_timestamps[int(cell)] = timestamp

    def update_snapshot(self, snapshot: BmsSnapshot) -> BmsSnapshot:
        with self._lock:
            for signal in snapshot.signals.values():
                current = self._signals.get(signal.name)
                if current is None or signal.timestamp >= current.timestamp:
                    self._signals[signal.name] = signal
            self._update_cells_locked(snapshot.cell_voltages_mv, snapshot.timestamp)
            if (
                snapshot.cell_voltage_sum_v is not None
                and snapshot.timestamp >= self._cell_voltage_sum_timestamp
            ):
                self._cell_voltage_sum_v = float(snapshot.cell_voltage_sum_v)
                self._summed_cell_count = int(snapshot.summed_cell_count)
                self._cell_voltage_sum_timestamp = snapshot.timestamp
            if snapshot.timestamp >= self._alarm_timestamp:
                self._active_alarms = tuple(snapshot.active_alarms)
                self._alarm_timestamp = snapshot.timestamp
            if snapshot.timestamp >= self._fault_timestamp:
                self._active_faults = tuple(snapshot.active_faults)
                self._fault_timestamp = snapshot.timestamp
            self._timestamp = max(self._timestamp, snapshot.timestamp)
            return self._snapshot_locked()

    def get_signal(self, name: str) -> DecodedSignal | None:
        with self._lock:
            return self._signals.get(name)

    def get_value(self, name: str, default: SignalValue = None) -> SignalValue:
        signal = self.get_signal(name)
        return default if signal is None else signal.value

    def snapshot(self) -> BmsSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> BmsSnapshot:
        return BmsSnapshot(
            timestamp=self._timestamp,
            signals=dict(self._signals),
            cell_voltages_mv=dict(sorted(self._cell_voltages_mv.items())),
            cell_voltage_sum_v=self._cell_voltage_sum_v,
            summed_cell_count=self._summed_cell_count,
            active_alarms=self._active_alarms,
            active_faults=self._active_faults,
        )

    def reset(self) -> None:
        with self._lock:
            self._timestamp = 0.0
            self._signals.clear()
            self._cell_voltages_mv.clear()
            self._cell_timestamps.clear()
            self._cell_voltage_sum_v = None
            self._summed_cell_count = 0
            self._cell_voltage_sum_timestamp = 0.0
            self._active_alarms = ()
            self._active_faults = ()
            self._alarm_timestamp = 0.0
            self._fault_timestamp = 0.0
            self._message_timestamps.clear()
