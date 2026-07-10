from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from bms_can_monitor.canio.dll_loader import (  # noqa: E402
    default_dll_path,
    inspect_dll,
    python_architecture,
    validate_dll_architecture,
)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dll_path()
    info = inspect_dll(path)
    print(f"Python architecture: {python_architecture()}")
    print(f"DLL path: {info.path}")
    print(f"DLL architecture: {info.architecture}")
    print(f"DLL size: {info.size}")
    validate_dll_architecture(path)
    print("DLL architecture matches Python.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

