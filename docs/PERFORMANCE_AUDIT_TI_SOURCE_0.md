# 阶段 0 — TI 源码查看路径的性能与重复职责审计

> 结论先行：**在本次可复核的环境与规模上，服务端不是秒级卡顿的来源（热请求 P95 43–76 ms）。**
> 唯一被复现的确定性退化，是「调用树按模型可达节点数线性放大」：
> 3 631 个节点 → 3 644 条 SQL、2 277 ms。其余「待核实线索」分为已证实、已证伪、未测三类，逐条列在下面。
> 浏览器侧指标（首屏可读、布局、绘制）**未测**：本机没有可离线使用的浏览器内核，不做替代性推断。

- 仓库：`master`，HEAD = `56f1977a41adf06ba19691c59ed7bb3816f8c52b`，工作区审计时为干净状态。
- 基线数据源：`data/demo`（只读打开）。规模：**3 437 个 TI / 3 338 个 Cube / 3 259 条静态调用边**。
- 合成模型：全部在临时目录建独立 DuckDB，不读取也不写入 `data/`。
- 测量工具（可复跑）：`scripts/measure_ti_source.py`、`scripts/measure_ti_http.py`、`scripts/measure_highlight.js`。

---

## A. `/explorer/process/{name}` 耗时分解

### A.1 机器与版本

| 项 | 值 |
|---|---|
| 平台 | Windows 11（10.0.22621） |
| CPU | Intel64 Family 6 Model 151，12 逻辑核 |
| Python | 3.13.12 |
| DuckDB | 1.5.6 |

### A.2 改造前 —— 真实规模库（只读，各样本 10 次，含 3 次预热后取稳态）

| 样本角色 | 代码行 | 响应体积 | 请求内 SQL | 连接 | get_process | 调用树 | 模板 | 热 P95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| largest | 1 210 | 170.6 KB | 26 | — | 21.6 ms | 12.5 ms | 1.5 ms | **38.3 ms** |
| highest_fan_in | 1 544 | 114.1 KB | 50 | — | 18.8 ms | 20.4 ms | 1.8 ms | **42.6 ms** |
| highest_fan_out | 592 | 53.8 KB | 43 | — | 18.5 ms | 13.8 ms | 1.2 ms | **45.2 ms** |
| median_size | 420 | 49.7 KB | 17 | — | 11.2 ms | 3.0 ms | 1.3 ms | **16.8 ms** |
| small | 8 | 22.0 KB | 14 | — | 4.5 ms | 0.8 ms | 1.7 ms | **7.1 ms** |

单次连接成本 P50 = **16.2 ms**；`detect_current_source()` P50 = 0.14 ms；数据源指纹 P50 = 0.15 ms。
（后两项排除：不是热点。）

### A.3 改造前 —— 合成模型（覆盖任务书要求的样本类型）

| 样本 | 代码行 | 响应体积 | SQL | 调用树 | 热 P95 |
|---|---:|---:|---:|---:|---:|
| normal | 171 | 39.0 KB | 14 | 0.8 ms | 10.6 ms |
| long（14 501 行） | 14 501 | 817.5 KB | 14 | 1.2 ms | 135.9 ms |
| multi_call（8×4 扇出） | 81 | 33.2 KB | 54 | 24.4 ms | 32.7 ms |
| high_fan_in（300 上游） | 41 | 28.9 KB | 74 | 48.6 ms | 77.9 ms |
| loop（WHILE 内 1 800 次写入） | 2 204 | 208.9 KB | 14 | 1.2 ms | 30.9 ms |
| long_name（120 字中文名） | 59 | 31.8 KB | 14 | 0.7 ms | 9.8 ms |
| cycle（A↔B） | 21 | 26.0 KB | 16 | 4.8 ms | 11.8 ms |
| **fan_out_bomb（3 631 节点）** | 21 | 25.4 KB | **3 644** | **2 270.2 ms** | **2 276.7 ms** |

### A.4 端到端 HTTP（进程内 ASGI，真实应用与真实数据源）

| 样本 | P50 | P95 | 响应 | 请求内 SQL |
|---|---:|---:|---:|---:|
| largest | 66.8 ms | **75.8 ms** | 175.2 KB | 26 |
| highest_fan_in | 66.2 ms | **69.8 ms** | 127.5 KB | 50 |
| median_size | 41.8 ms | **43.7 ms** | 51.0 KB | 17 |

**真冷启动**（新进程第一个请求）：**822 ms**；同一进程后续请求 78 ms。
其中 Python 侧 `import` 877 ms 另计；冷请求包含 DuckDB 首次打开 1.5 GB 库与模板编译。

