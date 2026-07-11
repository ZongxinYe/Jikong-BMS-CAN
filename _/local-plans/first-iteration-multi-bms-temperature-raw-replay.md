# 第一版迭代：温度卡片、多 BMS 监控与原始帧回放

## 背景与目的

当前程序已经能够通过 CANalyst-II 接收极空 BMS CAN V2.1 报文，完成单个 BMS 地址的实时解码、状态展示、波形显示、SQLite 记录和 CSV 回放。真实设备验证表明基础接收与记录链路可用，但当前版本仍存在三项直接影响台架使用的问题：

1. 总览页没有温度摘要卡片，协议中的最高、最低和平均电芯温度不够直观。
2. 单体压差卡片只显示压差，没有同时突出最高、最低单体电压。
3. 解码状态、波形缓存和总览页均绑定单个 BMS 地址；SQLite 同时保存原始帧和逐信号样本，无法经济地连续记录 5 台 BMS。

本迭代的目标是在同一个 CAN 通道上自动识别并同时监控协议允许的地址 `0..11`，重点保证 5 台 BMS 的实时显示、同图对比和连续记录。新记录格式以完整原始 CAN 帧为唯一数据事实，实时显示和离线回放都通过当前 DBC 重新解码，以显著降低数据库体积并保持 DBC 可修改能力。

### 本版交付范围

- 总览页为每个 BMS 提供独立标签页。
- 每个 BMS 总览增加电芯温度卡片。
- 单体压差卡片同时显示压差、最高电压和最低电压；最高值红色、最低值绿色。
- 实时波形可选择多个 BMS，并在同一信号图中叠加同名信号。
- SQLite 新会话只保存 `sessions`、`raw_frames` 和 `events`，不再逐条保存解码信号。
- GUI 可直接打开 SQLite 会话回放，并在回放过程中按 BMS 地址重新解码。
- 保留 CSV 原始帧回放和旧版 SQLite 数据库的读取能力。

### 明确不纳入本版

- 不开放非零 BMS 地址的控制发送；控制功能仍只允许地址 `0`。
- 不在本版同时打开 CANalyst-II 的 CAN1 和 CAN2；多 BMS 指同一已选 CAN 通道上的多地址设备。
- 不实现云端存储、远程监控或数据库压缩归档。
- 不以总览标签页当前选中项自动改变控制目标，避免误操作。

## 现状整理

### 协议与地址

- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\protocol\dbc_loader.py` 已支持将实际 CAN ID 减去一个显式 `device_address` 后按 DBC 解码，地址范围为 `0..11`。
- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\protocol\models.py` 的 `DecodedMessage` 已包含 `device_address`，可以继续作为多 BMS 消息身份字段。
- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\protocol\jk_bms_v2_1.py` 的 `JikongBmsDecoder` 内含有状态的 `CellVoltageAssembler`。不同 BMS 不能共用同一个 decoder，否则单体电压会串台。
- 当前没有根据 CAN ID 自动反推出 BMS 地址的统一解析器。

### 实时状态与波形

- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\data\pipeline.py` 只有一个 decoder、一个 `BmsStateStore` 和一个 `SignalRingBuffer`，并依赖单个 `device_address`。
- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\data\ring_buffer.py` 以信号名字符串作为键，无法区分 `BMS 0 / SOC` 和 `BMS 1 / SOC`。
- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\gui\controller.py` 只发出单个 `BmsSnapshot`，控制安全检查也直接读取唯一状态仓库的时间戳。

### GUI

- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\gui\main_window.py` 只创建一套指标、信号表、单体表和告警列表。
- 顶部现有卡片为总压、电流、SOC、SOH 和单体压差；单体压差只计算并显示一个 mV 值。
- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\gui\widgets.py` 的波形面板按“一个信号一个图”创建单条曲线，最多选择 6 个信号。
- 温度信号已经存在于波形信号列表，但总览页没有温度摘要。

### 记录与回放

- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\data\recorder.py` 的 schema v1 同时保存 `raw_frames` 和 `signal_samples`；每个解码信号单独占一行，是容量增长的主要来源。
- `DataPipeline.process_frame()` 先记录原始帧，解码后又调用 `record_message()` 写入所有信号。
- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\canio\replay_worker.py` 只支持 CSV，并会一次性把全部帧载入内存，不适合多 BMS 长时间记录。
- `E:\BatteryTest\bms_can_monitor\src\bms_can_monitor\data\export_csv.py` 的信号导出依赖 `signal_samples`，改成原始帧存储后必须改为导出时解码。

