import pytest

from bms_can_monitor.canio.controlcan import ControlCanBindingError, bind_library


REQUIRED_FUNCTIONS = (
    "VCI_OpenDevice",
    "VCI_CloseDevice",
    "VCI_InitCAN",
    "VCI_ReadBoardInfo",
    "VCI_GetReceiveNum",
    "VCI_ClearBuffer",
    "VCI_StartCAN",
    "VCI_ResetCAN",
    "VCI_Transmit",
    "VCI_Receive",
)


class FakeFunction:
    def __call__(self, *args):
        return 1


class FakeLibrary:
    pass


def make_library(*, omit=()):
    library = FakeLibrary()
    for name in REQUIRED_FUNCTIONS:
        if name not in omit:
            setattr(library, name, FakeFunction())
    return library


def test_binding_accepts_missing_optional_functions():
    library = make_library()
    assert bind_library(library) is library
    assert library.VCI_Receive.argtypes is not None


def test_binding_reports_missing_required_function():
    with pytest.raises(ControlCanBindingError, match="VCI_Receive"):
        bind_library(make_library(omit={"VCI_Receive"}))
