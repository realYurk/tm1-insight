# 模块档案 · Expense Account Balance 月度结转

> 入口：流程 `Chore.MonthEndClose` ｜ 目标 Cube：Expense Account Balance ｜ 分析日期：2026-10-31 ｜ 契约：module-dossier-1

本档案是**静态源码与已采集模型事实**的说明，不是运行记录。未执行 TM1、未读取单元格、未证明数值贡献或迁移等价。

## 0. 一页摘要

- 覆盖：流程 4 / 4 个，Cube 结构 2 个，写入点 2 处，Rule 2 条，Feeder 1 条。
- 未确认事项：22 项（见第 7 节与 Questions.md）。运行验证：0 项。
- 已确认的数据来源 Cube：General Ledger。
- 已确认的写入目标：Expense Account Balance。
- 人工说明：用户说明：月结时把总账里的费用科目汇总到费用余额表；未验证。

> 人工说明属于 USER_ANNOTATION，与源码事实分开记录，不作为证据。

## 1. 数据来源

每行是一个流程的真实声明或记录，**声明不等于值流**。变量位置是源列序号，不是维度序号。

### Chore.MonthEndClose

- 数据源：**未记录**（源码无 `DataSourceType` 赋值，快照也无数据源属性）。
- 参数（仅名称，类型未采集）：pOptionalStep

### TI.Load.ExpenseBalance

- 数据源类型：**VIEW**（状态 STATIC_BINDING）
- 绑定来源：Cube `General Ledger` ｜ View `ExpenseInput` ｜ 行布局 NATIVE_CELL_ROW ｜ 行集合 UNKNOWN
- 源码位置：prolog:1:1；prolog:2:1；prolog:3:1
- 说明：数据源声明不证明数据行值进入目标单元格

| 行变量 | 类型 | 源列 | 来源字段 | 状态 | 证据 |
|---|---|---|---|---|---|
| vAccount | String | 1 | 维度 Account | STATIC_NATIVE_LAYOUT | EV-0003 |
| vPeriod | String | 2 | 维度 Period | STATIC_NATIVE_LAYOUT | EV-0004 |
| vVersion | String | 3 | 维度 Version | STATIC_NATIVE_LAYOUT | EV-0005 |
| vMeasure | String | 4 | 维度 Measure | STATIC_NATIVE_LAYOUT | EV-0006 |
| vAmount | Numeric | 5 | 单元格值列 | STATIC_NATIVE_LAYOUT | EV-0007 |

- 参数：pSign（Numeric，默认 -1）；pPeriod（String，默认 Jan）

### TI.Report.ExpenseReview

- 数据源：**未记录**（源码无 `DataSourceType` 赋值，快照也无数据源属性）。
- 参数（仅名称，类型未采集）：vDept、vAccount、vPeriod

### }bedrock.synthetic.clear

- 数据源：**未记录**（源码无 `DataSourceType` 赋值，快照也无数据源属性）。
- 参数（仅名称，类型未采集）：pCube、pView

## 2. 数据模型

维度顺序即坐标粒度。层级、属性与权重只报采集状态，不推断汇总结果。

### Expense Account Balance（TARGET）

- 维度顺序（5）：Department → Account → Period → Version → Measure
- 顺序状态：RECORDED_COMPLETE ｜ 粒度状态：ORDER_RECORDED_GRANULARITY_UNVERIFIED
- 粒度说明：维度顺序定义坐标粒度；未采集层级/权重时不推断汇总结果，也不把 Cube 等同关系表。

| # | 维度 | 元素数 | 层级 | 属性 | 汇总边 | 证据 |
|---|---|---|---|---|---|---|
| 1 | Department | 3 | NOT_COLLECTED | recorded / 0 | recorded / 0 | EV-0011 |
| 2 | Account | 4 | Account、Account by Department | recorded / 1 | recorded / 3 | EV-0012 |
| 3 | Period | 3 | NOT_COLLECTED | recorded / 0 | recorded / 0 | EV-0013 |
| 4 | Version | 2 | NOT_COLLECTED | recorded / 0 | recorded / 0 | EV-0014 |
| 5 | Measure | 2 | NOT_COLLECTED | recorded / 0 | recorded / 0 | EV-0015 |

