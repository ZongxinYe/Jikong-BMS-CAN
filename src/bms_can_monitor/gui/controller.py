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
    CanEvent,
    CanEventType,
    CanReceiveWorker,
    Canalyst2Adapter,
    ReplayWorker,
    load_replay_csv,
)
from bms_can_monitor.data import (
    DataPipeline,
    RecorderError,
    SessionMetadata,
    SessionRecorder,
    SignalRingBuffer,
)
from bms_can_monitor.protocol import BmsSnapshot, CanFrame

from .demo import build_demo_frames


DEFAULT_WAVEFORM_SIGNALS = (
    "BattVolt",
    "BattCurr",
    "SOC",
    "MaxCellVolt",
    "MinCellVolt",
    "MaxCellTemp",
    "MinCellTemp",
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


class GuiController(QObject):
    """Keep worker threads and blocking SDK calls outside the Qt paint path."""

    frames_processed = Signal(object)
    snapshot_updated = Signal(object)
    events_received = Signal(object)
    source_changed = Signal(object)
    recording_changed = Signal(object)
    stats_updated = Signal(object)
    error_raised = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        frame_queue_size: int = 50_000,
        start_timers: bool = True,
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
        self._source_thread: Thread | None = None
        self._current_config = BusConfig()
        self._recorder: SessionRecorder | None = None
        self._shutdown_requested = False
        self._demo_step = 0

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

    def _set_source_state(self, state: SourceState) -> None:
        with self._source_lock:
            self._source_state = state
        self.source_changed.emit(state)

    def _enqueue_event(self, event: CanEvent) -> None:
        self._event_queue.put(event)

    def connect_live(self, config: BusConfig) -> None:
        if self.source_state.mode != "idle":
            raise RuntimeError("请先停止当前数据源")
        self._current_config = config
        self.pipeline.device_address = config.device_address
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

    def start_replay(self, path: str | Path, *, speed: float = 1.0, loop: bool = False) -> None:
        if self.source_state.mode != "idle":
            raise RuntimeError("请先停止当前数据源")
        replay_path = Path(path)
        self._set_source_state(
            SourceState("replay", "正在加载回放文件", busy=True, detail=str(replay_path))
        )
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
            if self._shutdown_requested:
                return
            worker = ReplayWorker(
                frames,
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
                    detail=f"{path.name} / {len(frames)} 帧 / {speed:g}x",
                )
            )
        except Exception as exc:
            with self._source_lock:
                self._replay_worker = None
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
            recorder.stop()
        finally:
            self._recording_state = RecordingState()
            self.recording_changed.emit(self._recording_state)

    def set_waveform_signals(self, names: list[str] | tuple[str, ...]) -> None:
        self.pipeline.ring_buffer.select(names, retain_existing=True)

    def reset_data(self) -> None:
        self._clear_queue(self.frame_queue)
        self._clear_queue(self._event_queue)
        self.pipeline.state_store.reset()
        self.pipeline.decoder.cell_voltages.reset()
        self.pipeline.ring_buffer.clear()
        self.pipeline.decode_errors = 0
        self._frames_processed = 0
        self._decoded_frames = 0
        self._rate_frames = 0
        self._last_rate = 0.0
        self._rate_started = monotonic()
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
                self._set_source_state(SourceState())
        if events:
            self.events_received.emit(events)

        started = monotonic()
        processed: list[tuple[CanFrame, str]] = []
        decoded_any = False
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
            processed.append((frame, "" if message is None else message.name))
            if message is not None:
                self._decoded_frames += 1
                decoded_any = True

        count = len(processed)
        if count:
            self._frames_processed += count
            self._rate_frames += count
            self.frames_processed.emit(processed)
        if decoded_any:
            self.snapshot_updated.emit(self.pipeline.state_store.snapshot())
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
        self._stop_source_blocking()
        try:
            self.stop_recording()
        except RecorderError as exc:
            self.error_raised.emit(f"停止记录失败：{exc}")