## 设计

### 文件结构

```text
E:\BatteryTest\bms_can_monitor\
├── src\bms_can_monitor\
│   ├── protocol\
│   │   ├── addressing.py                 # 新增：从上行 CAN ID 识别 BMS 地址
│   │   ├── dbc_loader.py                 # 修改：暴露可用于地址识别的消息定义
│   │   ├── jk_bms_v2_1.py                # 修改：支持每地址独立 decoder 上下文
│   │   └── __init__.py                   # 修改：导出地址解析 API
│   ├── data\
│   │   ├── pipeline.py                   # 重构：多 BMS 上下文、分派和快照集合
│   │   ├── ring_buffer.py                # 重构：以地址和信号名组成序列键
│   │   ├── recorder.py                   # 修改：schema v2、只写原始帧与事件
│   │   ├── recording_reader.py           # 新增：只读会话信息和分块原始帧迭代
│   │   ├── export_csv.py                 # 修改：从原始帧按地址重新解码后导出
│   │   └── __init__.py                   # 修改：导出新数据模型和读取 API
│   ├── canio\
│   │   ├── replay_worker.py              # 重构：支持可重复迭代、分块帧源
│   │   └── __init__.py                   # 修改：导出 SQLite 回放接口
│   └── gui\
│       ├── bms_dashboard.py              # 新增：单个 BMS 的可复用总览组件
│       ├── replay_dialog.py               # 新增：SQLite 多会话选择对话框
│       ├── widgets.py                     # 修改：范围卡片和多 BMS 叠加波形
│       ├── models.py                      # 修改：CAN 报文显示 BMS 地址
│       ├── controller.py                  # 重构：多快照通知、SQLite 回放与控制隔离
│       ├── main_window.py                 # 修改：总览内层标签页和回放文件选择
│       └── demo.py                        # 修改：生成多地址交错演示帧
├── tests\
│   ├── test_bms_addressing.py             # 新增：地址识别、冲突和未知帧测试
│   ├── test_multi_bms_pipeline.py         # 新增：5 台交错解码与状态隔离测试
│   ├── test_recording_reader.py           # 新增：SQLite 分块读取和会话测试
│   ├── test_multi_bms_waveform.py         # 新增：复合序列键和曲线选择测试
│   ├── test_data_pipeline.py              # 修改：原始帧只记录一次且不写信号表
│   ├── test_recorder_schema.py            # 修改：schema v2 和 v1 兼容测试
│   ├── test_export_csv.py                 # 修改：导出时按地址重新解码
│   ├── test_replay_worker.py              # 修改：SQLite 流式回放、循环和停止测试
│   ├── test_gui_controller.py             # 修改：分地址快照和控制地址隔离测试
│   ├── test_gui_models.py                 # 修改：最高/最低颜色和地址列测试
│   └── test_gui_window.py                 # 修改：动态 BMS 标签页和温度卡片测试
├── tools\
│   └── recording_stress_test.py           # 修改：5 台 BMS 原始帧持续写入压力测试
├── docs\
│   ├── phase7-multi-bms-raw-replay.md     # 新增：第一版迭代设计与使用说明
│   └── phase6-field-validation.md         # 修改：补充 5 台真机验收记录项
└── README.md                              # 修改：多 BMS、记录和回放入口
```

### 多 BMS 地址识别

新增 `BmsAddressResolver`，输入 `CanFrame`，输出 `device_address` 和规范化消息定义：

1. 从 DBC 上行消息建立基础 CAN ID、标准/扩展帧标志索引。
2. 排除外设发送给 BMS 的 `CTRL_INFO`，避免把控制帧当作上行状态。
3. 对地址 `0..11` 计算 `normalized_id = frame.can_id - address`，只有规范化 ID 和帧格式都精确匹配时才接受。
4. 若没有匹配，帧仍进入原始记录和 CAN 报文页，但不创建 BMS 状态。
5. 若出现多个候选匹配，视为协议/DBC 地址冲突，增加解析错误并记录结构化事件，不静默选择。

地址解析器必须通过测试证明当前 DBC 的所有上行基础 ID 在 `0..11` 偏移范围内无歧义。

### 多 BMS 数据上下文

将 `DataPipeline` 改造成多地址管线，内部维护：

```text
device_address -> BmsContext
                   ├── JikongBmsDecoder
                   ├── BmsStateStore
                   └── last_seen_timestamp
```

