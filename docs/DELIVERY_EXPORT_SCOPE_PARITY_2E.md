# 阶段 2 第五刀：导出跟随页面范围（并且自己把差异说清楚）

> 触发：用户「继续，该推推」。
> 上一阶段文档 `DELIVERY_COLLECTION_SCOPE_2D.md` 第 9.5 条自己记着一笔：
> 「导出仍未跟随范围，与本轮无关但仍是已知不一致」。这一刀把它结掉。

## 1. 用户问题

计算检查页早就按 `}` 前缀隐藏了系统写入点，页面上写着「已隐藏 1 条」。
但点「下载 JSON / 下载 Markdown」，拿到的却是**全量**：

- 屏幕上 14 条，文件里 15 条；
- 文件里没有任何一句话说明多出来的那条是什么、为什么在、怎么去掉。

核对材料的人第一反应是自己数错了，第二反应是这两份东西根本不是同一批数据。
无论哪种，工具都在让他怀疑自己——比少一个功能更伤。

## 2. 根因

不是漏写过滤，是**同一条规则被写了两遍，而且其中一遍没写**：

```python
# app.py 页面：就地过滤
items = [w for w in report['writes'] if system or not (w['cube'] or '').startswith('}')]
```

```python
# app.py 导出：直接整包吐出
report = _calculation_report(name, source)
content = markdown(report) if format=='markdown' else json.dumps(report, ...)
```

两处没有任何共享判断，也没有任何一处负责「我少了东西，得说一声」。
调用检查页（`/invocation`）同病：它压根没有 range 开关，导出更是全量。

## 3. 真实库证据（只读，未改任何数据）

库：`data/db/tm1_insight.duckdb`（1.4 GB，旧版采集，仍含 2 282 个 `}` cube、273 个 `}` 进程）。

抽 120 个源码里出现 `CellPutN(..., '}...')` 的 TI，逐个跑 `calculation.inspect`：

```
扫描 120 个，有写入点 118 个，受影响 63 个（53%），共隐藏 329 条写入点，耗时 5.6s
被隐藏的目标：}APQ Process Response Message 39 · }APQ Process Execution Log 26
              · }APQ Dimension Static Subsets And UDC 2 · 其余长尾
```

两个具体样本：

| TI | 全部写入点 | 页面可见 | 隐藏 | 被隐藏的目标 | 编号变化 |
|---|---:|---:|---:|---|---|
| `LOCAL.Caller` | 21 | 18 | 3 | `}APQ Process Response Message` | `0…20` → `0…5, 9…20`（空 6/7/8） |
| `1 add element` | 23 | 20 | 3 | 同上 | `0…22` → `0…5, 9…22` |

也就是说：**过半的 TI 在默认视图里少了东西**。这不是边角，所以更不能悄悄发生。

顺带查清一个容易误会的地方：`process_writes_cube` 这张表里**一条系统写入点都没有**
（2 752 条全是业务）。那是血缘图的既有口径——`is_framework_read` 明确把 `}` 开头的读取
判成「对业务血缘无意义」而丢弃。计算页的写入点不走这张表，是 `worksheet()` 直接解析源码，
所以两边数字本来就不会相等。这是历史设计，本轮不动，但记在这里免得下次又当成 bug 查一遍。

## 4. 改了什么

| 文件 | 改动 | 兼容性 |
|---|---|---|
| `store/scope_view.py`（新增） | `narrow_report` / `narrow_invocation` / `scope_lines`，范围过滤的唯一实现，复用 `ingest.scope.is_system_object` | 纯函数，不改入参 |
| `api/app.py` | `/calculation`、`/invocation` 页面改用 `narrow_*`；两个导出接口新增 `system` 参数，默认 `False` | 默认返回**变少**——这是本轮的本意 |
| `store/calculation.py` | `markdown()` 读取 `report['scope_view']`，输出「## 收录范围」段 | 无 `scope_view` 时整段省略，旧调用方行为不变 |
| `store/invocation.py` | 同上 | 同上 |
| `templates/calculation.html` | 导出卡文案改为「导出当前可见的 N 条」；链接带 `system`；有隐藏时多给一个「全量 JSON」 | 文案按数据切换 |
| `templates/invocation.html` | 新增逐参数「还有 N 条使用位置被隐藏」；导出链接带 `system`；给「包含/只看业务」切换 | 新增 URL 参数，旧链接仍可用 |
| `tests/test_export_scope_parity.py`（新增） | 8 条 | — |
| `tests/test_calculation_api.py` | 原断言 `len(writes)==2` 改为 `==1` + 全量 `==2` | 断言即契约 |

## 5. 四个关键决定

**① 编号不重编。** 隐藏第 6/7/8 条后，页面第 4 条仍然叫「写入 4」，不改成「写入 3」。
重编号看着更整齐，代价是同一份材料在两种视图里指向不同记录——对账直接失效。
跳号是诚实的痕迹，正文里补一句「缺的那几个就是被隐藏的记录」。

**② 只收「能独立成条的清单」。** 写入点、参数使用位置收；DAG 节点不收。
砍节点会打断 `children` 引用，而依赖图本来不是「收录清单」，是「这张图为什么这么推」的依据。

