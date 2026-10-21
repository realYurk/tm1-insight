# BLUEPRINT_PORTABILITY — 跨项目角色绑定

> 目标：一次设计，换一家公司、换一套维度名，仍然能用。
> 做法：**角色 + 绑定 + 重新生成**，不是字符串替换。

## 1. 两层结构

| 层 | 存在哪 | 例子 |
|---|---|---|
| Project Instance | `assets/projects/*.json` + 工作区 | `SalesVolume`、`Product`、`RetailSales.csv` |
| Reusable Blueprint | `assets/blueprints/*.json` | `dim_5 = 产品维度`、`member_1 = 场景固定成员` |

Blueprint 只保存**角色**、维度顺序、取值方式、模板与策略；具体名称在绑定阶段填入。

## 2. 角色模型

```json
{"id": "dim_5", "label": "Vehicle", "kind": "dimension", "required": true,
 "hint": "第 5 个目标维度（顺序固定）", "default": ""}
```

- `id` 稳定（`dim_1..n` 按顺序），不随项目变化；
- `label` 是提炼时的原始名称，仅作提示；
- `kind` 决定绑定值的用途：`cube / dimension / field / member / value`。

## 3. 映射模型

```json
{"dim_role": "dim_5", "kind": "FROM_SOURCE", "source_role": "field_5", "confirmed": true}
```

- `kind`：`FIXED / FROM_SOURCE / EXPRESSION`；
- `source_role` 指向承担具体值的角色（固定成员、来源字段、表达式）；
- 实例化时按 `dim_role` 的顺序生成目标维度与赋值语句。

## 4. 绑定校验（实例化前）

| 检查 | 结果 |
|---|---|
| 必需角色缺失或为空 | 拒绝 |
| 绑定值含换行 | 拒绝 |
| 两个维度角色绑定同名 | 拒绝（维度名重复） |
| 映射来源角色未绑定 | 拒绝 |
| 表达式角色不在安全子集 | 拒绝 |
| 未知角色 | 拒绝（防止拼错） |

拒绝时返回具体角色与原因，不静默忽略。

## 5. 实例化语义

`instantiate(blueprint, bindings, project_name)` 产出：

1. `CubeDraft`：名称 = `target_cube` 绑定；维度 = 按 `dimension_order` 的绑定值；
2. `CsvSchema`：名称 = `source_name` 绑定（缺省为项目名 + `.csv`）；字段 = 被引用的来源字段 + 数值字段；
3. `DesignRelation`：映射按 `dim_role` 顺序生成，值来自对应角色绑定；模板、写入策略、清空策略沿用 Blueprint；
4. `ProjectInstance`：保存绑定、设计快照、工作区 id、状态。

**为什么不是字符串替换**：替换只能在"名字已知且结构相同"时工作；一旦维度顺序变化、某个维度从固定改成来源、或多/少一个维度，替换就会生成结构错误的代码。角色绑定在结构层面重建，因此能处理顺序调换与维度增减。

## 6. 验收：同一 Blueprint 两个项目

| 项 | 项目 A | 项目 B |
|---|---|---|
| 来源 | `VehicleProduction.csv` | `RetailSales.csv` |
| 字段 | VehicleCode / Plant / Period / Quantity | SKU / ChannelCode / SalesPeriod / SalesQuantity |
| 目标 Cube | `VehicleVolume` | `SalesVolume` |
| 维度 | Scenario / Version / Year / Month / **Vehicle / Plant** / Measure | Scenario / Version / Year / Month / **Product / Channel** / Measure |
| 固定成员 | Forecast / Working / 2026 | Budget / Final / 2027 |
| 生成维度顺序 | 含 Vehicle、Plant | 含 Product、Channel |
| 代码指纹 | 不同 | 不同 |

关键断言（`tests/test_cross_project_reuse.py`）：

- B 的代码包含 `SalesVolume`、`RetailSales.csv`、`vProduct = vSKU;`、`vChannel = vChannelCode;`；
- B 的代码**不包含** A 的 `VehicleVolume`、`VehicleCode`、`VehicleProduction`、`Plant`、`'Forecast'`；
- 交换两个维度角色的绑定后，生成的赋值顺序随之改变（证明按角色而非按位置写死）。

## 7. 跨 Snapshot 的边界

- 项目实例记录 `snapshot_id`；在工作区打开时按现有规则做身份校验。
- Blueprint 本身**不绑定快照**，因此可以跨快照复用。
- 但**不会自动重绑**：新项目的维度必须由用户逐个确认，系统不做同名推断。

## 8. 未支持

| 能力 | 现状 |
|---|---|
| 一对多 / 多对一 / 聚合映射 | 不支持；绑定阶段无法表达，生成会被阻断 |
| `LOOKUP` / `FROM_CONTEXT` 坐标 | 不支持生成，只能保存意图 |
| 参数化占位符（`{ProductDimension}`） | 未实现，角色即参数 |
| 自动识别人工语义（把 Plant 识别为"工厂"） | 不做，避免臆测业务含义 |
| 维度增减后自动适配 | 需重新绑定；Blueprint 的维度槽位固定 |