### A.5 浏览器侧

| 指标 | 结果 |
|---|---|
| 首屏可读源码时间 | **未测**（无可用浏览器内核，未联网下载） |
| 布局 / 绘制 / 首个内容绘制 | **未测** |
| 高亮**计算**成本（Node，纯 `highlightLine`+字符串拼接） | 1 210 行 / 130 810 字符真实样本：**16.5 ms**（P50），产出 392 KB HTML、8 466 个元素 |
| 同上，等行数合成样本（46 780 字符） | 6.6 ms，7 260 个元素 |
| 高亮后 HTML 相对源码的膨胀 | **约 2.3 倍**（130 KB → 392 KB） |

高亮计算本身不是秒级问题；但它是「每段都要付一次 × 4 段」的固定税，且 2.3 倍 HTML 膨胀会放大浏览器解析与布局成本——这部分**未测**，只作为阶段 1 惰性化的依据，不作为结论。

---

## B. 测试模型

| 维度 | 合成模型 | 覆盖 |
|---|---|---|
| 普通 TI | `Normal.LoadSales`（171 行） | 基线 |
| 长 TI | `Long.Reconciliation.Deep`（14 501 行，817 KB） | 超过 1 万行降级阈值 |
| 多调用 | `Caller.Multi`（8 子 × 4 孙） | 扇出展开 |
| 高扇入 | `Hub.Shared.Calc`（300 上游，前 50 个还有第二层） | 上游展开 |
| 循环 | `Cycle.A ↔ Cycle.B` + `Loop.While.Write`（2 204 行 WHILE） | 环去重、循环体渲染 |
| 长名称 | 120 字中文名（`TI.年度预算重算…`） | 编码、链接、布局 |
| 规模放大 | `Bomb.Root`（3 631 可达节点） | 预算缺位的尾部风险 |

冷/热两态按「每次新建连接 / 复用连接」分别测量，两种状态都先丢弃 3 次预热。
合成模型刻意**低估**真实规模（无 3 000+ Cube），因此以真实规模和合成放大样本互为补充：前者校准常态，后者暴露尾部。

---

## C. 重复职责表

| 用户问题 | 当前入口 | 后端生产者 | 展示组件 | 导出消费者 |
|---|---|---|---|---|
| 这个 TI 的源码和基本信息 | `GET /explorer/process/{name}` | `queries.get_process`（14 条 SQL；`_resolve_source_cube` 每次全表读 `cubes` 并做 Python 模糊匹配） | `process_view.html` + `syntax.js` | 无（只读页） |
| 这个 TI 的调用树 | 同页右栏卡片 | `queries.process_call_tree`（改造前：逐节点一条 SQL） | `process_view.html` `render_tree` 宏 | 无 |
| 谁调用 / 调用谁的扁平清单 | `/graph` | `process_relation_graph` / `process_graph_rich` | `graph.html` + `graph.js` | `/api/architecture/tasks/{id}/export?format=flow-*` |
| 这个 TI 写了哪些 Cube | 页头、数据源头卡 | `get_process` 三个表求并集 | `process_view.html` | — |
| 这个 Cube 的值怎么形成 | `/explorer/cube/{c}`、`/api/cube/{c}/lineage`、`/api/cube/{c}/formation` | `cube_lineage`（writers 切面）；`cube_formation_view` 复用 `cube_lineage` | `cube_view.html`、`_cube_detail.html`、`cube-formation.js`、`cube-lineage.js` | 架构导出、`module_spec.py` |
| 某个 TI 的写入切面（反视角） | **无页面入口** | `ti_write_slices` —— **全仓无调用方** | — | — |
| 单 TI 计算检查 | `/calculation` | `store/calculation.inspect` | `calculation.html` | `/api/calculation/export`（json / markdown） |
| Rule / Feeder 语义 | `/explorer/cube/{c}`、`/api/cube/{c}/rules` | `cube_rule_semantics` → `learning.rule_semantics.parse_rule_semantics`（**单一解析器**，无第二套） | `cube_view.html`（rule-raw / rule-analysis） | `module_spec.py`、`api/workbench.py`、架构导出 |
| 架构 / 功能流程 | `/architecture` | `architecture_extraction` + `functional_flow` | `architecture.html` | json / markdown / mermaid / human-markdown / ai-package |
| TI 代码全文搜索 | `/processes?scope=code`、`/api/processes/search` | `queries.search_process_page`（SQL + 文本定位） | `processes.html` + `process-search.js` | — |
| 页内代码搜索 | 右栏搜索框 | 无后端；改造前每次输入遍历全部已高亮 DOM 行 | `process_view.html` 内联脚本 | — |

