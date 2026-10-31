# 阶段 1 — TI 源码查看的性能止损

## 1. 解决了哪个用户问题

「从本地资料快速查 Cube、TI、维度和 Rule」中的第一跳：**打开一个 TI 看源码**。
改造前，打开源码要先付一笔与被查看内容无关的钱——把整棵调用树按模型规模展开。
在可达节点 3 631 的模型上，这笔试为 **2 277 ms / 3 644 条 SQL**，且源码页面还要等它。

改造后：源码与最小基本信息先返回，调用关系在页面空闲时按需加载，
并且**加载量有显式预算、截断有显式说明**。

## 2. 实际证据与根因

来自 `docs/PERFORMANCE_AUDIT_TI_SOURCE_0.md`：

1. **调用树逐节点发 SQL**（主因）。`process_call_tree` 的递归对每个节点执行一次
   `SELECT DISTINCT callee FROM process_calls_process WHERE caller = ?`。
   SQL 次数与可达节点数 1:1，实测 3 631 节点 → 3 644 条 SQL → 2 270 ms。
2. **调用树在首屏同步构建**。`/explorer/process/{name}` 在返回页面前无条件构建整棵树，
   即使调用关系卡片只是一张右栏卡片。
3. **四段源码一次性全量高亮**。`syntax.js` 的 `scan(document.body)` 在 DOMContentLoaded
   把页面上所有 `pre.code` 都渲染成逐行 DOM。1 210 行样本：16.5 ms 计算、8 466 个元素、
   HTML 相对源码膨胀 2.3 倍（130 KB → 392 KB）。
4. **页内搜索每次输入遍历全部已高亮行**。`input` 事件无防抖，直接对
   `.tab-pane .code-line` 全量做 `textContent` 比对。

未测：浏览器布局与绘制、首屏可读时间（无可用浏览器内核）。

## 3. 复用了哪些现有能力

- `queries.process_call_tree`：保留原函数、原返回结构（`name/callers/callees`），
  只把遍历改成「逐层批量取子节点」并加 `max_nodes` 预算。
- `_call_tree.html`：把 `process_view.html` 里原有的 `render_tree` 宏原样搬出来，
  首屏占位与异步片段**共用同一份渲染实现**，没有第二套树 UI。
- `app._cached_page` 的思路（以数据指纹为失效依据）用于新增的调用树缓存。
- `process-search.js`：保留返回链接、页高自适应、TI 切换器，仅把 `#section-Ln`
  深链接交给页面自己的激活/渲染流程。
- `tm1Source.mount` 的转义、复制源码、`source-tools` 外框全部沿用。

## 4. 修改文件与兼容处理

| 文件 | 变更 |
|---|---|
| `src/tm1_insight/store/queries.py` | `process_call_tree` 改为逐层批量取子节点；新增 `max_nodes` 关键字参数；返回值**追加** `node_count` / `truncated` / `limits` |
| `src/tm1_insight/api/app.py` | 页面路由不再构建调用树；新增 `GET /explorer/process/{name}/call-tree`（片段、有预算、`no-store`、404/409）；新增 `CALL_TREE_LIMITS` 与有界缓存 `_call_tree_for` |
| `src/tm1_insight/api/templates/_call_tree.html` | 新增。调用树唯一渲染实现（宏 + 预算/截断说明） |
| `src/tm1_insight/api/templates/process_view.html` | 代码段改为 `data-lazy-source` 惰性段；默认段服务端标 `active`；调用树卡片改为占位 + 加载/取消/重试；搜索改为文本检索 + 180 ms 防抖；深链接自行处理 |
| `src/tm1_insight/api/static/syntax.js` | `scan()` 跳过未挂载的惰性段；`mount()` 支持分批渲染；新增 `revealLine()`、`isReady()`；超大源码仍走纯文本降级但支持按行高定位 |
| `src/tm1_insight/api/static/process-search.js` | 页面自带 `TM1ProcessView` 时不再抢行节点 id 与 hash 定位，保留其余行为 |
| `src/tm1_insight/api/static/workbench.css` | 调用树卡片样式 |
| `src/tm1_insight/api/templates/base.html` | `syntax.js?v=2` → `v=3`（资源内容已变，必须失效旧缓存） |

