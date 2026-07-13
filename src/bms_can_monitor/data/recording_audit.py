"""Append-only diagnostic log for SQLite recording sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from time import time
from typing import Mapping

from bms_can_monitor.config import default_recording_audit_path


class RecordingAuditError(RuntimeError):
    """Raised when a recording diagnostic entry cannot be persisted."""


class RecordingAuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_recording_audit_path()
        self._lock = RLock()

    def write(
        self,
        stage: str,
        database_path: str | Path,
        *,
        session_id: int | None = None,
        reason: str = "",
        details: Mapping[str, object] | None = None,
        timestamp: float | None = None,
    ) -> None:
        entry = {
            "timestamp": time() if timestamp is None else float(timestamp),
            "stage": str(stage),
            "database_path": str(Path(database_path).resolve()),
            "session_id": session_id,
            "reason": str(reason),
            "details": dict(details or {}),
        }
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(
                        json.dumps(
                            entry,
                            ensure_ascii=False,
                            default=repr,
                            separators=(",", ":"),
                        )
                    )
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        except OSError as exc:
            raise RecordingAuditError(
                f"failed to write recording audit log: {self.path}"
            ) from exc