### C.1 分类结论

**必要的多入口**（保留）
- `get_process` 同时服务 TI 页与 TI 切换器（`api/workbench.py`），消费者不同、投影不同。
- `process_relation_graph`（扁平、供 SVG）与 `process_graph_rich`（带预算的递归、供知识图谱）服务不同页面，不是重复。
- `cube_rule_semantics` 有 5 个消费者但只有 1 个解析器，属于正确的单一生产。

**可合并的展示**（后续可收敛，本次不动）
- 「调用树」与「引用关系图」是同一事实（`process_calls_process`）的两种呈现。
  两者都应只做投影；本次先把调用树改成有预算的按需加载，未合并 UI。

**重复的事实生产**（阶段 2 处理）
- `queries.ti_write_slices` 与 `cube_lineage` 的 `writers` 是两份手工复制的切面组装逻辑
  （源码注释自认「与 `cube_lineage` 的 writers 完全一致」），且 `ti_write_slices` **全仓无消费者**。
- `get_process` 的 `called_by` 取 `process_calls_process ∪ ti_business_calls`，
  而 `calls_process` / 调用树只取 `process_calls_process`。
  在真实库上实测：**126 个 TI 只在 `ti_business_calls` 里有调用者**，
  即页头「被 N 个进程调用」与调用树可能对不上。
  根因是两张表口径不同：`process_calls_process` 来自正则抓字面量进程名，
  `ti_business_calls` 来自解析器解析（含变量解析出的目标）。

**需要兼容保留的旧接口**
- `/explorer/process/{name}?source=<64 位指纹>`：指纹失效必须继续返回 409 且不用于定位。
- `/api/processes/search` 的 `source`/`scope`/`offset` 契约与 `no-store`。
- `/api/cube/{c}/lineage`、`/api/cube/{c}/rules`、`/api/cube/{c}/formation`。
- `/calculation?name=&source=` 与 `/api/calculation/export`。

---

## D. 待核实线索的裁定

| 线索 | 裁定 | 证据 |
|---|---|---|
| ① `/explorer/process` 同步构建 `process_call_tree` | **成立** | 首屏固定多付 12–20 ms；规模放大样本上 2.27 s |
| ② 递归逐节点发 SQL | **成立，且是主因** | 3 631 节点 → 3 644 SQL；SQL 次数与节点数 1:1 |
| ③ `get_process` 读源码 + 解析变量 + 多关系查询 | **成立但量级小** | 固定 14 条 SQL；最大样本 21.6 ms，其中 `_resolve_source_cube` 需全表读 3 338 个 Cube 名 |
| ④ 一次发四个 Section | **成立，但代价不在字节** | 817 KB 长样本仅 +4.3 ms 模板；代价在浏览器端逐行高亮（未测） |
| ⑤ `syntax.js` 逐行生成高亮 DOM | **成立，量级不大** | 1 210 行 16.5 ms 计算、8 466 元素、HTML 膨胀 2.3×；浏览器布局未测 |
| ⑥ 源码搜索在输入时遍历 DOM | **成立** | 每次 `input` 事件对全部 `.code-line` 做 `textContent` 比对，无防抖 |
| ⑦ 多页面/导出各自判断来源与写入投影 | **部分成立** | Rule 语义只有一个解析器（否）；写入切面有两份实现，其中一份是死代码（是） |
| ⑧ 分析包的维度资料可能只是采样摘要 | **本次未审计** | 属阶段 3 范围，未读取分析包内容 |

**审计中另发现（非性能线索，但更严重）**：调用树的 `max_breadth` 只限制**展示条数**，
不回报被丢弃的数量。真实库中扇入最大的 TI 有 317 个直接调用者，页面却显示「被调用（20）」，
且没有任何截断提示——这是静默截断，违反产品的事实规则。已在阶段 1 一并修复
（见 `docs/DELIVERY_TI_SOURCE_LATENCY_1.md` 第 5.1 节）。

**未测项**：浏览器首屏可读时间、布局与绘制、真实企业模型（本次只有本地 Demo 规模）、
网络/机械盘条件下的 I/O、多人并发下的 DuckDB 竞争。

---

## E. 阶段 0 的处置

阶段 1 只处理被证实且影响最大的三项：调用树的规模放大（②①）、四段全量高亮（⑤④）、
输入即遍历 DOM 的搜索（⑥）。其余线索保留原状，不在本次扩大改动面。
