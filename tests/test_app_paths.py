from pathlib import Path

from bms_can_monitor.config import (
    APP_DATA_ENV,
    default_control_audit_path,
    records_directory,
    resource_root,
    user_data_directory,
)


def test_user_data_path_can_be_overridden(monkeypatch, tmp_path):
    target = tmp_path / "portable-data"
    monkeypatch.setenv(APP_DATA_ENV, str(target))
    assert user_data_directory() == target.resolve()
    assert records_directory() == target.resolve() / "records"
    assert default_control_audit_path() == target.resolve() / "logs" / "control-audit.jsonl"


def test_resource_root_uses_pyinstaller_meipass(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)
    assert resource_root() == tmp_path.resolve()


def test_source_resource_root_contains_project_files():
    root = resource_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "third_party" / "controlcan" / "x64" / "ControlCAN.dll").is_file()
