"""Stateful CANalyst-II adapter built on the vendor ControlCAN SDK."""

from __future__ import annotations

import ctypes
from enum import Enum
from threading import RLock
from time import time

from bms_can_monitor.protocol.models import CanFrame

from .bus_config import BusConfig
from .controlcan import load_library
from .controlcan_constants import STATUS_OK
from .controlcan_types import VCI_CAN_OBJ, make_can_obj
from .device_discovery import DeviceInfo, read_board_info
from .events import CanEventType, EventSink, emit_event

RECEIVE_ERROR = 0xFFFFFFFF


class AdapterState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    INITIALIZED = "initialized"
    STARTED = "started"
    ERROR = "error"


class Canalyst2Error(RuntimeError):
    def __init__(self, operation: str, result: int | None = None) -> None:
        suffix = "" if result is None else f" (status {result})"
        super().__init__(f"{operation} failed{suffix}")
        self.operation = operation
        self.result = result


class Canalyst2Adapter:
    """Open, initialize, receive, transmit, reset, and close one CAN channel."""

    def __init__(
        self,
        config: BusConfig | None = None,
        *,
        dll: ctypes.CDLL | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.config = config or BusConfig()
        self._dll = dll
        self._event_sink = event_sink
        self._state = AdapterState.CLOSED
        self._device_open = False
        self._lock = RLock()
        self._last_error: str | None = None

    @property
    def state(self) -> AdapterState:
        return self._state

    @property
    def is_started(self) -> bool:
        return self._state is AdapterState.STARTED

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def library(self) -> ctypes.CDLL:
        if self._dll is None:
            raise Canalyst2Error("ControlCAN.dll is not loaded")
        return self._dll

    def _set_error(
        self,
        operation: str,
        result: int | None = None,
        *,
        fatal: bool = True,
    ) -> Canalyst2Error:
        error = Canalyst2Error(operation, result)
        self._last_error = str(error)
        if fatal:
            self._state = AdapterState.ERROR
        emit_event(
            self._event_sink,
            CanEventType.ADAPTER_ERROR,
            str(error),
            operation=operation,
            result=result,
            fatal=fatal,
        )
        return error

    def _require_state(self, *states: AdapterState) -> None:
        if self._state not in states:
            expected = ", ".join(state.value for state in states)
            raise Canalyst2Error(
                f"operation requires state {expected}; current state is {self._state.value}"
            )

    def open_device(self) -> None:
        with self._lock:
            self._require_state(AdapterState.CLOSED)
            if self._dll is None:
                self._dll = load_library(self.config.effective_dll_path)
            result = int(
                self.library.VCI_OpenDevice(
                    self.config.device_type,
                    self.config.device_index,
                    0,
                )
            )
            if result != STATUS_OK:
                raise self._set_error("VCI_OpenDevice", result)
            self._device_open = True
            self._state = AdapterState.OPEN
            self._last_error = None

    def initialize_channel(self) -> None:
        with self._lock:
            self._require_state(AdapterState.OPEN)
            init_config = self.config.build_init_config()
            result = int(
                self.library.VCI_InitCAN(
                    self.config.device_type,
                    self.config.device_index,
                    self.config.channel,
                    ctypes.byref(init_config),
                )
            )
            if result != STATUS_OK:
                raise self._set_error("VCI_InitCAN", result)
            self._state = AdapterState.INITIALIZED
            self.clear_buffer()

    def start(self) -> None:
        with self._lock:
            self._require_state(AdapterState.INITIALIZED)
            result = int(
                self.library.VCI_StartCAN(
                    self.config.device_type,
                    self.config.device_index,
                    self.config.channel,
                )
            )
            if result != STATUS_OK:
                raise self._set_error("VCI_StartCAN", result)
            self._state = AdapterState.STARTED

    def connect(self) -> None:
        if self._state is AdapterState.STARTED:
            return
        if self._state is AdapterState.ERROR:
            self.close(suppress_errors=True)
        emit_event(
            self._event_sink,
            CanEventType.CONNECTING,
            "Opening CANalyst-II",
            device_index=self.config.device_index,
            channel=self.config.channel,
            bitrate=self.config.bitrate,
        )
        try:
            self.open_device()
            self.initialize_channel()
            self.start()
        except Exception:
            self._close_after_failed_connect()
            raise
        emit_event(
            self._event_sink,
            CanEventType.CONNECTED,
            "CANalyst-II channel started",
            device_index=self.config.device_index,
            channel=self.config.channel,
        )

    def _close_after_failed_connect(self) -> None:
        if self._device_open and self._dll is not None:
            try:
                self.library.VCI_CloseDevice(
                    self.config.device_type, self.config.device_index
                )
            except Exception:
                pass
        self._device_open = False
        self._state = AdapterState.ERROR

    def close(self, *, suppress_errors: bool = False) -> None:
        with self._lock:
            if not self._device_open:
                self._state = AdapterState.CLOSED
                return
            result = int(
                self.library.VCI_CloseDevice(
                    self.config.device_type,
                    self.config.device_index,
                )
            )
            self._device_open = False
            if result != STATUS_OK:
                error = self._set_error("VCI_CloseDevice", result)
                if not suppress_errors:
                    raise error
                return
            self._state = AdapterState.CLOSED
            emit_event(
                self._event_sink,
                CanEventType.DISCONNECTED,
                "CANalyst-II closed",
                device_index=self.config.device_index,
            )

    def clear_buffer(self) -> None:
        with self._lock:
            self._require_state(AdapterState.INITIALIZED, AdapterState.STARTED)
            result = int(
                self.library.VCI_ClearBuffer(
                    self.config.device_type,
                    self.config.device_index,
                    self.config.channel,
                )
            )
            if result != STATUS_OK:
                raise self._set_error("VCI_ClearBuffer", result)

    def reset(self) -> None:
        with self._lock:
            self._require_state(AdapterState.INITIALIZED, AdapterState.STARTED)
            result = int(
                self.library.VCI_ResetCAN(
                    self.config.device_type,
                    self.config.device_index,
                    self.config.channel,
                )
            )
            if result != STATUS_OK:
                raise self._set_error("VCI_ResetCAN", result)
            self._state = AdapterState.INITIALIZED

    def restart(self) -> None:
        self.reset()
        self.clear_buffer()
        self.start()

    def board_info(self) -> DeviceInfo:
        with self._lock:
            self._require_state(
                AdapterState.OPEN,
                AdapterState.INITIALIZED,
                AdapterState.STARTED,
            )
            return read_board_info(self.library, self.config)

    def pending_count(self) -> int:
        with self._lock:
            self._require_state(AdapterState.INITIALIZED, AdapterState.STARTED)
            result = int(
                self.library.VCI_GetReceiveNum(
                    self.config.device_type,
                    self.config.device_index,
                    self.config.channel,
                )
            )
            if result == RECEIVE_ERROR:
                raise self._set_error("VCI_GetReceiveNum", result, fatal=False)
            return result

    def send(self, frame: CanFrame) -> int:
        with self._lock:
            self._require_state(AdapterState.STARTED)
            raw = make_can_obj(
                can_id=frame.can_id,
                data=frame.data,
                remote=frame.is_remote,
                extended=frame.is_extended,
                dlc=frame.dlc,
            )
            result = int(
                self.library.VCI_Transmit(
                    self.config.device_type,
                    self.config.device_index,
                    self.config.channel,
                    ctypes.byref(raw),
                    1,
                )
            )
            if result != 1:
                raise self._set_error("VCI_Transmit", result, fatal=False)
            return result

    def receive(self, max_frames: int, wait_ms: int = 0) -> list[CanFrame]:
        if not 1 <= max_frames <= 2500:
            raise ValueError("max_frames must be 1..2500")
        if not 0 <= wait_ms <= 1000:
            raise ValueError("wait_ms must be 0..1000")

        with self._lock:
            self._require_state(AdapterState.STARTED)
            buffer = (VCI_CAN_OBJ * max_frames)()
            result = int(
                self.library.VCI_Receive(
                    self.config.device_type,
                    self.config.device_index,
                    self.config.channel,
                    buffer,
                    max_frames,
                    wait_ms,
                )
            )
            if result == RECEIVE_ERROR or result > max_frames:
                raise self._set_error("VCI_Receive", result)
            if result == 0:
                return []

            host_timestamp = time()
            frames: list[CanFrame] = []
            for index in range(result):
                raw = buffer[index]
                dlc = int(raw.DataLen)
                if dlc > 8:
                    raise self._set_error("VCI_Receive invalid DLC", dlc)
                is_remote = bool(raw.RemoteFlag)
                payload = b"" if is_remote else bytes(raw.Data[:dlc])
                frames.append(
                    CanFrame(
                        can_id=int(raw.ID),
                        data=payload,
                        timestamp=host_timestamp,
                        is_extended=bool(raw.ExternFlag),
                        is_remote=is_remote,
                        dlc=dlc,
                        channel=self.config.channel,
                        hardware_timestamp=(
                            int(raw.TimeStamp) if raw.TimeFlag else None
                        ),
                        source="canalyst2",
                    )
                )
            return frames

    def __enter__(self) -> Canalyst2Adapter:
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close(suppress_errors=exc is not None)
