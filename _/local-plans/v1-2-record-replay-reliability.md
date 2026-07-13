# v1.2：记录完整性与回放末端保持

## 背景与目的

v1.1 实机放电记录暴露了两个现象：欠压报警出现后，用户无法从界面确认记录是否仍在继续；SQLite 回放到达末端后，波形地址和曲线立即被清空。

对 `E:\BatteryTest\bms_record20260713discharge.sqlite3` 及其 WAL/SHM 文件的只读分析已经确认：

- 数据库 `quick_check` 为 `ok`，会话包含 `387,170` 帧。
- 单体欠压报警在 `2026-07-13 16:05:31` 出现，之后仍连续记录 `91,021` 帧，持续约 42 分 56 秒，最大帧间隔仅 `0.110 s`。
- 当前程序可重新解码全部 `387,170` 帧，解码错误、未知帧和地址冲突均为 0。
- 最后 `1,622` 帧和 `sessions.ended_at` 仍依赖 WAL；仅打开主数据库的 immutable 视图时看不到这部分收尾数据。
- 回放完成事件与帧使用两个队列，GUI 控制器先处理完成事件并进入 idle；主窗口进入 idle 后调用 `set_available_addresses(())`，因此曲线身份被清空。

v1.2 的目标是：

1. 回放自然结束、用户停止回放或回放报错时，保留已经解码的末端快照、BMS 地址、波形选择和最后曲线。
2. 保证回放终态在最后一批帧消费完成后发布，避免完成事件越过尚未处理的帧。
3. 记录正常停止时显式完成 WAL checkpoint，使单独的主 SQLite 文件包含完整帧和会话结束状态。
4. 在界面和独立 JSONL 日志中保留记录开始、正常停止、异常停止、帧数及数据库收尾结果，避免异常原因消失后只能凭现象判断。
5. 对未正常结束或仍依赖 WAL 的会话给出明确提示，并用本次真实数据库完成只读回归验收。

本版本不修改极空 CAN 协议、DBC、BMS 地址解析、报警位定义或 SQLite schema v2，不实现 Ah 积分、容量估算、回放进度拖动和报警自动清除策略。

## 现状整理

### 回放生命周期

- `ReplayWorker` 将帧写入 `frame_queue`，将 `REPLAY_FINISHED`、`REPLAY_STOPPED`、`REPLAY_ERROR` 写入独立的事件队列。
- `GuiController.drain_once()` 当前先消费事件队列，再消费帧队列；遇到回放终态事件会立即清空 `_replay_worker` 和 `_replay_database_path`，并发布 idle `SourceState`。
- `MainWindow._apply_source_state()` 把 idle 同时解释为“数据源可重新选择”和“应删除波形地址”，导致正常回放结束时最后曲线消失。
- `GuiController.reset_data()` 已经能够清空管线、快照、地址和波形，并在实时连接、回放、演示开始以及用户点击“清空”时调用。因此，数据清空不需要继续绑定在 idle 状态上。

### SQLite 记录生命周期

- `DataPipeline.process_frame()` 在地址解析和 DBC 解码之前调用 `recorder.record_frame()`；报警帧或解码失败不会主动停止原始帧记录。
- `SessionRecorder` 使用 WAL、`synchronous=NORMAL`、后台队列和定时批量提交。`stop()` 会排空队列、写入 `sessions.ended_at`，但没有显式检查 `wal_checkpoint` 结果。
- `RecordingState` 当前只有 active、路径和 session ID。正常停止和异常停止都立即变成空状态，状态栏恢复为“未记录”，数据库路径、停止原因和最终写入统计随之丢失。
- 写入错误只通过临时错误对话框显示；如果用户没有记录提示文字，后续无法从独立日志追溯。
- `RecordingReader` 能安全读取同目录下的 WAL，但没有向 GUI 明确标识 `ended_at IS NULL` 的未收尾会话。

