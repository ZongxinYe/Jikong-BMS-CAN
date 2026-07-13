"""Stable resource and writable-data paths for source and frozen builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DATA_ENV = "BMS_CAN_MONITOR_DATA_DIR"
APP_DATA_DIRECTORY_NAME = "BMS CAN Monitor"


def resource_root() -> Path:
    """Return the repository root or PyInstaller extraction directory."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[3]


def user_data_directory() -> Path:
    override = os.environ.get(APP_DATA_ENV)
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_DATA_DIRECTORY_NAME


def records_directory() -> Path:
    return user_data_directory() / "records"


def logs_directory() -> Path:
    return user_data_directory() / "logs"


def default_control_audit_path() -> Path:
    return logs_directory() / "control-audit.jsonl"


def default_recording_audit_path() -> Path:
    return logs_directory() / "recording-audit.jsonl"
