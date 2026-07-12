"""GUI-facing orchestration for live CAN, replay, decoding, and recording."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
from threading import RLock, Thread
from time import monotonic, time

from PySide6.QtCore import QObject, QTimer, Signal

from bms_can_monitor.canio import (
    BusConfig,
    CONTROL_CONFIRMATION_PHRASE,
    CanEvent,
    CanEventType,
    CanReceiveWorker,
    Canalyst2Adapter,
    ControlAuthorization,
    ControlSafetyError,
    ControlSafetyGate,
    ReplayWorker,
    load_replay_csv,
)
from bms_can_monitor.data import (
    ControlAuditError,
    ControlAuditLog,
    DataPipeline,
    RecorderError,
    RecordingReadError,
    RecordingReader,
    SessionMetadata,
    SessionSummary,
    SessionRecorder,
    SignalRingBuffer,
    SqliteReplaySource,
)
from bms_can_monitor.protocol import BmsSnapshot, CanFrame, ControlCommand

from .demo import build_demo_frames


DEFAULT_WAVEFORM_SIGNALS = (
    "BattVolt",
    "CellVoltSum",
    "BattCurr",
    "SOC",
    "MaxCellVolt",
    "MinCellVolt",
    "MaxCellTemp",
    "MinCellTemp",
)
MAX_CONTROL_BMS_AGE_SECONDS = 3.0
SQLITE_REPLAY_SUFFIXES = {".sqlite3", ".sqlite", ".db"}


class DbcMismatchError(RuntimeError):
    def __init__(self, recorded_hash: str, current_hash: str) -> None:
        self.recorded_hash = recorded_hash
        self.current_hash = current_hash
        super().__init__(
            "recording DBC hash differs from the current DBC; replay would use "
            "the current protocol definition"
        )


@dataclass(frozen=True, slots=True)
class SourceState:
    mode: str = "idle"
    label: str = "未连接"
    active: bool = False
    busy: bool = False
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RecordingState:
    active: bool = False
    database_path: Path | None = None
    session_id: int | None = None


@dataclass(frozen=True, slots=True)
class GuiStats:
    frames_processed: int
    decoded_frames: int
    decode_errors: int
    queue_depth: int
    source_dropped_frames: int
    frames_per_second: float
    recorder_queue_depth: int


@dataclass(frozen=True, slots=True)
class ControlSendResult:
    success: bool
    message: str
    command: ControlCommand
    frame: CanFrame
    adapter_result: int | None = None


class GuiController(QObject):
    """Keep worker threads and blocking SDK calls outside the Qt paint path."""

    frames_processed = Signal(object)
    snapshot_updated = Signal(object)
    bms_snapshot_updated = Signal(int, object)
    detected_addresses_changed = Signal(object)
    events_received = Signal(object)
    source_changed = Signal(object)
    recording_changed = Signal(object)
    stats_updated = Signal(object)
    control_send_finished = Signal(object)
    error_raised = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        frame_queue_size: int = 50_000,
        start_timers: bool = True,
        control_audit_path: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.frame_queue: Queue[CanFrame] = Queue(maxsize=frame_queue_size)
        self._event_queue: Queue[CanEvent] = Queue()
        self.pipeline = DataPipeline(
            ring_buffer=SignalRingBuffer(
                DEFAULT_WAVEFORM_SIGNALS,
                window_seconds=300.0,
                max_points_per_signal=100_000,
            )
        )

        self._source_lock = RLock()
        self._source_state = SourceState()
        self._recording_state = RecordingState()
        self._adapter: Canalyst2Adapter | None = None
        self._receive_worker: CanReceiveWorker | None = None
        self._replay_worker: ReplayWorker | None = None
        self._replay_database_path: Path | None = None
        self._source_thread: Thread | None = None
        self._current_config = BusConfig()
        self._recorder: SessionRecorder | None = None
        self._control_gate = ControlSafetyGate()
        self._control_audit = ControlAuditLog(control_audit_path)
        self._control_send_pending = False
        self._control_thread: Thread | None = None
        self._shutdown_requested = False
        self._demo_step = 0
        self._reported_addresses: tuple[int, ...] = ()

        self._frames_processed = 0
        self._decoded_frames = 0
        self._rate_frames = 0
        self._rate_started = monotonic()
        self._last_rate = 0.0

        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(16)
        self._drain_timer.timeout.connect(self.drain_once)
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self.emit_stats)
        self._demo_timer = QTimer(self)
        self._demo_timer.setInterval(100)
        self._demo_timer.timeout.connect(self._emit_demo_tick)
        if start_timers:
            self._drain_timer.start()
            self._stats_timer.start()

    @property
    def source_state(self) -> SourceState:
        with self._source_lock:
            return self._source_state

    @property
    def recording_state(self) -> RecordingState:
        return self._recording_state

    @property
    def current_config(self) -> BusConfig:
        return self._current_config

    @property
    def control_send_pending(self) -> bool:
        with self._source_lock:
            return self._control_send_pending

    @property
    def control_ready(self) -> bool:
        try:
            probe = ControlCommand(mask=1, device_address=self._current_config.device_address)
            self._require_control_ready(probe)
        except (ControlSafetyError, ValueError):
            return False
        return True

    def _set_source_state(self, state: SourceState) -> None:
        with self._source_lock:
            self._source_state = state
        if state.mode == "idle":
            self._control_gate.revoke_all()
        self.source_changed.emit(state)

    def _enqueue_event(self, event: CanEvent) -> None:
        self._event_queue.put(event)

    def connect_live(self, config: BusConfig) -> None:
        if self.source_state.mode != "idle":
            raise RuntimeError("请先停止当前数据源")
        self._current_config = config
        self.pipeline.device_address = config.device_address
        self.reset_data()
        self._set_source_state(
            SourceState("live", "正在连接 CANalyst-II", busy=True)
        )
        self._source_thread = Thread(
            target=self._connect_live_worker,
            args=(config,),
            name="gui-connect-live",
            daemon=True,
        )
        self._source_thread.start()

    def _connect_live_worker(self, config: BusConfig) -> None:
        adapter = Canalyst2Adapter(config, event_sink=self._enqueue_event)
        try:
            adapter.connect()
            if self._shutdown_requested:
                adapter.close(suppress_errors=True)
                return
            worker = CanReceiveWorker(
                adapter,
                self.frame_queue,
                batch_size=config.receive_batch_size,
                wait_ms=config.receive_wait_ms,
                event_sink=self._enqueue_event,
            )
            with self._source_lock:
                self._adapter = adapter
                self._receive_worker = worker
            worker.start()
            self._set_source_state(
                SourceState(
                    "live",
                    "CANalyst-II 已连接",
                    active=True,
                    detail=(
                        f"设备 {config.device_index} / CAN{config.channel + 1} / "
                        f"{config.bitrate // 1000} kbps"
                    ),
                )
            )
        except Exception as exc:
            adapter.close(suppress_errors=True)
            with self._source_lock:
                self._adapter = None
                self._receive_worker = None
            self._set_source_state(SourceState())
            self.error_raised.emit(f"CANalyst-II 连接失败：{exc}")

    @property
    def current_dbc_sha256(self) -> str:
        return self.pipeline.address_resolver.dbc.content_sha256

    @staticmethod
    def recording_sessions(path: str | Path) -> tuple[SessionSummary, ...]:
        return RecordingReader(path).list_sessions()

    def start_replay(
        self,
        path: str | Path,
        *,
        speed: float = 1.0,
        loop: bool = False,
        session_id: int | None = None,
        allow_dbc_mismatch: bool = False,
    ) -> None:
        if self.source_state.mode != "idle":
            raise RuntimeError("请先停止当前数据源")
        replay_path = Path(path)
        sqlite_source: SqliteReplaySource | None = None
        if replay_path.suffix.lower() in SQLITE_REPLAY_SUFFIXES:
            reader = RecordingReader(replay_path)
            sessions = reader.list_sessions()
            if not sessions:
                raise RecordingReadError("recording database contains no sessions")
            selected_id = (
                sessions[-1].session_id if session_id is None else session_id
            )
            sqlite_source = SqliteReplaySource(replay_path, selected_id)
            recorded_hash = sqlite_source.summary.dbc_sha256
            current_hash = self.current_dbc_sha256
            if (
                recorded_hash
                and recorded_hash != current_hash
                and not allow_dbc_mismatch
            ):
                raise DbcMismatchError(recorded_hash, current_hash)
            if (
                self._recording_state.database_path is not None
                and self._recording_state.database_path.resolve()
                == replay_path.resolve()
            ):
                raise RuntimeError("cannot replay the database currently being recorded")
        self.reset_data()
        self._set_source_state(
            SourceState("replay", "正在加载回放文件", busy=True, detail=str(replay_path))
        )
        if sqlite_source is not None:
            self._replay_database_path = replay_path.resolve()
            self._source_thread = Thread(
                target=self._start_replay_source_worker,
                args=(sqlite_source, replay_path.name, speed, loop),
                name="gui-load-sqlite-replay",
                daemon=True,
            )
            self._source_thread.start()
            return
        self._source_thread = Thread(
            target=self._start_replay_worker,
            args=(replay_path, speed, loop),
            name="gui-load-replay",
            daemon=True,
        )
        self._source_thread.start()

    def start_demo(self) -> None:
        if self.source_state.mode != "idle":
            raise RuntimeError("请先停止当前数据源")
        self.reset_data()
        self._demo_step = 0
        self._demo_timer.start()
        self._set_source_state(
            SourceState("demo", "演示数据运行中", active=True, detail="本地模拟 BMS")
        )

    def _emit_demo_tick(self) -> None:
        self.inject_frames(build_demo_frames(time(), self._demo_step))
        self._demo_step += 1

    def _start_replay_worker(self, path: Path, speed: float, loop: bool) -> None:
        try:
            frames = load_replay_csv(path)
            self._start_replay_source_worker(frames, path.name, speed, loop)
        except Exception as exc:
            with self._source_lock:
                self._replay_worker = None
            self._replay_database_path = None
            self._set_source_state(SourceState())
            self.error_raised.emit(f"回放文件加载失败：{exc}")

    def _start_replay_source_worker(
        self,
        source,
        source_name: str,
        speed: float,
        loop: bool,
    ) -> None:
        try:
            if self._shutdown_requested:
                return
            worker = ReplayWorker(
                source,
                self.frame_queue,
                speed=speed,
                loop=loop,
                event_sink=self._enqueue_event,
            )
            with self._source_lock:
                self._replay_worker = worker
            worker.start()
            self._set_source_state(
                SourceState(
                    "replay",
                    "离线回放中",
                    active=True,
                    detail=(
                        f"{source_name} / {worker.source.frame_count} 帧 / "
                        f"{speed:g}x"
                    ),
                )
            )
        except Exception as exc:
            with self._source_lock:
                self._replay_worker = None
            self._replay_database_path = None
            self._set_source_state(SourceState())
            self.error_raised.emit(f"回放文件加载失败：{exc}")

    def disconnect_source(self) -> None:
        state = self.source_state
        if state.mode == "idle":
            return
        if state.mode == "demo":
            self._demo_timer.stop()
            self._set_source_state(SourceState())
            return
        self._set_source_state(
            SourceState(state.mode, "正在停止数据源", busy=True, detail=state.detail)
        )
        self._source_thread = Thread(
            target=self._stop_source_blocking,
            name="gui-stop-source",
            daemon=True,
        )
        self._source_thread.start()

    def _stop_source_blocking(self) -> None:
        with self._source_lock:
            receive_worker = self._receive_worker
            replay_worker = self._replay_worker
            adapter = self._adapter
        if receive_worker is not None:
            receive_worker.stop()
            receive_worker.join(2.0)
        if replay_worker is not None:
            replay_worker.stop()
            replay_worker.join(2.0)
        if adapter is not None:
            adapter.close(suppress_errors=True)
        with self._source_lock:
            self._receive_worker = None
            self._replay_worker = None
            self._adapter = None
        self._replay_database_path = None
        self._set_source_state(SourceState())

    def start_recording(
        self,
        database_path: str | Path,
        *,
        note: str = "",
    ) -> int:
        if self._recorder is not None:
            raise RuntimeError("当前已经在记录")
        path = Path(database_path)
        if (
            self._replay_database_path is not None
            and path.resolve() == self._replay_database_path
        ):
            raise RuntimeError("cannot record into the database currently being replayed")
        config = self._current_config
        recorder = SessionRecorder(path)
        session_id = recorder.start(
            SessionMetadata(
                device_type=config.device_type,
                device_index=config.device_index,
                channel=config.channel,
                bitrate=config.bitrate,
                device_address=config.device_address,
                note=note,
                detected_addresses=self.pipeline.detected_addresses,
                dbc_sha256=self.current_dbc_sha256,
            )
        )
        self._recorder = recorder
        self.pipeline.recorder = recorder
        self._recording_state = RecordingState(True, path, session_id)
        self.recording_changed.emit(self._recording_state)
        return session_id

    def stop_recording(self) -> None:
        recorder = self._recorder
        if recorder is None:
            return
        self.pipeline.recorder = None
        self._recorder = None
        try:
            recorder.stop(detected_addresses=self.pipeline.detected_addresses)
        finally:
            self._recording_state = RecordingState()
            self.recording_changed.emit(self._recording_state)

    def authorize_control(
        self,
        command: ControlCommand,
        confirmation_phrase: str,
    ) -> ControlAuthorization:
        frame: CanFrame | None = None
        try:
            self._require_control_ready(command)
            authorization = self._control_gate.issue(command, confirmation_phrase)
            frame = command.to_frame(channel=self._current_config.channel)
            self._control_audit.write(
                "authorized",
                command,
                frame=frame,
                details=self._control_details(command),
            )
        except Exception as exc:
            self._control_gate.revoke_all()
            self._record_control_rejection(command, exc)
            if isinstance(exc, ControlSafetyError):
                raise
            raise ControlSafetyError(str(exc)) from exc

        self._enqueue_event(
            CanEvent(
                event_type=CanEventType.CONTROL_AUTHORIZED,
                message="BMS control command explicitly authorized",
                details=self._control_details(command, frame=frame),
            )
        )
        return authorization

    def send_control(
        self,
        command: ControlCommand,
        authorization: ControlAuthorization | None,
    ) -> None:
        pending_reserved = False
        try:
            adapter = self._require_control_ready(command)
            self._control_gate.consume(authorization, command)
            with self._source_lock:
                if self._control_send_pending:
                    raise ControlSafetyError(
                        "another BMS control command is still pending"
                    )
                self._control_send_pending = True
                pending_reserved = True
            frame = command.to_frame(channel=self._current_config.channel)
            self._control_audit.write(
                "send_requested",
                command,
                frame=frame,
                details=self._control_details(command),
            )
        except Exception as exc:
            if pending_reserved:
                with self._source_lock:
                    self._control_send_pending = False
            self._record_control_rejection(command, exc)
            if isinstance(exc, ControlSafetyError):
                raise
            raise ControlSafetyError(str(exc)) from exc
        self._enqueue_event(
            CanEvent(
                event_type=CanEventType.CONTROL_SEND_REQUESTED,
                message="BMS control frame queued for transmission",
                details=self._control_details(command, frame=frame),
            )
        )
        try:
            self._control_thread = Thread(
                target=self._send_control_worker,
                args=(adapter, command, frame),
                name="gui-bms-control-send",
                daemon=True,
            )
            self._control_thread.start()
        except Exception:
            with self._source_lock:
                self._control_send_pending = False
            raise

    def _require_control_ready(self, command: ControlCommand) -> Canalyst2Adapter:
        command.validate_for_send()
        state = self.source_state
        if state.mode != "live" or not state.active:
            raise ControlSafetyError("BMS control requires an active live CAN connection")
        config = self._current_config
        if config.mode != 0:
            raise ControlSafetyError("BMS control is disabled in listen-only or self-test mode")
        if config.device_address != 0:
            raise ControlSafetyError(
                "BMS control is disabled for non-default device addresses until verified"
            )
        if command.device_address != config.device_address:
            raise ControlSafetyError("control target does not match the connected BMS address")
        with self._source_lock:
            adapter = self._adapter
            pending = self._control_send_pending
        if adapter is None or not adapter.is_started:
            raise ControlSafetyError("CAN adapter is not ready for transmission")
        if pending:
            raise ControlSafetyError("another BMS control command is still pending")
        snapshot_timestamp = self.pipeline.last_seen(config.device_address)
        age = time() - snapshot_timestamp
        if snapshot_timestamp <= 0 or age < 0 or age > MAX_CONTROL_BMS_AGE_SECONDS:
            raise ControlSafetyError("no recent BMS frame was received for the control target")
        return adapter

    def _send_control_worker(
        self,
        adapter: Canalyst2Adapter,
        command: ControlCommand,
        frame: CanFrame,
    ) -> None:
        result: int | None = None
        try:
            result = adapter.send(frame)
            if result != 1:
                raise RuntimeError(f"CAN adapter returned transmit status {result}")
            event = CanEvent(
                event_type=CanEventType.TX_SUCCEEDED,
                message="BMS control frame sent successfully",
                details=self._control_details(command, frame=frame, result=result),
            )
            outcome = ControlSendResult(True, "控制帧发送成功", command, frame, result)
            self._write_control_outcome("succeeded", command, frame, result=result)
        except Exception as exc:
            event = CanEvent(
                event_type=CanEventType.TX_FAILED,
                message=f"BMS control frame send failed: {exc}",
                details=self._control_details(command, frame=frame, error=repr(exc)),
            )
            outcome = ControlSendResult(False, f"控制帧发送失败：{exc}", command, frame, result)
            self._write_control_outcome("failed", command, frame, error=repr(exc))
        finally:
            with self._source_lock:
                self._control_send_pending = False
        self._enqueue_event(event)
        self.control_send_finished.emit(outcome)

    def _write_control_outcome(
        self,
        stage: str,
        command: ControlCommand,
        frame: CanFrame,
        **details: object,
    ) -> None:
        try:
            self._control_audit.write(stage, command, frame=frame, details=details)
        except ControlAuditError as exc:
            self.error_raised.emit(str(exc))

    def _record_control_rejection(self, command: ControlCommand, error: Exception) -> None:
        details = self._control_details(command, error=repr(error))
        try:
            self._control_audit.write("rejected", command, details=details)
        except ControlAuditError as audit_error:
            self.error_raised.emit(str(audit_error))
        self._enqueue_event(
            CanEvent(
                event_type=CanEventType.CONTROL_REJECTED,
                message=f"BMS control command rejected: {error}",
                details=details,
            )
        )

    @staticmethod
    def _control_details(
        command: ControlCommand,
        *,
        frame: CanFrame | None = None,
        **extra: object,
    ) -> dict[str, object]:
        details: dict[str, object] = {
            "device_address": command.device_address,
            "mask": int(command.mask),
            "charge_on": command.charge_on,
            "discharge_on": command.discharge_on,
            "balance_on": command.balance_on,
            "selected_changes": command.selected_changes,
        }
        if frame is not None:
            details.update(
                can_id=frame.can_id,
                data=frame.data.hex(" ").upper(),
                channel=frame.channel,
            )
        details.update(extra)
        return details

    def set_waveform_signals(self, names: list[str] | tuple[str, ...]) -> None:
        self.pipeline.ring_buffer.select(names, retain_existing=True)

    def reset_data(self) -> None:
        self._clear_queue(self.frame_queue)
        self._clear_queue(self._event_queue)
        previous_addresses = self.pipeline.detected_addresses
        self.pipeline.reset()
        self._frames_processed = 0
        self._decoded_frames = 0
        self._rate_frames = 0
        self._last_rate = 0.0
        self._rate_started = monotonic()
        for address in previous_addresses:
            self.bms_snapshot_updated.emit(
                address, BmsSnapshot(timestamp=0.0)
            )
        self._reported_addresses = ()
        self.detected_addresses_changed.emit(())
        self.snapshot_updated.emit(BmsSnapshot(timestamp=0.0))
        self.emit_stats()

    @staticmethod
    def _clear_queue(queue: Queue[object]) -> None:
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return

    def drain_once(self, *, frame_limit: int = 2_000, time_budget_ms: float = 8.0) -> int:
        events: list[CanEvent] = []
        for _ in range(200):
            try:
                event = self._event_queue.get_nowait()
            except Empty:
                break
            events.append(event)
            try:
                self.pipeline.process_event(event)
            except RecorderError as exc:
                self._handle_recorder_error(exc)
            if event.event_type in {
                CanEventType.REPLAY_FINISHED,
                CanEventType.REPLAY_STOPPED,
                CanEventType.REPLAY_ERROR,
            }:
                with self._source_lock:
                    self._replay_worker = None
                self._replay_database_path = None
                self._set_source_state(SourceState())
        if events:
            self.events_received.emit(events)

        started = monotonic()
        processed: list[tuple[CanFrame, str, int | None]] = []
        changed_addresses: set[int] = set()
        while len(processed) < frame_limit:
            if (monotonic() - started) * 1000.0 >= time_budget_ms:
                break
            try:
                frame = self.frame_queue.get_nowait()
            except Empty:
                break
            try:
                message = self.pipeline.process_frame(frame)
            except RecorderError as exc:
                self._handle_recorder_error(exc)
                message = None
            except Exception as exc:
                self.error_raised.emit(f"处理 CAN 帧失败：{exc}")
                message = None
            processed.append(
                (
                    frame,
                    "" if message is None else message.name,
                    None if message is None else message.device_address,
                )
            )
            if message is not None:
                self._decoded_frames += 1
                changed_addresses.add(message.device_address)

        count = len(processed)
        if count:
            self._frames_processed += count
            self._rate_frames += count
            self.frames_processed.emit(processed)
        for address in sorted(changed_addresses):
            snapshot = self.pipeline.snapshot(address)
            self.bms_snapshot_updated.emit(address, snapshot)
            if address == self.pipeline.device_address:
                self.snapshot_updated.emit(snapshot)
        detected_addresses = self.pipeline.detected_addresses
        if detected_addresses != self._reported_addresses:
            self._reported_addresses = detected_addresses
            self.detected_addresses_changed.emit(detected_addresses)
        return count

    def _handle_recorder_error(self, exc: RecorderError) -> None:
        recorder = self._recorder
        self.pipeline.recorder = None
        self._recorder = None
        self._recording_state = RecordingState()
        self.recording_changed.emit(self._recording_state)
        self.error_raised.emit(f"数据记录已停止：{exc}")
        if recorder is not None:
            Thread(
                target=self._stop_failed_recorder,
                args=(recorder,),
                name="gui-stop-failed-recorder",
                daemon=True,
            ).start()

    def _stop_failed_recorder(self, recorder: SessionRecorder) -> None:
        try:
            recorder.stop()
        except RecorderError:
            pass

    def emit_stats(self) -> GuiStats:
        now = monotonic()
        elapsed = now - self._rate_started
        if elapsed >= 0.25:
            self._last_rate = self._rate_frames / elapsed
            self._rate_frames = 0
            self._rate_started = now

        dropped = 0
        with self._source_lock:
            if self._receive_worker is not None:
                dropped += self._receive_worker.stats.frames_dropped
            if self._replay_worker is not None:
                dropped += self._replay_worker.stats.dropped
        recorder_depth = 0
        if self._recorder is not None:
            recorder_depth = self._recorder.stats.queued_items
        stats = GuiStats(
            frames_processed=self._frames_processed,
            decoded_frames=self._decoded_frames,
            decode_errors=self.pipeline.decode_errors,
            queue_depth=self.frame_queue.qsize(),
            source_dropped_frames=dropped,
            frames_per_second=self._last_rate,
            recorder_queue_depth=recorder_depth,
        )
        self.stats_updated.emit(stats)
        return stats

    def inject_frames(self, frames: list[CanFrame] | tuple[CanFrame, ...]) -> int:
        """Feed deterministic demo/test frames through the same bounded queue."""

        accepted = 0
        for frame in frames:
            try:
                self.frame_queue.put_nowait(frame)
            except Full:
                break
            accepted += 1
        return accepted

    def shutdown(self) -> None:
        self._shutdown_requested = True
        self._drain_timer.stop()
        self._stats_timer.stop()
        self._demo_timer.stop()
        self._control_gate.revoke_all()
        if self._control_thread is not None:
            self._control_thread.join(2.0)
        self._stop_source_blocking()
        try:
            self.stop_recording()
        except RecorderError as exc:
            self.error_raised.emit(f"停止记录失败：{exc}")