### 自动测试缺口

- 现有测试验证 SQLite 回放能重建多 BMS 快照，但没有强制让终态事件先于多批帧被 GUI 消费，也没有断言回放结束后的曲线仍存在。
- 现有记录器测试验证行数和 schema，但没有使用 immutable 主文件确认 checkpoint 后 WAL 已不再是完整读取的必要条件。
- 没有覆盖记录器异常停止原因、独立诊断日志和状态栏终态文案。

## 设计

### 回放终态屏障

在 `GuiController` 中增加一个待处理的回放终态事件。收到 `REPLAY_FINISHED`、`REPLAY_STOPPED` 或 `REPLAY_ERROR` 时，不立即发布 idle，而是先保存终态事件并继续消费 `frame_queue`。只有确认终态事件已经到达且队列中不再有该回放产生的帧后，才执行以下动作：

1. 将终态事件交给数据管线和运行事件表。
2. 清理回放 worker 与数据库路径引用。
3. 发布可重新选择数据源的 idle 状态。
4. 保留 `DataPipeline`、`SignalRingBuffer`、已检测地址和 GUI 选择。

回放 worker 只有在最后一帧成功入队后才发送终态事件，因此“终态事件已到达且帧队列为空”可以作为本轮回放结束屏障。开始新数据源之前仍调用 `reset_data()`，不会把上一轮数据混入下一轮。

### 波形保留规则

从 `MainWindow._apply_source_state()` 移除 idle 时的隐式地址清空。统一采用以下规则：

- 回放自然结束：保留最后快照、地址、曲线和用户勾选项。
- 用户停止回放、实时 CAN 或演示源：保留停止时的最后画面，便于现场读数。
- 回放错误：保留错误发生前已成功处理的数据，同时显示错误原因。
- 用户点击“清空”：调用 `reset_data()`，清除快照、地址和波形。
- 启动任意新数据源：先调用 `reset_data()`，再接收新数据。

不把“数据源是否运行”和“当前数据是否应该显示”绑定为同一个状态。

### 记录停止结果与 WAL 收尾

为 `SessionRecorder.stop()` 定义可验证的停止结果，至少包含：会话 ID、结束时间、已写帧数、已写事件数、丢弃数、checkpoint 是否完成以及 checkpoint 返回值。

停止顺序固定为：

1. 断开 `DataPipeline.recorder`，阻止新帧进入该会话。
2. 将 `_StopItem` 放入后台队列并等待此前帧全部提交。
3. 更新 `sessions.ended_at` 和检测到的 BMS 地址并提交。
4. 执行 `PRAGMA wal_checkpoint(TRUNCATE)`，检查 busy、log 和 checkpointed 页数。
5. 返回停止结果；若 checkpoint 因读锁未完成，数据仍保留在 WAL，但界面和日志必须显示“数据库仍依赖 WAL”，不得误报为完整单文件。

schema 继续保持 v2，原始帧表和回放重解码策略不变。

### 记录可观测性

扩展 GUI 记录状态，使停止后仍保留最后一次会话的路径、session ID、停止类型、消息、帧统计和 checkpoint 状态。停止类型至少区分：

- `user`：用户主动停止。
- `shutdown`：应用正常关闭时停止。
- `error`：队列满、SQLite 写入失败或停止超时。

状态栏显示规则：

- 记录中：`记录 #N`，可附加队列深度。
- 正常停止：`已保存 #N`，工具提示显示路径、帧数和 WAL 收尾结果。
- 异常停止：`记录异常停止 #N`，保留原因和数据库路径，记录按钮取消勾选。
- 尚未开始过记录：`未记录`。

新增 append-only `recording-audit.jsonl`，复用现有控制审计日志的线程锁、UTF-8 JSONL、flush 和 fsync 模式。每条记录包含时间、stage、数据库路径、session ID、停止原因、记录器统计、checkpoint 结果和错误文本。该日志位于用户数据目录的 `logs` 下，不写入安装目录；日志自身写入失败不得中断 CAN 监测或损坏 SQLite 会话。

