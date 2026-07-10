"""Read optional ControlCAN error and controller-status registers."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from time import time

from .canalyst2_adapter import Canalyst2Adapter
from .controlcan_constants import STATUS_OK
from .controlcan_types import VCI_CAN_STATUS, VCI_ERR_INFO


@dataclass(frozen=True, slots=True)
class CanErrorInfo:
    error_code: int
    passive_error_data: tuple[int, int, int]
    arbitration_lost_data: int


@dataclass(frozen=True, slots=True)
class CanControllerStatus:
    error_interrupt: int
    mode: int
    status: int
    arbitration_lost_capture: int
    error_code_capture: int
    warning_limit: int
    receive_error_counter: int
    transmit_error_counter: int


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    timestamp: float
    adapter_state: str
    pending_frames: int
    error_info: CanErrorInfo | None
    controller_status: CanControllerStatus | None
    unavailable: tuple[str, ...] = ()


def collect_diagnostics(adapter: Canalyst2Adapter) -> DiagnosticSnapshot:
    library = adapter.library
    config = adapter.config
    unavailable: list[str] = []

    error_info: CanErrorInfo | None = None
    if hasattr(library, "VCI_ReadErrInfo"):
        raw_error = VCI_ERR_INFO()
        result = int(
            library.VCI_ReadErrInfo(
                config.device_type,
                config.device_index,
                config.channel,
                ctypes.byref(raw_error),
            )
        )
        if result == STATUS_OK:
            error_info = CanErrorInfo(
                error_code=int(raw_error.ErrCode),
                passive_error_data=tuple(int(value) for value in raw_error.Passive_ErrData),
                arbitration_lost_data=int(raw_error.ArLost_ErrData),
            )
        else:
            unavailable.append(f"VCI_ReadErrInfo status {result}")
    else:
        unavailable.append("VCI_ReadErrInfo not exported")

    controller_status: CanControllerStatus | None = None
    if hasattr(library, "VCI_ReadCANStatus"):
        raw_status = VCI_CAN_STATUS()
        result = int(
            library.VCI_ReadCANStatus(
                config.device_type,
                config.device_index,
                config.channel,
                ctypes.byref(raw_status),
            )
        )
        if result == STATUS_OK:
            controller_status = CanControllerStatus(
                error_interrupt=int(raw_status.ErrInterrupt),
                mode=int(raw_status.regMode),
                status=int(raw_status.regStatus),
                arbitration_lost_capture=int(raw_status.regALCapture),
                error_code_capture=int(raw_status.regECCapture),
                warning_limit=int(raw_status.regEWLimit),
                receive_error_counter=int(raw_status.regRECounter),
                transmit_error_counter=int(raw_status.regTECounter),
            )
        else:
            unavailable.append(f"VCI_ReadCANStatus status {result}")
    else:
        unavailable.append("VCI_ReadCANStatus not exported")

    return DiagnosticSnapshot(
        timestamp=time(),
        adapter_state=adapter.state.value,
        pending_frames=adapter.pending_count(),
        error_info=error_info,
        controller_status=controller_status,
        unavailable=tuple(unavailable),
    )