- 每个地址使用独立 decoder，确保 25 串单体电压组帧不会串台。
- 原始帧在地址识别之前由全局 recorder 记录一次。
- 成功识别后，消息进入对应地址的状态仓库和多 BMS 波形缓存。
- `process_frame()` 继续返回带有 `device_address` 的 `DecodedMessage`，未知帧返回 `None`。
- 新增 `snapshot(address)`、`snapshots()`、`detected_addresses`、`last_seen(address)` 和 `reset(address=None)`。
- Controller 每次 drain 汇总本批次发生变化的地址，每个地址最多发出一次快照通知，避免 5 台高频报文造成 Qt 信号风暴。

### 波形序列身份

新增不可变键：

```python
BmsSignalKey(device_address: int, signal_name: str)
```

波形缓存从单纯的 `signal_name` 改为 `BmsSignalKey`。时间窗和每序列最大点数仍沿用现有边界。波形 UI 分成两个选择区：

- BMS 列表：动态显示已发现地址，可多选。
- 信号列表：继续最多选择 6 个信号。

每个信号占一个 plot，同一 plot 中按所选 BMS 地址叠加多条曲线。颜色稳定绑定 BMS 地址，图例显示 `BMS 0`、`BMS 1` 等；不同刷新周期不要求时间戳完全对齐，所有曲线按共同最新时间转换为相对时间。5 台 BMS、6 个信号时最多 30 条曲线。

新发现 BMS 默认加入选择，用户手动更改选择后保持用户选择，不因后续刷新重置。

### 总览页与指标卡片

顶层“BMS 总览”内部增加一个 `QTabWidget`，每个已发现地址对应一个 `BmsDashboard`：

- 标签名采用 `BMS 0`、`BMS 1` 等，按地址升序排列。
- 每个页面拥有独立的信号表、单体电压表、告警/故障列表和指标卡片。
- 标签页显示最近更新时间；超过约定超时后显示“数据陈旧”，但不删除最后值。
- 清空操作同时清空所有地址页面和波形；单独地址清空作为未来扩展。

卡片采用 3 列 2 行布局，保证在 `1024x680` 最小窗口且连接 dock 可见时仍能完整显示：

1. 电池总压
2. 电池电流
3. SOC
4. SOH
5. 单体压差
6. 电芯温度

“单体压差”使用范围卡片：

- 主值：`最高单体电压 - 最低单体电压`，单位 mV。
- 次值：最高单体电压，红色 `#b42318`。
- 次值：最低单体电压，绿色 `#13705a`。
- 优先使用 100 ms `CELL_VOLT` 中的 `MaxCellVolt` 和 `MinCellVolt`；缺失时才从已组装的单体电压集合计算。
- 少于两个有效单体值时显示 `--`，不产生误导性压差。

“电芯温度”使用 `CELL_TEMP` 中的：

- 主值：`AvrgCellTemp`，单位 `°C`。
- 次值：`MaxCellTemp` 及 `MaxCtNO`。
- 次值：`MinCellTemp` 及 `MinCtNO`。
- 传感器缺失或未收到温度帧时显示 `--`。
- 本版不自行推算温度，只显示 BMS 上报值。

### 记录格式 v2

新会话采用 `raw_only` 模式：

- `sessions`：保留设备、通道、波特率、开始/结束时间和备注，并新增：
  - `storage_mode = 'raw_only'`
  - `detected_addresses_json`
  - `dbc_sha256`
- `raw_frames`：完整保存总线收到的所有帧，包括未知帧、通道和硬件时间戳。
- `events`：继续保存连接、错误、队列溢出、回放和控制事件。
- 新建 v2 数据库不再创建 `signal_samples` 表，也不再创建其索引。
- `DataPipeline` 不再调用 `record_message()`；记录吞吐统计只统计 frame、event、drop 和 queue。

兼容原则：

- 不删除或改写用户已有 v1 数据库中的 `signal_samples`。
- v1 数据库可继续列出会话、导出原始帧并从 `raw_frames` 回放。
- 在已有 v1 数据库追加新会话时执行非破坏性 schema 升级，旧信号样本保留，新会话不再写信号样本。
- `PRAGMA user_version` 升级到 2，并为不支持的未来版本明确报错。
- 会话结束时写入实际发现的 BMS 地址集合。

