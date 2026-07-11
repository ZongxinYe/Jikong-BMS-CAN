# Phase 4：上位机 GUI 第一版

## 功能范围

Phase 4 将已有 CAN 输入、DBC 解码、实时状态和 SQLite 记录能力接入 PySide6 桌面界面。主窗口包含：

- CANalyst-II 设备号、通道、波特率、BMS 地址、工作模式和 `ControlCAN.dll` 路径设置。
- 实时 CAN、CSV 离线回放和本地模拟 BMS 三种数据源。
- 电池总压、电流、SOC、SOH、单体压差、全部解码信号和单体电压总览。
- 最多 6 条信号的分轨实时波形，支持 30 秒、1 分钟和 5 分钟时间窗。
- 限长 CAN 报文表，支持全文筛选、暂停显示和清空。
- 适配器、接收线程、回放和队列异常事件表。
- SQLite 会话记录开关和记录队列状态。

Phase 4 保持监控优先，不在当时版本中发送 BMS 控制报文。Phase 5 已增加受保护的单帧 `Ctrl_INFO` 控制，详见 `phase5-control-safety.md`；控制帧周期发送仍不开放。

## 启动

在项目虚拟环境中安装一次项目：

```powershell
python -m pip install -e ".[dev]"
```

启动空白工作台：

```powershell
bms-can-monitor
```

没有连接 CANalyst-II 时，可直接启动连续变化的本地演示数据：

```powershell
bms-can-monitor --demo
```

也可以在启动时指定 Phase 2/3 格式的 CAN 帧 CSV：

```powershell
bms-can-monitor --replay exports\session_1_raw_frames.csv --speed 5
```

等价入口为 `python -m bms_can_monitor`。

## 线程与刷新边界

- `CanReceiveWorker`、`ReplayWorker` 和设备连接操作不占用 Qt 主线程。
- 接收线程只向最大 50,000 帧的队列写入统一 `CanFrame`。
- Qt 主线程每 16 ms 消费一次队列，每次最多处理 2,000 帧且默认占用不超过 8 ms。
- 报文表最多保留 20,000 行，事件表最多保留 2,000 行。
- 波形由 Phase 3 的线程安全环形缓冲区提供，绘图周期为 100 ms。
- SQLite 仍由独立写线程批量落盘，界面只显示队列深度和会话号。

这些上限用于避免长时间采集时表格、绘图和内存无界增长。数据库记录不受报文表显示上限影响。

## 操作顺序

1. 在左侧确认设备号、CAN 通道、250 kbps、BMS 地址和 DLL 路径。
2. 单击“连接”，状态变为“CANalyst-II 已连接”后开始接收。
3. 需要落盘时单击“记录”，选择新的 SQLite 数据库。
4. 在“实时波形”勾选所需信号，在“CAN 报文”输入 CAN ID、报文名或数据片段筛选。
5. 先停止记录，再单击“停止”关闭当前数据源。

CSV 回放和演示数据不需要硬件；三种数据源在同一时刻只允许启用一种。

## 验证

无硬件自动化验证：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -B -m pytest -p no:cacheprovider
```

当前测试覆盖 GUI 控制器、队列消费预算、SQLite 联动、限长模型、报文筛选和完整窗口离屏构建。真实 CANalyst-II 的持续运行验收仍需连接设备后完成：

- 连续接收 30 分钟，确认接收队列不持续增长、无异常丢帧。
- 同时显示波形并记录 2 小时，确认窗口交互和停止记录正常。
- 分别验证 CAN1/CAN2、正常模式/只听模式及实际 BMS 地址。
