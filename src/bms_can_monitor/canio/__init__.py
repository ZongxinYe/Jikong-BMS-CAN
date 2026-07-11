"""CAN hardware access, background workers, scheduling, and replay."""

from .bus_config import BusConfig
from .can_worker import CanReceiveWorker, ReceiveWorkerStats
from .canalyst2_adapter import AdapterState, Canalyst2Adapter, Canalyst2Error
from .control_safety import (
    CONTROL_CONFIRMATION_PHRASE,
    ControlAuthorization,
    ControlSafetyError,
    ControlSafetyGate,
)
from .device_discovery import DeviceInfo, discover_devices
from .diagnostics import DiagnosticSnapshot, collect_diagnostics
from .events import CanEvent, CanEventType
from .replay_worker import (
    MemoryReplaySource,
    ReplayFrameSource,
    ReplayWorker,
    load_replay_csv,
    write_replay_csv,
)
from .tx_scheduler import TxScheduler, TxTaskSnapshot

__all__ = [
    "AdapterState",
    "BusConfig",
    "CanEvent",
    "CanEventType",
    "CanReceiveWorker",
    "Canalyst2Adapter",
    "Canalyst2Error",
    "CONTROL_CONFIRMATION_PHRASE",
    "ControlAuthorization",
    "ControlSafetyError",
    "ControlSafetyGate",
    "DeviceInfo",
    "DiagnosticSnapshot",
    "MemoryReplaySource",
    "ReceiveWorkerStats",
    "ReplayWorker",
    "ReplayFrameSource",
    "TxScheduler",
    "TxTaskSnapshot",
    "collect_diagnostics",
    "discover_devices",
    "load_replay_csv",
    "write_replay_csv",
]
