"""Append-only JSONL audit trail for every protected control attempt."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from time import time
from typing import Mapping

from bms_can_monitor.protocol.control import ControlCommand
from bms_can_monitor.protocol.models import CanFrame


class ControlAuditError(RuntimeError):
    """Raised when a required control audit record cannot be persisted."""


class ControlAuditLog:
    def __init__(self, path: str | Path = "logs/control-audit.jsonl") -> None:
        self.path = Path(path)
        self._lock = RLock()

    def write(
        self,
        stage: str,
        command: ControlCommand,
        *,
        frame: CanFrame | None = None,
        details: Mapping[str, object] | None = None,
        timestamp: float | None = None,
    ) -> None:
        entry = {
            "timestamp": time() if timestamp is None else float(timestamp),
            "stage": str(stage),
            "command": {
                "device_address": command.device_address,
                "mask": int(command.mask),
                "charge_on": command.charge_on,
                "discharge_on": command.discharge_on,
                "balance_on": command.balance_on,
            },
            "frame": (
                None
                if frame is None
                else {
                    "can_id": f"0x{frame.can_id:08X}",
                    "is_extended": frame.is_extended,
                    "dlc": frame.dlc,
                    "data": frame.data.hex(" ").upper(),
                    "channel": frame.channel,
                }
            ),
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
            raise ControlAuditError(f"failed to write control audit log: {self.path}") from exc