- Rule 作用区域：2 条（按区域见第 5 节）；区域定位：第 1 行、第 2 行
- 已知引用：Rule/Feeder 引用 General Ledger；被 TI 读取：TI.Report.ExpenseReview；被 TI 写入：TI.Load.ExpenseBalance

### General Ledger（SOURCE）

- 维度顺序（4）：Account → Period → Version → Measure
- 顺序状态：RECORDED_COMPLETE ｜ 粒度状态：ORDER_RECORDED_GRANULARITY_UNVERIFIED
- 粒度说明：维度顺序定义坐标粒度；未采集层级/权重时不推断汇总结果，也不把 Cube 等同关系表。

| # | 维度 | 元素数 | 层级 | 属性 | 汇总边 | 证据 |
|---|---|---|---|---|---|---|
| 1 | Account | 4 | Account、Account by Department | recorded / 1 | recorded / 3 | EV-0026 |
| 2 | Period | 3 | NOT_COLLECTED | recorded / 0 | recorded / 0 | EV-0027 |
| 3 | Version | 2 | NOT_COLLECTED | recorded / 0 | recorded / 0 | EV-0028 |
| 4 | Measure | 2 | NOT_COLLECTED | recorded / 0 | recorded / 0 | EV-0029 |

- Rule：本快照未记录 Rule 源码（`has_rules=false`，不等于该 Cube 一定没有 Rule）。
- 已知引用：被 TI 读取：TI.Load.ExpenseBalance

## 3. 逐步转换

步骤按静态调用深度排序，TI 内部按源码位置排序。**这不是运行顺序**，也不代表条件一定成立。

### STEP-01 · Chore.MonthEndClose

- 类型：APPLICATION ｜ 数据源：NONE ｜ 读：未观察到 ｜ 写：未观察到

源码位置顺序（不代表执行顺序）：

1. `prolog:1:1` 调用 }bedrock.synthetic.clear · EV-0031
2. `prolog:2:1` 调用 TI.Load.ExpenseBalance · EV-0032
3. `prolog:3:1` 调用 动态目标待确认 · EV-0033

### STEP-02 · TI.Load.ExpenseBalance

- 类型：APPLICATION ｜ 数据源：VIEW ｜ 读：General Ledger ｜ 写：Expense Account Balance

源码位置顺序（不代表执行顺序）：

1. `prolog:4:1` 准备成员子集：Account · EV-0054
2. `prolog:5:1` 准备成员子集：Account · EV-0055
3. `prolog:6:1` 准备成员子集：Account · EV-0056
4. `prolog:7:1` 准备视图与筛选：General Ledger · EV-0057
5. `data:4:3` 覆盖数值 → Expense Account Balance · EV-0058
6. `epilog:1:1` 累加数值 → Expense Account Balance · EV-0059

### STEP-03 · }bedrock.synthetic.clear

- 类型：TECHNICAL_NAMESPACE ｜ 数据源：NONE ｜ 读：未观察到 ｜ 写：未观察到

源码位置顺序（不代表执行顺序）：

1. `prolog:1:1` 清理数据：ViewZeroOut · EV-0061

### STEP-04 · TI.Report.ExpenseReview

- 类型：APPLICATION ｜ 数据源：NONE ｜ 读：未观察到 ｜ 写：未观察到

_该流程未观察到影响输出的读写动作（未被后续引用的读取不计入）。_

## 4. 目标结果

每处写入独立成项：写入模式、目标坐标、值表达式、字段映射与条件分开陈述。

> 表达式中的字符串常量由解析层统一脱敏为 `<常量>`；已在成员目录中确认的固定成员会直接出现在坐标表里。需要原值时按 Section/行号回到源码核对。

### 结果形成前的清空与准备

| 程序 | 类别 | 操作 | 目标 | 位置 | 证据 |
|---|---|---|---|---|---|
| }bedrock.synthetic.clear | 清理数据 | ViewZeroOut | 参数决定（未解析） | prolog:1:1 | EV-0068 |

