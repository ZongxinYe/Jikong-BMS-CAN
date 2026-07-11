"""Resolve Jikong BMS device addresses from offset CAN frame IDs."""

from __future__ import annotations

from dataclasses import dataclass

from .dbc_loader import DbcDecoder, MAX_DEVICE_ADDRESS, load_default_decoder
from .models import CanFrame


@dataclass(frozen=True, slots=True)
class ResolvedBmsFrame:
    device_address: int
    message_name: str
    normalized_frame_id: int


class BmsAddressConflictError(ValueError):
    """Raised when one physical CAN ID maps to multiple BMS messages."""

    def __init__(
        self,
        frame: CanFrame,
        candidates: tuple[ResolvedBmsFrame, ...],
    ) -> None:
        self.frame = frame
        self.candidates = candidates
        choices = ", ".join(
            f"address {item.device_address} / {item.message_name}"
            for item in candidates
        )
        super().__init__(f"CAN ID 0x{frame.can_id:X} is ambiguous: {choices}")


class BmsAddressResolver:
    """Build an exact physical-ID index for every supported device address."""

    def __init__(self, dbc: DbcDecoder | None = None) -> None:
        self.dbc = dbc or load_default_decoder()
        candidates: dict[
            tuple[int, bool], list[ResolvedBmsFrame]
        ] = {}
        for message in self.dbc.messages:
            if "BMS" not in message.senders:
                continue
            for address in range(MAX_DEVICE_ADDRESS + 1):
                physical_id = message.frame_id + address
                key = (physical_id, bool(message.is_extended_frame))
                candidates.setdefault(key, []).append(
                    ResolvedBmsFrame(
                        device_address=address,
                        message_name=message.name,
                        normalized_frame_id=message.frame_id,
                    )
                )
        self._candidates = {
            key: tuple(values) for key, values in candidates.items()
        }

    def candidates_for_frame(
        self, frame: CanFrame
    ) -> tuple[ResolvedBmsFrame, ...]:
        return self._candidates.get((frame.can_id, frame.is_extended), ())

    def resolve(self, frame: CanFrame) -> ResolvedBmsFrame | None:
        candidates = self.candidates_for_frame(frame)
        if not candidates:
            return None
        if len(candidates) > 1:
            raise BmsAddressConflictError(frame, candidates)
        return candidates[0]

    @property
    def conflicts(self) -> dict[tuple[int, bool], tuple[ResolvedBmsFrame, ...]]:
        return {
            key: candidates
            for key, candidates in self._candidates.items()
            if len(candidates) > 1
        }
