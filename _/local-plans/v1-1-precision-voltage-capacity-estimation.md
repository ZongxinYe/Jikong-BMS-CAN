# v1.1：单体合计电压、地址确认与 BATT_ST2 展示

## 背景与目的

v1.1 暂不实现安时积分、容量测量、满端/空端识别和截止状态机。本版只交付以下四项：

1. 将完整一轮单体电压相加，在电池总压卡片中以括号形式显示“单体合计电压”。
2. 将单体合计电压作为 `CellVoltSum` 加入实时波形，可与多个 BMS 同图比较。
3. 根据接收帧 ID 自动解析并明确显示 BMS 协议地址。
4. 在每台 BMS 总览页显示电池状态 2 的四项数据：剩余容量、满充容量、循环容量、循环次数。

数据库继续采用完整原始帧记录。单体合计电压属于回放时重新计算的显示派生量，本版不新增派生数据表或 schema 迁移。

## 现状整理

- `BATT_ST2` 已在 DBC 中定义，`CapRemain`、`FulChargeCap`、`CycleCap`、`CycleCount` 已能正确解码，但总览页此前只显示 `CapRemain` 波形选项，没有四项卡片。
- 多 BMS 地址解析和按地址路由已完成，物理 CAN ID 按“基础 ID + 地址”解析，支持地址 `0..11`。
- 每个 BMS 已有独立的解码器、状态仓库、总览标签页和波形序列。
- 单体分帧已能组装为 `cell_voltages_mv`，但此前没有完整扫描边界，也没有合计电压派生值。
- SQLite v2 只保存原始帧，回放会重新经过地址解析、DBC 解码和数据管线。

## 设计

### 完整单体扫描

- `CellVoltageAssembler` 继续维护实时单体值，同时增加当前扫描、已观察分帧、预期电芯数和最近一次完整扫描快照。
- 非 4 的倍数电芯数量由末帧零填充立即确认；25 节由最后专用帧确认。
- 16、20、24 等整组数量在下一轮首帧到来时确认上一轮，后续轮次在最后一个预期分帧到达时立即发布。
- 只有编号连续的 `1..N` 且所需分帧完整时才发布合计，避免波形出现 4、8、12 节逐帧累加的假锯齿。
- 计算公式：`CellVoltSum = sum(cell_voltage_mv[1:N]) / 1000.0`，单位 V，显示 3 位小数。
- 每个 BMS 独立维护扫描状态，不跨地址共享电芯值、数量或合计结果。

### 快照与波形

- `BmsSnapshot` 增加 `cell_voltage_sum_v` 和 `summed_cell_count`，明确它们是上位机派生值而非 DBC 原始信号。
- `BmsStateStore` 保存最近一次完整扫描合计及其时间戳。
- `DataPipeline` 仅在完整扫描版本更新时追加一个 `CellVoltSum` 波形点。
- `SignalRingBuffer` 继续以 `(device_address, signal_name)` 隔离多 BMS 曲线。
- 原始帧记录不变；实时和 SQLite 回放使用相同算法重新生成合计值。

### 总览界面

- 总压主值继续显示 BMS 上报的 `BattVolt`。
- 总压卡片增加次级文本：`(单体合计 52.901 V)`；尚未得到完整扫描时不显示括号值。
- 总览页明确显示 `设备地址 N`，地址来自实际接收帧解析结果。
- 指标区改为四列，新增：
  - `CapRemain`：剩余容量，Ah。
  - `FulChargeCap`：满充容量，Ah。
  - `CycleCap`：循环容量，Ah。
  - `CycleCount`：循环次数，次。
- 波形信号列表新增“单体合计电压”，用户可选择一个或多个 BMS 同图比较。

## 文件结构

```text
src/bms_can_monitor/
├── protocol/
│   ├── models.py              # BmsSnapshot 派生合计字段
│   └── jk_bms_v2_1.py         # 完整单体扫描与合计计算
├── data/
│   ├── state_store.py         # 保存最近完整合计
│   └── pipeline.py            # 追加 CellVoltSum 波形点
└── gui/
    ├── widgets.py             # 波形名称、单位与指标详情文本
    ├── bms_dashboard.py       # 地址、总压括号、BATT_ST2 卡片
    ├── main_window.py         # 默认总览别名
    ├── controller.py          # 可缓冲派生波形信号
    └── demo.py                # 演示 BATT_ST2 数据

tests/
├── test_cell_voltage_assembly.py
├── test_multi_bms_pipeline.py
├── test_bms_dashboard.py
├── test_multi_bms_waveform.py
└── test_gui_window.py
```

## 实现步骤

### Phase 1：协议与派生快照

1. 扩展 `CellVoltageAssembler`，识别完整扫描并发布稳定合计。
2. 扩展 `BmsSnapshot` 和 `BmsStateStore`，保存合计值与电芯数。
3. 验证零填充数量、整组数量、复位和连续周期更新。

完成条件：不完整扫描不发布值；完整 16 节扫描得到正确合计；第二轮变化能稳定更新。

### Phase 2：多 BMS 波形与地址

1. `DataPipeline` 在完整扫描版本变化时追加 `CellVoltSum`。
2. 波形列表增加名称和单位。
3. 验证 5 台 BMS 交错输入时地址、快照和曲线互不串台。
4. 总览页显示由 CAN ID 解析得到的设备地址。

完成条件：每台 BMS 只有自己的合计曲线，地址与标签页一致。

### Phase 3：BATT_ST2 与总览布局

1. 总压卡片增加括号内单体合计文本。
2. 新增 BATT_ST2 四项指标卡片。
3. 演示源加入四项数据。
4. 在 1024x680 和 1440x900 检查指标区、表格和告警区无重叠或截断。

完成条件：真实数据、演示数据和回放数据均能显示四项 BATT_ST2 信息；合计值未完成时界面保持 `--`/隐藏详情，不显示部分和。

### Phase 4：回归与版本控制

1. 运行定向测试和全量 pytest，继续禁用 `.pytest_cache`。
2. 验证原始帧记录行数和 schema v2 不变。
3. 验证 SQLite 回放可重新生成地址、BATT_ST2 和 `CellVoltSum`。
4. 检查工作区差异，得到授权后创建本地提交并推送 `feature/multi-bms-v1`。

## 验证方法

```powershell
python -m pytest -p no:cacheprovider --basetemp=pytest-tmp-v11
```

- 16 节均为 3300 mV 时，完整扫描合计为 `52.800 V`。
- 第一轮只到 4/8/12 节时不得发布部分合计波形。
- 两台或五台 BMS 交错发送时，地址、单体值和合计曲线不得串台。
- 总压卡同时显示 BMS 总压和括号内单体合计，括号值固定 3 位小数。
- BATT_ST2 示例应显示 `30 Ah / 40 Ah / 100 Ah / 100 次`。
- 原始 SQLite 回放结果与实时计算结果一致，不新增派生存储表。
- 项目根目录不产生 `.pytest_cache`，测试临时目录在结束后清理。

## 暂缓内容

- Ah 积分和本次充入/放出容量。
- 满端、空端、过压和欠压边界状态机。
- 容量区间记录、派生数据表和 schema v3。
- 读取或下发 BMS 保护参数。

这些内容不进入 v1.1，后续单独评估并建立新版本计划。
