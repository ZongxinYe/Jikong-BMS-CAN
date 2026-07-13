from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write_manifest(release_directory: str | Path) -> Path:
    release = Path(release_directory).resolve()
    files = (
        release / "BMS-CAN-Monitor.exe",
        release / "_internal" / "third_party" / "controlcan" / "x64" / "ControlCAN.dll",
        release
        / "_internal"
        / "bms_can_monitor"
        / "protocol"
        / "bms_jikong_v2_1.dbc",
    )
    missing = [path for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError("manifest input missing: " + ", ".join(map(str, missing)))
    manifest = {
        "product": "BMS CAN Monitor",
        "version": "1.2.0",
        "architecture": "x64",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "build_python": platform.python_version(),
        "files": [
            {
                "path": path.relative_to(release).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        ],
    }
    output = release / "release-manifest.json"
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Write release resource hashes")
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    output = write_manifest(args.release)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
