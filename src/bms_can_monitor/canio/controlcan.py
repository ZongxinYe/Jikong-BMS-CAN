"""Thin binding layer for ControlCAN.dll.

This module does not open hardware on import. It only loads the DLL and assigns
function signatures when a caller explicitly asks for a library instance.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

from .controlcan_constants import CANALYST_II_DEVICE_TYPE
from .controlcan_types import (
    INT,
    DWORD,
    ULONG,
    VCI_BOARD_INFO,
    VCI_CAN_OBJ,
    VCI_CAN_STATUS,
    VCI_ERR_INFO,
    VCI_INIT_CONFIG,
)
from .dll_loader import load_controlcan


class ControlCanBindingError(RuntimeError):
    """Raised when a required SDK function is missing from the DLL."""


def _bind_function(
    dll: ctypes.CDLL,
    name: str,
    argtypes: list[object],
    restype: object,
    *,
    required: bool,
) -> bool:
    try:
        function = getattr(dll, name)
    except AttributeError as exc:
        if required:
            raise ControlCanBindingError(
                f"ControlCAN.dll is missing required function {name}"
            ) from exc
        return False
    function.argtypes = argtypes
    function.restype = restype
    return True


def bind_library(dll: ctypes.CDLL) -> ctypes.CDLL:
    """Assign ctypes signatures without opening a device."""

    required = {
        "VCI_OpenDevice": ([DWORD, DWORD, DWORD], DWORD),
        "VCI_CloseDevice": ([DWORD, DWORD], DWORD),
        "VCI_InitCAN": (
            [DWORD, DWORD, DWORD, ctypes.POINTER(VCI_INIT_CONFIG)],
            DWORD,
        ),
        "VCI_ReadBoardInfo": (
            [DWORD, DWORD, ctypes.POINTER(VCI_BOARD_INFO)],
            DWORD,
        ),
        "VCI_GetReceiveNum": ([DWORD, DWORD, DWORD], ULONG),
        "VCI_ClearBuffer": ([DWORD, DWORD, DWORD], DWORD),
        "VCI_StartCAN": ([DWORD, DWORD, DWORD], DWORD),
        "VCI_ResetCAN": ([DWORD, DWORD, DWORD], DWORD),
        "VCI_Transmit": (
            [DWORD, DWORD, DWORD, ctypes.POINTER(VCI_CAN_OBJ), ULONG],
            ULONG,
        ),
        "VCI_Receive": (
            [DWORD, DWORD, DWORD, ctypes.POINTER(VCI_CAN_OBJ), ULONG, INT],
            ULONG,
        ),
    }
    optional = {
        "VCI_FindUsbDevice2": ([ctypes.POINTER(VCI_BOARD_INFO)], DWORD),
        "VCI_ReadErrInfo": (
            [DWORD, DWORD, DWORD, ctypes.POINTER(VCI_ERR_INFO)],
            DWORD,
        ),
        "VCI_ReadCANStatus": (
            [DWORD, DWORD, DWORD, ctypes.POINTER(VCI_CAN_STATUS)],
            DWORD,
        ),
        "VCI_GetReference": (
            [DWORD, DWORD, DWORD, DWORD, ctypes.c_void_p],
            DWORD,
        ),
        "VCI_SetReference": (
            [DWORD, DWORD, DWORD, DWORD, ctypes.c_void_p],
            DWORD,
        ),
        "VCI_GetReference2": (
            [DWORD, DWORD, DWORD, DWORD, ctypes.c_void_p],
            DWORD,
        ),
        "VCI_SetReference2": (
            [DWORD, DWORD, DWORD, DWORD, ctypes.c_void_p],
            DWORD,
        ),
        "VCI_UsbDeviceReset": ([DWORD, DWORD, DWORD], DWORD),
    }

    for name, (argtypes, restype) in required.items():
        _bind_function(dll, name, argtypes, restype, required=True)
    for name, (argtypes, restype) in optional.items():
        _bind_function(dll, name, argtypes, restype, required=False)
    return dll


def load_library(path: str | Path | None = None) -> ctypes.CDLL:
    """Load ControlCAN.dll and set signatures for core functions."""

    return bind_library(load_controlcan(path))


__all__ = [
    "CANALYST_II_DEVICE_TYPE",
    "ControlCanBindingError",
    "bind_library",
    "load_library",
]