> 清空/准备动作只证明源码中发生过该调用；目标 Cube 若由参数决定，则未确认实际清空范围。

### RES-001 · CellPutN → Expense Account Balance

- 写入模式：**OVERWRITE_NUMERIC**（覆盖数值）｜ 来源：data:4:3 ｜ 确认度：PARTIAL
- 值表达式：`nSigned`
- 值定义链：`nSigned = vAmount * pSign`
- 目标坐标：Department=动态坐标（待确认）；Account=vAccount（行变量）；Period=vPeriod（行变量）；Version=vVersion（行变量）；Measure=vMeasure（行变量）
- 条件（未求值）：`( vVersion @ = '<常量>' & vMeasure @ = '<常量>' )`

| 来源 Cube | 来源维度 | 源列 | 行变量 | 目标维度 | 依据 |
|---|---|---|---|---|---|
| General Ledger | Account | 1 | vAccount | Account | NATIVE_VIEW_LAYOUT_AND_RECORDED_CUBE_ORDER |
| General Ledger | Period | 2 | vPeriod | Period | NATIVE_VIEW_LAYOUT_AND_RECORDED_CUBE_ORDER |
| General Ledger | Version | 3 | vVersion | Version | NATIVE_VIEW_LAYOUT_AND_RECORDED_CUBE_ORDER |
| General Ledger | Measure | 4 | vMeasure | Measure | NATIVE_VIEW_LAYOUT_AND_RECORDED_CUBE_ORDER |
| General Ledger | （值列） | 5 | vAmount | 写入值 | ENDMOST_VALUE_COLUMN |

> 上表是**静态列布局对应**（NativeView 列 + 记录的维度顺序），不证明成员变换、汇总或实际行数。

- 行值依赖：vAmount（General Ledger）
- 未确认：函数 AttrS 的返回值语义未支持；不推导其值流
- 证据：EV-0047

### RES-002 · CellIncrementN → Expense Account Balance

- 写入模式：**INCREMENT_NUMERIC**（累加数值）｜ 来源：epilog:1:1 ｜ 确认度：COMPLETE
- 值表达式：`1`
- 目标坐标：Department=UNASSIGNED（固定）；Account=6200 Rent（固定）；Period=pPeriod（参数）；Version=ACTUAL（固定）；Measure=QTY（固定）
- 字段到目标坐标映射：无数据行来源（写入值为静态常量或表达式）
- 证据：EV-0053

## 5. Rule 与 Feeder

Rule 是声明式计算，**不是 TI 的物理写入**；Feeder 只声明稀疏支持关系，不产生业务数值。

### Rule

| 行 | 目标区域 | 条件 | 表达式 | 状态 | 引用 | 证据 |
|---|---|---|---|---|---|---|
| 1-1 | `[ 'AMT' ]` | N | `DB ( 'General Ledger' , ! Account , ! Period , ! Version , 'AMT' ) * pFactor` | PARTIAL | General Ledger | EV-0020 |
| 2-2 | `[ 'QTY' ]` | N | `DB ( pSourceCube , ! Account , ! Period , ! Version , 'QTY' )` | PARTIAL | pSourceCube（未解析） | EV-0022 |

Rule 未确认项：

- Expense Account Balance 第 1 行：AREA_MEMBER_OWNERSHIP_UNKNOWN: 裸成员/集合缺少成员归属索引；不能按 Cube 维度顺序推断
- Expense Account Balance 第 1 行：AREA_COORDINATE_UNCONFIRMED: 区域坐标仍有未确认项
- Expense Account Balance 第 1 行：EXPRESSION_SEMANTICS_NOT_RECONSTRUCTED: 仅保留表达式结构和引用，未还原完整计算语义
- Expense Account Balance 第 2 行：AREA_MEMBER_OWNERSHIP_UNKNOWN: 裸成员/集合缺少成员归属索引；不能按 Cube 维度顺序推断
- Expense Account Balance 第 2 行：AREA_COORDINATE_UNCONFIRMED: 区域坐标仍有未确认项
- Expense Account Balance 第 2 行：DB_CUBE_DYNAMIC: Cube 身份没有由字面量和目录共同确认