**兼容性**
- `process_call_tree(con, root, max_depth, max_breadth)` 原调用方式不变，默认 `max_nodes=None`
  即旧行为（无预算），因此 CLI/测试/其他调用方不受影响。
- 旧链接 `/explorer/process/{name}?source=…`、`#prolog-L120` 语义保持不变；
  指纹失效仍返回 409 且不用于定位。
- 未删除任何旧接口、旧模板宏、旧字段。`ti_write_slices` 等死代码**原样保留**，
  清理属阶段 2。

**有意变更的语义（已写入函数 docstring）**
遍历由深度优先改为逐层展开。可达集合不变，但「一个进程经多条路径可达」时，
现在被放在**层数最小**的位置，而不再由 DFS 的访问先后决定。
结果是同一个模型上结果更确定，且深度更浅。

## 5. 页面/操作前后效果

| 操作 | 改造前 | 改造后 |
|---|---|---|
| 打开 TI 页 | 等整棵调用树构建完才返回 HTML | 源码与基本信息立刻返回；调用树在 `requestIdleCallback` 后异步加载 |
| 右栏调用关系 | 首屏内联，无法取消、无预算 | 占位 + 「加载调用树」；加载中可点「取消加载」；失败可重试且不影响读源码 |
| 切到未看过的 Section | 首屏已经付过全量高亮代价 | 切到该 Tab 时才渲染那一段 |
| 段内搜索 | 每次输入遍历全部行 DOM | 180 ms 防抖；在源码文本上检索（未渲染的行也能命中）；命中可跳转并自动渲染目标行 |
| 超长段（>1 500 行） | 一次性生成全部行节点 | 先渲染 800 行，滚动接近底部再追加；行号连续、行锚点可用 |
| 截断 | 无预算，可能 2 秒以上 | 达预算即停，页面明说「已按预算截断…更远的调用未展开，不代表不存在」 |

## 5.1 实施中发现并修复的缺陷：根层扇入被静默截断

改造过程中用真实库复核时发现一个**产品级错误**，与性能无关但更严重：

- 真实模型里扇入最大的 TI 有 **317 个直接调用者**，而调用树按「每个父节点最多 30 个」
  只列出前 20–30 个，页面上却显示「↑ 被调用（20）」，**没有任何截断提示**。
- 改造前的实现同样如此（`max_breadth` 只限展示条数，不回报被丢弃的数量）。

处置：
1. `process_call_tree` 增加逐层 `count(*) OVER (PARTITION BY …)`，同时取回
   「每个父节点的真实子节点数」，不再只拿裁剪后的行。
2. 根层的直接调用者单独放宽（`root_breadth`，默认 120），因为「谁调用我」是最高频信息；
   更深层仍按 `max_breadth` 限制。
3. 返回值新增 `direct`（每个方向的 `shown` / `total` / `capped`）与
   `truncation`（`nodes` / `breadth_parents` / `root_capped_callers` /
   `root_capped_callees` / `depth`），页面据此显示「显示 120 / 共 317」并逐条说明
   哪里有内容未展开、为什么未展开。**没有静默截断。**

对应测试：`test_root_fan_in_shows_true_total_instead_of_silent_breadth_cap`、
`test_depth_and_breadth_truncation_are_reported`。

## 6. 测试命令与精确结果

```
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest -q
```

- 全量离线回归：**1202 passed, 1 warning**（`163.95 s`，含新增 13 条）。
- 新增针对性测试 `tests/test_ti_source_view_perf.py`（13 passed）覆盖：
  SQL 次数只与层数有关（宽窄两个模型计数相同）；节点预算 / 每层广度 / 根层广度 /
  深度四种截断各自被显式上报；根层被截断时给出「显示多少 / 共多少」而不是只报展开条数；
  环去重；广度限制按父节点生效；首屏 HTML 不含 `tree-node`；
  片段端点 200/404/409 与 `no-store`；预算可配置；缓存按数据源指纹分区；
  惰性段保留完整源码文本与行锚点；前端分批渲染行为（Node）。
