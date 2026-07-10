"""CANalyst-II discovery and board-information conversion."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path

from .bus_config import BusConfig
from .controlcan import load_library
from .controlcan_constants import STATUS_OK
from .controlcan_types import VCI_BOARD_INFO

DISCOVERY_ERROR = 0xFFFFFFFF
DEFAULT_DISCOVERY_CAPACITY = 50


class DeviceDiscoveryError(RuntimeError):
    """Raised when the SDK cannot enumerate or identify a device."""


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    index: int
    serial_number: str
    hardware_type: str
    can_channels: int
    hardware_version: int
    firmware_version: int
    driver_version: int
    interface_version: int

    @property
    def hardware_version_text(self) -> str:
        return format_sdk_version(self.hardware_version)

    @property
    def firmware_version_text(self) -> str:
        return format_sdk_version(self.firmware_version)


def format_sdk_version(value: int) -> str:
    return f"{(value >> 8) & 0xFF:X}.{value & 0xFF:02X}"


def _decode_c_string(value: bytes | ctypes.Array[ctypes.c_char]) -> str:
    raw = bytes(value).split(b"\x00", 1)[0]
    return raw.decode("ascii", errors="replace").strip()


def board_info_to_device(index: int, board: VCI_BOARD_INFO) -> DeviceInfo:
    return DeviceInfo(
        index=index,
        serial_number=_decode_c_string(board.str_Serial_Num),
        hardware_type=_decode_c_string(board.str_hw_Type),
        can_channels=int(board.can_Num),
        hardware_version=int(board.hw_Version),
        firmware_version=int(board.fw_Version),
        driver_version=int(board.dr_Version),
        interface_version=int(board.in_Version),
    )


def discover_devices(
    *,
    dll: ctypes.CDLL | None = None,
    dll_path: str | Path | None = None,
    capacity: int = DEFAULT_DISCOVERY_CAPACITY,
) -> tuple[DeviceInfo, ...]:
    if not 1 <= capacity <= DEFAULT_DISCOVERY_CAPACITY:
        raise ValueError(f"discovery capacity must be 1..{DEFAULT_DISCOVERY_CAPACITY}")
    library = dll or load_library(dll_path)
    if not hasattr(library, "VCI_FindUsbDevice2"):
        raise DeviceDiscoveryError("ControlCAN.dll does not export VCI_FindUsbDevice2")

    boards = (VCI_BOARD_INFO * capacity)()
    count = int(library.VCI_FindUsbDevice2(boards))
    if count == DISCOVERY_ERROR:
        raise DeviceDiscoveryError("VCI_FindUsbDevice2 returned 0xFFFFFFFF")
    if count > capacity:
        raise DeviceDiscoveryError(
            f"VCI_FindUsbDevice2 returned {count}, larger than buffer {capacity}"
        )
    return tuple(board_info_to_device(index, boards[index]) for index in range(count))


def read_board_info(dll: ctypes.CDLL, config: BusConfig) -> DeviceInfo:
    board = VCI_BOARD_INFO()
    result = int(
        dll.VCI_ReadBoardInfo(
            config.device_type,
            config.device_index,
            ctypes.byref(board),
        )
    )
    if result != STATUS_OK:
        raise DeviceDiscoveryError(f"VCI_ReadBoardInfo failed with status {result}")
    return board_info_to_device(config.device_index, board)