### 未收尾会话提示

`SessionSummary` 增加只读派生属性标识会话是否正常结束。GUI 打开 `ended_at IS NULL` 的会话时显示确认提示：该数据库可能仍在记录、程序曾异常退出，或复制时遗漏了 `-wal`/`-shm` 文件；允许用户继续只读回放当前可见帧，但不得把它显示为完整记录。

正常停止并成功 checkpoint 的新记录，应能只复制主 `.sqlite3` 文件并完整回放。异常退出的恢复场景仍要求主文件、WAL 和 SHM 保持同名且位于同一目录。

### 文件结构

```text
E:\BatteryTest\bms_can_monitor\
├── src\bms_can_monitor\
│   ├── config\
│   │   ├── __init__.py                     # 导出默认记录审计路径
│   │   └── app_paths.py                    # recording-audit.jsonl 用户路径
│   ├── data\
│   │   ├── __init__.py                     # 导出停止结果和记录审计类型
│   │   ├── recorder.py                     # 停止结果、队列排空和 WAL checkpoint
│   │   ├── recording_audit.py              # 新增 append-only 记录诊断日志
│   │   └── recording_reader.py             # 未收尾会话派生状态
│   └── gui\
│       ├── controller.py                   # 回放终态屏障、记录停止原因和审计接入
│       └── main_window.py                  # 保留末端波形、状态栏和未收尾提示
├── tests\
│   ├── test_gui_controller.py              # 多批回放终态顺序和记录状态
│   ├── test_gui_window.py                  # 回放结束后曲线/末值保持
│   ├── test_recorder_schema.py             # clean stop checkpoint 与 immutable 主库
│   ├── test_recording_audit.py             # 新增 JSONL 诊断日志测试
│   ├── test_recording_reader.py            # 未收尾会话识别
│   └── test_release_verifier.py            # v1.2 发布资源检查
├── docs\
│   ├── v1.2-record-replay-reliability.md   # 新增 v1.2 行为与现场验收说明
│   ├── phase6-windows-release.md            # 更新记录收尾和回放末端验收
│   └── phase7-multi-bms-raw-replay.md       # 更新停止/清空和 WAL 规则
├── packaging\version_info.txt              # Windows 文件版本 1.2.0
├── tools\
│   ├── build_windows_release.ps1            # 打包 v1.2 文档
│   ├── verify_windows_release.py            # 校验 v1.2 文档和版本资源
│   └── write_release_manifest.py            # 发布清单版本 1.2.0
├── src\bms_can_monitor\__init__.py         # __version__ = 1.2.0
├── pyproject.toml                           # 项目版本 1.2.0
└── README.md                                # v1.2 记录与回放行为说明
```

## 实现步骤

### Phase 0：版本基线与回归样本

1. 继续使用当前 `feature/multi-bms-v1` 分支，以已推送的 v1.1 提交 `1bc9f77` 作为 v1.2 开发基线；不再创建新分支。
2. 运行当前完整测试，记录测试数量和结果，确认 v1.1 基线可复现。
3. 将本次真实数据库三件套登记为本机只读验收样本，确认它们继续被 `.gitignore` 排除，不复制到 `tests`、`records` 或发布包。
4. 先补充能够稳定重现“终态事件先到、帧需多次 drain 才处理完、波形地址被清空”的失败测试。

完成条件：当前分支基线为 `1bc9f77`；基线测试通过；新增回归测试在未修复代码上准确失败，且不会修改真实数据库。

Phase 0 执行记录（2026-07-13）：

