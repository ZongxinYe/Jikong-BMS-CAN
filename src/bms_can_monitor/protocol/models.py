"""Protocol-level data models shared by live CAN and replay sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Mapping, TypeAlias

SignalValue: TypeAlias = bool | int | float | str | None


@dataclass(frozen=True, slots=True)
class CanFrame:
    """A CAN 2.0 frame independent of the hardware adapter."""

    can_id: int
    data: bytes | bytearray = b""
    timestamp: float = field(default_factory=time)
    is_extended: bool = False
    is_remote: bool = False
    dlc: int | None = None
    channel: int = 0
    hardware_timestamp: int | None = None
    source: str = "live"

    def __post_init__(self) -> None:
        payload = bytes(self.data)
        object.__setattr__(self, "data", payload)

        max_id = 0x1FFFFFFF if self.is_extended else 0x7FF
        if not 0 <= self.can_id <= max_id:
            frame_type = "extended" if self.is_extended else "standard"
            raise ValueError(f"CAN ID 0x{self.can_id:X} is outside the {frame_type} range")
        if len(payload) > 8:
            raise ValueError("CAN 2.0 payload length must be 0..8 bytes")
        if not 0 <= self.channel:
            raise ValueError("CAN channel must be non-negative")

        dlc = len(payload) if self.dlc is None else self.dlc
        if not 0 <= dlc <= 8:
            raise ValueError("CAN DLC must be 0..8")
        if self.is_remote:
            if payload:
                raise ValueError("remote frames cannot contain payload bytes")
        elif dlc != len(payload):
            raise ValueError("data frame DLC must equal payload length")
        object.__setattr__(self, "dlc", dlc)


@dataclass(frozen=True, slots=True)
class DecodedSignal:
    """One engineering value decoded from a CAN message."""

    name: str
    value: SignalValue
    raw_value: int | float | None
    unit: str | None
    timestamp: float
    source_frame_id: int


@dataclass(frozen=True, slots=True)
class DecodedMessage:
    """A DBC message plus its source frame and decoded signals."""

    name: str
    normalized_frame_id: int
    frame: CanFrame
    signals: tuple[DecodedSignal, ...]
    device_address: int = 0

    @property
    def signal_map(self) -> dict[str, DecodedSignal]:
        return {signal.name: signal for signal in self.signals}

    @property
    def values(self) -> dict[str, SignalValue]:
        return {signal.name: signal.value for signal in self.signals}


@dataclass(frozen=True, slots=True)
class BmsSnapshot:
    """Read-only aggregate suitable for a dashboard or recorder."""

    timestamp: float
    signals: Mapping[str, DecodedSignal] = field(default_factory=dict)
    cell_voltages_mv: Mapping[int, int] = field(default_factory=dict)
    active_alarms: tuple[str, ...] = ()
    active_faults: tuple[str, ...] = ()
