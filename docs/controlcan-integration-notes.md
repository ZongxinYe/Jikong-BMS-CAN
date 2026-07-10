# ControlCAN 集成说明

Phase 0 只做 SDK 封装基础，不连接真实硬件。

## 调用链

后续真实接入时使用：

1. `VCI_OpenDevice(VCI_USBCAN2, device_index, 0)`
2. `VCI_InitCAN(VCI_USBCAN2, device_index, channel, init_config)`
3. `VCI_ClearBuffer(VCI_USBCAN2, device_index, channel)`
4. `VCI_StartCAN(VCI_USBCAN2, device_index, channel)`
5. 循环 `VCI_Receive(...)` 或按需 `VCI_Transmit(...)`
6. `VCI_ResetCAN(...)` 或 `VCI_CloseDevice(...)`

## 默认 BMS 初始化参数

- `AccCode = 0x00000000`
- `AccMask = 0xFFFFFFFF`
- `Filter = 1`
- `Timing0 = 0x01`
- `Timing1 = 0x1C`
- `Mode = 0`

## 发送帧约定

- 手动发送默认 `SendType=1`。
- 标准帧 ID 范围为 `0x000` 到 `0x7FF`。
- 扩展帧 ID 范围为 `0x00000000` 到 `0x1FFFFFFF`。
- 远程帧不应携带有效数据。