### Feeder（非数值流）

| 行 | 源区域 | 目标区域 | 状态 | 证据 |
|---|---|---|---|---|
| 4 | `[ 'AMT' ]` | `DB ( 'General Ledger' , ! Account , ! Period , ! Version , 'AMT' )` | UNKNOWN | EV-0024 |

## 6. 执行调用

调用关系不是数据流；参数值不执行，条件不求值。参数按其源码位置编号显示（参数名与字符串值沿用既有脱敏契约）。

| 调用方 | 被调用方 | 参数 | 条件 | 位置 | 证据 |
|---|---|---|---|---|---|
| Chore.MonthEndClose | }bedrock.synthetic.clear | `#1 '<常量>'；#2 '<常量>'` | `未观察到` | prolog:1:1 | EV-0064 |
| Chore.MonthEndClose | TI.Load.ExpenseBalance | `#1 '<常量>'` | `未观察到` | prolog:2:1 | EV-0065 |
| Chore.MonthEndClose | 动态目标待确认 | `无` | `未观察到` | prolog:3:1 | EV-0066 |

调度定义：Nightly Expense Close → Chore.MonthEndClose（步骤 0）

## 7. 验证缺口

每条缺口都说明「为什么不知道」和「需要补什么」，不静默补值。

| # | 对象 | 环节 | 代码 | 原因 | 影响 | 如何确认 |
|---|---|---|---|---|---|---|
| GAP-001 | Expense Account Balance | rules | RULE_PARTIAL | 第 1–1 行：AREA_MEMBER_OWNERSHIP_UNKNOWN: 裸成员/集合缺少成员归属索引；不能按 Cube 维度顺序推断 | 该条 Rule 的完整区域或表达式未确认 | 核对该行源码与成员索引 |
| GAP-002 | Expense Account Balance | rules | RULE_PARTIAL | 第 1–1 行：AREA_COORDINATE_UNCONFIRMED: 区域坐标仍有未确认项 | 该条 Rule 的完整区域或表达式未确认 | 核对该行源码与成员索引 |
| GAP-003 | Expense Account Balance | rules | RULE_PARTIAL | 第 1–1 行：EXPRESSION_SEMANTICS_NOT_RECONSTRUCTED: 仅保留表达式结构和引用，未还原完整计算语义 | 该条 Rule 的完整区域或表达式未确认 | 核对该行源码与成员索引 |
| GAP-004 | Expense Account Balance | rules | RULE_PARTIAL | 第 2–2 行：AREA_MEMBER_OWNERSHIP_UNKNOWN: 裸成员/集合缺少成员归属索引；不能按 Cube 维度顺序推断 | 该条 Rule 的完整区域或表达式未确认 | 核对该行源码与成员索引 |
| GAP-005 | Expense Account Balance | rules | RULE_PARTIAL | 第 2–2 行：AREA_COORDINATE_UNCONFIRMED: 区域坐标仍有未确认项 | 该条 Rule 的完整区域或表达式未确认 | 核对该行源码与成员索引 |
| GAP-006 | Expense Account Balance | rules | RULE_PARTIAL | 第 2–2 行：DB_CUBE_DYNAMIC: Cube 身份没有由字面量和目录共同确认 | 该条 Rule 的完整区域或表达式未确认 | 核对该行源码与成员索引 |
| GAP-007 | Expense Account Balance | rules | RULE_DYNAMIC_REFERENCE | Rule 引用了未解析的 Cube 名（动态表达式） | 跨 Cube 依赖与目标坐标不完整 | 确认该 DB() 参数的取值来源 |
| GAP-008 | Expense Account Balance | feeders | FEEDER_PARTIAL | 第 4 行：FEEDER_SOURCE_INCOMPLETE: 馈送源区域不完整 | Feeder 目标区域未完全确认 | 核对该行源码与区域成员 |
| GAP-009 | Expense Account Balance | feeders | FEEDER_PARTIAL | 第 4 行：AREA_MEMBER_OWNERSHIP_UNKNOWN: 裸成员/集合缺少成员归属索引；不能按 Cube 维度顺序推断 | Feeder 目标区域未完全确认 | 核对该行源码与区域成员 |
| GAP-010 | Expense Account Balance | feeders | FEEDER_PARTIAL | 第 4 行：AREA_COORDINATE_UNCONFIRMED: 区域坐标仍有未确认项 | Feeder 目标区域未完全确认 | 核对该行源码与区域成员 |
| GAP-011 | Expense Account Balance | feeders | FEEDER_PARTIAL | 第 4 行：FEEDER_AREA_UNKNOWN: 馈送源/目标关键结构未确认 | Feeder 目标区域未完全确认 | 核对该行源码与区域成员 |
| GAP-012 | General Ledger | rules | RULE_SOURCE_NOT_RECORDED | 本快照未记录该 Cube 的 Rule 源码（has_rules=false） | 不能据此断定该 Cube 没有 Rule；若存在 Rule，计算关系缺失 | 在源模型中确认该 Cube 是否有 Rule，并补采其源码 |
| GAP-013 | TI.Load.ExpenseBalance | target_results | COORDINATE_UNRESOLVED | 写入 CellPutN → Expense Account Balance 的目标坐标未完整确认（PARTIAL） | 实际写入的成员范围不确定 | 核对目标维度顺序、动态坐标与成员目录 |
| GAP-014 | TI.Load.ExpenseBalance | target_results | WRITE_VALUE_UNRESOLVED | 写入值或依赖未解析：函数 AttrS 的返回值语义未支持；不推导其值流 | 该写入点无法给出完整公式 | 核对该位置的变量定义链与来源字段 |
| GAP-015 | TI.Load.ExpenseBalance | target_results | CONDITION_NOT_EVALUATED | 写入受条件/循环控制但未求值：( vVersion @ = &#x27;&lt;常量&gt;&#x27; &amp; vMeasure @ = &#x27;&lt;常量&gt;&#x27; ) | 不能确认实际写入次数与哪一行会执行 | 用覆盖该条件的测试夹具验证可达性 |
| GAP-016 | Chore.MonthEndClose | data_sources | PARAMETER_TYPE_NOT_COLLECTED | 未采集该 Process 的参数定义；仅有参数名可用。 | 只能列出参数名，无法确认可接受取值范围 | 用 collect-process-metadata 补采该 TI 的参数定义 |
| GAP-017 | TI.Report.ExpenseReview | data_sources | PARAMETER_TYPE_NOT_COLLECTED | 未采集该 Process 的参数定义；仅有参数名可用。 | 只能列出参数名，无法确认可接受取值范围 | 用 collect-process-metadata 补采该 TI 的参数定义 |
| GAP-018 | }bedrock.synthetic.clear | data_sources | PARAMETER_TYPE_NOT_COLLECTED | 未采集该 Process 的参数定义；仅有参数名可用。 | 只能列出参数名，无法确认可接受取值范围 | 用 collect-process-metadata 补采该 TI 的参数定义 |
| GAP-019 | Chore.MonthEndClose | execution_calls | DYNAMIC_CALL_TARGET | 动态调用目标未确认：pOptionalStep | 被调用流程、参数契约与副作用未知 | 核对该位置的调用目标表达式与参数来源 |
| GAP-020 | }bedrock.synthetic.clear | target_results | CLEAR_TARGET_UNRESOLVED | 清空操作（ViewZeroOut）的目标由参数决定，未解析到具体 Cube | 不能确认目标 Cube 是否先被清空，也就不能推断结果是覆盖还是叠加 | 核对调用方传入了哪个 Cube 参数，或在授权环境记录清空前后范围 |
| GAP-021 | Expense Account Balance 月度结转 | verification | EXECUTION_ORDER_UNPROVEN | 跨独立 TI 的全局执行顺序、重复执行与清空范围未验证 | 不能据此推断最终数值、幂等性或覆盖结果 | 在授权测试环境按调用参数、清空成员范围与重复累加建立金标测试 |
| GAP-022 | Expense Account Balance 月度结转 | verification | RUNTIME_NOT_VERIFIED | 本档案为静态源码与采集模型事实，未执行 TM1 | 所有公式与映射都不是运行贡献或迁移等价证明 | 需要隔离环境的运行记录、数值对账与等价测试 |

