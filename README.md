# BMS CAN Monitor

自研 CanTool 风格上位机，面向 CANalyst-II + ControlCAN.dll + 极空 BMS CAN 协议。

当前已完成：

- 固化 ControlCAN SDK 文件和 DLL 位数。
- 用 Python ctypes 定义 ControlCAN 数据结构。
- 固化 CANalyst-II 常量、250 kbps 参数和 ID 对齐规则。
- 将极空 BMS CAN V2.1 的 18 类报文固化为可修改的 DBC。
- 支持默认/偏移设备地址、大小端字段、告警故障和 25 串单体电压组帧。
- 支持 CANalyst-II 设备发现、连接、批量接收、单帧/周期发送和诊断。
- 支持 CSV 离线回放，并与真实设备统一输出 `CanFrame`。
- 支持最新 BMS 状态、波形环形缓存、SQLite 后台记录和 CSV 导出。
- 支持 CANalyst-II 连接、CSV 回放、实时总览、分轨波形、报文筛选和记录控制 GUI。
- 在不连接硬件的情况下用 PDF 示例帧完成协议测试。

## 桌面程序

```powershell
python -m pip install -e ".[dev]"
bms-can-monitor
```

无硬件试用：

```powershell
bms-can-monitor --demo
```

也可通过 `bms-can-monitor --replay <CAN帧.csv> --speed 5` 启动离线回放。界面功能、线程边界和真机验收项见 `docs\phase4-gui.md`。

## 验证

```powershell
python -m pytest -p no:cacheprovider
python tools\inspect_controlcan_dll.py
python tools\canalyst2_check.py
```

64 位 Python 应加载 `third_party\controlcan\x64\ControlCAN.dll`。

## 协议解码

默认 DBC 位于 `src\bms_can_monitor\protocol\bms_jikong_v2_1.dbc`，修改后可通过 `DbcDecoder.reload()` 重新加载。

```python
from bms_can_monitor.protocol import CanFrame, JikongBmsDecoder

decoder = JikongBmsDecoder()
message = decoder.decode(
    CanFrame(0x02F4, bytes.fromhex("13 01 D7 11 33"))
)

print(message.values)
# {'BattVolt': 27.5, 'BattCurr': 56.7, 'SOC': 51}
```

协议原文中的冲突及当前选择记录在 `docs\jikong-protocol-v2.1-decisions.md`。

## CAN 数据源

```python
from queue import Queue

from bms_can_monitor.canio import BusConfig, Canalyst2Adapter, CanReceiveWorker

frames = Queue(maxsize=10000)
adapter = Canalyst2Adapter(BusConfig(channel=0, bitrate=250_000))
adapter.connect()

worker = CanReceiveWorker(adapter, frames)
worker.start()
```

真实设备、周期发送、诊断和 CSV 回放接口见 `docs\phase2-can-io.md`。

## 数据记录

```python
from bms_can_monitor.data import DataPipeline, SessionMetadata, SessionRecorder

recorder = SessionRecorder("records/test.sqlite3")
recorder.start(SessionMetadata(note="BMS 台架测试"))
pipeline = DataPipeline(recorder=recorder)

# 对接收队列中的每个 frame 调用：
pipeline.process_frame(frame)

recorder.stop()
```

数据库结构、波形缓存和 CSV 导出说明见 `docs\phase3-data-recording.md`。