记录时保存 DBC SHA-256。回放发现数据库保存的 hash 与当前 DBC 不一致时，界面提示“将使用当前 DBC 重新解码”，允许用户继续或取消，确保 DBC 可修改与结果可追溯两者兼顾。

### SQLite 直接回放

抽象可重复读取的帧源，`ReplayWorker` 不再强制把所有帧转换为 list：

```text
ReplayFrameSource
├── CsvReplaySource
└── SqliteReplaySource
```

`SqliteReplaySource` 的规则：

- 数据库以只读模式打开。
- 指定一个 session，按 `(timestamp, id)` 分块查询 `raw_frames`。
- 提供帧数和首尾时间，用于 UI 会话信息和回放状态。
- 每次循环重新执行查询，不在内存保留整段记录。
- ReplayWorker 仍按原始帧间隔和速度倍率发送，并将时间重基准到当前回放时间。

GUI 的“回放”文件选择增加 `*.sqlite3` 和 `*.db`：

- 只有一个会话时直接使用。
- 多个会话时弹出会话选择对话框，显示时间、时长、帧数、通道、波特率和已发现地址。
- 回放进入与实时数据完全相同的多 BMS 管线，重新生成各总览页和波形。
- 禁止把正在回放的数据库同时选作记录目标，避免自读自写。
- 保持 CSV 回放兼容。

### CSV 导出兼容

- 原始帧 CSV 导出保持现有列格式，可继续作为通用回放文件。
- 信号导出不再读取 `signal_samples`，而是分块读取 `raw_frames` 并按地址重新解码。
- 命令行增加 `--address`；指定地址时生成该 BMS 的宽表。
- 未指定地址时为每个检测到的 BMS 生成 `session_N_bms_A_signals_wide.csv`，避免不同 BMS 的同名信号覆盖。
- 事件 CSV 保持不变。
- 大数据导出采用流式写入，不在内存构建整个会话。

### 控制安全边界

- `BusConfig.device_address` 在本版继续表示控制目标/兼容默认地址，不再限制监控解码范围；连接面板文字改为“控制地址”。
- 自动识别和显示地址 `0..11`，但 Phase 5 的非零地址控制禁用规则保持不变。
- 控制安全检查必须读取 `pipeline.snapshot(0)` 或地址 `0` 的 `last_seen`，不能读取任意最近 BMS 的时间戳。
- 切换总览标签页不会改变控制地址，也不会解锁控制页面。
- 地址 `0` 不在线而其他 BMS 在线时，控制仍必须拒绝。

## 实现步骤

### Phase 1：多地址识别与数据管线基础

1. 在 `protocol/addressing.py` 实现基于 DBC 上行消息和地址 `0..11` 的无歧义地址解析器，并定义未知、冲突两类结果。
2. 为每个地址创建独立 `BmsContext`，重构 `DataPipeline` 的 frame 分派、状态查询、重置和解析错误统计。
3. 将波形缓存键升级为 `BmsSignalKey`，保留时间窗、乱序拒绝和容量限制。
4. 调整 controller 的 drain 逻辑，按本批次变化地址发出快照更新，并让 CAN 报文行携带识别出的 BMS 地址。
5. 将控制近期状态校验固定到控制目标地址，保持地址 `0` 限制。
6. 增加 5 台 BMS 地址交错、同名信号隔离、单体组帧隔离、未知帧和地址冲突测试。

完成条件：合成地址 `0..4` 的交错帧经过同一 pipeline 后得到 5 份独立快照；任一地址数据不会覆盖其他地址；地址 `0` 离线时控制检查不会被其他地址的最新帧满足。

版本控制检查点：完整运行协议、数据管线和控制测试，创建独立本地提交；得到用户明确确认后推送 `main`。

### Phase 2：原始帧记录格式与 SQLite 流式回放

1. 将 recorder schema 升级到 v2，新数据库只建立 sessions、raw_frames、events 及必要索引。
2. 停止实时管线的逐信号写入，更新统计、队列容量测试和记录错误处理。
3. 实现 v1 到 v2 的非破坏性升级，确保旧表和旧数据保留。
4. 记录 `storage_mode`、DBC SHA-256 和会话实际发现地址。
5. 新增只读、分块的 recording reader 和 `SqliteReplaySource`，重构 ReplayWorker 接受可重复帧源。
6. 在 controller 中加入 SQLite session 回放入口、DBC hash 检查和同库读写保护。
7. 将信号 CSV 导出改为从 raw_frames 按地址重新解码，保留原始帧和事件导出。
8. 更新记录压力工具，模拟 5 台 BMS 的协议报文率，核对帧数、丢弃数、写入速度和文件体积。

