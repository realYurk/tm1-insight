# 模块架构说明

## 1. 模块概览

入口 Cube：**Cube_B**

仅沿已确认向前调用展开业务 TI；直接辅助源码保留效果，默认停止辅助内部调用扩展。Rule 消费者在边界外，Chore 仅按核心 TI / 已验证入口 Caller 关联。

核心 Cube：Cube_B、Cube_A。

读取对象：Cube_A。

写入对象：Cube_B。

本报告为静态源码与模型事实，不证明运行结果。逐项证据见 Architecture.json 对应摘要的 evidence_refs 和 Evidence.json；原始诊断见 Diagnostics.json。

## 2. 数据模型

- **Cube_B**（2 维）：Product、Scenario。维度顺序完整。
- **Cube_A**（2 维）：Scenario、Product。维度顺序完整。
- Dimension Product：已采集层级 元数据未采集；直接汇总边 1 条。原始权重按需分页核对，不推断运行时汇总结果。
- Dimension Scenario：已采集层级 元数据未采集；直接汇总边 未采集。原始权重按需分页核对，不推断运行时汇总结果。

源 / 目标结构比较（不证明成员映射或数据传输）：

- Cube_A / Cube_B：共享 Scenario、Product；仅源端 无已记录项；仅目标端 无已记录项。

同名维度不证明同粒度；目标新增维度不代表自动汇总。指标维和成员映射仍需坐标/属性证据。

## 3. 数据加工流程

### Load

该 TI 读取 Cube_A，并写入 Cube_B；仅下列已还原表达式支持对应值依赖，其余读写关联不证明数据传输。

- Cube_A：写入值表达式依赖（1 处）。
- 显式读取 1 处，写入 1 处（CellPutN × 1）。
- 已还原表达式：`Cube_B[Product=pProduct,Scenario='ACT'] = (Cube_A[Scenario='ACT',Product=pProduct] * 2)`
- 写入 **Cube_B**：1 个独立写入点。
  - 公共目标坐标：Product = pProduct（参数）；Scenario = 'ACT'（固定成员）。
  - data:1:41 · 覆盖 · 值表达式 `n * 2`。
    - 已还原静态表达式：`Cube_B[Product=pProduct,Scenario='ACT'] = (Cube_A[Scenario='ACT',Product=pProduct] * 2)`。
    - 坐标表达式对应：Cube_A.Scenario / Cube_B.Scenario 使用 `'ACT'`；不据此证明汇总或成员变换。
    - 坐标表达式对应：Cube_A.Product / Cube_B.Product 使用 `pProduct`；不据此证明汇总或成员变换。

## 4. 执行与调度

- Caller → Load。
- Chore Nightly → Caller，离线步骤 0；未验证启用或实际运行。

通用辅助调用默认折叠；实际读取、写入、清理效果保留于加工摘要。源码调用位置不保证运行完成顺序。

## 5. Rule 与计算关系

- Cube_B Rule 引用 Cube_A：1 处。
- Cube_B Feeder 引用 Cube_A：1 处。

Feeder 属于稀疏计算支持关系，不直接产生业务数据值。外部规则消费者只列为边界依赖，不成为核心计算。

## 6. 模块边界与迁移关注点

- 外部 / 技术 Cube：无已记录项。
- 边界外消费者记录 1 条；仅按标明的源码读取或目录候选理解，不扩展为其他核心模块。
- 核对 Data Source Variables/字段定义：未采集时，vValue 等 Data 输入不能绑定为某个 VIEW 单元格值。
- 核对各写入点的固定成员、运行时坐标、条件及累加/覆盖；动态 Subset/MDX 未求值。
- Rule/Feeder 与层级权重仅保留源码/结构事实；执行路径、最终金额和迁移等价仍需隔离运行验证。
- 维度顺序定义多维坐标粒度，不自动假定一个 Cube 对应一张关系表。
- 需验证层级权重、汇总、Rule/Feeder、稀疏、零值/空值、清理切面、覆盖/累加与运行顺序。
- 静态表达式依赖不是运行时贡献；本结果未执行 TM1，也未验证迁移等价。
- Cube_B：外部文件/SQL 数据源、视图实际成员、独立层级及运行结果尚未完整还原。

Java 重构需保留维度顺序、各写入点的坐标/条件/覆盖或累加契约、调用参数和 Rule/Feeder 边界；尚无等价运行证据，不能据此宣称迁移完成。
