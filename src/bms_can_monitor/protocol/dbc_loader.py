"""Thread-safe DBC loading, reloading, and frame decoding."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

import cantools
from cantools.database.can import Database, Message

from .models import CanFrame, DecodedMessage, DecodedSignal

DEFAULT_DBC_PATH = Path(__file__).with_name("bms_jikong_v2_1.dbc")
MAX_DEVICE_ADDRESS = 0x0B


class DbcDecodeError(ValueError):
    """Raised when a frame cannot be matched to or decoded by the DBC."""


def validate_device_address(device_address: int) -> int:
    if not 0 <= device_address <= MAX_DEVICE_ADDRESS:
        raise ValueError(
            f"device address must be 0..{MAX_DEVICE_ADDRESS}; larger values "
            "would overflow the standard 0x07F4 frame ID"
        )
    return device_address


class DbcDecoder:
    """Decode normalized Jikong CAN IDs with a reloadable cantools database."""

    def __init__(self, path: str | Path = DEFAULT_DBC_PATH) -> None:
        self.path = Path(path).resolve()
        self._lock = RLock()
        self._database: Database
        self.reload()

    @property
    def database(self) -> Database:
        return self._database

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._database.messages)

    def reload(self) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(f"DBC file not found: {self.path}")
        database = cantools.database.load_file(self.path, strict=True)
        with self._lock:
            self._database = database

    def message_for_frame(
        self, frame: CanFrame, *, device_address: int = 0
    ) -> tuple[Message, int]:
        validate_device_address(device_address)
        normalized_id = frame.can_id - device_address
        if normalized_id < 0:
            raise DbcDecodeError(f"CAN ID 0x{frame.can_id:X} cannot be normalized")

        with self._lock:
            try:
                message = self._database.get_message_by_frame_id(normalized_id)
            except KeyError as exc:
                raise DbcDecodeError(
                    f"CAN ID 0x{frame.can_id:X} (normalized 0x{normalized_id:X}) "
                    "is not defined in the DBC"
                ) from exc

        if message.is_extended_frame != frame.is_extended:
            expected = "extended" if message.is_extended_frame else "standard"
            raise DbcDecodeError(
                f"CAN ID 0x{frame.can_id:X} must be marked as an {expected} frame"
            )
        return message, normalized_id

    def decode(self, frame: CanFrame, *, device_address: int = 0) -> DecodedMessage:
        if frame.is_remote:
            raise DbcDecodeError("remote frames do not carry decodable signal data")

        message, normalized_id = self.message_for_frame(
            frame, device_address=device_address
        )
        try:
            with self._lock:
                physical = message.decode(
                    frame.data,
                    decode_choices=False,
                    scaling=True,
                    allow_truncated=True,
                    allow_excess=False,
                )
                raw = message.decode(
                    frame.data,
                    decode_choices=False,
                    scaling=False,
                    allow_truncated=True,
                    allow_excess=False,
                )
        except (ValueError, cantools.database.errors.DecodeError) as exc:
            raise DbcDecodeError(
                f"failed to decode {message.name} from CAN ID 0x{frame.can_id:X}: {exc}"
            ) from exc

        definitions = {signal.name: signal for signal in message.signals}
        signals = tuple(
            DecodedSignal(
                name=name,
                value=value,
                raw_value=raw.get(name),
                unit=definitions[name].unit,
                timestamp=frame.timestamp,
                source_frame_id=frame.can_id,
            )
            for name, value in physical.items()
        )
        return DecodedMessage(
            name=message.name,
            normalized_frame_id=normalized_id,
            frame=frame,
            signals=signals,
            device_address=device_address,
        )


def load_default_decoder() -> DbcDecoder:
    return DbcDecoder(DEFAULT_DBC_PATH)
