# 第一版迭代：多 BMS、温度与原始帧回放

## 功能范围

本次迭代在同一个 CANalyst-II 通道上自动识别极空 BMS 地址 `0..11`，并提供：

- 每个地址独立的总览标签页、实时信号、单体电压和告警/故障列表。
- 平均、最高/探头号和最低/探头号温度卡片。
- 单体压差、红色最高单体电压和绿色最低单体电压摘要。
- 多选 BMS 的同信号波形叠加，地址配色和图例保持稳定。
- raw-only SQLite 记录，以及回放、导出时按当前 DBC 重新解码。
- SQLite 多会话选择、DBC SHA-256 不一致提示和分块流式回放。

多 BMS 监控不改变控制安全边界。连接面板中的“控制地址”只决定受保护控制功能的目标；非零地址控制仍然禁用，切换总览标签页也不会改变控制目标。

## 连接与地址

1. 确认所有 BMS 的地址唯一且位于 `0..11`。
2. 所有设备使用相同的 250 kbps 波特率，并接入当前选择的同一 CAN 通道。
3. 总线只在物理两端各保留一个 120 欧终端电阻，断电测量 CAN-H 与 CAN-L 通常应接近 60 欧。
4. 先使用只听模式确认报文，再进入正常模式；控制功能保持锁定。
5. 程序根据上行 CAN ID 自动建立 `BMS 0`、`BMS 1` 等标签页，不需要逐台修改控制地址来查看。

未知帧仍会进入 CAN 报文页和原始记录，但不会创建错误的 BMS 状态。CAN 报文页的 `BMS` 列对已识别帧显示地址，未知帧显示 `--`。

## 总览与温度

总览页内层标签按地址升序排列，每个页面拥有独立的数据模型。单体压差优先使用协议 `CELL_VOLT` 报文中的最高/最低值，缺失时从已经组装的单体电压回退计算；少于两个有效单体值时显示 `--`。

温度卡片只显示 BMS 在 `CELL_TEMP` 中上报的 `AvrgCellTemp`、`MaxCellTemp/MaxCtNO` 和 `MinCellTemp/MinCtNO`，不由上位机推算温度。

## 多 BMS 波形

- 左侧 BMS 列表选择要对比的地址，信号列表最多选择 6 个信号。
- 每个信号占一个图，每个已选 BMS 在该图中对应一条曲线。
- 地址颜色固定；新发现地址默认勾选，不会重置已有地址的手动选择。
- 所有已选曲线使用共同最新时间作为相对时间零点。
- 协议最多 12 个地址，因此最极端情况下为 6 个图、72 条曲线。
- 回放自然结束或停止数据源时保留最后快照、地址和波形；清空或启动新的实时/回放/演示数据源时才清理旧波形身份。

## 记录格式

schema v2 新会话使用 `raw_only` 模式，只保存：

- `sessions`：设备、通道、波特率、实际发现地址、DBC SHA-256 和备注。
- `raw_frames`：完整 CAN ID、标准/扩展帧、DLC、数据、通道、时间戳和来源。
- `events`：连接、错误、回放、控制和队列事件。

新数据库不创建 `signal_samples`。旧 schema v1 数据库升级时保留原表和旧信号数据，新会话仍只记录原始帧。

记录结束时应先停止记录，再停止数据源。正常停止会排空记录队列并执行 WAL checkpoint；状态栏显示“已保存”后主 SQLite 文件可独立携带，显示“需保留 WAL”时必须同时保存同名 `-wal` 和 `-shm`。5 台 BMS 的实测增长需要以现场报文率为准；当前合成抽样约为 `70.2 bytes/帧`，正常负载估算约 `125~146 MB/小时`。

## SQLite 回放与导出

界面“回放”可直接选择 `.sqlite3`、`.sqlite` 或 `.db`：

1. 多个会话时先选择会话。
2. 记录的 DBC SHA-256 与当前 DBC 不一致时，确认是否仍使用当前协议定义重新解码。
3. 回放帧通过与实时 CAN 相同的多地址管线，重新生成总览、温度、单体和波形。
4. 禁止同时回放正在记录的同一个数据库。

命令行导出：

```powershell
python tools\export_recording.py records\test.sqlite3 --list
python tools\export_recording.py records\test.sqlite3 --session 1 --output exports
python tools\export_recording.py records\test.sqlite3 --session 1 --address 2
```

未指定 `--address` 时，每个检测到的 BMS 分别生成信号宽表，避免同名信号互相覆盖。原始帧 CSV 仍可直接作为回放输入。

## 验证状态

- 单台 CANalyst-II 的数据显示和 SQLite 记录已经完成实机验证。
- 5 台合成地址的状态隔离、单体组帧、温度、波形叠加和 SQLite 记录回放已有自动化测试。
- 5 地址、100 万帧 raw-only 压力测试完整写入，用时 `22.220 s`，数据库约 `67.5 MiB`，按 535 帧/s 等效约 31.2 分钟；该结果用于验证写入余量，不代表 5 台真实 BMS 的总线和长稳结果。
- 5 台真机 30 分钟接收、2 小时记录、USB 异常和回放一致性仍需按 `phase6-field-validation.md` 现场执行。

## Windows 发布

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_windows_release.ps1
python -B tools\verify_windows_release.py dist\BMS-CAN-Monitor --launch
```

必须分发整个 `BMS-CAN-Monitor` 目录或对应 zip，不能只复制 EXE。目标电脑仍需安装 CANalyst-II 驱动。
