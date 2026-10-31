# 阶段 2 第二刀：让调用事实可以被核对

## 1. 解决了哪个用户问题

上一刀把调用事实收敛成一个口径后，出现了一个更难缠的问题：

> 「你是更准了，还是咋了？我前端什么都看不出来。」

准确但不可见，等于没有交付——使用者无法判断数字为什么变，只能选择不信。
这一刀不改事实本身，只做一件事：**把事实的来源和解法摆到界面上，让人能自己核对**。
用户问题从「谁调用我」变成「这个数字凭什么」。

范围：进程调用这一类事实的可见性。

- 做：页头数字可拆解到来源表；调用树说明每个节点是什么证据；提供全模型口径差异清单。
- 不做：写入 / Rule / Feeder 的口径收敛（仍是下一刀）；不新增分析、评分、趋势；
  不导出；不引入任何运行期证据。

## 2. 证据与根因

**证据一：一个数量级的差距被藏在一个数字里。**

真实库（`data/demo`）`}bedrock.cube.viewandsubsets.delete`：

| 口径 | 调用方个数 | 说明 |
|---|---|---|
| 旧（只读 `process_calls_process`） | 131 | 只能看到源码里直接写死的进程名 |
| 三表合并去重 | **1996** | 其中框架调用表 1996，正则表 131 是它的子集 |

全库共 **153 个被调用对象**在新旧口径下数字不同，全部集中在 `}bedrock.*` 框架进程上——
因为几乎所有 TI 都用变量调 bedrock，而旧的页头只能看见字面写法。

**证据二：页面上没有任何一处能回答「为什么」。**

页头只有一个「被 131 个进程调用」，调用树只有一个数字，二者都不说明取自哪张表，
也不说明这个数字是否包含变量解析的结果。数字从 131 跳到 1996，没有任何解释入口。

**证据三（实施中新发现的缺陷）：上游节点被贴错证据标签。**

`process_call_tree` 的邻接表里，kind 只按**被调用方**分类，而上游方向展示的是**调用方**。
把父节点的 kind 贴到子节点身上，结果是：打开任何框架进程，
**121 个上游节点全部被标成「框架」**——`Balance Sheet Opening Balance.From.General Ledger`
这样的普通业务 TI 也顶着「框架」标签。这是明确的错误事实，不是措辞问题。

修法：`store.calls` 的 CTE 增加 `caller_kind`（按调用方自己分类：`}`前缀 / 目录中是否存在），
上游方向使用 `caller_kind`。修后同一页面标「框架」的节点为 1 个（那 1 个确实是 `}bedrock.*`）。

## 3. 复用了哪些现有能力

- `store.calls` 的三表合并 CTE：本次只加列（来源标记、`caller_kind`），没有另起一套查询。
- `calls.summary`：页头与调用树本来就共用它，来源计数直接挂在返回值上，页面只做投影。
- 原生 `<details>` 折叠：不写一行 JS，无脚本也能展开——与「无脚本可读源码」的既有约定一致。
- 既有 `table` / `tree-kind` / `muted small` 样式与文案语气，不引入新的视觉语言。

## 4. 修改文件与兼容处理

| 文件 | 变更 |
|---|---|
| `src/tm1_insight/store/calls.py` | `_SOURCES` 每张表带来源标识；CTE 增加 `from_regex` / `from_resolved` / `from_framework` 与 `caller_kind`；`edges()` 增加 `source` / `sources` / `caller_kind`；`summary()` 增加 `callers_by_source` / `callees_by_source`；新增 `caller_counts_by_target()` |
| `src/tm1_insight/store/queries.py` | `process_call_tree` 上游方向改用 `caller_kind`；返回值增加 `kind_counts` |
| `src/tm1_insight/api/app.py` | 新增只读页 `GET /calls/sources`（口径差异清单，`no-store`） |
| `src/tm1_insight/api/templates/process_view.html` | 页头增加「这些调用数字是怎么来的」折叠区：三张表各自的调用方/目标计数、去重后合计、静态读取声明、差异清单入口 |
| `src/tm1_insight/api/templates/_call_tree.html` | 增加图例：图中节点分别有多少是字面写死 / 框架调用 / 目录中不存在，外加未解析计数 |
| `src/tm1_insight/api/templates/calls_sources.html` | 新增。差异清单页：被调用对象、旧口径、三个来源、去重后、差、性质 |
| `src/tm1_insight/api/static/workbench.css` | `.call-evidence` / `.table.compact` / `.num` / `.row-focus` 等样式 |
| `src/tm1_insight/api/templates/base.html` | `workbench.css` 版本号 `process-head-2` → `call-evidence-3` |

**兼容性**

- `summary()` / `edges()` 只**追加**字段，原有键（`callers` / `callees` / `counts` /
  `node_callees` / `dynamic_callees`）语义不变，学习报告与导出不受影响。
