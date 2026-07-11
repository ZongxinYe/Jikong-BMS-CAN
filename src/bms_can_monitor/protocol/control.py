"""Encoding for the safety-sensitive Jikong Ctrl_INFO command."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag
from time import time

from .models import CanFrame

CTRL_INFO_FRAME_ID = 0x18F0F428
CTRL_INFO_DLC = 8


class ControlProtocolError(ValueError):
    """Raised when a control command cannot be represented safely."""


class ControlMask(IntFlag):
    NONE = 0
    CHARGE = 1 << 0
    DISCHARGE = 1 << 1
    BALANCE = 1 << 2


ALL_CONTROL_MASK = ControlMask.CHARGE | ControlMask.DISCHARGE | ControlMask.BALANCE


@dataclass(frozen=True, slots=True)
class ControlCommand:
    mask: ControlMask = ControlMask.NONE
    charge_on: bool = False
    discharge_on: bool = False
    balance_on: bool = False
    device_address: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.mask, bool) or not isinstance(self.mask, (int, ControlMask)):
            raise ControlProtocolError(f"invalid control mask: {self.mask!r}")
        try:
            mask = ControlMask(self.mask)
        except (TypeError, ValueError) as exc:
            raise ControlProtocolError(f"invalid control mask: {self.mask!r}") from exc
        if int(mask) & ~int(ALL_CONTROL_MASK):
            raise ControlProtocolError(f"control mask contains reserved bits: 0x{int(mask):02X}")
        for name, value in (
            ("charge_on", self.charge_on),
            ("discharge_on", self.discharge_on),
            ("balance_on", self.balance_on),
        ):
            if not isinstance(value, bool):
                raise ControlProtocolError(f"{name} must be a boolean")
        if isinstance(self.device_address, bool) or not isinstance(self.device_address, int):
            raise ControlProtocolError("BMS device address must be an integer")
        if not 0 <= self.device_address <= 11:
            raise ControlProtocolError("BMS device address must be 0..11")
        object.__setattr__(self, "mask", mask)

    @property
    def payload(self) -> bytes:
        return bytes(
            (
                int(self.mask),
                int(self.charge_on),
                int(self.discharge_on),
                int(self.balance_on),
                0,
                0,
                0,
                0,
            )
        )

    @property
    def fingerprint(self) -> tuple[int, bool, bool, bool, int]:
        return (
            int(self.mask),
            self.charge_on,
            self.discharge_on,
            self.balance_on,
            self.device_address,
        )

    @property
    def selected_changes(self) -> tuple[tuple[str, bool], ...]:
        changes: list[tuple[str, bool]] = []
        if self.mask & ControlMask.CHARGE:
            changes.append(("charge", self.charge_on))
        if self.mask & ControlMask.DISCHARGE:
            changes.append(("discharge", self.discharge_on))
        if self.mask & ControlMask.BALANCE:
            changes.append(("balance", self.balance_on))
        return tuple(changes)

    def validate_for_send(self) -> None:
        if self.mask == ControlMask.NONE:
            raise ControlProtocolError("at least one control mask bit must be selected")
        if self.device_address != 0:
            raise ControlProtocolError(
                "Ctrl_INFO sending is locked to device address 0 until non-default "
                "downlink addressing is verified on hardware"
            )

    def to_frame(self, *, channel: int = 0, timestamp: float | None = None) -> CanFrame:
        self.validate_for_send()
        return CanFrame(
            can_id=CTRL_INFO_FRAME_ID,
            data=self.payload,
            timestamp=time() if timestamp is None else timestamp,
            is_extended=True,
            channel=channel,
            source="control",
        )
