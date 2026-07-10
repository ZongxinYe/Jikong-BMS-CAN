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
    VCI_INIT_CONFIG,
)
from .dll_loader import load_controlcan


def load_library(path: str | Path | None = None) -> ctypes.CDLL:
    """Load ControlCAN.dll and set signatures for core functions."""

    dll = load_controlcan(path)

    dll.VCI_OpenDevice.argtypes = [DWORD, DWORD, DWORD]
    dll.VCI_OpenDevice.restype = DWORD

    dll.VCI_CloseDevice.argtypes = [DWORD, DWORD]
    dll.VCI_CloseDevice.restype = DWORD

    dll.VCI_InitCAN.argtypes = [DWORD, DWORD, DWORD, ctypes.POINTER(VCI_INIT_CONFIG)]
    dll.VCI_InitCAN.restype = DWORD

    dll.VCI_ReadBoardInfo.argtypes = [DWORD, DWORD, ctypes.POINTER(VCI_BOARD_INFO)]
    dll.VCI_ReadBoardInfo.restype = DWORD

    dll.VCI_GetReceiveNum.argtypes = [DWORD, DWORD, DWORD]
    dll.VCI_GetReceiveNum.restype = ULONG

    dll.VCI_ClearBuffer.argtypes = [DWORD, DWORD, DWORD]
    dll.VCI_ClearBuffer.restype = DWORD

    dll.VCI_StartCAN.argtypes = [DWORD, DWORD, DWORD]
    dll.VCI_StartCAN.restype = DWORD

    dll.VCI_ResetCAN.argtypes = [DWORD, DWORD, DWORD]
    dll.VCI_ResetCAN.restype = DWORD

    dll.VCI_Transmit.argtypes = [DWORD, DWORD, DWORD, ctypes.POINTER(VCI_CAN_OBJ), ULONG]
    dll.VCI_Transmit.restype = ULONG

    dll.VCI_Receive.argtypes = [DWORD, DWORD, DWORD, ctypes.POINTER(VCI_CAN_OBJ), ULONG, INT]
    dll.VCI_Receive.restype = ULONG

    if hasattr(dll, "VCI_FindUsbDevice2"):
        dll.VCI_FindUsbDevice2.argtypes = [ctypes.POINTER(VCI_BOARD_INFO)]
        dll.VCI_FindUsbDevice2.restype = DWORD

    return dll


__all__ = ["CANALYST_II_DEVICE_TYPE", "load_library"]