**③ 参数使用位置被隐藏，必须逐参数喊停。** 这是本轮最危险的一处：
`pAmount` 在子 TI 里写了两个立方体（业务一个、`}Audit` 一个），隐藏后只剩一条；
如果不说，读的人会得出「这个参数只用了一次」甚至「这个参数没被用到」的结论。
所以每个受影响的参数卡片下面都有一行：

> 范围 · 还有 1 条使用位置指向 } 前缀立方体，已按页面范围隐藏；此处偏少不等于该参数未使用。

导出正文里补一句更狠的：「空白不等于未使用，需按全量重新导出一份再判读。」

实测还发现波纹不止在目标参数上：`pDept` 作为 `}Audit` 的**坐标**也少了一条使用位置。
所以受影响参数个数要单独记（`bindings_affected`），不能只报总数。

**④ 没有隐藏时也要写一行「本次没有」。** 否则读的人分不清
「这个 TI 真没有系统写入」和「被悄悄过滤了」。三种状态各有各的话：
全量 / 有隐藏 / 无隐藏。

## 6. 前后对比

| 场景 | 改前 | 改后 |
|---|---|---|
| 页面可见 18 条、下载 JSON | 文件里 21 条，无说明 | 文件里 18 条 + 「另有 3 条未包含，指向 `}APQ Process Response Message`」 |
| 想知道被藏了什么 | 只能自己猜、或去翻源码 | 加 `&system=1`，同一地址拿到全量，范围段自动变成「全量」 |
| `LOCAL.Caller` 核对材料 | 编号 0–20 连续 | 0–5、9–20，跳号处即隐藏处，正文有解释 |
| `/invocation` 某参数「只用过 1 次」 | 可能是假的 | 卡片下方明确写还有几条被隐藏 |
| 没有系统写入的 TI | 「已隐藏 0 条」（像在说废话） | 「这个 TI 没有 } 前缀写入点」 |

## 7. 测试

```bash
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_export_scope_parity.py -q
# 8 passed, 1 warning

PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest -q
# 1250 passed, 1 warning in 162.47s
```

新测试钉住的是「一致性」本身，不是某个数字：

1. 页面 `<span class="tag">` 里的条数 == 导出 JSON 的 `writes` 长度；
2. `system=1` 拿回全部，且 `scope_view.scope == 'all'`；
3. Markdown 正文包含「收录范围 / 另有 N 条 / `}Audit` / system=1」四要素；
4. 系统写入点排在前面时，剩下的那条保持原编号（`[1]`），Markdown 出现「## 写入 2」且没有「## 写入 1」；
5. 没有系统写入时不撒谎：「这个 TI 没有 } 前缀写入点」，且不出现「已隐藏 0 条」；
6. 调用页：`uses_hidden` 逐参数为 `[1, 1]`（`pAmount` 与 `pDept` 都被波及），
   全量 5 条使用位置按 `Result:3 / }Audit:2` 分布，`visible_uses == 3`；
7. 调用页切到 `system=1` 后能看到 `}Audit`，且页面上有路回「只看业务对象」；
8. `system=maybe` 之类垃圾值返回 422，不静默当成 `false`。

## 8. 性能

`narrow_*` 是 O(写入点数) 的列表推导，实测 21 条写入点的 TI 看不出差异；
不新增 SQL，不新增连接，`scope_view` 只做内存过滤。

## 9. 剩余限制

1. **页面没在真实浏览器里走一遍**：本轮验证到 `TestClient` 渲染 + 真实库数据，
   没有做浏览器端到端（无可用浏览器环境）。模板里新增的 `url(system=0 if system else 1)`
   走的是已有 `url()` 辅助函数，但仍建议人工点一次。
2. **两套写入口径并存**：`process_writes_cube`（血缘用，滤掉 `}`）与
   `worksheet()` 写入点（计算检查用，不滤）。页面上的数字与血缘图上的数字天然不等，
   目前没有任何一处解释这件事——值得下一刀统一，或在血缘图上给出口径注脚。
3. **`usage.cube` 对 `read_coordinate` 语义偏**：`invocation.py` 里 usage 一律写
   `cube=write['cube']`，所以 `role=read_coordinate` 的 `cube` 标的是**写入目标**而非读取源。
   本轮读代码时发现，未改（会动现有页面文案），记在此处。
4. **老库未重采集**：`data/db` 仍是 2D 之前采的，2 282 个 `}` cube / 273 个 `}` 进程还在库里。
   要真正瘦下来，得重新采集或用 `prune-system-objects --apply`（未执行，需授权）。
5. 导出文件名固定为 `TI_Calculation.json` / `TI_Invocation.json`，没有带上范围标记，
   同一个目录里可能并存两份不同范围的文件而名字相同。可用文件名加 `-all` 后缀解决，
   但会改变既有下游脚本的预期，故本轮未动。

## 10. 下一阶段建议

把「范围」从一个散落的 URL 参数变成一个**常驻显示**的状态条：
两页顶部一行「当前范围：业务对象 · 已排除 3 条 · 切到全量」，与导出链接共用同一状态。
现在虽然有切换链接，但它只在有隐藏时出现，使用者未必意识到自己处在一个被裁剪过的视图里。
