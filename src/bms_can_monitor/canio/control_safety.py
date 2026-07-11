"""Single-use authorization tokens for BMS control commands."""

from __future__ import annotations

from dataclasses import dataclass
from secrets import token_urlsafe
from threading import RLock
from time import monotonic
from typing import Callable

from bms_can_monitor.protocol.control import ControlCommand

CONTROL_CONFIRMATION_PHRASE = "CONFIRM_JIKONG_BMS_CONTROL"


class ControlSafetyError(RuntimeError):
    """Raised when a control command is not explicitly and currently authorized."""


@dataclass(frozen=True, slots=True)
class ControlAuthorization:
    token: str
    expires_at: float


class ControlSafetyGate:
    def __init__(
        self,
        *,
        ttl_seconds: float = 30.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("control authorization TTL must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._lock = RLock()
        self._pending: dict[str, tuple[tuple[int, bool, bool, bool, int], float]] = {}

    def issue(
        self,
        command: ControlCommand,
        confirmation_phrase: str,
    ) -> ControlAuthorization:
        command.validate_for_send()
        if confirmation_phrase != CONTROL_CONFIRMATION_PHRASE:
            raise ControlSafetyError("explicit BMS control confirmation is required")
        now = self._clock()
        expires_at = now + self.ttl_seconds
        token = token_urlsafe(24)
        with self._lock:
            self._prune_locked(now)
            self._pending[token] = (command.fingerprint, expires_at)
        return ControlAuthorization(token=token, expires_at=expires_at)

    def consume(
        self,
        authorization: ControlAuthorization | None,
        command: ControlCommand,
    ) -> None:
        if authorization is None:
            raise ControlSafetyError("BMS control command has not been confirmed")
        now = self._clock()
        with self._lock:
            pending = self._pending.pop(authorization.token, None)
            self._prune_locked(now)
        if pending is None:
            raise ControlSafetyError("control authorization is invalid or has already been used")
        fingerprint, expires_at = pending
        if now >= expires_at or now >= authorization.expires_at:
            raise ControlSafetyError("control authorization has expired")
        if fingerprint != command.fingerprint:
            raise ControlSafetyError("control command changed after confirmation")

    def revoke_all(self) -> None:
        with self._lock:
            self._pending.clear()

    def _prune_locked(self, now: float) -> None:
        expired = [token for token, (_, expiry) in self._pending.items() if now >= expiry]
        for token in expired:
            del self._pending[token]
