"""ControlCAN.dll path and architecture validation."""

from __future__ import annotations

import ctypes
import platform
import struct
from dataclasses import dataclass
from pathlib import Path

from .controlcan_constants import (
    CONTROL_CAN_WIN32_DLL,
    CONTROL_CAN_X64_DLL,
    PE_MACHINE_AMD64,
    PE_MACHINE_I386,
)


@dataclass(frozen=True)
class ControlCanDllInfo:
    path: Path
    machine: int
    architecture: str
    size: int


class DllArchitectureError(RuntimeError):
    """Raised when a DLL bitness does not match the Python process."""


def python_architecture() -> str:
    """Return x86 or x64 for the current Python process."""

    return "x64" if struct.calcsize("P") * 8 == 64 else "x86"


def default_dll_path() -> Path:
    """Choose the bundled DLL matching the current Python process."""

    return CONTROL_CAN_X64_DLL if python_architecture() == "x64" else CONTROL_CAN_WIN32_DLL


def read_pe_machine(path: str | Path) -> int:
    """Read the PE machine field from a Windows DLL or EXE."""

    dll_path = Path(path)
    with dll_path.open("rb") as fh:
        if fh.read(2) != b"MZ":
            raise ValueError(f"Not a PE file: {dll_path}")
        fh.seek(0x3C)
        pe_offset = int.from_bytes(fh.read(4), "little")
        fh.seek(pe_offset)
        if fh.read(4) != b"PE\0\0":
            raise ValueError(f"Missing PE signature: {dll_path}")
        return int.from_bytes(fh.read(2), "little")


def machine_to_arch(machine: int) -> str:
    """Convert a PE machine code to a short architecture name."""

    if machine == PE_MACHINE_AMD64:
        return "x64"
    if machine == PE_MACHINE_I386:
        return "x86"
    return f"0x{machine:04X}"


def inspect_dll(path: str | Path) -> ControlCanDllInfo:
    """Return path, PE machine, architecture and size for a DLL."""

    dll_path = Path(path)
    machine = read_pe_machine(dll_path)
    return ControlCanDllInfo(
        path=dll_path,
        machine=machine,
        architecture=machine_to_arch(machine),
        size=dll_path.stat().st_size,
    )


def validate_dll_architecture(path: str | Path | None = None) -> ControlCanDllInfo:
    """Ensure the ControlCAN DLL matches the current Python architecture."""

    dll_path = Path(path) if path is not None else default_dll_path()
    info = inspect_dll(dll_path)
    expected = python_architecture()
    if info.architecture != expected:
        raise DllArchitectureError(
            f"ControlCAN.dll is {info.architecture}, but Python is {expected}: {info.path}"
        )
    return info


def load_controlcan(path: str | Path | None = None) -> ctypes.CDLL:
    """Load ControlCAN.dll after architecture validation."""

    info = validate_dll_architecture(path)
    if platform.system() == "Windows":
        return ctypes.WinDLL(str(info.path))
    return ctypes.CDLL(str(info.path))

