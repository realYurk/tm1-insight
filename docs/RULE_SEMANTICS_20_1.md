# Task 20.1 — Rule 语义准确性加固

本轮只修正既有 Rule/Feeder IR 的分类与确定性，不连接 TM1，不执行规则，不写正式库，
不新建解析器、不添加页面、不开发 Java。保持 `rule-semantics-1` 字段兼容，增加
`engine_revision=2`。架构修订号从 9 升到 10，使新分析不复用旧语义缓存；历史导出不改写。

## 三个根因与修复

1. 原 `_classify_rhs` 仅检查 DB 开头、一个 DB 和末尾右括号，`DB(...) + ABS(1)` 也符合，
   因而把计算错当直引。现在按 token 类型平衡括号，核对首个 DB 调用是否消费整个 RHS；
   字符串内的括号不参与平衡。直接区域引用也不能吞掉后续运算。
2. 原 Rule.status 未汇总 LHS、动态 Cube/坐标、未知函数等缺口；顶层 unknowns 总是空。
   现在 Rule、LHS、RHS、DB 引用及 Feeder 分别保留状态和原因，再汇总带源码位置的未知项。
   Cube 身份、语法形态与完整计算语义分别表达。函数名称识别不是语义实现的白名单。
3. 原 `_resolve_positional_coordinates` 把裸成员列表按 Cube 维度顺序填入字段。这不是 Rule
   区域的成员归属证据。保留 helper 名称以兼容调用，但停止该推断；未接成员索引时原成员
   和集合不变、dimension 为 null、状态和原因明确。显式标签仅在 Cube 目录中确认。

## 正反例

```text
['Measure':'Amount'] = N: DB('Cube_A', !Year, 'Amount');
```

当 Measure/Year 是当前 Cube 已记录维度、Cube_A 在目录中时，RHS 形态为 DB_REFERENCE。
当前契约可把引用结构标为 PARSED，但仍不承诺运行值、成员存在、目标维度元数/位置或迁移等价。

```text
DB('Cube_A', !Year, 'Amount') + ABS(1)
DB('Cube_A', !Year, 'Amount') * 2
Opaque(DB('Cube_A', !Year, 'Amount'))
```

这些都不是直接 DB RHS。已确认的 Cube 引用保留；表达式语义为 PARTIAL，未知函数有独立原因。
`DB(pCube, ...)` 的 cube_resolved=false，原始动态表达式不丢弃；不能据此宣称完整依赖。

```text
['Amount'] = N: 1;
```

即使当前 Cube 顺序为 Year、Product、Measure，也不能把 Amount 放到 Year。当前只接收
维度顺序的接口会保留 dimension=null；成员归属索引是明确的后续缺口。空区域 `[]` 则保留
为合法的全区域结构，不与缺失右括号/不完整集合混淆。

## 契约与状态

旧字段保留：Rule/Feeder 数组、raw、源码行、lhs/source_area/target_area、rhs_kind、
db_references、cube_resolved、status 和 unresolved_reasons。

增量字段：RHS status/semantic_status；DB cube_resolution/status/unresolved_reasons；
坐标 dimension_resolution 和必要时 declared_dimension；顶层 engine_revision。

PARSED 是当前有限契约下的结构解析；PARTIAL 是保留部分事实但仍有语义缺口；UNKNOWN 是
关键结构无法确认。raw/source_hash 和语句数量不因置信度降级而改变。顶层 unknowns 每条
原因带 Rule/Feeder 类型及源码位置，不把 Feeder 引用解释为数值贡献。

query API 原有字段继续返回；异常降级不再返回空 unknowns 而伪装成没有缺口。
架构旧 references/groups 保留，新增语义记录采用修正后的状态。页面布局无改动。

## 测试修正说明

没有删除 Task 20 测试。三项旧断言被纠正：

- 原裸成员顺序映射测试改为验证成员保留、维度未知和具体原因。
- 原直接 DB Rule 测试保留 RHS 直引断言，但裸 Amount 的 LHS 不能让整个 Rule PARSED。
- 原 Feeder 分离测试保留 DB 目标断言，但源裸成员的维度仍未确认，整体应为 PARTIAL。

`tests/test_rule_semantics_accuracy.py` 新增严格正反例，覆盖完整 DB、算术/嵌套函数、动态和
缺失 Cube、已知/未知函数、破损 LHS/集合、最后一维成员、重复成员、无元数据、Rule 与
Feeder 独立状态、动态坐标、当前 Cube 的 !维度、查询异常和证据定位。

测试全程使用网络禁用保护和临时数据目录；本地真实验证只读打开三份指定 Cube Rule。
真实源码与前后 IR/统计存放在工作区外的私有验收目录，不加入仓库。

## 明确限制

不新增成员归属解析引擎；不解释完整复合表达式 AST、所有函数的返回值与签名、动态 Cube
名称、层级别名、规则优先级、成员实际存在性或运行时贡献；多目标 Feeder 仍可能 UNKNOWN。
这些缺口不能通过提高 PARSED 比例消除，本轮结束后等待验收。