- 新增前端行为验收 `tests/ui/source_viewer_lazy.js`（由上面的 pytest 调用）：
  2 000 行源码首屏只渲染 800 行、`text()` 仍返回全文、`revealLine(1600)` 追加到 1 600 行、
  >1 MB 走纯文本降级但仍可定位、尖括号转义不变、重复 `mount` 不重建。
- 既有 `tests/test_human_workbench.py` 有两处随实现更新：
  资源版本断言由 `syntax.js?v=2` 放宽为 `syntax.js?v=`；
  DOM 桩补齐 `replaceChildren` / `insertAdjacentHTML` / `getBoundingClientRect`
  （桩缺标准 DOM API，不是产品行为变化；复制、CRLF 与尾随空格、转义断言原样保留）。

## 7. 性能测量及未测范围

同机、同数据源、同脚本，改造前后各测一遍（机器配置见阶段 0 文档）。
**同一台机器上反复运行的抖动约 ±20%**，因此以「SQL 次数」这类确定性指标为主证，
墙钟时间只作量级参考。

### 合成模型（warm P95 / 请求内 SQL；该脚本仍走「源码 + 调用树 + 渲染」的旧页面形状，用于可比）

| 样本 | 前 | 后 | 前 SQL | 后 SQL |
|---|---:|---:|---:|---:|
| normal | 10.6 ms | 11.6 ms | 14 | 14 |
| long（14 501 行） | 135.9 ms | 153.9 ms | 14 | 14 |
| multi_call | 32.7 ms | **16.8 ms** | 54 | 16 |
| high_fan_in | 77.9 ms | **17.5 ms** | 74 | 16 |
| loop | 30.9 ms | 29.6 ms | 14 | 14 |
| long_name | 9.8 ms | 9.8 ms | 14 | 14 |
| cycle | 11.8 ms | 12.7 ms | 16 | 16 |
| **fan_out_bomb（3 631 节点）** | **2 276.7 ms** | **64.8 ms** | **3 644** | **17** |

`long` 的 135.9 → 153.9 ms 是抖动（该样本只有 14 条 SQL，调用树 1.8 ms，未被改动）。

### 真实规模库（只读）

| 样本 | 前 warm P95 | 后 warm P95 | 前 SQL | 后 SQL |
|---|---:|---:|---:|---:|
| largest | 38.3 ms | 36.4 ms | 26 | 17 |
| highest_fan_in | 42.6 ms | 32.5 ms | 50 | 18 |
| highest_fan_out | 45.2 ms | 34.8 ms | 43 | 17 |
| median_size | 16.8 ms | 26.9 ms | 17 | 17 |
| small | 7.1 ms | 7.9 ms | 14 | 14 |

### 端到端 HTTP（打开 TI 页本身；后测取 3 轮 × 12 次的中位数）

| 样本 | 前 P95（单轮） | 后 P95（3 轮中位，范围） | 前 SQL | 后 SQL |
|---|---:|---:|---:|---:|
| largest | 75.8 ms | **57.4 ms**（56.5–69.6） | 26 | **12** |
| highest_fan_in | 69.8 ms | **50.0 ms**（49.9–51.0） | 50 | **12** |
| median_size | 43.7 ms | **41.8 ms**（40.3–43.4） | 17 | **13** |

`median_size` 的墙钟几乎没变——它的调用树本来就只有 3 ms；改善主要体现在 SQL 次数
（17 → 13）与不再阻塞源码。

真冷启动（新进程第一个请求）：822 ms → **691 ms**（仍是 DuckDB 首次打开 1.5 GB 库为主）。

### 对照建议目标

| 目标 | 结果 |
|---|---|
| 普通 TI 可读源码 P95 ≤ 1 s | **达标**（端到端 41.8–57.4 ms；真冷 691 ms） |
| 热访问 P95 ≤ 300 ms | **达标**（26.9–57.4 ms） |
| 已加载 Section 切换 P95 ≤ 100 ms | **未测（浏览器）**。已加载即无计算；首次切换只付那一段的高亮计算，同规模实测 6.6–16.5 ms（Node） |

