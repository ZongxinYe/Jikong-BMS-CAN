# Phase 2 CAN 数据源说明

Phase 2 将 CANalyst-II 实时通信和 CSV 离线回放统一为 `CanFrame` 数据流。此阶段不包含 GUI，也不主动发送极空 BMS 控制帧。

## CANalyst-II 生命周期

`Canalyst2Adapter.connect()` 顺序执行：

1. `VCI_OpenDevice`
2. `VCI_InitCAN`
3. `VCI_ClearBuffer`
4. `VCI_StartCAN`

任一步失败都会产生 `ADAPTER_ERROR` 事件，并在设备已打开时尽力调用 `VCI_CloseDevice`。正常关闭使用 `close()`；通道复位后重新启动使用 `restart()`。

极空 BMS 默认配置为：

- `DeviceType=4`
- `DeviceInd=0`
- `CANInd=0`
- `250000 bps`，即 `Timing0=0x01`、`Timing1=0x1C`
- 正常模式 `Mode=0`
- 接收全部帧 `AccMask=0xFFFFFFFF`

## 实时接收

`CanReceiveWorker` 在后台线程中批量调用 `VCI_Receive`，默认每批最多 2500 帧。帧通过线程安全的 `queue.Queue` 交给后续协议解析、记录和 GUI。

- SDK 返回 `0xFFFFFFFF` 时作为接收错误处理。
- 主机时间戳使用 Python Unix 时间；设备 `TimeStamp` 在 `TimeFlag=1` 时保存为附加字段，单位沿用厂商定义的 0.1 ms。
- 输出队列已满时不阻塞硬件接收线程，而是丢弃该帧并产生 `RX_QUEUE_OVERFLOW` 事件。
- 一段时间没有报文时产生一次 `RX_TIMEOUT`；收到新帧后重新计时。

## 发送

`Canalyst2Adapter.send()` 发送单帧，校验工作由 `CanFrame` 和 `make_can_obj()` 完成：

- 标准帧 ID 不超过 `0x7FF`，扩展帧 ID 不超过 `0x1FFFFFFF`。
- 数据帧 DLC 必须等于数据长度；远程帧可以没有数据但保留请求 DLC。
- 默认使用 `SendType=1` 单次发送。

`TxScheduler` 在应用层实现周期发送，记录每个任务的尝试、成功、失败和剩余次数。当前只提供通用 CAN 能力；BMS 控制帧安全确认在 Phase 5 实现。

## 离线回放 CSV

CSV 列定义：

| 列 | 必需 | 示例 | 说明 |
| --- | --- | --- | --- |
| `timestamp` | 是 | `1710000000.125` | Unix 秒或任意单调递增秒值 |
| `can_id` | 是 | `0x18F128F4` | 十进制、带 `0x` 十六进制或含 A-F 的无前缀十六进制 |
| `data` | 是 | `2C 01 90 01 E8 03 00 64` | 空格分隔或连续十六进制 |
| `is_extended` | 否 | `1` | 默认标准帧 |
| `is_remote` | 否 | `0` | 默认数据帧 |
| `dlc` | 否 | `8` | 默认等于数据长度 |
| `channel` | 否 | `0` | 默认 CAN1，即索引 0 |

回放按相邻时间戳保持间隔，并用 `speed` 调整速度；输出时间会重新基准到本次回放开始时间。

## 现场检查

默认命令只枚举设备，不打开 CAN 通道：

```powershell
python tools\canalyst2_check.py
```

显式指定接收时长才会以只接收方式打开 CAN1，期间不会发送报文：

```powershell
python tools\canalyst2_check.py --channel 0 --bitrate 250000 --receive-seconds 5
```

CSV 回放：

```powershell
python tools\replay_log.py records\raw_frames.csv --speed 2
```