## 8. 阅读边界与证据索引

### 事实分层

- **观察**：源码与已采集模型事实，带 EV 编号与 Section/行号。
- **静态推断**：仅源列→目标的列布局对应（标注 STATIC_INFERENCE）。
- **人工说明**：仅出现在模块摘要，不影响任何事实字段。
- **UNKNOWN**：第 7 节，不参与确定结论。
- **运行验证**：0 项。本档案没有执行证据。

### 证据索引（前 60 条，完整列表见 Evidence.json）

| 证据 | 类型 | 对象 | 定位 |
|---|---|---|---|
| EV-0001 | TI_DATASOURCE_DECLARATION | Chore.MonthEndClose | 模型表 processes |
| EV-0002 | TI_DATASOURCE_DECLARATION | TI.Load.ExpenseBalance | prolog:1:1 |
| EV-0003 | DATASOURCE_VARIABLE | TI.Load.ExpenseBalance | 列位置 1 |
| EV-0004 | DATASOURCE_VARIABLE | TI.Load.ExpenseBalance | 列位置 2 |
| EV-0005 | DATASOURCE_VARIABLE | TI.Load.ExpenseBalance | 列位置 3 |
| EV-0006 | DATASOURCE_VARIABLE | TI.Load.ExpenseBalance | 列位置 4 |
| EV-0007 | DATASOURCE_VARIABLE | TI.Load.ExpenseBalance | 列位置 5 |
| EV-0008 | TI_DATASOURCE_DECLARATION | TI.Report.ExpenseReview | 模型表 processes |
| EV-0009 | TI_DATASOURCE_DECLARATION | }bedrock.synthetic.clear | 模型表 processes |
| EV-0010 | CUBE_STRUCTURE | Expense Account Balance | 模型事实（无源码行） |
| EV-0011 | DIMENSION_METADATA | Department | Cube 内第 1 位 |
| EV-0012 | DIMENSION_METADATA | Account | Cube 内第 2 位 |
| EV-0013 | DIMENSION_METADATA | Period | Cube 内第 3 位 |
| EV-0014 | DIMENSION_METADATA | Version | Cube 内第 4 位 |
| EV-0015 | DIMENSION_METADATA | Measure | Cube 内第 5 位 |
| EV-0016 | RULE_INDEX_REFERENCE | Expense Account Balance | 模型事实（无源码行） |
| EV-0017 | CUBE_READER | Expense Account Balance | 模型事实（无源码行） |
| EV-0018 | CUBE_WRITER | Expense Account Balance | 模型事实（无源码行） |
| EV-0019 | RULE_REFERENCE | Expense Account Balance | rule 第 1 行 |
| EV-0020 | RULE_TARGET | Expense Account Balance | rule:1 |
| EV-0021 | RULE_REFERENCE | Expense Account Balance | rule 第 2 行 |
| EV-0022 | RULE_TARGET | Expense Account Balance | rule:2 |
| EV-0023 | FEEDER_REFERENCE | Expense Account Balance | rule 第 4 行 |
| EV-0024 | FEEDER | Expense Account Balance | rule:4 |
| EV-0025 | CUBE_STRUCTURE | General Ledger | 模型事实（无源码行） |
| EV-0026 | DIMENSION_METADATA | Account | Cube 内第 1 位 |
| EV-0027 | DIMENSION_METADATA | Period | Cube 内第 2 位 |
| EV-0028 | DIMENSION_METADATA | Version | Cube 内第 3 位 |
| EV-0029 | DIMENSION_METADATA | Measure | Cube 内第 4 位 |
| EV-0030 | CUBE_READER | General Ledger | 模型事实（无源码行） |
| EV-0031 | TI_SOURCE_ACTION | Chore.MonthEndClose | prolog:1 |
| EV-0032 | TI_SOURCE_ACTION | Chore.MonthEndClose | prolog:2 |
| EV-0033 | TI_SOURCE_ACTION | Chore.MonthEndClose | prolog:3 |
| EV-0034 | TRANSFORMATION_STEP | Chore.MonthEndClose | 模型事实（无源码行） |
| EV-0035 | WRITE_COORDINATE | TI.Load.ExpenseBalance | data:4:3 |
| EV-0036 | WRITE_COORDINATE | TI.Load.ExpenseBalance | data:4:3 |
| EV-0037 | WRITE_COORDINATE | TI.Load.ExpenseBalance | data:4:3 |
| EV-0038 | WRITE_COORDINATE | TI.Load.ExpenseBalance | data:4:3 |
| EV-0039 | WRITE_COORDINATE | TI.Load.ExpenseBalance | data:4:3 |
| EV-0040 | FIELD_TO_COORDINATE | TI.Load.ExpenseBalance | 模型事实（无源码行） |
| EV-0041 | FIELD_TO_COORDINATE | TI.Load.ExpenseBalance | 模型事实（无源码行） |
| EV-0042 | FIELD_TO_COORDINATE | TI.Load.ExpenseBalance | 模型事实（无源码行） |
| EV-0043 | FIELD_TO_COORDINATE | TI.Load.ExpenseBalance | 模型事实（无源码行） |
| EV-0044 | VALUE_FIELD_TO_WRITE | TI.Load.ExpenseBalance | 模型事实（无源码行） |
| EV-0045 | WRITE_CONDITION | TI.Load.ExpenseBalance | data:2 |
| EV-0046 | VALUE_DEFINITION | TI.Load.ExpenseBalance | data:3:3 |
| EV-0047 | TI_WRITE | TI.Load.ExpenseBalance | data:4 |
| EV-0048 | WRITE_COORDINATE | TI.Load.ExpenseBalance | epilog:1:1 |
| EV-0049 | WRITE_COORDINATE | TI.Load.ExpenseBalance | epilog:1:1 |
| EV-0050 | WRITE_COORDINATE | TI.Load.ExpenseBalance | epilog:1:1 |
| EV-0051 | WRITE_COORDINATE | TI.Load.ExpenseBalance | epilog:1:1 |
| EV-0052 | WRITE_COORDINATE | TI.Load.ExpenseBalance | epilog:1:1 |
| EV-0053 | TI_WRITE | TI.Load.ExpenseBalance | epilog:1 |
| EV-0054 | TI_SOURCE_ACTION | TI.Load.ExpenseBalance | prolog:4 |
| EV-0055 | TI_SOURCE_ACTION | TI.Load.ExpenseBalance | prolog:5 |
| EV-0056 | TI_SOURCE_ACTION | TI.Load.ExpenseBalance | prolog:6 |
| EV-0057 | TI_SOURCE_ACTION | TI.Load.ExpenseBalance | prolog:7 |
| EV-0058 | TI_SOURCE_ACTION | TI.Load.ExpenseBalance | data:4 |
| EV-0059 | TI_SOURCE_ACTION | TI.Load.ExpenseBalance | epilog:1 |
| EV-0060 | TRANSFORMATION_STEP | TI.Load.ExpenseBalance | 模型事实（无源码行） |

_其余 8 条证据见 Evidence.json。_

### 已知限制

- 步骤顺序为 TI 内源码位置顺序；跨 TI 的顺序只是静态调用深度，不是运行顺序。
- 同名维度不证明同粒度；目标新增维度不证明自动汇总。
- Rule 是声明式计算，不是 TI 的物理写入；Feeder 不是数值流。
- 行集合（Subset/MDX/隐式切片器）、参数实际值与覆盖/累加次数未求值。
- 表达式中的字符串常量沿用既有解析契约，统一显示为 &lt;常量&gt;；目标成员只在成员目录确认后展示。
- 未被写入或调用引用的读取可能已被既有分析器裁剪，本档案不补造该动作。

模块 ID：`623a1df78eed8d9fa81d2fe8c9bf2a355c1167c51475e2712a24ba4e6c3dea25` ｜ Snapshot：synthetic-expense-module