- 按用户决定继续使用 `feature/multi-bms-v1`，最终发布提交再创建 `v1.2` 标签。
- v1.1 基线完整测试为 `166 passed in 8.05s`。
- 主数据库 SHA-256：`AEA05AB8150DF6165EB127AE3D809601C4C5236BAF0126B9541D0117D0293EF0`。
- WAL SHA-256：`A92AAD8E91E756DFC2679A10C143D0FE033BFEDCD19004A893CE2DF73B70A61C`。
- SHM SHA-256：`5B144B0D26B930605763B4584DD25D1F3871FA5841151BA79B4AD8EC0527DA38`。
- 新增控制器回归测试准确失败于：终态事件到达后，队列仍剩 1 帧但 `source_state.mode` 已由 `replay` 变成 `idle`。
- 新增窗口回归测试准确失败于：回放完成后 `selected_addresses` 从 `(0,)` 变成 `()`。
- 三个真实数据库文件位于 Git 仓库外部，仅作为本机只读验收样本，不纳入版本控制。

### Phase 1：回放终态顺序与末端波形保持

1. 在 `GuiController` 中加入 pending replay terminal event，分离“收到终态事件”和“完成 GUI 帧消费”。
2. 修改 `drain_once()`：先保存回放终态，再按帧数和时间预算消费队列；仅在帧队列排空后发布终态事件和 idle 状态。
3. 覆盖完成、用户停止、错误和空回放四种终态，避免 worker 引用、数据库路径或控制授权残留。
4. 从 `_apply_source_state()` 移除 idle 隐式调用 `set_available_addresses(())`；保留 `reset_data()` 作为唯一数据清空入口。
5. 增加 GUI/controller 测试，确认回放结束后 BMS 地址、最后快照、曲线对象、选中状态和最后 y 值仍存在；开始下一数据源或点击清空后才消失。

完成条件：使用大于单次 `frame_limit` 的回放时，idle 不会早于最后一帧；自然结束和手动停止均保留末端曲线；新回放不会混入旧曲线。

### Phase 2：SQLite 正常停止与 WAL checkpoint

1. 为记录器增加结构化停止结果，不改变 schema v2 和 `raw_only` 存储格式。
2. 在后台队列排空、会话结束元数据提交后执行 `wal_checkpoint(TRUNCATE)`，检查 SQLite 返回值并区分成功、busy 和异常。
3. 保证 checkpoint 失败不会删除或破坏 WAL；停止结果明确提示主文件是否可以独立携带。
4. 增加测试：正常停止后，用 `mode=ro&immutable=1` 仅打开主数据库，必须看到全部原始帧和非空 `ended_at`；WAL 应不存在或不再包含必要数据。
5. 增加 checkpoint busy/异常模拟测试，确认已提交数据仍可由主库加 WAL 读取，并返回可诊断结果。

完成条件：正常停止后的单个 `.sqlite3` 文件可以完整列出会话并回放；异常收尾不会误报成功，也不会擅自删除恢复所需 sidecar。

### Phase 3：记录状态、审计日志与未收尾提示

1. 新增 `RecordingAuditLog` 和默认日志路径，写入 started、stopped、shutdown、failed 等阶段。
2. 扩展 `RecordingState`，在停止后保留最后路径、session ID、停止原因、统计和 checkpoint 状态。
3. 统一用户停止、应用关闭、队列满和 SQLite writer error 的状态转移；异常停止继续弹出错误，同时在状态栏和日志中保留原因。
4. 为 `SessionSummary` 增加 finalized 派生状态；打开 `ended_at IS NULL` 的会话时显示遗漏 WAL/异常退出风险提示。
5. 增加记录审计、异常停止、状态栏和未收尾确认的自动测试。

完成条件：用户能够从状态栏工具提示和 `recording-audit.jsonl` 判断记录何时、为何停止以及写入多少帧；未收尾会话不会被当成完整文件静默回放。

### Phase 4：真实数据库回归与文档

