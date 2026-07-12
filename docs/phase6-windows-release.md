# Phase 6：Windows 发行包与现场使用

## 发行形式

Phase 6 使用 PyInstaller 生成 64 位 one-folder 发行包：

```text
dist\BMS-CAN-Monitor\
  BMS-CAN-Monitor.exe
  Documentation\
    phase7-multi-bms-raw-replay.md
  release-manifest.json
  _internal\
    bms_can_monitor\protocol\bms_jikong_v2_1.dbc
    third_party\controlcan\x64\ControlCAN.dll
    ... Python、PySide6、pyqtgraph 运行文件
```

必须复制或解压整个 `BMS-CAN-Monitor` 目录，不能只拿走 EXE。目标电脑不需要安装 Python，但仍需安装 CANalyst-II 厂商驱动。

构建命令：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_release.ps1
```

只重新生成文档、校验清单和压缩包，不重新运行 PyInstaller：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_release.ps1 -SkipBuild
```

`release-manifest.json` 保存 EXE、DBC 和 x64 DLL 的大小及 SHA-256。压缩包旁生成 `.sha256` 文件。

## 用户数据目录

打包程序不向安装目录写记录，默认使用：

```text
%LOCALAPPDATA%\BMS CAN Monitor\
  records\
  logs\control-audit.jsonl
```

台架需要把数据写到其他磁盘时，可在启动前设置：

```powershell
$env:BMS_CAN_MONITOR_DATA_DIR = "D:\BMS-Test-Data"
& "C:\Tools\BMS-CAN-Monitor\BMS-CAN-Monitor.exe"
```

## 接线与上电

1. 断电确认 CANalyst-II、BMS 和测试设备的 CAN 电平兼容。
2. CAN-H 对 CAN-H，CAN-L 对 CAN-L，并连接信号地 GND。
3. 总线两端各使用一个 120 欧终端电阻；断电测量 CAN-H 与 CAN-L 通常应接近 60 欧。
4. 连接 CANalyst-II USB，并确认 Windows 设备驱动正常。
5. 先使用“只听模式”确认报文，再根据需要切换正常模式。极空协议默认 250 kbps。
6. 程序自动监测地址 `0..11`；左侧“控制地址”只决定受保护控制功能的目标，非零地址控制发送仍被锁定。

不要把 CAN-H/CAN-L 接到电池正负极。首次接线和首次控制应在有保险、急停及隔离措施的台架上完成。

## 启动与采集

1. 解压完整发行目录并双击 `BMS-CAN-Monitor.exe`。
2. 在左侧确认设备号、CAN1/CAN2、250 kbps、控制地址和 DLL 路径。
3. 单击“连接”，确认状态显示 CANalyst-II 已连接。
4. 在 CAN 报文页确认存在 `0x02F4`、`0x18F128F4` 等预期报文。
5. 开启记录后选择 SQLite 文件，观察状态栏记录队列不持续增长。
6. 停止时先停止记录，再停止 CAN 数据源。

多个 BMS 地址会自动出现在总览标签和波形 BMS 列表中。SQLite 新会话只保存完整原始帧；记录可直接从界面回放，并按当前 DBC 重新生成各地址数据。详细说明见 `phase7-multi-bms-raw-replay.md`。

BMS 控制功能默认锁定。现场控制流程和审计要求见 `phase5-control-safety.md`。

## 常见问题

### 找不到设备

- 确认 CANalyst-II USB 指示灯、设备管理器和厂商驱动。
- 避免同时打开 CANtest、USB-CAN Tool 或其他占用设备的软件。
- 确认程序使用 `_internal\third_party\controlcan\x64\ControlCAN.dll`。
- 不要用周立功调试工具目录中的 x86 DLL替换发行包 x64 DLL。

### 已连接但没有报文

- 核对 CAN-H/CAN-L 是否接反、GND 是否连接、终端电阻和 BMS 是否上电。
- 核对通道和 250 kbps。
- 先使用只听模式排除本软件主动发送影响。
- 核对 BMS APP 地址是否为 `0..11` 且各设备唯一；程序会自动解析有效地址，未知帧只保留在原始报文和记录中。

### 运行中拔掉 USB

接收线程应停止并在“运行事件”显示适配器错误。重新连接前先单击停止；如果厂商 DLL 未释放设备，关闭程序、重新插拔 USB 后重试。

### 记录或审计无法写入

- 检查 `%LOCALAPPDATA%\BMS CAN Monitor` 或覆盖目录的磁盘空间和写权限。
- 控制审计在发送前无法落盘时，控制帧会被拒绝。
- SQLite 文件被其他程序独占时，停止记录并选择新文件。

## 发行验证

`tools\verify_windows_release.py` 验证 EXE、DBC、ControlCAN.dll、多 BMS 使用文档和 x64 架构。带 `--launch` 时，会清除 `PYTHONHOME/PYTHONPATH`，把 PATH 缩减到 Windows 系统目录，从临时工作目录启动打包 EXE，运行 1.5 秒多地址演示数据后自动关闭。

这能验证发行包不依赖开发机 Python 路径，但不能替代一台从未安装 Python 的干净 Windows 电脑验收。
