# BMS CAN Monitor

自研 CanTool 风格上位机，面向 CANalyst-II + ControlCAN.dll + 极空 BMS CAN 协议。

Phase 0 目标：

- 固化 ControlCAN SDK 文件和 DLL 位数。
- 用 Python ctypes 定义 ControlCAN 数据结构。
- 固化 CANalyst-II 常量、250 kbps 参数和 ID 对齐规则。
- 在不连接硬件的情况下完成基础测试。

## Phase 0 验证

```powershell
cd E:\BatteryTest\bms_can_monitor
python -m pytest
python tools\inspect_controlcan_dll.py
```

64 位 Python 应加载 `third_party\controlcan\x64\ControlCAN.dll`。