### 明确未测

- 浏览器首屏可读时间、布局、绘制、样式重算（本机无可用浏览器内核，未联网下载）。
- 「DOM 元素数」是由行数推导的下限（每行固定 3 个元素 + 词法 token），**不是浏览器实测**。
- 真实企业模型的规模与磁盘条件（本次只有本地 Demo 数据集 3 437 TI / 3 338 Cube）。
- 多人并发下的 DuckDB 连接竞争。

## 8. 数据安全与 Git 状态

- 全程只读打开既有库（`read_only=True`）；未执行 TI、未连接任何 TM1 Server、未写服务器。
- 未修改 `data/`、`collections/`、`cache/` 下任何文件；合成模型建在系统临时目录并在结束时删除。
- 为测量高亮成本曾把最大的一个 TI 源码临时写到 `.workbuddy/`，测量完立即删除，未进入产物。
  阶段 0 产物中不含任何进程名或源码。
- 未安装依赖、未联网下载、未重建虚拟环境、未 `reset/clean/checkout`、未 push。
- 未同步另一个程序副本 `tm1-insight-master`（本次未读取它，未做差异比较）。

`git status`（本次改动范围）：

```
 M src/tm1_insight/api/app.py
 M src/tm1_insight/api/static/process-search.js
 M src/tm1_insight/api/static/syntax.js
 M src/tm1_insight/api/static/workbench.css
 M src/tm1_insight/api/templates/base.html
 M src/tm1_insight/api/templates/process_view.html
 M src/tm1_insight/store/queries.py
 M tests/test_human_workbench.py
?? docs/DELIVERY_TI_SOURCE_LATENCY_1.md
?? docs/PERFORMANCE_AUDIT_TI_SOURCE_0.md
?? scripts/measure_highlight.js
?? scripts/measure_ti_http.py
?? scripts/measure_ti_source.py
?? src/tm1_insight/api/templates/_call_tree.html
?? tests/test_ti_source_view_perf.py
?? tests/ui/source_viewer_lazy.js
```

## 9. 剩余限制

1. **调用口径仍不一致**：页头「被 N 个进程调用」取
   `process_calls_process ∪ ti_business_calls`，调用树只取前者。
   真实库上 126 个 TI 只在 `ti_business_calls` 里有调用者，因此两者的数字可能对不上。
   本次只在卡片上写明「只展开源码中可直接读到的进程名」，未改口径——属阶段 2。
2. **调用树仍是逐层两条 SQL 起**（每层一条，上下游各一遍；到达深度上限时多一条探测
   是否有更深层），未改成单条递归 CTE。当前预算下实测 17–18 条 SQL、7–10 ms；
   若将来要更深，需换实现。
3. **分批渲染是追加式**：用户一路滚到底时 DOM 会重新增长到该段总行数。
   这是「用户显式要求读全文」的场景，未做窗口回收。
4. **缓存只在进程内**：重启后第一次仍要重算；缓存上限 128 条，满了整体清空（非 LRU）。
5. **纯文本降级段（>1 MB）无法高亮**，只保证可读与按行定位。
6. **深链接与搜索的浏览器行为未实测**，只有 Node 桩与 HTML 契约测试。
7. 交接验收（两名未参与实现的开发者完成固定任务）**待验收**，本次未组织。

## 10. 下一阶段最小任务

**阶段 2 第一刀：把「谁调用我」的口径统一到一个事实生产者。**

- 先在同一合成模型上复现 126 差异：页头计数与调用树计数不一致。
- 决定唯一口径（`process_calls_process` 字面量 vs `ti_business_calls` 解析结果），
  在同一处产出「直接调用 / 间接可达 / 未解析动态调用」三类事实，各自带证据与置信度。
- 页面与导出只做投影；先逐一迁移消费者，确认无引用后才清理
  `ti_write_slices` 这类死代码。
- 验收：同一合成模型下，Cube 页、TI 页、血缘页、架构导出、Markdown、Mermaid、JSON
  对同一次写入给出相同的关系类型、方向与确认程度。
