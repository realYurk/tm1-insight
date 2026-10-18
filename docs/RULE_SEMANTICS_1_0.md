# Rule & Feeder 计算语义还原（Task 20）

本文档说明 TM1 Insight 如何把 Rule / FEEDERS 源码升级为**可解释、可追溯的计算语义 IR**，
让用户从 Cube 进入后能读懂可证明的 TM1 计算逻辑，而不只是看到 Cube 之间的引用线。

## 1. 目标与边界

- 不连接任何 TM1 Server，不执行规则，不读取服务器单元格，不验证稀疏计算结果。
- 只对**本地已采集的 Rule 源码**做纯解析，产出结构化 IR。
- 无法证明的内容显式标记 `UNKNOWN`，不伪造公式、成员映射或运行结果。
- Feeder 与 Rule 语义**分离**，Feeder 不解释为数值计算公式。

## 2. 核心模块

`src/tm1_insight/learning/rule_semantics.py`

- 复用 `learning.syntax` 的平衡括号词法层（`statements` / `calls`），**不用正则粗暴切割嵌套表达式**。
- `parse_rule_semantics(code, cube, dimensions, cube_catalog) -> dict` 一站式入口。
- `RuleSemanticsParser` 类：可配置维度顺序与 Cube 目录。

## 3. Semantic IR 数据结构

### 3.1 顶层结构

```jsonc
{
  "version": "rule-semantics-1",
  "cube": "Allocation Driver BP",
  "source_hash": "<sha256 of rules 源码>",
  "directives": [ { "kind": "SKIPCHECK"|"FEEDSTRINGS", "line": 1, "column": 1, "raw": "..." } ],
  "rules":    [ RuleIR ... ],      // 每条计算规则
  "feeders":  [ FeederIR ... ],    // 每条 FEEDERS 语句（独立）
  "unknowns": [ { "reason": "...", "cube": "..." } ]
}
```

### 3.2 RuleIR（计算规则）

| 字段 | 类型 | 含义 |
|------|------|------|
| `cube` | str | 所属 Cube |
| `line_start` / `line_end` | int | 源码行区间（证据定位） |
| `raw` | str | 原始语句文本（可回原文） |
| `lhs` | AreaIR | 左侧目标区域 |
| `qualifier` | `N`/`S`/`C`/null | 数值/字符串/汇总限定符 |
| `rhs_kind` | enum | `DB_REFERENCE` / `AREA_REFERENCE` / `EXPRESSION` / `STET` / `CONTINUE` / `EMPTY` / `UNKNOWN` |
| `rhs` | obj | `{ kind, expression, line }` 右侧计算表达式 |
| `db_references` | list | 跨 Cube `DB()` 引用 |
| `attribute_calls` | list | `ATTRS`/`ATTRN` 属性查询 |
| `conditions` | list | `IF`/`ELISANC`/`ELISPAR` 等条件分支 |
| `special` | `STET`/`CONTINUE`/null | 特殊语义 |
| `status` | `PARSED`/`PARTIAL`/`UNKNOWN` | 解析状态 |
| `unresolved_reasons` | list[str] | 未解析原因 |

### 3.3 AreaIR（坐标区域 `[...]`）

```jsonc
{
  "kind": "area",
  "coordinates": [ CoordIR ... ],
  "raw": "[ { 'ACT' , 'BG' } , 'WIP' , 'CKD' , ... ]",
  "status": "PARSED"
}
```

CoordIR 按坐标类型分：

- `{ dimension, member, kind: "single" }` —— `'Scenario':'ACT'` 或裸成员 `'WIP'`
- `{ dimension, members: [...], kind: "set" }` —— `'Scenario':{'A','B'}` 或裸集合
- `{ dimension, raw, kind: "dynamic", status: "UNKNOWN" }` —— 动态坐标（如 `!Year`），保留原文
- `{ dimension, member, kind: "member_ref" }` —— 右侧区域简写 `['Amount']`（当前单元格成员）

Task 20.1 修正：Rule 区域的裸成员/集合不是位置坐标。仅有 Cube 维度顺序不能证明成员
归属；当前接口未接收完整成员索引，因此保留原始成员，`dimension: null`，并记录原因。
显式标签也必须在当前 Cube 维度目录中确认；未确认的原标签保存在 `declared_dimension`。
解析器不会为了可读性制造维度关系。

