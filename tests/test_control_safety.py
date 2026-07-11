import pytest

from bms_can_monitor.canio import (
    CONTROL_CONFIRMATION_PHRASE,
    ControlSafetyError,
    ControlSafetyGate,
)
from bms_can_monitor.protocol import ControlCommand, ControlMask


def command(*, charge_on=True):
    return ControlCommand(mask=ControlMask.CHARGE, charge_on=charge_on)


def test_confirmation_token_is_single_use_and_command_bound():
    gate = ControlSafetyGate()
    original = command()
    authorization = gate.issue(original, CONTROL_CONFIRMATION_PHRASE)
    gate.consume(authorization, original)
    with pytest.raises(ControlSafetyError, match="already been used"):
        gate.consume(authorization, original)

    authorization = gate.issue(original, CONTROL_CONFIRMATION_PHRASE)
    with pytest.raises(ControlSafetyError, match="changed after confirmation"):
        gate.consume(authorization, command(charge_on=False))


def test_confirmation_phrase_is_required():
    gate = ControlSafetyGate()
    with pytest.raises(ControlSafetyError, match="explicit"):
        gate.issue(command(), "yes")
    with pytest.raises(ControlSafetyError, match="not been confirmed"):
        gate.consume(None, command())


def test_confirmation_token_expires():
    now = [100.0]
    gate = ControlSafetyGate(ttl_seconds=5.0, clock=lambda: now[0])
    authorization = gate.issue(command(), CONTROL_CONFIRMATION_PHRASE)
    now[0] = 106.0
    with pytest.raises(ControlSafetyError, match="expired"):
        gate.consume(authorization, command())


def test_revoke_all_invalidates_pending_confirmation():
    gate = ControlSafetyGate()
    authorization = gate.issue(command(), CONTROL_CONFIRMATION_PHRASE)
    gate.revoke_all()
    with pytest.raises(ControlSafetyError, match="invalid"):
        gate.consume(authorization, command())