完成条件：记录 N 条输入帧时 raw_frames 精确为 N、没有新信号样本；同一 SQLite session 回放后能重建 5 台 BMS 快照；长会话回放内存占用不随总帧数线性增长；旧 v1 数据库可读取且原数据未改变。

版本控制检查点：运行 recorder、export、replay 和压力测试，创建独立本地提交；得到用户明确确认后推送 `main`。

### Phase 3：多 BMS 总览与温度/压差卡片

1. 提取 `BmsDashboard` 可复用组件，将指标、信号表、单体表和告警列表封装为每地址一套。
2. 在总览页增加内层 BMS 标签页，按地址动态创建、更新和清空页面。
3. 实现范围卡片组件，支持主值和两项次值的独立颜色与空值状态。
4. 将单体压差卡片改为“压差 + 最高红色 + 最低绿色”，落实数据源优先级和单位格式。
5. 增加温度卡片，显示平均、最高/位置、最低/位置。
6. 在 CAN 报文表增加 BMS 地址列或在报文名中明确显示地址，未知帧显示 `--`。
7. 更新演示数据，使 `--demo` 默认产生至少 3 个地址的不同电压、SOC 和温度。
8. 增加 offscreen GUI 测试，覆盖标签页数量、页面隔离、颜色角色、空温度和 1024x680 布局。

完成条件：5 台合成 BMS 出现 5 个总览标签页；各页值与对应地址一致；温度卡片有数据；最高单体电压为红色、最低为绿色；最小窗口中卡片和表格无重叠、无截断。

版本控制检查点：运行 GUI 和模型测试，生成并检查桌面截图，创建独立本地提交；得到用户明确确认后推送 `main`。

### Phase 4：多 BMS 同图波形

1. 在波形面板增加已发现 BMS 的多选列表，保留最多 6 个信号的限制。
2. 每个信号创建一个 plot，并为每个选中 BMS 创建独立曲线和图例项。
3. 固定地址到颜色的映射，确保切换信号、标签页或刷新后颜色不跳变。
4. 处理不同 BMS 采样时间不一致、某台暂时无数据、地址后发现和数据陈旧场景。
5. 在 reset、停止、重新回放时清理所有地址曲线，防止上一个数据源残留。
6. 增加 5 台同名信号叠加测试，验证每条曲线数据、图例、颜色和选择状态。

完成条件：同一 `BattVolt` 图中可同时显示 5 条 BMS 曲线，图例与地址一致；取消任一 BMS 后只移除该地址曲线；切换到温度信号后仍保持设备选择。

版本控制检查点：运行波形和 GUI 测试，生成并检查多曲线截图，创建独立本地提交；得到用户明确确认后推送 `main`。

### Phase 5：整体验证、文档与 Windows 发布

1. 更新 README 和 Phase 7 文档，说明地址设置、总览标签、波形选择、raw-only 记录和 SQLite 回放。
2. 更新现场验收表，加入 5 台 BMS 地址规划、终端电阻、总线负载、帧丢弃、记录体积和回放一致性。
3. 运行全量 pytest，并确认不生成 `.pytest_cache`。
4. 运行 5 台合成压力测试至少 30 分钟等效帧量，确认 recorder 队列不溢出。
5. 重新执行 PyInstaller one-folder 构建和隔离环境 smoke test，验证新模块被正确打包。
6. 在 1440x900 和 1024x680 两个窗口尺寸检查总览与波形截图。
7. 真机接入 5 台 BMS 时，连续记录至少 30 分钟，记录实际帧率、数据库增长、CPU、内存和丢帧数；随后直接回放数据库并核对 5 台设备身份与关键数值。

完成条件：全量自动测试通过；Windows 发布包可启动；5 台真机或在真机条件未具备时的等效数据回放无串台、无记录丢帧；现场未完成项在文档中明确标记，不能以模拟测试代替真机结论。

版本控制检查点：文档和发布验证完成后创建第一版迭代收尾提交；得到用户明确确认后推送 `main` 并生成对应发布包校验值。

## 并行执行策略

