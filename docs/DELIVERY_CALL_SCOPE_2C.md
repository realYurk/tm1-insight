# 阶段 2 第三刀：把系统对象从默认视图里请出去（但每次报数）

日期：2026-10-31 · 提交见本轮 Git 记录 · 数据源：本机 `data/demo`（只读）

---

## 1. 解决的用户问题

使用者原话：「我并不关心 bedrock 相关的，我甚至不关心 `}` 开头相关的，我甚至都想去掉了。」

上一轮把调用数字改准了，代价是把 `}` 开头的系统对象全部推到眼前：
打开 `}bedrock.cube.viewandsubsets.delete` 是「被 1996 个进程调用」，
打开自己的业务 TI 是满屏 `}bedrock.*`。准确的东西如果全是自己不关心对象，
等于没交付——这一轮回答的是「我不关心的那部分能不能先让开，同时别骗我」。

## 2. 证据与根因（先量，再改）

在本机 Demo 库上按对象前缀统计（只读，不涉及任何业务数据）：

| 事实 | 数值 |
|---|---|
| 进程总数 / `}` 开头 | 3 437 / 273（7.9%） |
| 有下游的业务 TI | 2 949 |
| 其中**只调用系统对象** | 2 130（72.2%） |
| 其中业务、系统都调 | 594（20.1%） |
| 其中只调用业务对象 | 225（7.6%） |
| 下游调用边：系统 / 业务 | 3 394（63.2%） / 1 976 |
| 口径差异对象（全范围） | 153 = 系统 19 + 业务 122 + 变量占位 12 |

根因不是「系统对象不该存在」，而是**两类对象混在同一个视图里**：
72% 的业务 TI 一旦展开调用树，图里只有 `}bedrock.*`，使用者看不到自己调用的业务子进程；
而 `}bedrock.*` 由产品方维护，既改不了也不该由使用者核对。

## 3. 复用的能力

- `store.calls` 仍是唯一事实生产者：范围只是它输出的一个**投影维度**，没有第二套口径。
- 调用树的预算/截断机制、`_call_tree.html` 宏、按需异步加载全部沿用，未新增渲染路径。
- `store.calls.edges_cte()` 单条 SQL 不变：范围过滤在内存 BFS 时完成，不额外发 SQL。

## 4. 修改文件与兼容

| 文件 | 改动 |
|---|---|
| `store/calls.py` | 新增 `is_system_object` / `scope_of` / `in_scope` 与 `SCOPE_*` 常量；`summary()` 增加 `callers_business` / `callers_system` / `callees_by_scope` / `scope`；`caller_counts_by_target()` 每行增加 `system` |
| `store/queries.py` | `process_call_tree(..., include_system=True)`，返回 `hidden_system: {callers, callees, deeper}`；`search_process_page(..., objects="all")` |
| `api/app.py` | `_call_scope()` 决定默认范围（业务 TI → 业务，系统对象 → 全部）；`/explorer/process/{name}`、`.../call-tree`、`/calls/sources` 增加 `scope`；`/processes` 增加 `objects` |
| `api/templates/process_view.html` | 页头改为「被 N 个业务 TI 调用，另有 M 个系统对象未计入」；调用树卡片标出当前范围并给切换链接 |
| `api/templates/_call_tree.html` | 折叠说明（直接上下游与更下层分开报数）；无节点时的措辞不再说「未记录调用关系」 |
| `api/templates/calls_sources.html` | 三个页签（业务/系统/全部），默认业务，并报出被排除的 19 + 12 条 |
| `api/templates/processes.html` | 「只看业务对象 / 显示全部」开关，写明当前排除了 273 个系统对象 |
| `api/static/workbench.css` | `.scope-switch`、`.call-tree-scope` 样式；版本号 `call-scope-4` |

兼容性：

- `search_process_page` 默认仍是 `objects="all"`——**列表页默认行为未变**，开关是显式选择，不擅自改既有语义；
- `process_call_tree` 默认仍是 `include_system=True`——直接调用方（图谱、脚本、旧接口）行为不变；
- `proc.called_by` / `proc.calls_process` 兼容字段保留，仍由同一份 `call_facts` 投影；
- 导出（`/api/invocation/export`、`/api/calculation/export`）**没有**跟随页面范围，仍是全范围，见第 9 节。

## 5. 前后效果（真实数据）