- CTE 只加列，`process_call_tree`、`learning.engine` 的既有 SELECT 不受影响。
- 旧链接、旧接口、旧模板宏一个未删；`/calls/sources` 是新增页，不替代任何页面。

**顺带修掉的实现缺陷**：`edges()` 在上一版把 `WHERE` 子句漏掉了——
`edges(con, caller=…)` 曾经静默返回全模型边。该函数此前只有测试调用，
现在补回子句并加了测试（`test_edge_carries_primary_source_and_all_sources`）。

## 5. 前后效果（使用者能看见什么）

| 位置 | 之前 | 现在 |
|---|---|---|
| TI 页页头 | 「被 1996 个进程调用」，无法知道为什么不是 131 | 同一行下面多一个「这些调用数字是怎么来的」，点开是：正则 131 / 变量解析 0 / 框架表 1996，去重后 1996，并说明各来源可重叠、都是静态读取 |
| 框架进程的调用树 | 120 个上游全部标「框架」（错误事实） | 只有真正的框架进程被标；图例写明本图 154 个字面 / 1 个框架 / 0 个目录中不存在 |
| 想核对差异时 | 只能逐个 TI 打开猜 | `/calls/sources` 一次列出 153 个差异对象，含旧/新/差值/性质；`?focus=` 高亮当前 TI |
| 动态占位（如 `<sProc2>`） | 混在调用方计数里，看不出不是成员 | 清单里灰显并标注「动态占位，不是成员」 |

## 6. 测试命令与精确结果

```
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_call_fact_consistency.py -q
# 17 passed
```

新增 6 条（`tests/test_call_fact_consistency.py`）：

- `test_source_breakdown_shows_which_table_produced_each_caller`：
  同一调用方被两张表记录时按名字去重（3 个而非 4 行），且各来源之和 > 总数（页面必须说明重叠）。
- `test_edge_carries_primary_source_and_all_sources`：主证据优先字面，`sources` 保留全部来源。
- `test_target_counts_separate_old_scope_from_merged_scope`：旧/新并排、差值、动态占位标记。
- `test_header_and_sources_page_explain_the_numbers`：页头拆解文案存在、差异页含占位且已标注。
- `test_sources_page_marks_focus_object`：`?focus=` 高亮生效。
- `test_tree_legend_states_what_the_nodes_are`：图例计数与 `kind_counts` 一致（含目录中不存在的调用方）。

全量离线回归：

```
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest -q
# 1220 passed, 1 warning in 154.05s
```

## 7. 性能测量及未测范围

同机、`data/demo` 只读连接，单次请求：

| 指标 | 数值 | 备注 |
|---|---|---|
| `calls.summary`（热） | 20.4 ms | 加两列标记后与阶段 2 第一刀的 17–28 ms 持平 |
| `calls.summary`（冷） | 536 ms | 首次打开进程的页缓存代价，与改造前同量级 |
| 调用树片段 | 23–24 ms | 修复 `caller_kind` 后未退化（原 17–28 ms） |
| 全模型口径对照（1604 个对象） | 80.5 ms | 单条 SQL；仅 `/calls/sources` 使用 |
| `/calls/sources` 端到端 | 142 ms | 含 153 行渲染 |

**明确未测**：浏览器首屏布局绘制时间、`<details>` 展开后的重排耗时、窄屏下表宽溢出。
本机无浏览器内核，未联网下载；这部分只有 HTML 结构与样式约束测试。

## 8. 数据安全与 Git 状态

- 全程只读：`duckdb.connect(..., read_only=True)`；未写入 `data/`、`collections/`、`cache/`，
  未重建快照，未连接任何 TM1 服务。
- `/calls/sources` 为只读页，无表单、无导出、不落盘。
- 页面按 `Cache-Control: no-store` 返回，避免把口径差异缓存成「事实」。

## 9. 剩余限制

1. **只覆盖调用这一类事实**：写入、Rule、Feeder 仍是各自的旧逻辑，还没有对应的
   「为什么是这个数」入口。
2. **差异清单只按差值排序、默认前 200 行**，未提供筛选与分页；超过 200 时页面明说未列全。
3. **来源只到「哪张表」这一层**：还不能定位到源码第几行、哪个语句。
   `store.calculation.inspect()` 已有条件与参数信息，尚未并入。
4. **`caller_kind` 判据只有三种**（`}`前缀 / 目录中存在 / 不存在）：调用方若不是 TI
   （理论上不会发生），会被归进 `missing`，目前只靠这一条护栏。
5. **未说明「为什么某个具体调用方只出现在框架表」**：差异页只给计数，
   要回答到单个调用方还得点进 TI 页看源码。

## 10. 下一阶段最小任务

把「来源」从表级下探到语句级：让每条调用边能指回源码位置（section + 行号）与原始语句，
页面点击即在源码中定位。这样「131 与 1865」的差别就不再需要解释，而是可以逐条验证。
前提是复用现有 `source_anchor` 与 `store.calculation.inspect()`，不新建解析器。
