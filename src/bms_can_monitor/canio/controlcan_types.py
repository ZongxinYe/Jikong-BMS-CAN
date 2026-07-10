"""ctypes structures for ControlCAN.dll.

The field layout follows ControlCAN.h from the CANalyst-II SDK.
Use fixed-width ctypes instead of c_ulong because c_ulong is 64-bit on
some non-Windows Python builds.
"""

from __future__ import annotations

import ctypes

DWORD = ctypes.c_uint32
UINT = ctypes.c_uint32
ULONG = ctypes.c_uint32
INT = ctypes.c_int32
USHORT = ctypes.c_uint16
BYTE = ctypes.c_ubyte
UCHAR = ctypes.c_ubyte
CHAR = ctypes.c_char


class VCI_BOARD_INFO(ctypes.Structure):
    _fields_ = [
        ("hw_Version", USHORT),
        ("fw_Version", USHORT),
        ("dr_Version", USHORT),
        ("in_Version", USHORT),
        ("irq_Num", USHORT),
        ("can_Num", BYTE),
        ("str_Serial_Num", CHAR * 20),
        ("str_hw_Type", CHAR * 40),
        ("Reserved", USHORT * 4),
    ]


class VCI_CAN_OBJ(ctypes.Structure):
    _fields_ = [
        ("ID", UINT),
        ("TimeStamp", UINT),
        ("TimeFlag", BYTE),
        ("SendType", BYTE),
        ("RemoteFlag", BYTE),
        ("ExternFlag", BYTE),
        ("DataLen", BYTE),
        ("Data", BYTE * 8),
        ("Reserved", BYTE * 3),
    ]


class VCI_INIT_CONFIG(ctypes.Structure):
    _fields_ = [
        ("AccCode", DWORD),
        ("AccMask", DWORD),
        ("Reserved", DWORD),
        ("Filter", UCHAR),
        ("Timing0", UCHAR),
        ("Timing1", UCHAR),
        ("Mode", UCHAR),
    ]


class VCI_FILTER_RECORD(ctypes.Structure):
    _fields_ = [
        ("ExtFrame", DWORD),
        ("Start", DWORD),
        ("End", DWORD),
    ]


class VCI_CAN_STATUS(ctypes.Structure):
    _fields_ = [
        ("ErrInterrupt", UCHAR),
        ("regMode", UCHAR),
        ("regStatus", UCHAR),
        ("regALCapture", UCHAR),
        ("regECCapture", UCHAR),
        ("regEWLimit", UCHAR),
        ("regRECounter", UCHAR),
        ("regTECounter", UCHAR),
        ("Reserved", DWORD),
    ]


class VCI_ERR_INFO(ctypes.Structure):
    _fields_ = [
        ("ErrCode", UINT),
        ("Passive_ErrData", BYTE * 3),
        ("ArLost_ErrData", BYTE),
    ]


class VCI_BOARD_INFO1(ctypes.Structure):
    _fields_ = [
        ("hw_Version", USHORT),
        ("fw_Version", USHORT),
        ("dr_Version", USHORT),
        ("in_Version", USHORT),
        ("irq_Num", USHORT),
        ("can_Num", BYTE),
        ("reserved", BYTE),
        ("str_Serial_Num", CHAR * 8),
        ("str_hw_Type", CHAR * 16),
        ("str_Usb_Serial", (CHAR * 4) * 4),
    ]


EXPECTED_SIZES = {
    "VCI_BOARD_INFO": 80,
    "VCI_CAN_OBJ": 24,
    "VCI_INIT_CONFIG": 16,
    "VCI_FILTER_RECORD": 12,
    "VCI_CAN_STATUS": 12,
    "VCI_ERR_INFO": 8,
    "VCI_BOARD_INFO1": 52,
}


def make_init_config(
    *,
    acc_code: int = 0x00000000,
    acc_mask: int = 0xFFFFFFFF,
    filter_mode: int = 1,
    timing0: int,
    timing1: int,
    mode: int = 0,
) -> VCI_INIT_CONFIG:
    """Create a ControlCAN initialization structure."""

    return VCI_INIT_CONFIG(
        acc_code,
        acc_mask,
        0,
        filter_mode,
        timing0,
        timing1,
        mode,
    )


def make_can_obj(
    *,
    can_id: int,
    data: bytes | bytearray = b"",
    remote: bool = False,
    extended: bool = False,
    send_type: int = 1,
    dlc: int | None = None,
) -> VCI_CAN_OBJ:
    """Build a single CAN frame structure for VCI_Transmit."""

    payload = bytes(data)
    if len(payload) > 8:
        raise ValueError("CAN data length must be 0..8 bytes")
    frame_dlc = len(payload) if dlc is None else dlc
    if not 0 <= frame_dlc <= 8:
        raise ValueError("CAN DLC must be 0..8")
    if remote:
        if payload:
            raise ValueError("remote frames cannot contain payload bytes")
    elif frame_dlc != len(payload):
        raise ValueError("data frame DLC must equal payload length")

    padded = payload + b"\x00" * (8 - len(payload))
    return VCI_CAN_OBJ(
        can_id,
        0,
        0,
        send_type,
        1 if remote else 0,
        1 if extended else 0,
        frame_dlc,
        (BYTE * 8)(*padded),
        (BYTE * 3)(0, 0, 0),
    )