1. 使用提供的数据库三件套进行只读回放，确认总帧数为 `387,170`，欠压后的 `91,021` 帧可达，最后快照包含 `BattVolt=40.9 V` 和 `CellVoltSum=40.962 V`。
2. 高速回放到末端后保持 BMS 0、最后快照和波形；确认 idle 状态下可以立即开始另一轮回放。
3. 新建一个小型记录，会话正常停止后只保留主数据库副本，验证仍可完整回放。
4. 更新 README、v1.2 专项文档、Windows 发布指南和多 BMS 原始帧回放文档。
5. 更新“停止数据源会清空波形”的旧说明，改为“停止保留，清空或新数据源重置”。

完成条件：真实样本和新建样本均满足预期；文档与程序行为一致；真实数据库及 sidecar 的时间戳、大小和哈希在验证前后不变。

### Phase 5：版本、完整回归与 Windows 发布

1. 将 Python 包、项目元数据、Windows 文件资源和 release manifest 统一更新为 `1.2.0`。
2. 运行定向测试和完整 pytest；检查项目根目录不生成 `.pytest_cache`。
3. 构建 PyInstaller x64 发布目录和 ZIP，执行资源校验及隔离 GUI smoke test。
4. 在 CANalyst-II 实机上执行欠压后继续记录、正常停止、单文件回放和回放末端保持验收。
5. 检查 Git diff；每个 Phase 仅在用户明确授权后创建本地提交，并在再次明确授权后推送到 `feature/multi-bms-v1`。全部验收通过后，在最终发布提交上创建 `v1.2` Git 标签；提交、推送分支和推送标签分别取得用户授权。

完成条件：完整测试通过；发布包显示 1.2.0；实机欠压后记录状态仍为 active，停止后单文件可回放，末端波形保持；Git 工作区只包含已审阅的 v1.2 改动；最终发布提交标记为 `v1.2`。

Phase 1–5 自动执行记录（2026-07-13）：

- Phase 1：回放终态等待帧队列排空，回放结束和停止数据源不再隐式清空波形；原有两条红灯回归测试已转绿。
- Phase 2：`SessionRecorder.stop()` 返回结构化停止结果，并在提交 `ended_at` 后执行 `wal_checkpoint(TRUNCATE)`；immutable 主库测试可独立读取全部帧。
- Phase 3：新增 `recording-audit.jsonl`、记录终态、异常停止原因和未收尾会话提示；审计日志不可写不会中断 SQLite。
- Phase 4：使用真实数据库三件套的临时副本完成 `387,170` 帧 GUI 回放，结束后保持 BMS 0、`40.9 V` 最终曲线、`40.962 V` 单体合计和 20 节单体；原始三件套 SHA-256 前后不变。
- Phase 5：项目、Python 包、Windows EXE 和 release manifest 统一为 `1.2.0`；完整自动测试 `176 passed`；x64 资源校验和隔离 GUI smoke test 通过。
- 发布 ZIP：`E:\BatteryTest\bms_can_monitor\dist\BMS-CAN-Monitor-windows-x64.zip`，SHA-256 为 `800C9D063A1C06955906C6C742103B00343123787DD82311B72DD194036F7E54`。
- 现场复测：用户于 2026-07-13 明确决定本次不再复测，以已有真实记录回放验证和自动化测试结果作为发布依据。
- 版本操作：用户已授权创建最终提交、推送 `feature/multi-bms-v1` 分支，并创建和推送 `v1.2` Git 标签。

## 并行执行策略

- Phase 1 的回放终态修复与 Phase 2 的记录器 checkpoint 可在完成 Phase 0 后并行开发，因为主要修改文件分别位于 GUI 控制器和记录器核心。
- Phase 3 需要同时消费 Phase 1 的状态规则和 Phase 2 的停止结果，因此必须在两者稳定后集成。
- 文档草稿可以与 Phase 3 并行，但真实数据库回归、版本更新和发布包必须使用最终代码顺序执行。
- `controller.py`、`main_window.py` 和版本文件存在交叉修改时应串行合并，避免覆盖用户或其他阶段的工作。

