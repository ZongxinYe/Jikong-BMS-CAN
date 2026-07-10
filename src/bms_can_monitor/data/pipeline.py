"""One-frame data pipeline shared by future GUI and headless tools."""

from __future__ import annotations

from bms_can_monitor.canio.events import CanEvent
from bms_can_monitor.protocol import DbcDecodeError, JikongBmsDecoder
from bms_can_monitor.protocol.jk_bms_v2_1 import normalized_cell_chunk
from bms_can_monitor.protocol.models import CanFrame, DecodedMessage

from .recorder import SessionRecorder
from .ring_buffer import SignalRingBuffer
from .state_store import BmsStateStore


class DataPipeline:
    def __init__(
        self,
        *,
        decoder: JikongBmsDecoder | None = None,
        state_store: BmsStateStore | None = None,
        ring_buffer: SignalRingBuffer | None = None,
        recorder: SessionRecorder | None = None,
        device_address: int = 0,
    ) -> None:
        self.decoder = decoder or JikongBmsDecoder()
        self.state_store = state_store or BmsStateStore()
        self.ring_buffer = ring_buffer or SignalRingBuffer()
        self.recorder = recorder
        self.device_address = device_address
        self.decode_errors = 0

    def process_frame(self, frame: CanFrame) -> DecodedMessage | None:
        if self.recorder is not None:
            self.recorder.record_frame(frame)
        try:
            message = self.decoder.decode(
                frame, device_address=self.device_address
            )
        except DbcDecodeError:
            self.decode_errors += 1
            return None

        cell_values = (
            self.decoder.cell_voltages.values
            if normalized_cell_chunk(frame.can_id, self.device_address) is not None
            else None
        )
        active_alarms = (
            self.decoder.active_alarms(message)
            if message.name == "ALM_INFO"
            else None
        )
        active_faults = (
            self.decoder.active_faults(message)
            if message.name == "BMSERR_INFO"
            else None
        )
        self.state_store.update_message(
            message,
            cell_voltages_mv=cell_values,
            active_alarms=active_alarms,
            active_faults=active_faults,
        )
        self.ring_buffer.append_message(message)
        if self.recorder is not None:
            self.recorder.record_message(message)
        return message

    def process_event(self, event: CanEvent) -> None:
        if self.recorder is not None:
            self.recorder.record_event(event)

    def flush(self, timeout: float = 5.0) -> None:
        if self.recorder is not None:
            self.recorder.flush(timeout)
