# 阶段 2 实施记录：调用事实的唯一口径（第一刀）

- 日期：2026-10-31
- 范围：进程调用这一**类**事实的收敛（写入、Rule、Feeder 的口径收敛留到本阶段后续刀次）
- 基线：`8e3040f`（阶段 1 提交后）

## 1. 解决了哪个用户问题

用户打开一个 TI，页头写「被 3 个进程调用」，点开调用关系只有 2 个，谁也没说第 3 个去哪了。
同一次查看给出两个不同答案，用户就无法用这个页面判断"谁在跑我"。

这不是显示误差，是**同一事实有两份生产逻辑**。

## 2. 实际证据与根因

采集阶段把调用写进了三张表，口径各不相同：

| 表 | 来源 | 有什么 | 缺什么 |
|---|---|---|---|
| `process_calls_process` | 正则扫源码 | 字面目标（含 `}` 框架进程） | 变量已解析的调用 |
| `ti_business_calls` | 语句级解析器 | 变量解析后的目标、参数 | 会把 `<sProc2>` 这类**占位**写进来 |
| `ti_framework_calls` | 同上 | `}bedrock.*` / `}APQ.*` 及用途 | —— |

而读取端各读各的：

- `get_process.called_by` = `process_calls_process` **并** `ti_business_calls`；
- `process_call_tree` / `process_relation_graph` / `learning` 引擎 = 只读 `process_calls_process`。

本机 Demo 库（3 437 TI / 3 259 + 2 764 + 8 834 条调用记录）实测：

- **113 个 TI** 的页头计数 ≠ 调用树计数；
- 最大偏差 `Sys.E-mail.Send`：页头 56，树 55；
- `APQ.Process.Execute`：页头 4，树 2；
- `ti_business_calls` 里有 **24 条动态占位目标**（`<sProc2>`、`<DimNm(...)>`、
  `<GetProcessName(...)>.Localized` …），分布在 **20 个 TI**。这些字符串一旦被当作
  进程名渲染，就是把动态坐标当成固定成员——产品事实规则明确禁止；
- 另有 **63 个**字面目标在本地目录里根本不存在，旧实现把它们渲染成可点击链接，
  点开是 404。

合并去重后：`literal 1917 / framework 3733 / dynamic 24 / missing 63`，共 5 737 条边。

## 3. 复用了哪些现有能力

- 复用采集阶段的结果，**不重新解析源码**：三张表就是三种解析器的产出，收敛发生在读取端。
- 复用阶段 1 的调用树函数形状、预算参数与 `_call_tree.html` 宏。
- 复用 `process_view.html` 的页头结构，只加一个计数片段。
- 学习报告 `learning/engine.py` 原本就把调用边收在一个 `relations` dict 里，
  换掉它的取数来源即可，不必改报告结构。

## 4. 修改文件与兼容处理

新增 **`src/tm1_insight/store/calls.py`**——调用事实的唯一生产者：

- `edges_cte(con)`：三张表合并去重（`max(detail)` 取非空侧），再按
  `dynamic → framework → missing → literal` 分类；
- `object_edges_cte(con, name)`：同样的规则，但把 `caller/callee` 过滤下推到表扫描；
- `summary(con, name)`：一条 SQL 拿到上下游，返回 `callers` / `callees`(带 kind) /
  `counts` / `dynamic_callees`；
- `is_dynamic_target(name)`：判据是「以 `<` 开头」而不是「形如 `<...>`」，
  因为解析器对拼接目标会保留后缀（`<GetProcessName(...)>.Localized`）。

迁移的消费者：

| 消费者 | 改动 |
|---|---|
| `queries.get_process` | `called_by` / `calls_process` / `business_calls` / `framework_calls` 全部由 `summary()` 投影；新增 `call_facts` 字段 |
| `queries.process_call_tree` | 邻接表来自同一 CTE；节点带 `kind`；动态目标不入图，只报 `dynamic_targets` |
| `queries.process_relation_graph` | 调用边改走 `store.calls`（该函数目前无页面消费者，保留旧结构） |
| `learning/engine.py` | `relations["process_calls_process"]` 改由 `calls.edges()` 提供，排除动态目标 |
| `_call_tree.html` | `missing` 节点不渲染链接、标「目录中无此 TI」；`framework` 标「框架」；新增自环与动态调用说明 |
| `process_view.html` | 页头加「N 处动态调用目标未解析」 |

**兼容**：`get_process` 的旧字段名与类型完全保留（列表、排序不变），只增不改；
`process_call_tree` 的返回结构只增字段（`dynamic_targets` / `recursive_self_call` / 节点 `kind`）；
旧接口一个没删。缺表的老快照会少读一份来源而不是报错（有测试覆盖）。

## 5. 页面与操作前后效果

| 位置 | 前 | 后 |
|---|---|---|
| 页头 | 「被 N 个进程调用」，N 与树不一致（113 个 TI） | N 与树恒等；另报「N 处动态调用目标未解析」 |
| 调用树标签 | 只报展开条数 | 「显示 120 / 共 317」+ 逐条截断原因（阶段 1 起） |
| 目录中不存在的目标 | 可点击链接 → 404 | 灰字 + 虚线下划线 + 「目录中无此 TI」，不生成链接 |
| 框架调用 | 与业务调用混在一起 | 同列展示但标「框架」 |
| 自环 | 被环去重静默吞掉 | 「本 TI 的源码里有调用自己的语句」+ 说明它不代表执行次数 |
| 动态目标 | 以 `<sProc2>` 形式混入业务调用列表 | 只出现在「N 处未解析」里，不点名、不可点 |