- Phase 1 是公共基础，必须先完成。
- Phase 1 稳定后，Phase 2 的 recorder/replay 工作与 Phase 3 的 dashboard 组件工作可以并行开发，但合并前都必须基于同一多地址 pipeline API。
- Phase 4 依赖复合波形键和 GUI 地址发现机制，应在 Phase 1、Phase 3 的接口稳定后实施。
- 文档可随各 Phase 增量更新；最终发布构建和真机验证必须在所有功能合并后执行。
- 每个 Phase 只提交本阶段相关文件，避免将用户其他未提交改动混入提交；所有 GitHub push 均在用户对具体提交哈希明确授权后执行。

## 验证方法

### 自动测试

在 `E:\BatteryTest\bms_can_monitor` 执行：

```powershell
python -m pytest -p no:cacheprovider
```

预期：全部测试通过，项目根目录不产生 `.pytest_cache`。

重点断言：

- 地址 `0..4` 的标准帧和扩展帧均映射到正确 BMS。
- 同一时刻不同地址的 `BattVolt`、SOC、温度和单体电压互不覆盖。
- 5 台帧只在 `raw_frames` 中各写一次，新会话没有信号样本写入。
- SQLite 回放重建出的各地址最终快照与录制输入一致。
- v1 数据库升级前后原始帧、旧信号样本和事件行数不变。
- 控制安全门只接受地址 `0` 的新鲜状态。
- 波形缓存的 `(address, signal)` 序列互相独立。
- 最高电压和最低电压的 Qt ForegroundRole 分别为红色和绿色。

### 性能与容量

```powershell
python tools\recording_stress_test.py --frames 1000000
```

补充 5 台协议周期模拟参数后，验收：

- `stored == input`。
- `dropped_items == 0`。
- 持续写入能力显著高于约 535 帧/秒的 5 台峰值估算。
- raw-only 文件增长接近实测的约 125~146 MB/小时范围，允许因页大小、事件和元数据产生合理偏差。

### GUI 与视觉检查

- `--demo` 显示多个 BMS 标签页。
- 1440x900：信息密度合理，标签、卡片、表格和图例无重叠。
- 1024x680：所有卡片内容完整，最高/最低值不溢出容器。
- 多 BMS 波形中每个地址颜色稳定，图例可读，空序列不会生成异常缩放。
- 温度卡片在有/无 `CELL_TEMP` 时分别显示有效值和 `--`。

### 记录回放闭环

1. 生成包含地址 `0..4` 的交错测试流并记录为 SQLite。
2. 核对 session 元数据、DBC hash、检测地址和 raw_frames 数量。
3. 关闭实时源后直接在 GUI 打开该 SQLite session。
4. 以 1x 和 10x 各回放一次。
5. 核对 5 个标签页、关键终值、单体电压、温度、告警和波形设备身份。
6. 使用修改后的 DBC 回放同一文件，确认出现 hash 不一致提示且用户可以取消。

### Windows 发布验证

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_release.ps1
```

预期：

- `dist\BMS-CAN-Monitor\BMS-CAN-Monitor.exe` smoke test 通过。
- 打包目录包含当前 DBC、ControlCAN.dll 和所有新增模块。
- 在无开发 Python 环境下可启动 demo、打开 SQLite 回放并显示多 BMS 标签和波形。

## 风险与控制

- **地址误识别**：只允许 DBC 精确 ID、帧类型和 `0..11` 偏移共同匹配；冲突显式报错。
- **状态串台**：每个地址独立 decoder、单体组帧器和状态仓库；复合波形键必须包含地址。
- **回放不可复现**：会话保存 DBC SHA-256；hash 不一致时明确提示。
- **大文件内存占用**：SQLite 回放和信号导出必须分块迭代，不允许 `fetchall()` 整个长会话。
- **旧数据损坏**：schema 升级只新增列/表，不删除旧 `signal_samples`，升级测试使用数据库副本。
- **控制误目标**：监控地址与控制地址分离；非零地址控制限制保持；标签页切换不影响控制目标。
- **GUI 负载**：controller 每批每地址只发一次快照；波形刷新保持 100 ms；最多 6 个信号图。

## 未来扩展

- 将单个 CAN 通道扩展为 CAN1/CAN2 同时采集，设备身份升级为 `(channel, device_address)`。
- 提供记录自动分卷、保留天数和磁盘剩余空间预警。
- 增加每台 BMS 的用户别名、序列号绑定和地址冲突提示。
- 增加“BMS 上报 SOH”和“上位机容量估算 SOH”的对比视图。
- 在完成厂家确认和实机验证后，再单独设计非零地址控制协议与安全流程。
