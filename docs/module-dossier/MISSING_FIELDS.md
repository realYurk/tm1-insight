# Module Dossier P0 — 缺失字段台账

本台账逐项说明：档案里的某个字段**为什么可能为空或缺失**、当前会输出什么、需要补采什么、补采后能变成什么状态。
原则：缺失保留为缺失，不静默补值，不用变量名或对象名猜来源。

状态词表：

| 状态 | 含义 |
| --- | --- |
| `RECORDED` | 已有采集记录且与当前源码哈希一致 |
| `STATIC_INFERENCE` | 由已记录结构按明确规则推导（如源列 → 维度） |
| `UNKNOWN` | 关键结构无法确认，附原因 |
| `NOT_APPLICABLE` | 该对象本就不适用（如无数据源的 TI 没有行变量） |

## 1. 数据来源

| 字段 | 状态 | 缺失原因 | 当前输出 | 补采方式 | 补采后 |
| --- | --- | --- | --- | --- | --- |
| `datasource.declared_type` | `UNKNOWN` / `NONE` | Prolog 中无 `DataSourceType` 赋值，或赋值来自动态表达式 | `UNKNOWN` + 原因；无赋值时明确写「未声明」 | 无需采集；核对源码 Prolog | 仍为 `UNKNOWN`（动态）或 `NONE`（确实无源） |
| `datasource.cube/view` | `UNKNOWN` | 数据源由参数/条件动态设置，或元数据未采集 | 空 + `SOURCE_BINDING_UNKNOWN` | `collect-process-metadata` | `STATIC_BINDING` ↔ 可绑定 NativeView |
| `variables` | 空 | 旧快照无 `process_source_metadata` 表 | 空表 + `MISSING_VARIABLE_METADATA` / `VARIABLE_BINDING_MISSING` | `collect-process-metadata --process <TI>` | 名称/类型/位置/字节 |
| `variables[].source_dimension` | `null` | 非 NativeView、MDX 视图、视图被本 TI 重建、Cube 维度顺序不匹配、多值列 | 保留名称与列位置，来源字段为「未确认」 | 采集该 TI 的 View 身份 + 源 Cube 完整维度顺序 | `STATIC_NATIVE_LAYOUT` |
| `row_context.membership_status` | `UNKNOWN` | Subset 成员、MDX、隐式切片器未求值 | 明确写 `UNKNOWN` + 说明 | 需运行或解析视图成员（本轮不做） | 仍为 `UNKNOWN` |
| `parameters[].type/default` | 名称可用、类型缺失 | 未采集参数定义，或元数据哈希不一致 | 只列参数名 + `PARAMETER_TYPE_NOT_COLLECTED` | `collect-process-metadata` | `RECORDED` |
| 外部数据源字段 | 空 | ODBC/CSV 只确认类型，未解析 SQL/路径/字段 | `EXTERNAL_SOURCE_FIELDS_UNKNOWN` | 需单独采集数据源定义 | 字段级映射仍为 `UNKNOWN` |

## 2. 数据模型

| 字段 | 状态 | 缺失原因 | 当前输出 | 补采方式 |
| --- | --- | --- | --- | --- |
| `dimension_order` | `INCOMPLETE` | `cube_has_dimension` 行数与 `cubes.dimension_count` 不一致 | 明确 `INCOMPLETE` + 缺口 | 重新采集该 Cube 结构 |
| `dimensions[].element_count` | `UNKNOWN` | 维度未采集元素 | 空值 + 说明 | 采集维度 |
| `dimensions[].attributes` | `UNKNOWN` | `dimensions.attributes` 不是有效数组 | `UNKNOWN / null` | 重新采集维度属性 |
| `dimensions[].hierarchies` | `NOT_COLLECTED` | 旧快照无 `dimension_metadata` 表 | 只写状态，不生成层级名 | 维度元数据采集 |
| `consolidation` | `UNKNOWN` | 未采集 `edges` 或权重记录非法/超长 | `UNKNOWN / 权重未确认` | 采集汇总边 |
| 粒度（单维度唯一层级） | `ORDER_RECORDED_GRANULARITY_UNVERIFIED` | 只有一个元素清单，无法证明每个维度只有一层 | 明确写未验证 | 需要层级/权重与业务确认 |

## 3. 逐步转换

