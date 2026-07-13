# BMS CAN Monitor

自研 CanTool 风格上位机，面向 CANalyst-II + ControlCAN.dll + 极空 BMS CAN 协议。

当前已完成：

- 固化 ControlCAN SDK 文件和 DLL 位数。
- 用 Python ctypes 定义 ControlCAN 数据结构。
- 固化 CANalyst-II 常量、250 kbps 参数和 ID 对齐规则。
- 将极空 BMS CAN V2.1 的 18 类报文固化为可修改的 DBC。
- 支持默认/偏移设备地址、大小端字段、告警故障和 25 串单体电压组帧。
- 支持 CANalyst-II 设备发现、连接、批量接收、单帧/周期发送和诊断。
- 支持 CSV 和 SQLite 离线回放，并与真实设备统一输出 `CanFrame`。
- 支持多 BMS 地址自动路由、独立状态和复合波形缓存。
- 支持 raw-only SQLite 后台记录和回放/导出时按当前 DBC 重新解码。
- 支持记录停止时 WAL checkpoint、停止原因留存和独立 `recording-audit.jsonl` 诊断日志。
- 回放自然结束或停止后保留最后快照和波形；只有主动清空或启动新数据源时才重置。
- 支持按地址切换的多 BMS 总览、温度摘要和带红绿极值的单体压差卡片。
- 支持完整单体扫描后的合计电压，在总压卡片中对照显示并作为多 BMS 波形信号。
- 支持显示由 CAN ID 解析的设备地址，以及 BATT_ST2 的剩余容量、满充容量、循环容量和循环次数。
- 支持多选 BMS 并在同一信号图中叠加对比，地址颜色和图例保持稳定。
- 支持 CANalyst-II 连接、离线回放、实时总览、分轨波形、报文筛选和记录控制 GUI。
- 支持默认锁定、双重确认、单次授权和独立审计的 `Ctrl_INFO` 控制发送。
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

演示模式默认生成 `BMS 0`、`BMS 1`、`BMS 2` 三个地址，可直接检查多页签隔离、温度、BATT_ST2 和单体合计电压显示。连接面板中的“控制地址”只决定受保护控制功能的目标，不限制总线上的 BMS 自动发现。

也可通过下面的命令启动离线回放：

```powershell
bms-can-monitor --replay <CAN帧.csv> --speed 5
bms-can-monitor --replay <记录.sqlite3> --session 1 --speed 5
```

SQLite 未指定 `--session` 时默认回放最新会话。多 BMS 地址、温度、波形、raw-only 记录和 SQLite 回放的完整说明见 `docs\phase7-multi-bms-raw-replay.md`；界面线程边界见 `docs\phase4-gui.md`。

BMS 控制默认锁定，只允许真实 CAN、正常模式、默认地址和近期有报文的场景。MaskCode、双重确认、审计日志及限制见 `docs\phase5-control-safety.md`。

## Windows 发行包

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_release.ps1
```

生成 `dist\BMS-CAN-Monitor\BMS-CAN-Monitor.exe` 和 zip 压缩包。目标电脑无需 Python，但必须安装 CANalyst-II 驱动，并完整保留 `_internal` 目录。打包结构、接线、用户数据目录和故障排查见 `docs\phase6-windows-release.md`；当前真机验收进度见 `docs\phase6-field-validation.md`。

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

recorder.stop(detected_addresses=pipeline.detected_addresses)
```

schema v2 新会话只保存完整原始帧和事件，不保存逐信号样本。数据库结构、波形缓存和 CSV 导出说明见 `docs\phase3-data-recording.md`。

正常停止会排空后台队列、写入会话结束时间并执行 WAL checkpoint。状态栏显示“已保存”后，主 `.sqlite3` 文件可以独立携带；若显示“需保留 WAL”，必须把同名 `-wal` 和 `-shm` 文件与主库放在同一目录。记录开始、停止和错误原因另存于用户数据目录的 `logs\recording-audit.jsonl`。v1.2 的完整行为和验收结果见 `docs\v1.2-record-replay-reliability.md`。
