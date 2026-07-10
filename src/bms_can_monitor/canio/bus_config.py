"""Validated runtime configuration for one CANalyst-II channel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .controlcan_constants import (
    CANALYST_II_DEVICE_TYPE,
    DEFAULT_DEVICE_INDEX,
    MODE_NORMAL,
)
from .controlcan_types import VCI_INIT_CONFIG, make_init_config
from .dll_loader import default_dll_path
from .timing import DEFAULT_BMS_BITRATE, timing_for_bitrate

MAX_BMS_DEVICE_ADDRESS = 0x0B


@dataclass(frozen=True, slots=True)
class BusConfig:
    device_type: int = CANALYST_II_DEVICE_TYPE
    device_index: int = DEFAULT_DEVICE_INDEX
    channel: int = 0
    bitrate: int = DEFAULT_BMS_BITRATE
    device_address: int = 0
    dll_path: Path | str | None = None
    record_enabled: bool = False
    mode: int = MODE_NORMAL
    acc_code: int = 0x00000000
    acc_mask: int = 0xFFFFFFFF
    filter_mode: int = 1
    receive_batch_size: int = 2500
    receive_wait_ms: int = 20

    def __post_init__(self) -> None:
        if self.device_index < 0:
            raise ValueError("device index must be non-negative")
        if self.channel not in (0, 1):
            raise ValueError("CANalyst-II channel must be 0 or 1")
        if not 0 <= self.device_address <= MAX_BMS_DEVICE_ADDRESS:
            raise ValueError(
                f"BMS device address must be 0..{MAX_BMS_DEVICE_ADDRESS}"
            )
        if self.mode not in (0, 1, 2):
            raise ValueError("CAN mode must be normal(0), listen-only(1), or self-test(2)")
        if self.filter_mode not in (0, 1, 2, 3):
            raise ValueError("ControlCAN filter mode must be 0..3")
        if not 1 <= self.receive_batch_size <= 2500:
            raise ValueError("receive batch size must be 1..2500")
        if not 0 <= self.receive_wait_ms <= 1000:
            raise ValueError("receive wait time must be 0..1000 ms")
        timing_for_bitrate(self.bitrate)
        if self.dll_path is not None:
            object.__setattr__(self, "dll_path", Path(self.dll_path))

    @property
    def timing(self) -> tuple[int, int]:
        return timing_for_bitrate(self.bitrate)

    @property
    def effective_dll_path(self) -> Path:
        return Path(self.dll_path) if self.dll_path is not None else default_dll_path()

    def build_init_config(self) -> VCI_INIT_CONFIG:
        timing0, timing1 = self.timing
        return make_init_config(
            acc_code=self.acc_code,
            acc_mask=self.acc_mask,
            filter_mode=self.filter_mode,
            timing0=timing0,
            timing1=timing1,
            mode=self.mode,
        )
