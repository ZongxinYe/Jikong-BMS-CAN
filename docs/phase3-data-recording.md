# Phase 3 实时状态与数据记录

Phase 3 将 Phase 2 的 `CanFrame` 流接入最新状态、波形缓存和 SQLite 记录，并提供 Excel 可读的 CSV 导出。

## 数据管线

`DataPipeline.process_frame()` 按以下顺序处理每一帧：

1. 原始帧进入 `SessionRecorder`。
2. `JikongBmsDecoder` 尝试 DBC 解码。
3. 已知报文更新 `BmsStateStore` 最新快照。
4. 用户选择的数值信号进入 `SignalRingBuffer`。
5. 解码信号进入 `signal_samples` 表。

未知 CAN ID 不会中断采集：原始帧仍被记录，协议解码计数增加，但不会生成信号样本。

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
| `sessions` | 开始/结束时间、设备、通道、波特率、设备地址、协议版本、备注 |
| `raw_frames` | 时间戳、CAN ID、帧类型、DLC、二进制数据、通道、硬件时间戳、来源 |
| `signal_samples` | 消息名、信号名、工程值、原始值、单位、来源帧 ID |
| `events` | 连接、错误、超时、发送结果、用户事件及 JSON 详情 |

`flush()` 是持久化屏障；返回时此前数据已经提交。队列满会显式抛出 `RecorderQueueFull`，后台写入失败会通过 `RecorderWriteError` 返回，不会静默丢失。

## CSV 导出

```powershell
python tools\export_recording.py records\test.sqlite3 --list
python tools\export_recording.py records\test.sqlite3 --session 1 --output exports
```

每个会话生成三份文件：

- `session_N_raw_frames.csv`：列格式兼容 Phase 2 的 `load_replay_csv()`，可直接离线回放。
- `session_N_signals_wide.csv`：按时间排列的信号宽表，默认用最近值前向填充。
- `session_N_events.csv`：事件类型、消息和 JSON 详情。

CSV 使用 UTF-8 BOM，便于中文版 Excel 直接打开；文本开头的公式字符会被转义。

## 容量验证

自动测试覆盖 5000 帧批量写入、持久化数量核对和记录后回放闭环。可用以下工具做更高数据量的本机测试：

```powershell
python tools\recording_stress_test.py --frames 100000
```

2026-07-10 在当前开发机执行 100000 帧测试，SQLite 核对写入 100000 行，用时 1.603 秒，约 62400 帧/秒。按 20 ms 报文周期折算，帧数量覆盖约 33 分钟。

当前尚未连接真实 CANalyst-II，因此 30 分钟/2 小时真机持续采集和 GUI 响应测试留到设备接入及 Phase 4 界面完成后执行。
