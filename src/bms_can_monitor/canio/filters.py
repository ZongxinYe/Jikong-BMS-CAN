"""CAN ID validation and ControlCAN filter alignment helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .controlcan_constants import EXTENDED_ID_MASK, STANDARD_ID_MASK


@dataclass(frozen=True)
class AcceptanceFilter:
    """SJA1000-style acceptance-code and acceptance-mask pair."""

    acc_code: int
    acc_mask: int


def validate_can_id(can_id: int, *, extended: bool) -> int:
    """Validate and normalize a standard or extended CAN ID."""

    if can_id < 0:
        raise ValueError("CAN ID cannot be negative")
    limit = EXTENDED_ID_MASK if extended else STANDARD_ID_MASK
    if can_id > limit:
        frame = "extended" if extended else "standard"
        raise ValueError(f"{frame} CAN ID out of range: 0x{can_id:X}")
    return can_id


def right_aligned_id(can_id: int, *, extended: bool) -> int:
    """Return the ControlCAN VCI_CAN_OBJ.ID value.

    ControlCAN stores transmitted/received CAN IDs right-aligned.
    """

    return validate_can_id(can_id, extended=extended)


def left_aligned_filter_id(can_id: int, *, extended: bool) -> int:
    """Return the left-aligned ID used by AccCode/AccMask filters."""

    can_id = validate_can_id(can_id, extended=extended)
    return (can_id << (3 if extended else 21)) & 0xFFFFFFFF


def single_id_acceptance_filter(can_id: int, *, extended: bool) -> AcceptanceFilter:
    """Build AccCode/AccMask values that match exactly one CAN ID."""

    width_mask = EXTENDED_ID_MASK if extended else STANDARD_ID_MASK
    shift = 3 if extended else 21
    acc_code = left_aligned_filter_id(can_id, extended=extended)
    relevant_bits = (width_mask << shift) & 0xFFFFFFFF
    acc_mask = (~relevant_bits) & 0xFFFFFFFF
    return AcceptanceFilter(acc_code=acc_code, acc_mask=acc_mask)

