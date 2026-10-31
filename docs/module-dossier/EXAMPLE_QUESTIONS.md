# 待确认问题 · Expense Account Balance 月度结转

以下问题全部来自档案中的缺口项。每项说明「要确认什么」和「为什么现在不能确定」。
回答这些问题不会自动改写事实；请把结论作为人工标注另行保存。

_同一对象上的同一原因已合并：20 组问题覆盖 22 处缺口，逐条位置见 Module.json。_

## 数据来源与字段

### GAP-014 · Chore.MonthEndClose

- 现象：未采集该 Process 的参数定义；仅有参数名可用。
- 影响：只能列出参数名，无法确认可接受取值范围
- 需要：用 collect-process-metadata 补采该 TI 的参数定义
- 证据：EV-0001

### GAP-015 · TI.Report.ExpenseReview

- 现象：未采集该 Process 的参数定义；仅有参数名可用。
- 影响：只能列出参数名，无法确认可接受取值范围
- 需要：用 collect-process-metadata 补采该 TI 的参数定义
- 证据：EV-0008

### GAP-016 · }bedrock.synthetic.clear

- 现象：未采集该 Process 的参数定义；仅有参数名可用。
- 影响：只能列出参数名，无法确认可接受取值范围
- 需要：用 collect-process-metadata 补采该 TI 的参数定义
- 证据：EV-0009

## 目标结果与坐标

### GAP-011 · TI.Load.ExpenseBalance

- 现象：写入 CellPutN → Expense Account Balance 的目标坐标未完整确认（PARTIAL）
- 影响：实际写入的成员范围不确定
- 需要：核对目标维度顺序、动态坐标与成员目录
- 证据：EV-0047

### GAP-012 · TI.Load.ExpenseBalance

- 现象：写入值或依赖未解析：函数 AttrS 的返回值语义未支持；不推导其值流
- 影响：该写入点无法给出完整公式
- 需要：核对该位置的变量定义链与来源字段
- 证据：EV-0047

### GAP-013 · TI.Load.ExpenseBalance

- 现象：写入受条件/循环控制但未求值：( vVersion @ = '<常量>' & vMeasure @ = '<常量>' )
- 影响：不能确认实际写入次数与哪一行会执行
- 需要：用覆盖该条件的测试夹具验证可达性
- 证据：EV-0047

### GAP-018 · }bedrock.synthetic.clear

- 现象：清空操作（ViewZeroOut）的目标由参数决定，未解析到具体 Cube
- 影响：不能确认目标 Cube 是否先被清空，也就不能推断结果是覆盖还是叠加
- 需要：核对调用方传入了哪个 Cube 参数，或在授权环境记录清空前后范围
- 证据：EV-0068

## Rule 计算

### GAP-001 · Expense Account Balance · 第 1–1 行、第 2–2 行

- 现象：AREA_MEMBER_OWNERSHIP_UNKNOWN: 裸成员/集合缺少成员归属索引；不能按 Cube 维度顺序推断
- 影响：该条 Rule 的完整区域或表达式未确认
- 需要：核对该行源码与成员索引
- 证据：EV-0020 EV-0022

### GAP-002 · Expense Account Balance · 第 1–1 行、第 2–2 行

- 现象：AREA_COORDINATE_UNCONFIRMED: 区域坐标仍有未确认项
- 影响：该条 Rule 的完整区域或表达式未确认
- 需要：核对该行源码与成员索引
- 证据：EV-0020 EV-0022

### GAP-003 · Expense Account Balance · 第 1–1 行

- 现象：EXPRESSION_SEMANTICS_NOT_RECONSTRUCTED: 仅保留表达式结构和引用，未还原完整计算语义
- 影响：该条 Rule 的完整区域或表达式未确认
- 需要：核对该行源码与成员索引
- 证据：EV-0020

### GAP-004 · Expense Account Balance · 第 2–2 行

- 现象：DB_CUBE_DYNAMIC: Cube 身份没有由字面量和目录共同确认
- 影响：该条 Rule 的完整区域或表达式未确认
- 需要：核对该行源码与成员索引
- 证据：EV-0022

### GAP-005 · Expense Account Balance

- 现象：Rule 引用了未解析的 Cube 名（动态表达式）
- 影响：跨 Cube 依赖与目标坐标不完整
- 需要：确认该 DB() 参数的取值来源
- 证据：EV-0022

### GAP-010 · General Ledger

- 现象：本快照未记录该 Cube 的 Rule 源码（has_rules=false）
- 影响：不能据此断定该 Cube 没有 Rule；若存在 Rule，计算关系缺失
- 需要：在源模型中确认该 Cube 是否有 Rule，并补采其源码
- 证据：EV-0025

## Feeder 支持

### GAP-006 · Expense Account Balance · 第 4 行

- 现象：FEEDER_SOURCE_INCOMPLETE: 馈送源区域不完整
- 影响：Feeder 目标区域未完全确认
- 需要：核对该行源码与区域成员
- 证据：EV-0024

### GAP-007 · Expense Account Balance · 第 4 行

- 现象：AREA_MEMBER_OWNERSHIP_UNKNOWN: 裸成员/集合缺少成员归属索引；不能按 Cube 维度顺序推断
- 影响：Feeder 目标区域未完全确认
- 需要：核对该行源码与区域成员
- 证据：EV-0024

### GAP-008 · Expense Account Balance · 第 4 行

- 现象：AREA_COORDINATE_UNCONFIRMED: 区域坐标仍有未确认项
- 影响：Feeder 目标区域未完全确认
- 需要：核对该行源码与区域成员
- 证据：EV-0024

### GAP-009 · Expense Account Balance · 第 4 行

- 现象：FEEDER_AREA_UNKNOWN: 馈送源/目标关键结构未确认
- 影响：Feeder 目标区域未完全确认
- 需要：核对该行源码与区域成员
- 证据：EV-0024

## 执行调用

### GAP-017 · Chore.MonthEndClose

- 现象：动态调用目标未确认：pOptionalStep
- 影响：被调用流程、参数契约与副作用未知
- 需要：核对该位置的调用目标表达式与参数来源
- 证据：EV-0066

## 验证与运行

### GAP-019 · Expense Account Balance 月度结转

- 现象：跨独立 TI 的全局执行顺序、重复执行与清空范围未验证
- 影响：不能据此推断最终数值、幂等性或覆盖结果
- 需要：在授权测试环境按调用参数、清空成员范围与重复累加建立金标测试
- 证据：无（结构性缺口）

### GAP-020 · Expense Account Balance 月度结转

- 现象：本档案为静态源码与采集模型事实，未执行 TM1
- 影响：所有公式与映射都不是运行贡献或迁移等价证明
- 需要：需要隔离环境的运行记录、数值对账与等价测试
- 证据：无（结构性缺口）
