# Phase 3 实时状态与数据记录

Phase 3 将 Phase 2 的 `CanFrame` 流接入最新状态、波形缓存和 SQLite 记录，并提供 Excel 可读的 CSV 导出。

## 数据管线

`DataPipeline.process_frame()` 按以下顺序处理每一帧：

1. 原始帧进入 `SessionRecorder`。
2. 地址解析器识别 BMS 地址，每个地址使用独立 `JikongBmsDecoder`。
3. 已知报文更新对应地址的 `BmsStateStore` 最新快照。
4. 用户选择的数值信号以 `(BMS 地址, 信号名)` 进入 `SignalRingBuffer`。

未知 CAN ID 不会中断采集：原始帧仍被记录，协议解码计数增加。

## 最新状态与波形

`BmsStateStore` 对每个信号和单体电压保存独立时间戳，旧报文不会覆盖新值。`snapshot()` 返回与内部字典分离的 `BmsSnapshot`。

`SignalRingBuffer` 只接收已选择的数值信号，并使用两层边界：

- `window_seconds` 控制保留时长，默认 300 秒。
- `max_points_per_signal` 控制每条曲线最大点数，默认 100000。

无效值、非数值、非有限数值以及乱序样本不会进入波形缓存。

## SQLite 记录器

`SessionRecorder` 使用单独写线程，采集线程只执行非阻塞入队。数据库启用 WAL、外键、5 秒 busy timeout 和批量事务。

| 表 | 内容 |
| --- | --- |
| `sessions` | 开始/结束时间、设备、通道、波特率、检测地址、协议版本、DBC SHA-256、存储模式和备注 |
| `raw_frames` | 时间戳、CAN ID、帧类型、DLC、二进制数据、通道、硬件时间戳、来源 |
| `events` | 连接、错误、超时、发送结果、用户事件及 JSON 详情 |

schema v2 的新会话使用 `raw_only` 模式，不创建 `signal_samples`。升级 v1 数据库时，旧 `signal_samples` 表和数据原样保留，旧会话标记为 `legacy_signals`，新会话仍只写原始帧。

`flush()` 是持久化屏障；返回时此前数据已经提交。队列满会显式抛出 `RecorderQueueFull`，后台写入失败会通过 `RecorderWriteError` 返回，不会静默丢失。

## CSV 导出

```powershell
python tools\export_recording.py records\test.sqlite3 --list
python tools\export_recording.py records\test.sqlite3 --session 1 --output exports
python tools\export_recording.py records\test.sqlite3 --session 1 --address 2
```

默认生成原始帧、事件以及每个已检测 BMS 的信号文件：

- `session_N_raw_frames.csv`：列格式兼容 Phase 2 的 `load_replay_csv()`，可直接离线回放。
- `session_N_bms_A_signals_wide.csv`：从原始帧按当前 DBC 重新解码，默认用最近值前向填充。
- `session_N_events.csv`：事件类型、消息和 JSON 详情。

桌面程序也可以直接打开 `.sqlite3` 或 `.db`，选择会话后分块回放。记录中的 DBC SHA-256 与当前 DBC 不一致时会要求用户确认。

CSV 使用 UTF-8 BOM，便于中文版 Excel 直接打开；文本开头的公式字符会被转义。

## 容量验证

自动测试覆盖 5000 帧批量写入、持久化数量核对和记录后回放闭环。可用以下工具做更高数据量的本机测试：

```powershell
python tools\recording_stress_test.py --frames 100000 --bms-count 5
```

工具会核对输入/写入帧数、确认新数据库不存在 `signal_samples`，并报告写入速率、文件大小和每帧平均字节数。按当前 schema 抽样，5 台 BMS 正常记录约为 125~146 MB/小时，实际值取决于报文构成、事件量和 SQLite 页利用率。

2026-07-11 使用 5 个地址和 100,000 帧完成 raw-only 短时压力验证：写入用时约 `1.698 s`，吞吐约 `58,892 帧/s`，数据库大小 `7,016,448 bytes`，约 `70.2 bytes/帧`。该结果是合成数据写入能力验证，不替代 5 台真机长时间记录验收。

单台 CANalyst-II 实机已验证数据显示和记录可用；5 台 BMS 的 30 分钟/2 小时持续采集、文件增长和 GUI 响应仍需在多机接线条件具备后验收。