`Cub.CM KPE Deduction Model Year by FC.Caller`：

- 改前：调用树 61 个节点里混着 `}bedrock.*`，页头「调用 27 个子进程」不区分类型。
- 改后：页头「调用 26 个业务子进程，另有 1 个系统对象未计入」；
  树内「当前只画业务对象：直接下游另有 1 个，图中更下层还有 1 个未画 · 全部显示」。

`Cub.MC Info Price.Update.Caller`：14 个业务子进程 + 1 个系统对象（更下层 2 个）。
`/calls/sources`：默认 122 行（业务），系统页签 19 行，全部页签 153 行（含 12 条占位）。
`/processes?objects=business`：3 437 → 3 164 条，并写明「已排除 273 个」。

## 6. 测试命令与精确结果

```
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_call_fact_consistency.py -q
# 22 passed, 1 warning

PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest -q
# 见第 8 节
```

新增 5 条（`tests/test_call_fact_consistency.py`）：

1. `test_call_tree_scope_folds_system_objects_and_reports_the_count` —— 折叠后节点集合正确，
   `hidden_system` 三个数正确，片段里写清「直接上游/直接下游/更下层」；
2. `test_summary_reports_business_and_system_callers_separately` —— 2 个调用方拆成 1 + 1，
   `callees_by_scope` 三类分开；
3. `test_default_scope_follows_the_object_and_links_to_the_other_scope` —— 业务 TI 默认业务范围、
   系统对象默认不折叠，两种范围都能一键切换；
4. `test_header_and_tree_agree_inside_each_scope` —— 同一范围内页头数字 == 树的上游数字
   （1/1 与 2/2 各验一遍），这是上一轮那类错误的回归防线；
5. `test_process_list_can_hide_system_objects_and_says_how_many` —— 列表开关生效且报出排除数。

修改 2 条既有断言（措辞变化，语义未放宽）：
`被 1 个进程调用` → `被 1 个业务 TI 调用`；占位条目从 `/calls/sources` 默认视图移到 `scope=all`。

## 7. 性能

| 请求 | 结果 |
|---|---|
| 调用树（业务范围） | 冷 66.0 ms / 热 23.5–25.1 ms（改造前 17–28 ms） |
| 调用树（全部范围） | 冷 92.2 ms / 热 22.2–23.0 ms |
| `/calls/sources` 业务 / 系统 / 全部 | 229.8 ms（冷） / 95.5 ms / 106.5 ms |
| `/processes` 全部 / 业务 | 584.8 ms（冷） / 28.2 ms |

SQL 次数未增加：范围过滤发生在内存 BFS，不额外查库；缓存键加入范围维度，两种视图互不污染。
浏览器端（首屏可读、绘制、交互）仍未测——本机无浏览器内核，和第 1、2 阶段一致。

## 8. 全量回归

```
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest -q
# 1225 passed, 1 warning in 167.15s
```

## 9. 剩余限制

1. **导出仍是全范围**：`/api/invocation/export`、`/api/calculation/export` 没有 `scope`，
   页面看到的「26 个业务子进程」与导出文件的「27 条」会不一致。这不是新问题，
   但现在页面有范围概念后它变得更刺眼，下一刀应统一。
2. **调用边仍无行号**：三张调用表只有 `caller` / `callee`（`ti_business_calls` 多一列 `params`），
   还点不回源码第几行。要做「点一下在源码里定位」，得改解析器落行号，不是界面工作。
3. **范围只按 `}` 前缀判定**：没有识别「框架进程但名字不以 `}` 开头」（如 `APQ.*` 系列）。
   实测 `APQ.Process.Execute` 是业务名，仍按业务对象计——按名字猜语义被产品宪法禁止，
   所以这里保持前缀这一条硬规则，不做启发式。
4. **系统对象被折叠后，其分支整体不展开**：一个业务 TI 经 `}bedrock.*` 再调用业务 TI 的路径，
   在业务范围下看不见（`deeper` 只报个数）。要追这条链需切到「全部」。
5. 每父节点上限 20、根层 120、节点预算 400 的截断规则未变，仍显式上报。

## 10. 下一阶段最小任务（建议，未开工）

把 `scope` 贯通到导出与学习报告，使「页面上看到的」与「导出的」是同一套数字；
仍不做行号定位（那需要改解析器，单独评估）。