| 字段 | 状态 | 缺失原因 | 当前输出 |
| --- | --- | --- | --- |
| `sequence` | 有界 | 单 TI 超过源码预算（250k 字符）或节点预算（5000） | 该 TI 只报解析器诊断，不生成步骤 |
| 未被引用的读取 | 缺失 | 既有分析器会裁剪「未被写入/调用引用」的节点 | 不补造；§3 注明「未被后续引用的读取不计入」 |
| `conditions` | `UNKNOWN`（结构可见） | 条件分支不求值；字符串常量按既有契约脱敏 | 表达式结构 + `CONDITION_NOT_EVALUATED` |
| 跨 TI 顺序 | `UNKNOWN` | 静态源码不能证明运行顺序 | 只按静态调用深度排序并声明 |

## 4. 目标结果

| 字段 | 状态 | 缺失原因 | 当前输出 |
| --- | --- | --- | --- |
| `coordinates[].binding_kind` = `UNRESOLVED` | `UNKNOWN` | 坐标由不支持的函数（如 `AttrS`）、动态表达式或未确认成员决定 | `Department=动态坐标（待确认）` + 缺口 |
| 固定成员 | `OBSERVED` | 仅当成员在维度目录中存在 | 显示成员原文；否则退回 `UNRESOLVED` |
| `field_mapping` | 空 | 无 Variables、行布局不成立、或坐标为查找值而非行变量 | 空表 + 说明，不做位置猜测 |
| `mode` | `UNKNOWN` | 写入函数不在 `CellPutN/S`、`CellIncrementN` | `UNKNOWN / 未支持或未分类` |
| 清空目标 | `PARAMETER_DRIVEN_UNKNOWN` | `ViewZeroOut(pCube, pView)` 目标是参数 | 表格写「参数决定（未解析）」+ `CLEAR_TARGET_UNRESOLVED` |
| 实际写入次数 | `UNKNOWN` | 条件/循环未求值、重复执行未记录 | 不声明次数 |

## 5. Rule / Feeder

| 字段 | 状态 | 缺失原因 | 当前输出 |
| --- | --- | --- | --- |
| `area.coordinates[].dimension` | `null` | 裸成员（`['AMT']`）且无成员归属索引 | 保留原文，`dimension=null` + `AREA_MEMBER_OWNERSHIP_UNKNOWN` |
| `references[].cube_resolved` | `false` | `DB(pCube, …)` 动态 Cube 名 | 保留表达式，不生成依赖边 |
| `expression` 完整语义 | `PARTIAL` | 无完整表达式 AST/函数求值契约 | 保留表达式文本与结构，不声称可执行 |
| Rule 条数 | 截断 | 超过 `max_rules`（默认 40，上限 120） | `RULE_BUDGET` 诊断 |
| Feeder 目标 | `UNKNOWN` | 多目标/条件 Feeder 未完全支持 | 保留源/目标原文 + 状态 |

## 6. 执行调用

| 字段 | 状态 | 缺失原因 | 当前输出 |
| --- | --- | --- | --- |
| `callee` | `null` | `ExecuteProcess(pTarget)` 动态目标 | `动态目标待确认` + `DYNAMIC_CALL_TARGET` |
| 参数名/值 | 脱敏 | 既有解析契约：字符串常量与参数名不导出 | 按位置 `#1 #2 …` 显示 |
| 调度是否启用 | `UNKNOWN` | `chores` 表无运行状态 | 只报采集的步骤定义 |
| 被排除的调用目标 | 内容缺失 | 用户主动排除 | 调用事实保留 + `EXCLUDED_DEPENDENCY` |

## 7. 验证与运行

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 运行验证 | 恒为 0 | 本档案不执行 TI、不读单元格、不写 TM1 |
| 数值贡献 | `UNKNOWN` | 静态依赖 ≠ 运行时贡献 |
| 迁移等价 | `UNKNOWN` | 需要金标数据集与对账 |
| 证据条目 | 预算截断 | `max_evidence`（默认 4000，上限 20000）；超限写 `Diagnostics.json` |

## 8. 补采命令（只读）

```powershell
# 1. 只采选定 TI 的参数、Variables、数据源与 VIEW 身份（GET only）
tm1-insight collect-process-metadata --process "TI.Load.ExpenseBalance" --output "metadata-new.json"

# 2. 显式导入离线副本（不触碰原始快照）
tm1-insight import-process-metadata --bundle "metadata-new.json" --database "offline-copy.duckdb"

# 3. 重新生成档案
tm1-insight module-dossier --name "Expense 月结" --entry "Chore.MonthEndClose" `
  --target-cube "Expense Account Balance" --database "offline-copy.duckdb" --output ".\dossier"
```

补采失败时不要用变量名推断来源；档案会继续显示 `UNKNOWN` 与具体原因。
