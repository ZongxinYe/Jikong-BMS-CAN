import json
import importlib.util
from pathlib import Path

import pytest

from bms_can_monitor import __version__
from bms_can_monitor.canio.dll_loader import default_dll_path


def test_packaging_inputs_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "packaging" / "bms_can_monitor.spec").is_file()
    assert (root / "packaging" / "launcher.py").is_file()
    assert (root / "packaging" / "version_info.txt").is_file()
    assert (root / "src" / "bms_can_monitor" / "protocol" / "bms_jikong_v2_1.dbc").is_file()
    assert default_dll_path().is_file()
    assert (root / "docs" / "phase7-multi-bms-raw-replay.md").is_file()
    assert (root / "docs" / "v1.2-record-replay-reliability.md").is_file()
    assert __version__ == "1.2.0"
    assert 'version = "1.2.0"' in (root / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    version_info = (root / "packaging" / "version_info.txt").read_text(
        encoding="utf-8"
    )
    assert "FileVersion', u'1.2.0" in version_info
    assert "ProductVersion', u'1.2.0" in version_info


def test_release_verifier_reports_missing_directory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = root / "tools" / "verify_windows_release.py"
    spec = importlib.util.spec_from_file_location("release_verifier_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match="release is missing"):
        module.verify_release(tmp_path / "missing")


def test_release_manifest_contains_critical_hashes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    release = tmp_path / "release"
    files = (
        release / "BMS-CAN-Monitor.exe",
        release / "_internal" / "third_party" / "controlcan" / "x64" / "ControlCAN.dll",
        release
        / "_internal"
        / "bms_can_monitor"
        / "protocol"
        / "bms_jikong_v2_1.dbc",
    )
    for index, path in enumerate(files):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"file-{index}".encode())

    script = root / "tools" / "write_release_manifest.py"
    spec = importlib.util.spec_from_file_location("release_manifest_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = module.write_manifest(release)
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["architecture"] == "x64"
    assert manifest["version"] == "1.2.0"
    assert len(manifest["files"]) == 3
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
