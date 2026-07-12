from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from bms_can_monitor.canio.controlcan_constants import PE_MACHINE_AMD64  # noqa: E402
from bms_can_monitor.canio.dll_loader import read_pe_machine  # noqa: E402


def verify_release(path: str | Path, *, launch: bool = False) -> tuple[str, ...]:
    release = Path(path).resolve()
    internal = release / "_internal"
    executable = release / "BMS-CAN-Monitor.exe"
    dll = internal / "third_party" / "controlcan" / "x64" / "ControlCAN.dll"
    dbc = internal / "bms_can_monitor" / "protocol" / "bms_jikong_v2_1.dbc"
    multi_bms_guide = (
        release / "Documentation" / "phase7-multi-bms-raw-replay.md"
    )
    required = (release, internal, executable, dll, dbc, multi_bms_guide)
    missing = [item for item in required if not item.exists()]
    if missing:
        raise RuntimeError("release is missing: " + ", ".join(str(item) for item in missing))
    if read_pe_machine(executable) != PE_MACHINE_AMD64:
        raise RuntimeError("BMS-CAN-Monitor.exe is not x64")
    if read_pe_machine(dll) != PE_MACHINE_AMD64:
        raise RuntimeError("bundled ControlCAN.dll is not x64")

    checks = [
        f"executable={executable}",
        f"controlcan={dll}",
        f"dbc={dbc}",
        f"multi_bms_guide={multi_bms_guide}",
    ]
    if launch:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        system_root = Path(environment.get("SystemRoot", r"C:\Windows"))
        environment["PATH"] = str(system_root / "System32")
        with tempfile.TemporaryDirectory(prefix="bms-can-release-") as work_directory:
            completed = subprocess.run(
                [str(executable), "--smoke-test"],
                cwd=work_directory,
                env=environment,
                timeout=45,
                check=False,
            )
        if completed.returncode != 0:
            raise RuntimeError(
                f"packaged GUI smoke test returned {completed.returncode}"
            )
        checks.append("gui_smoke_test=passed")
    return tuple(checks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Windows release directory")
    parser.add_argument("release", type=Path)
    parser.add_argument("--launch", action="store_true", help="run packaged GUI smoke test")
    args = parser.parse_args()
    try:
        checks = verify_release(args.release, launch=args.launch)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    for check in checks:
        print(f"OK: {check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
