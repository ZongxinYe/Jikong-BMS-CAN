"""Multi-BMS frame routing shared by GUI and headless tools."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Mapping

from bms_can_monitor.canio.events import CanEvent
from bms_can_monitor.protocol import (
    BmsAddressConflictError,
    BmsAddressResolver,
    BmsSnapshot,
    DbcDecodeError,
    JikongBmsDecoder,
)
from bms_can_monitor.protocol.dbc_loader import validate_device_address
from bms_can_monitor.protocol.jk_bms_v2_1 import normalized_cell_chunk
from bms_can_monitor.protocol.models import CanFrame, DecodedMessage

from .recorder import SessionRecorder
from .ring_buffer import SignalRingBuffer
from .state_store import BmsStateStore


@dataclass(slots=True)
class BmsContext:
    device_address: int
    decoder: JikongBmsDecoder
    state_store: BmsStateStore


class DataPipeline:
    def __init__(
        self,
        *,
        decoder: JikongBmsDecoder | None = None,
        state_store: BmsStateStore | None = None,
        ring_buffer: SignalRingBuffer | None = None,
        recorder: SessionRecorder | None = None,
        device_address: int = 0,
        address_resolver: BmsAddressResolver | None = None,
    ) -> None:
        validate_device_address(device_address)
        primary_decoder = decoder or JikongBmsDecoder(
            address_resolver.dbc if address_resolver is not None else None
        )
        self.address_resolver = address_resolver or BmsAddressResolver(
            primary_decoder.dbc
        )
        self._dbc = primary_decoder.dbc
        self._contexts: dict[int, BmsContext] = {
            device_address: BmsContext(
                device_address,
                primary_decoder,
                state_store or BmsStateStore(),
            )
        }
        self._detected_addresses: set[int] = set()
        self._context_lock = RLock()
        self._device_address = device_address
        self.ring_buffer = ring_buffer or SignalRingBuffer()
        self.ring_buffer.default_device_address = device_address
        self.recorder = recorder
        self.decode_errors = 0
        self.unknown_frames = 0
        self.address_conflicts = 0

    @property
    def device_address(self) -> int:
        """Compatibility address used by the current single-dashboard GUI."""

        return self._device_address

    @device_address.setter
    def device_address(self, value: int) -> None:
        address = validate_device_address(int(value))
        self._device_address = address
        self.ring_buffer.default_device_address = address
        self._context(address)

    def _context(self, device_address: int) -> BmsContext:
        address = validate_device_address(device_address)
        with self._context_lock:
            context = self._contexts.get(address)
            if context is None:
                context = BmsContext(
                    address,
                    JikongBmsDecoder(self._dbc),
                    BmsStateStore(),
                )
                self._contexts[address] = context
            return context

    @property
    def contexts(self) -> Mapping[int, BmsContext]:
        with self._context_lock:
            return dict(self._contexts)

    @property
    def detected_addresses(self) -> tuple[int, ...]:
        with self._context_lock:
            return tuple(sorted(self._detected_addresses))

    @property
    def decoder(self) -> JikongBmsDecoder:
        return self._context(self.device_address).decoder

    @property
    def state_store(self) -> BmsStateStore:
        return self._context(self.device_address).state_store

    def context(self, device_address: int) -> BmsContext:
        return self._context(device_address)

    def snapshot(self, device_address: int | None = None) -> BmsSnapshot:
        address = self.device_address if device_address is None else device_address
        return self._context(address).state_store.snapshot()

    def snapshots(self) -> Mapping[int, BmsSnapshot]:
        with self._context_lock:
            addresses = tuple(sorted(self._detected_addresses))
        return {
            address: self._context(address).state_store.snapshot()
            for address in addresses
        }

    def last_seen(self, device_address: int) -> float:
        with self._context_lock:
            context = self._contexts.get(validate_device_address(device_address))
        return 0.0 if context is None else context.state_store.timestamp

    def process_frame(self, frame: CanFrame) -> DecodedMessage | None:
        if self.recorder is not None:
            self.recorder.record_frame(frame)
        try:
            resolved = self.address_resolver.resolve(frame)
        except BmsAddressConflictError:
            self.decode_errors += 1
            self.address_conflicts += 1
            return None
        if resolved is None:
            self.decode_errors += 1
            self.unknown_frames += 1
            return None

        context = self._context(resolved.device_address)
        try:
            message = context.decoder.decode(
                frame, device_address=resolved.device_address
            )
        except DbcDecodeError:
            self.decode_errors += 1
            return None

        cell_values = (
            context.decoder.cell_voltages.values
            if normalized_cell_chunk(frame.can_id, resolved.device_address) is not None
            else None
        )
        active_alarms = (
            context.decoder.active_alarms(message)
            if message.name == "ALM_INFO"
            else None
        )
        active_faults = (
            context.decoder.active_faults(message)
            if message.name == "BMSERR_INFO"
            else None
        )
        context.state_store.update_message(
            message,
            cell_voltages_mv=cell_values,
            active_alarms=active_alarms,
            active_faults=active_faults,
        )
        with self._context_lock:
            self._detected_addresses.add(resolved.device_address)
        self.ring_buffer.append_message(message)
        return message

    def process_event(self, event: CanEvent) -> None:
        if self.recorder is not None:
            self.recorder.record_event(event)

    def flush(self, timeout: float = 5.0) -> None:
        if self.recorder is not None:
            self.recorder.flush(timeout)

    def reset(self, device_address: int | None = None) -> None:
        if device_address is None:
            with self._context_lock:
                contexts = tuple(self._contexts.values())
                self._detected_addresses.clear()
            for context in contexts:
                context.state_store.reset()
                context.decoder.cell_voltages.reset()
            self.ring_buffer.clear()
            self.decode_errors = 0
            self.unknown_frames = 0
            self.address_conflicts = 0
            return

        context = self._context(device_address)
        context.state_store.reset()
        context.decoder.cell_voltages.reset()
        self.ring_buffer.clear(device_address=device_address)
        with self._context_lock:
            self._detected_addresses.discard(device_address)