### 3.4 FeederIR（馈送关系，独立于 Rule 数值公式）

```jsonc
{
  "kind": "feeder",
  "cube": "...",
  "line_start": 19,
  "raw": "[...] => DB('...', ...);",
  "source_area": AreaIR,       // => 左侧源区域
  "target_area": {             // => 右侧目标（DB 引用或区域）
    "kind": "db_reference" | "area",
    "db": { "cube": "...", "cube_resolved": true, "coordinates": [...] },
    "raw": "...",
    "status": "PARSED"
  },
  "db_references": [...],
  "status": "PARSED",
  "unresolved_reasons": []
}
```

Feeder 仅建立「源区域 → 目标区域」的静态/动态关系，**不据此断言目标单元格的值来源**。

### 3.5 DB 跨 Cube 引用

```jsonc
{
  "cube": "BP PnL Assumption",
  "cube_resolved": true,          // false 表示动态/缺失 Cube 名
  "coordinates": [
    { "kind": "literal", "value": "CKD" },
    { "kind": "region", "dimension": "Scenario" },   // !Scenario
    { "kind": "dynamic", "raw": "vYear", "status": "UNKNOWN" }
  ],
  "line": 6, "column": 1
}
```

## 4. 集成点

- **架构引擎** `architecture.py`：`build()` 的 `rules` 段新增 `rule_semantics` /
  `feeder_semantics` / `rule_directives` / `rule_unknowns` 字段（保留旧 `references`/`groups`）。
- **查询层** `store/queries.py`：新增 `cube_rule_semantics(con, cube)`。
- **API** `api/app.py`：新增 `GET /api/cube/{cube}/rules`。
- **Cube 详情页** `_cube_detail.html`：规则卡片新增结构化语义展示
  （目标区域、计算表达式、DB 引用跳转、条件、属性查询、Feeder 独立分组、UNKNOWN 标记），
  原始源码折叠为 `<details>`。

## 5. 状态准确性（Task 20.1）

- `PARSED` 仅表示当前契约支持的结构已解析，不表示执行、数值贡献或迁移等价已验证。
- `PARTIAL` 保留已确认子结构，但存在影响完整解释的区域、Cube、坐标、函数或计算缺口。
- `UNKNOWN` 表示关键区域/表达式结构无法确认。各记录的原因同步到顶层 `unknowns`，并
  区分 `kind: rule/feeder`，保留源码行、列和原文。
- `rhs_kind` 是语法形态，独立于确定性。只有完整、平衡且消费整个 RHS 的 DB 调用才是
  `DB_REFERENCE`；DB 后有算术或外层函数时是 `EXPRESSION`。
- `rhs.status` / `rhs.semantic_status`、DB 的 `cube_resolution` / `status` /
  `unresolved_reasons` 为增量字段。`cube_resolved: true` 仅证明字面 Cube 名在目录中，
  不等于完整坐标、公式或运行贡献已经确认。
- 已知函数名称不等于已实现返回值语义。当前没有完整表达式 AST/函数求值契约，复合表达式
  与未知函数都不能仅因调用被识别而标为完整解析；已确认的 DB 引用继续保留。
- Feeder 独立评估区域与目标，不能从其中一个已知 DB 子调用推断完整目标，更不生成数值公式。

## 6. 已知限制

- 未接入完整的成员归属索引，裸成员、裸成员集合、同名成员均保留维度未知；即使裸成员
  列表长度等于 Cube 维数，也不按顺序猜测。
- `['Account'] \ ['Amount']` 一类的区域除法只保留在 `rhs.expression`，未进一步拆为
  独立运算节点。
- 不支持的函数（如自定义函数、`DIMNM` 等非数值语义函数）保留原始表达式，不静默删除。
- 动态 Cube 名（如 `DB(pCube, ...)`）标记 `cube_resolved: false`，不据此制造假依赖。
- 多目标/条件 Feeder 的完整目标结构仍未支持，保留源码和可确认引用，状态诚实降级。

详见 [Task 20.1 准确性修正](RULE_SEMANTICS_20_1.md)。
