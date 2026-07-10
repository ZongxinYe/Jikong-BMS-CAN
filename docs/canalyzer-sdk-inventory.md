# CANalyst-II SDK 资料清单

## 已归档文件

| 用途 | 项目内路径 | 来源 | 备注 |
| --- | --- | --- | --- |
| x64 运行 DLL | `third_party/controlcan/x64/ControlCAN.dll` | `CAN分析仪资料/二次开发库文件/x64(64bit)/ControlCAN.dll` | 64 位 Python/PyInstaller 首选 |
| win32 备用 DLL | `third_party/controlcan/win32/ControlCAN.dll` | `CAN分析仪资料/二次开发库文件/win32(32bit)/ControlCAN.dll` | 仅用于 32 位 Python |
| SDK 头文件 | `third_party/controlcan/ControlCAN.h` | `CAN分析仪资料/二次开发库文件/ControlCAN For VC/ControlCAN.h` | ctypes 结构体与函数签名基准 |

## DLL 校验

| 文件 | 架构 | 大小 | SHA256 |
| --- | --- | ---: | --- |
| `third_party/controlcan/x64/ControlCAN.dll` | x64 | 2683392 | `6D151F92217983C39A6690DED76B41F86EBAD7570BCC27FC9D13F7141425B1E3` |
| `third_party/controlcan/win32/ControlCAN.dll` | x86 | 2065408 | `9ABE40E48EE1BAE1A4C6957D9FBED6FC4D718EB89AD39FB964C0BF16BC494408` |

## Phase 0 结论

- CANalyst-II 设备类型为 `VCI_USBCAN2 = 4`。
- 默认设备索引为 `0`，双通道为 `CANInd=0` 和 `CANInd=1`。
- 极空 BMS 协议使用 `250000` bps，对应 `Timing0=0x01`、`Timing1=0x1C`。
- 实车通信使用正常模式 `Mode=0`，不使用厂商示例中的自测模式。
- `VCI_CAN_OBJ.ID` 为右对齐；`AccCode/AccMask` 滤波参数为左对齐。
- `调试工具/周立功ZLG调试工具/ControlCAN.dll` 在当前资料包中是 x86，不作为 64 位程序主 DLL。