## 6. 测试命令与精确结果

```
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_call_fact_consistency.py -q
# 11 passed

PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest -q
# 1213 passed, 1 warning
```

新增 `tests/test_call_fact_consistency.py`（11 条）覆盖：

- 三张来源表合并后的四类分类（`literal` / `framework` / `missing` / `dynamic`）；
- 同一条调用同时出现在两张表里只算一次，`detail` 取非空侧；
- 缺表快照降级（少读一份而非整体失败）；
- **只在变量解析表里记录的调用方**，页头与调用树必须都看得到（113 类缺陷的回归）；
- 动态目标不出现在树节点、但计数正确；页头与片段都有说明；
- `missing` 节点不产出 `/explorer/process/...` 链接（用真实 Jinja 模板渲染断言）；
- 自环显式说明、环在单个方向只展开一次；
- 学习报告的 `called_by` 与 TI 页同一个集合。

## 7. 性能测量及未测范围

同机、同数据源、同脚本。`p95` 取 3 轮 × 12 次的中位数（单轮抖动约 ±20%）。

| 样本 | 阶段 1 后 p95 | 阶段 2 p95（范围） | SQL 次数 |
|---|---:|---:|---:|
| largest | 57.4 ms | 62.9 ms（61.2–66.8） | 12 → **9** |
| median_size | 41.8 ms | 46.9 ms（44.5–50.5） | 13 → **10** |
| highest_fan_in | 50.0 ms | 59.6 ms（57.2–62.1） | 12 → **9** |

**这是一次有意的、可解释的变慢**：页头要给出统一口径的调用方集合，
多了一次跨三张表的事实查询（实测 `summary()` 中位 8.1 ms，其中 `SHOW TABLES` 1.45 ms、
CTE 执行约 4.8 ms）。SQL 次数反而少了 3 条（旧实现是 5 条小查询）。

调用树片段（`/explorer/process/{name}/call-tree`）：hub 样本 p50 28.1 ms、64 KB。
阶段 1 它是 14 条 SQL、7–10 ms；现在是 **1 条 SQL** 但要把全模型 5 737 条边读进内存走 BFS，
约 17–28 ms。换成"口径统一"后这条 SQL 要跨三张表合并，逐层重算会到 60–70 ms，
所以改成一次取邻接表。**这条路径随模型边数线性增长**，是新的已知边界（见第 9 节）。

未测：浏览器端渲染（本机无可用浏览器内核）、并发用户下的 DuckDB 竞争、
真实企业模型（本次只有 Demo 规模）。

## 8. 数据安全与 Git 状态

- 全程 `read_only=True` 连接，未执行 TI、未写服务器、未改 `data/`、`collections/`、WAL；
- 未联网、未安装依赖、未重建虚拟环境；
- 合成模型全部在 `:memory:` 或 `tmp_path` 里构造。

## 9. 剩余限制

1. **写入事实、Rule、Feeder 尚未收敛**。本刀只做了「调用」。三条事实链仍各有重复生产者：
   - 写入：`process_writes_cube`（正则）vs `store.calculation.inspect()`（语句级）vs
     `ti_flow_dims`（血缘解析）；`queries.ti_write_slices` 与 `cube_lineage.writers`
     仍是两份实现（`ti_write_slices` 全仓无调用方）。
   - Rule：`cube_rule_semantics` / `rule_expression` / `learning.understanding.analyze_rule`
     三处各有解释器。
2. **`process_graph_rich` 仍读 `process_calls_process`**，只在测试中使用、无页面消费者；
   已在 docstring 标注：若重新接入页面必须先迁到 `store.calls`。
3. **调用树的邻接表随模型边数增长**（每次请求读全表边）。5 737 条约 20 ms；
   若企业模型到十万级边，需要改成只取可达子图（递归 CTE 或按层取子图）。
4. 调用仍不含**条件与参数**：`store.calculation.inspect()` 有 `control_context` 与
   `arguments`，本刀没有把它们并进 `store.calls`，因此调用树无法回答"在什么条件下调用"。
   这是下一刀的第一项（调用树与 invocation 报告共用同一份带条件的边）。
5. `dynamic` 只计数不点名，是**有意的**：无法确认的调用目标不能猜。

## 10. 下一阶段最小任务

1. 把 `store.calculation.inspect()` 的 `control_context` / `arguments` 并进
   `store.calls` 的边（`detail` 已预留），让 invocation 报告与调用树共用同一份带条件的边。
2. 在同一合成模型上复现写入口径差异（`process_writes_cube` vs `inspect()`），
   用与本次相同的"唯一生产者 + 四类分类"方法收敛写入事实，覆盖
   常量写入 / CellGet 值依赖 / 无关读取 / 动态 Cube / 未知函数 / 条件分支 /
   NativeView 缺元数据 / Rule / Feeder / 自环 这十种情形。
