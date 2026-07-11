"""Main operational window for live BMS CAN monitoring."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QTabWidget,
    QTableView,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bms_can_monitor.canio import CONTROL_CONFIRMATION_PHRASE, BusConfig
from bms_can_monitor.config import records_directory, user_data_directory
from bms_can_monitor.protocol import BmsSnapshot, ControlCommand

from .bms_dashboard import BmsDashboard
from .control_panel import ControlPanel
from .controller import (
    ControlSendResult,
    DbcMismatchError,
    GuiController,
    GuiStats,
    RecordingState,
    SourceState,
    SQLITE_REPLAY_SUFFIXES,
)
from .models import (
    EventTableModel,
    FrameFilterProxyModel,
    FrameTableModel,
)
from .widgets import WaveformPanel
from .replay_dialog import ReplaySessionDialog


APP_STYLE = """
QMainWindow, QWidget { background: #f7f8fa; color: #1f2933; }
QToolBar { background: #ffffff; border: 0; border-bottom: 1px solid #d8dde5; spacing: 3px; padding: 4px; }
QToolButton { border: 1px solid transparent; border-radius: 3px; padding: 5px 8px; background: transparent; }
QToolButton:hover { background: #eef2f6; border-color: #d8dde5; }
QToolButton:pressed, QToolButton:checked { background: #dfeaf3; border-color: #9bb8cf; }
QDockWidget { color: #344054; }
QDockWidget::title { background: #eef1f4; border-bottom: 1px solid #d8dde5; padding: 7px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #ffffff; border: 1px solid #c9d0da; border-radius: 3px; padding: 4px; min-height: 22px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #377aa6; }
QPushButton { background: #ffffff; border: 1px solid #b8c0ca; border-radius: 3px; padding: 6px 10px; }
QPushButton:hover { background: #eef2f6; }
QTabWidget::pane { border: 1px solid #d8dde5; background: #ffffff; }
QTabBar::tab { background: #e9edf1; border: 1px solid #d8dde5; padding: 7px 16px; }
QTabBar::tab:selected { background: #ffffff; border-bottom-color: #ffffff; color: #205f85; }
QTableView, QListWidget { background: #ffffff; alternate-background-color: #f6f8fa; border: 1px solid #d8dde5; gridline-color: #e6e9ed; selection-background-color: #d9e8f2; selection-color: #17212b; }
QHeaderView::section { background: #eef1f4; border: 0; border-right: 1px solid #d8dde5; border-bottom: 1px solid #d8dde5; padding: 6px; font-weight: 600; }
QFrame#metricDisplay { background: #ffffff; border: 1px solid #d8dde5; border-radius: 4px; }
QLabel#metricTitle { color: #667085; font-size: 11px; }
QLabel#metricValue { color: #17212b; font-size: 20px; font-weight: 600; }
QLabel#metricDetail { color: #667085; font-size: 10px; }
QLabel#sectionTitle { color: #344054; font-weight: 600; padding: 2px 0; }
QLabel#mutedLabel { color: #667085; }
QLabel#sourceConnected { color: #13705a; font-weight: 600; }
QLabel#sourceIdle { color: #667085; }
QLabel#sourceBusy { color: #8a5a00; font-weight: 600; }
QLabel#controlWarning { color: #8a2f25; background: #fff4e8; border: 1px solid #e7b98a; border-radius: 3px; padding: 9px; }
QStatusBar { background: #ffffff; border-top: 1px solid #d8dde5; }
"""


class MainWindow(QMainWindow):
    def __init__(self, controller: GuiController | None = None) -> None:
        super().__init__()
        self.controller = controller or GuiController(self)
        self.setWindowTitle("BMS CAN Monitor")
        self.resize(1440, 900)
        self.setMinimumSize(1024, 680)
        self.setStyleSheet(APP_STYLE)
        self._user_data_directory = user_data_directory()
        self._last_recording_directory = records_directory()

        self._create_actions()
        self._create_toolbar()
        self._create_connection_dock()
        self._create_central_tabs()
        self._create_status_bar()
        self._connect_signals()
        self._apply_source_state(self.controller.source_state)

        self.waveform_timer = QTimer(self)
        self.waveform_timer.setInterval(100)
        self.waveform_timer.timeout.connect(self.waveform_panel.refresh)
        self.waveform_timer.start()

    def _icon(self, icon: QStyle.StandardPixmap):
        return self.style().standardIcon(icon)

    def _create_actions(self) -> None:
        self.connect_action = QAction(
            self._icon(QStyle.StandardPixmap.SP_DriveNetIcon), "连接", self
        )
        self.connect_action.setToolTip("连接 CANalyst-II")
        self.stop_action = QAction(
            self._icon(QStyle.StandardPixmap.SP_MediaStop), "停止", self
        )
        self.stop_action.setToolTip("停止当前数据源")
        self.replay_action = QAction(
            self._icon(QStyle.StandardPixmap.SP_DialogOpenButton), "回放", self
        )
        self.replay_action.setToolTip("打开 CAN 帧 CSV 回放")
        self.demo_action = QAction(
            self._icon(QStyle.StandardPixmap.SP_MediaPlay), "演示", self
        )
        self.demo_action.setToolTip("运行本地模拟 BMS 数据")
        self.record_action = QAction(
            self._icon(QStyle.StandardPixmap.SP_DialogSaveButton), "记录", self
        )
        self.record_action.setToolTip("开始或停止 SQLite 数据记录")
        self.record_action.setCheckable(True)
        self.control_action = QAction(
            self._icon(QStyle.StandardPixmap.SP_MessageBoxWarning), "控制锁定", self
        )
        self.control_action.setToolTip("启用受保护的 BMS 控制功能")
        self.control_action.setCheckable(True)
        self.clear_action = QAction(
            self._icon(QStyle.StandardPixmap.SP_TrashIcon), "清空", self
        )
        self.clear_action.setToolTip("清空当前显示和波形缓存")

        self.connect_action.triggered.connect(self._connect_live)
        self.stop_action.triggered.connect(self.controller.disconnect_source)
        self.replay_action.triggered.connect(self._open_replay)
        self.demo_action.triggered.connect(self.controller.start_demo)
        self.record_action.triggered.connect(self._toggle_recording)
        self.control_action.triggered.connect(self._toggle_control_workspace)
        self.clear_action.triggered.connect(self._clear_data)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.connect_action)
        toolbar.addAction(self.stop_action)
        toolbar.addSeparator()
        toolbar.addAction(self.replay_action)
        toolbar.addAction(self.demo_action)
        toolbar.addSeparator()
        toolbar.addAction(self.record_action)
        toolbar.addAction(self.control_action)
        toolbar.addAction(self.clear_action)
        self.addToolBar(toolbar)

    def _create_connection_dock(self) -> None:
        dock = QDockWidget("连接与回放", self)
        dock.setObjectName("connectionDock")
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        panel = QWidget()
        root = QVBoxLayout(panel)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.source_label = QLabel("未连接")
        self.source_label.setObjectName("sourceIdle")
        self.source_detail_label = QLabel("")
        self.source_detail_label.setObjectName("mutedLabel")
        self.source_detail_label.setWordWrap(True)
        root.addWidget(self.source_label)
        root.addWidget(self.source_detail_label)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.device_index_spin = QSpinBox()
        self.device_index_spin.setRange(0, 15)
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("CAN1", 0)
        self.channel_combo.addItem("CAN2", 1)
        self.bitrate_combo = QComboBox()
        for bitrate in (50_000, 100_000, 125_000, 250_000, 500_000, 800_000, 1_000_000):
            label = f"{bitrate // 1000} kbps" if bitrate < 1_000_000 else "1 Mbps"
            self.bitrate_combo.addItem(label, bitrate)
        self.bitrate_combo.setCurrentIndex(self.bitrate_combo.findData(250_000))
        self.address_spin = QSpinBox()
        self.address_spin.setRange(0, 11)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("正常模式", 0)
        self.mode_combo.addItem("只听模式", 1)
        self.dll_path_edit = QLineEdit(str(BusConfig().effective_dll_path))
        self.dll_path_edit.setCursorPosition(0)
        self.dll_path_edit.setToolTip(self.dll_path_edit.text())
        dll_row = QWidget()
        dll_layout = QHBoxLayout(dll_row)
        dll_layout.setContentsMargins(0, 0, 0, 0)
        dll_layout.setSpacing(4)
        dll_layout.addWidget(self.dll_path_edit, 1)
        dll_button = QToolButton()
        dll_button.setIcon(self._icon(QStyle.StandardPixmap.SP_DirOpenIcon))
        dll_button.setToolTip("选择 ControlCAN.dll")
        dll_button.clicked.connect(self._browse_dll)
        dll_layout.addWidget(dll_button)
        form.addRow("设备号", self.device_index_spin)
        form.addRow("通道", self.channel_combo)
        form.addRow("波特率", self.bitrate_combo)
        form.addRow("控制地址", self.address_spin)
        form.addRow("工作模式", self.mode_combo)
        form.addRow("驱动库", dll_row)
        root.addLayout(form)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(separator)
        replay_form = QFormLayout()
        self.replay_speed_spin = QDoubleSpinBox()
        self.replay_speed_spin.setRange(0.1, 100.0)
        self.replay_speed_spin.setValue(1.0)
        self.replay_speed_spin.setSuffix(" x")
        self.replay_loop_check = QCheckBox("循环")
        replay_form.addRow("回放速度", self.replay_speed_spin)
        replay_form.addRow("", self.replay_loop_check)
        root.addLayout(replay_form)
        root.addStretch(1)
        dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _create_central_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)
        self._create_dashboard_tab()
        self._create_waveform_tab()
        self._create_frames_tab()
        self._create_events_tab()
        self._create_control_tab()

    def _create_dashboard_tab(self) -> None:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(6, 6, 6, 6)
        self.bms_overview_tabs = QTabWidget()
        self.bms_overview_tabs.setDocumentMode(True)
        self.bms_dashboards: dict[int, BmsDashboard] = {}
        root.addWidget(self.bms_overview_tabs)
        self.tabs.addTab(page, "BMS 总览")
        self._ensure_bms_dashboard(self.controller.pipeline.device_address)

    def _create_waveform_tab(self) -> None:
        self.waveform_panel = WaveformPanel(self.controller.pipeline.ring_buffer)
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.waveform_panel)
        self.tabs.addTab(wrapper, "实时波形")

    def _create_frames_tab(self) -> None:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(10, 10, 10, 10)
        controls = QHBoxLayout()
        self.frame_filter_edit = QLineEdit()
        self.frame_filter_edit.setPlaceholderText("CAN ID / 报文名 / 数据")
        self.frame_pause_check = QCheckBox("暂停显示")
        controls.addWidget(QLabel("筛选"))
        controls.addWidget(self.frame_filter_edit, 1)
        controls.addWidget(self.frame_pause_check)
        root.addLayout(controls)
        self.frame_model = FrameTableModel(self)
        self.frame_proxy = FrameFilterProxyModel(self)
        self.frame_proxy.setSourceModel(self.frame_model)
        self.frame_table = self._table(self.frame_proxy)
        header = self.frame_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.frame_table)
        self.frame_filter_edit.textChanged.connect(self.frame_proxy.set_query)
        self.frame_pause_check.toggled.connect(self._pause_frames)
        self.tabs.addTab(page, "CAN 报文")

    def _create_events_tab(self) -> None:
        self.event_model = EventTableModel(self)
        self.event_table = self._table(self.event_model)
        header = self.event_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.event_table)
        self.tabs.addTab(page, "运行事件")

    def _create_control_tab(self) -> None:
        self.control_panel = ControlPanel()
        self.control_tab_index = self.tabs.addTab(self.control_panel, "BMS 控制")
        self.tabs.setTabEnabled(self.control_tab_index, False)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    @staticmethod
    def _table(model) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(False)
        return table

    def _create_status_bar(self) -> None:
        self.rate_status = QLabel("0 帧/s")
        self.total_status = QLabel("0 帧")
        self.queue_status = QLabel("队列 0")
        self.decode_status = QLabel("解析失败 0")
        self.record_status = QLabel("未记录")
        for widget in (
            self.rate_status,
            self.total_status,
            self.queue_status,
            self.decode_status,
            self.record_status,
        ):
            self.statusBar().addPermanentWidget(widget)

    def _connect_signals(self) -> None:
        self.controller.frames_processed.connect(self._append_frames)
        self.controller.bms_snapshot_updated.connect(self._update_bms_snapshot)
        self.controller.detected_addresses_changed.connect(self._sync_bms_dashboards)
        self.controller.detected_addresses_changed.connect(
            self.waveform_panel.set_available_addresses
        )
        self.controller.snapshot_updated.connect(self._update_snapshot)
        self.controller.events_received.connect(self.event_model.append_batch)
        self.controller.source_changed.connect(self._apply_source_state)
        self.controller.recording_changed.connect(self._apply_recording_state)
        self.controller.stats_updated.connect(self._update_stats)
        self.controller.control_send_finished.connect(self._apply_control_result)
        self.controller.error_raised.connect(self._show_error)
        self.control_panel.send_requested.connect(self._send_control_command)

    def _bus_config(self) -> BusConfig:
        path_text = self.dll_path_edit.text().strip()
        return BusConfig(
            device_index=self.device_index_spin.value(),
            channel=int(self.channel_combo.currentData()),
            bitrate=int(self.bitrate_combo.currentData()),
            device_address=self.address_spin.value(),
            mode=int(self.mode_combo.currentData()),
            dll_path=Path(path_text) if path_text else None,
        )

    def _connect_live(self) -> None:
        try:
            self.controller.connect_live(self._bus_config())
        except Exception as exc:
            self._show_error(str(exc))

    def _open_replay(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 CAN 回放",
            str(
                self._last_recording_directory
                if self._last_recording_directory.exists()
                else self._user_data_directory
            ),
            "记录数据库 (*.sqlite3 *.sqlite *.db);;CAN CSV (*.csv);;所有文件 (*)",
        )
        if not path:
            return
        replay_path = Path(path)
        session_id: int | None = None
        try:
            if replay_path.suffix.lower() in SQLITE_REPLAY_SUFFIXES:
                sessions = self.controller.recording_sessions(replay_path)
                if not sessions:
                    raise RuntimeError("记录数据库中没有可回放会话")
                if len(sessions) > 1:
                    dialog = ReplaySessionDialog(sessions, self)
                    if dialog.exec() != ReplaySessionDialog.DialogCode.Accepted:
                        return
                    session_id = dialog.selected_session_id
                else:
                    session_id = sessions[0].session_id
            self.controller.start_replay(
                replay_path,
                speed=self.replay_speed_spin.value(),
                loop=self.replay_loop_check.isChecked(),
                session_id=session_id,
            )
        except DbcMismatchError:
            answer = QMessageBox.warning(
                self,
                "DBC 定义不一致",
                "记录使用的 DBC 与当前 DBC 不一致。继续时将使用当前 DBC 重新解码。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    self.controller.start_replay(
                        replay_path,
                        speed=self.replay_speed_spin.value(),
                        loop=self.replay_loop_check.isChecked(),
                        session_id=session_id,
                        allow_dbc_mismatch=True,
                    )
                except Exception as exc:
                    self._show_error(str(exc))
        except Exception as exc:
            self._show_error(str(exc))

    def _browse_dll(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 ControlCAN.dll",
            self.dll_path_edit.text(),
            "ControlCAN.dll (ControlCAN.dll);;DLL (*.dll)",
        )
        if path:
            self.dll_path_edit.setText(path)

    def _toggle_recording(self, checked: bool) -> None:
        if not checked:
            try:
                self.controller.stop_recording()
            except Exception as exc:
                self._show_error(str(exc))
            return
        self._last_recording_directory.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "新建记录数据库",
            str(self._last_recording_directory / "bms_record.sqlite3"),
            "SQLite 数据库 (*.sqlite3 *.db)",
        )
        if not path:
            self.record_action.setChecked(False)
            return
        try:
            self.controller.start_recording(path)
            self._last_recording_directory = Path(path).parent
        except Exception as exc:
            self.record_action.setChecked(False)
            self._show_error(str(exc))

    def _clear_data(self) -> None:
        self.frame_model.clear()
        self.event_model.clear()
        self.controller.reset_data()

    def _toggle_control_workspace(self, checked: bool) -> None:
        if not checked:
            self._lock_control_workspace()
            return
        if not self.controller.control_ready:
            self._lock_control_workspace()
            self._show_error("控制条件不满足：需要默认地址、正常模式和近期 BMS 实时报文")
            return
        answer = QMessageBox.warning(
            self,
            "启用 BMS 控制",
            "控制命令会直接改变充电、放电或均衡开关。\n\n"
            "请确认 CAN 通道、BMS 地址、接线和现场安全条件均正确。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._lock_control_workspace()
            return
        self.control_panel.set_unlocked(True)
        self.tabs.setTabEnabled(self.control_tab_index, True)
        self.control_action.setText("控制已启用")
        self.tabs.setCurrentIndex(self.control_tab_index)

    def _lock_control_workspace(self) -> None:
        self.control_panel.set_unlocked(False)
        self.tabs.setTabEnabled(self.control_tab_index, False)
        if self.tabs.currentIndex() == self.control_tab_index:
            self.tabs.setCurrentIndex(0)
        self.control_action.blockSignals(True)
        self.control_action.setChecked(False)
        self.control_action.setText("控制锁定")
        self.control_action.blockSignals(False)

    def _send_control_command(self, command: ControlCommand) -> None:
        answer = QMessageBox.warning(
            self,
            "确认发送 BMS 控制帧",
            self.control_panel.summary_text()
            + "\n\n该操作将立即作用于真实 BMS，是否发送？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.control_panel.status_label.setText("发送已取消")
            return
        try:
            authorization = self.controller.authorize_control(
                command,
                CONTROL_CONFIRMATION_PHRASE,
            )
            self.controller.send_control(command, authorization)
            self.control_panel.set_pending(True)
            self.control_action.setEnabled(False)
        except Exception as exc:
            self.control_panel.set_result(False, f"发送被拒绝：{exc}")
            self._show_error(str(exc))

    def _apply_control_result(self, result: ControlSendResult) -> None:
        self.control_panel.set_result(result.success, result.message)
        self._refresh_control_availability()
        if not result.success:
            self._show_error(result.message)

    def _refresh_control_availability(self) -> None:
        if self.controller.control_send_pending:
            self.control_action.setEnabled(False)
            return
        ready = self.controller.control_ready
        self.control_action.setEnabled(ready)
        if not ready and self.control_action.isChecked():
            self._lock_control_workspace()

    def _pause_frames(self, paused: bool) -> None:
        self.frame_model.paused = paused

    def _append_frames(self, rows: list[tuple]) -> None:
        scrollbar = self.frame_table.verticalScrollBar()
        follow_tail = scrollbar.value() >= scrollbar.maximum() - 2
        self.frame_model.append_batch(rows)
        if follow_tail and not self.frame_model.paused:
            self.frame_table.scrollToBottom()

    def _update_snapshot(self, snapshot: BmsSnapshot) -> None:
        self.control_panel.update_snapshot(snapshot)
        self._refresh_control_availability()

    def _update_bms_snapshot(self, device_address: int, snapshot: BmsSnapshot) -> None:
        self._ensure_bms_dashboard(device_address).update_snapshot(snapshot)

    def _sync_bms_dashboards(self, addresses: tuple[int, ...]) -> None:
        desired = set(addresses)
        if not desired:
            desired.add(self.controller.pipeline.device_address)
        for address in tuple(self.bms_dashboards):
            if address not in desired:
                dashboard = self.bms_dashboards.pop(address)
                index = self.bms_overview_tabs.indexOf(dashboard)
                if index >= 0:
                    self.bms_overview_tabs.removeTab(index)
                dashboard.deleteLater()
        for address in sorted(desired):
            self._ensure_bms_dashboard(address)
        self._refresh_dashboard_aliases()

    def _ensure_bms_dashboard(self, device_address: int) -> BmsDashboard:
        dashboard = self.bms_dashboards.get(device_address)
        if dashboard is not None:
            return dashboard
        dashboard = BmsDashboard(device_address, self)
        insertion_index = sum(
            existing_address < device_address
            for existing_address in self.bms_dashboards
        )
        self.bms_dashboards[device_address] = dashboard
        self.bms_overview_tabs.insertTab(
            insertion_index, dashboard, f"BMS {device_address}"
        )
        self._refresh_dashboard_aliases()
        return dashboard

    def _refresh_dashboard_aliases(self) -> None:
        if not self.bms_dashboards:
            return
        default_address = self.controller.pipeline.device_address
        dashboard = self.bms_dashboards.get(default_address)
        if dashboard is None:
            dashboard = self.bms_dashboards[min(self.bms_dashboards)]
        self.signal_model = dashboard.signal_model
        self.signal_table = dashboard.signal_table
        self.cell_model = dashboard.cell_model
        self.cell_table = dashboard.cell_table
        self.issue_list = dashboard.issue_list
        self.voltage_metric = dashboard.voltage_metric
        self.current_metric = dashboard.current_metric
        self.soc_metric = dashboard.soc_metric
        self.soh_metric = dashboard.soh_metric
        self.delta_metric = dashboard.delta_metric
        self.temperature_metric = dashboard.temperature_metric

    def _apply_source_state(self, state: SourceState) -> None:
        self.source_label.setText(state.label)
        self.source_detail_label.setText(state.detail)
        self.source_label.setObjectName(
            "sourceBusy" if state.busy else "sourceConnected" if state.active else "sourceIdle"
        )
        self.source_label.style().unpolish(self.source_label)
        self.source_label.style().polish(self.source_label)
        idle = state.mode == "idle"
        if idle:
            self.waveform_panel.set_available_addresses(())
        self.connect_action.setEnabled(idle)
        self.replay_action.setEnabled(idle)
        self.demo_action.setEnabled(idle)
        self.stop_action.setEnabled(state.active)
        for widget in (
            self.device_index_spin,
            self.channel_combo,
            self.bitrate_combo,
            self.address_spin,
            self.mode_combo,
            self.dll_path_edit,
        ):
            widget.setEnabled(idle)
        self.control_panel.set_device_address(self.controller.current_config.device_address)
        self._refresh_control_availability()

    def _apply_recording_state(self, state: RecordingState) -> None:
        self.record_action.blockSignals(True)
        self.record_action.setChecked(state.active)
        self.record_action.blockSignals(False)
        if state.active:
            self.record_status.setText(f"记录 #{state.session_id}")
            self.record_status.setToolTip(str(state.database_path))
        else:
            self.record_status.setText("未记录")
            self.record_status.setToolTip("")

    def _update_stats(self, stats: GuiStats) -> None:
        self.rate_status.setText(f"{stats.frames_per_second:,.0f} 帧/s")
        self.total_status.setText(f"{stats.frames_processed:,} 帧")
        self.queue_status.setText(f"队列 {stats.queue_depth:,}")
        errors = stats.decode_errors + stats.source_dropped_frames
        self.decode_status.setText(f"解析/丢帧 {errors:,}")
        recording = self.controller.recording_state
        if recording.active:
            queue_text = (
                f" / 队列 {stats.recorder_queue_depth:,}"
                if stats.recorder_queue_depth
                else ""
            )
            self.record_status.setText(f"记录 #{recording.session_id}{queue_text}")
        self._refresh_control_availability()

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "BMS CAN Monitor", message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.waveform_timer.stop()
        self.controller.shutdown()
        event.accept()
