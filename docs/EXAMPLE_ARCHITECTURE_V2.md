# 模块架构说明

## 1. 模块概览

入口 TI：**Load**

仅沿已确认向前调用展开业务 TI；直接辅助源码保留效果，默认停止辅助内部调用扩展。Rule 消费者在边界外，Chore 仅按核心 TI / 已验证入口 Caller 关联。

核心 Cube：Cube_A、Cube_B。

读取对象：Cube_A。

写入对象：Cube_B。

本报告为静态源码与模型事实，不证明运行结果。逐项证据见 Architecture.json 对应摘要的 evidence_refs 和 Evidence.json；原始诊断见 Diagnostics.json。

## 2. 数据模型

- **Cube_A**（2 维）：Year、Product。维度顺序完整。
- **Cube_B**（3 维）：Year、Region、Measure。维度顺序完整。

源 / 目标结构比较（不证明成员映射或数据传输）：

- Cube_A / Cube_B：共享 Year；仅源端 Product；仅目标端 Region、Measure。

同名维度不证明同粒度；目标新增维度不代表自动汇总。指标维和成员映射仍需坐标/属性证据。

## 3. 数据加工流程

### Load

该 TI 读取 Cube_A，并写入 Cube_B；仅下列已还原表达式支持对应值依赖，其余读写关联不证明数据传输。

- VIEW 记录来源：Cube_A；视图 未确认。成员筛选和行变量值流仍需核对。
- 显式读取 1 处，写入 2 处（CellPutN × 2）。
- 准备视图与筛选：Cube_A（2 处观察；各条件分组在 JSON 独立保留）。
- 准备成员子集：Product（2 处观察；各条件分组在 JSON 独立保留）。
- 清理数据：Cube_B（1 处观察；各条件分组在 JSON 独立保留）。
- 已还原表达式：`Cube_B[Year=vYear,Region=pRegion,Measure=pMeasure] = (Cube_A[Year=vYear,Product=vProduct] * 2)`
- 1 个写入点的公式/坐标或条件尚未完整解析；位置：data:1。各写入点在 JSON 独立保留。
- 待追溯的变量 / 表达式：表达式；需核对 Data Source 字段、赋值或属性查询定义。

### BusinessChild

该 TI 未观察到直接 Cube 读写；已确认调用：Load。动态调用及实现边界另行保留。

- 显式读取 0 处，写入 0 处（无已记录项）。

## 4. 执行与调度

- Load → BusinessChild。
- Load → 动态调用目标待确认。
- BusinessChild → Load。
- Caller → Load。
- Chore Nightly → Caller，离线步骤 0；未验证启用或实际运行。

通用辅助调用默认折叠；实际读取、写入、清理效果保留于加工摘要。源码调用位置不保证运行完成顺序。

## 5. Rule 与计算关系

- Cube_B Rule 引用 Cube_A：600 处。
- Cube_B Feeder 引用 Cube_A：1 处。

Feeder 属于稀疏计算支持关系，不直接产生业务数据值。外部规则消费者只列为边界依赖，不成为核心计算。

## 6. 模块边界与迁移关注点

- 外部 / 技术 Cube：Journal。
- 下游规则索引候选 1 条；默认不读取其内部规则或纳入 CORE，目录候选不等于源码确认。
- 核对 VIEW/Subset 的实际成员和 Data 行变量，再验证记录来源到写入值的映射。
- 分别核对覆盖、累加及清理切面；静态源码不能证明本次执行路径或执行顺序。
- 核对未解析的调用目标与边界外辅助调用；完整诊断保存在 Diagnostics.json。
- 维度顺序定义多维坐标粒度，不自动假定一个 Cube 对应一张关系表。
- 需验证层级权重、汇总、Rule/Feeder、稀疏、零值/空值、清理切面、覆盖/累加与运行顺序。
- 静态表达式依赖不是运行时贡献；本结果未执行 TM1，也未验证迁移等价。
- Load：外部文件/SQL 数据源、视图实际成员、独立层级及运行结果尚未完整还原。

Java 重构需保留维度顺序、各写入点的坐标/条件/覆盖或累加契约、调用参数和 Rule/Feeder 边界；尚无等价运行证据，不能据此宣称迁移完成。