## 验证方法

### 自动测试

```powershell
python -m pytest -p no:cacheprovider --basetemp=pytest-tmp-v12 tests\test_gui_controller.py tests\test_gui_window.py tests\test_replay_worker.py
python -m pytest -p no:cacheprovider --basetemp=pytest-tmp-v12 tests\test_recorder_schema.py tests\test_recording_reader.py tests\test_recording_audit.py
python -m pytest -p no:cacheprovider --basetemp=pytest-tmp-v12
```

关键断言：

- 终态事件已经到达但帧队列尚未排空时，`source_state.mode` 仍为 `replay`。
- 最后一帧处理完成后，`source_state.mode` 变为 `idle`，但 `detected_addresses`、ring buffer 和 GUI 曲线仍存在。
- 用户点击清空或开始新数据源后，旧地址、快照和曲线全部重置。
- 正常停止记录后，immutable 主库行数等于记录器统计，`ended_at` 非空。
- 强制 writer error 后，记录按钮取消勾选，状态为异常停止，路径和错误文本仍可查看，JSONL 存在 failed 条目。
- 打开 `ended_at IS NULL` 的会话时出现风险确认；正常 finalized 会话不出现误报。

### 真实数据库只读验收

验证前后记录以下三件套的文件大小、修改时间和 SHA-256，确保分析过程没有写入：

```text
E:\BatteryTest\bms_record20260713discharge.sqlite3
E:\BatteryTest\bms_record20260713discharge.sqlite3-wal
E:\BatteryTest\bms_record20260713discharge.sqlite3-shm
```

验收点：

- 会话 1 显示 `387,170` 帧，回放可到 `2026-07-13 16:48:27`。
- 欠压报警后数据仍连续，最终总压为 `40.9 V`、单体合计为 `40.962 V`、单体数量为 20。
- 回放自然结束后波形不清空，最后读数保持；点击“清空”后才清除。

### Windows 发布验证

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_release.ps1
python -B tools\verify_windows_release.py dist\BMS-CAN-Monitor --launch
```

确认发布目录包含 v1.2 文档、x64 EXE、x64 ControlCAN.dll 和 DBC；ZIP 生成 SHA-256。目标电脑使用真实 ControlCAN 驱动完成以下手工流程：

1. 连接 CANalyst-II 并开始 SQLite 记录。
2. 放电至单体欠压保护，保持 CAN 通信至少 5 分钟，确认帧数和记录统计继续增长。
3. 正常停止记录，确认状态栏显示已保存和帧数。
4. 仅使用主 `.sqlite3` 文件回放，确认欠压后数据存在。
5. 回放到末端，确认波形和最后读数停留；再点击清空确认可以主动重置。

## 风险与回退

- 回放终态延迟到队列排空后，超高速大文件回放可能在 worker 已结束后短暂保持“回放中”。状态栏可显示“正在处理末端缓存”，避免被误认为卡死。
- `wal_checkpoint(TRUNCATE)` 可能因外部 SQLite 读连接返回 busy。此时必须保留 WAL 并提示用户关闭占用程序后再处理，不进行强制删除。
- 独立记录审计日志是诊断辅助，不作为原始 CAN 帧完整性的唯一依据；SQLite 会话和记录器统计仍是主证据。
- 若 v1.2 引入回归，可分别回退 Phase 1 GUI 生命周期提交或 Phase 2/3 记录可靠性提交，不需要回退协议和 v1.1 多 BMS 功能。

## 未来扩展

- 回放暂停、继续、进度条、拖动定位和末端重新播放。
- 应用异常退出后的 WAL 恢复/封装工具。
- 报警出现、恢复和去抖动的独立状态机及事件持久化。
- 本次充入/放出 Ah 统计和容量边界识别；继续保持在 v1.2 范围之外。
