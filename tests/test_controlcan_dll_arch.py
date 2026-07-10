import pytest

from bms_can_monitor.canio.controlcan_constants import (
    CONTROL_CAN_WIN32_DLL,
    CONTROL_CAN_X64_DLL,
)
from bms_can_monitor.canio.dll_loader import (
    DllArchitectureError,
    inspect_dll,
    python_architecture,
    validate_dll_architecture,
)


def test_bundled_dll_architectures_are_identified():
    assert inspect_dll(CONTROL_CAN_X64_DLL).architecture == "x64"
    assert inspect_dll(CONTROL_CAN_WIN32_DLL).architecture == "x86"


def test_default_runtime_dll_matches_python_architecture():
    info = validate_dll_architecture()
    assert info.architecture == python_architecture()


def test_mismatched_dll_is_rejected_for_current_python():
    current = python_architecture()
    wrong = CONTROL_CAN_WIN32_DLL if current == "x64" else CONTROL_CAN_X64_DLL
    with pytest.raises(DllArchitectureError):
        validate_dll_architecture(wrong)

