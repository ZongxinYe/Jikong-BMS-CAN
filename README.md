# BMS CAN Monitor

自研 CanTool 风格上位机，面向 CANalyst-II + ControlCAN.dll + 极空 BMS CAN 协议。

当前已完成：

- 固化 ControlCAN SDK 文件和 DLL 位数。
- 用 Python ctypes 定义 ControlCAN 数据结构。
- 固化 CANalyst-II 常量、250 kbps 参数和 ID 对齐规则。
- 将极空 BMS CAN V2.1 的 18 类报文固化为可修改的 DBC。
- 支持默认/偏移设备地址、大小端字段、告警故障和 25 串单体电压组帧。
- 在不连接硬件的情况下用 PDF 示例帧完成协议测试。

## 验证

```powershell
cd E:\BatteryTest\bms_can_monitor
python -m pytest -p no:cacheprovider
python tools\inspect_controlcan_dll.py
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
