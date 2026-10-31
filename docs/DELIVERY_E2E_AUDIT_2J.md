# 2J · 真实库端到端巡检

范围这条线（2C→2I）一直是**单点修**：改一处、跑单测、推。八刀下来，单元测试 1267 条全绿，但从未在真实库上把整页渲染出来从头走到尾。

历史上出问题的地方恰好都在「层与层之间」：

| 出过的事 | 层 |
|---|---|
| 页头说 131，树里 1996 | 两个函数各算一遍 |
| 导出 15 条，页面 14 条 | 模板与端点各过滤一次 |
| 折叠后空树说「未记录」 | 数据层对，模板说错话 |
| 121 个上游节点类型标错 | 值传对了位置，贴错了对象 |

单测逐层验，正是验不出这类。所以这一轮不加功能，把真实库打开跑一遍。

## 巡检工具（只读，可重复）

两份脚本放在 `tests/` 下，文件名不以 `test_` 开头，不进 pytest 默认收集：

- `tests/audit_scope_e2e.py` — **store 层**：条数守恒、编号不重编、分类自洽、读取依赖不裁剪、调用树位置能指回调用行
- `tests/audit_pages.py` — **渲染层**：从渲染后的 HTML 里抠数字，与导出 JSON、与库比对

分工是刻意的：第一份验「账本对不对」，第二份验「模板有没有各算一遍」。

跑法：

```bash
./.venv/Scripts/python.exe tests/audit_pages.py
./.venv/Scripts/python.exe tests/audit_scope_e2e.py
```

两份都只读，不写 `data/`。

## 发现一：日志判据是按合成模型写的

第一条巡检就把 `APQ.Process.Execute` 打出来了：6 条写入点，全部指向 `}APQ Process Execution Log`，但分类是 **system**（系统立方体），不是 log。

原判据（`ingest/lineage.py`）是一份**字面清单**：

```python
LOG_CUBE_PATTERNS = ["}APQProcessExecutionLog", ...]   # 紧凑，无空格
return any(pat in target for pat in LOG_CUBE_PATTERNS) # 子串匹配
```

真实库里那个 cube 叫 `}APQ Process Execution Log`，**带空格**。`"}APQProcessExecutionLog" in "}APQ Process Execution Log"` 为 `False`，于是降级。

更麻烦的是：`ingest/hard_extract.py` 里**另有一份**判据，用的是正则 `}APQ.*Log`，它认得带空格的。两份判据，两个答案：

| 判据 | 认出的日志 cube（全库） |
|---|---:|
| `hard_extract`（正则） | 27 |
| `lineage`（字面子串） | 6 |

差 21 个，其中包括真实存在的 `}APQ Process Execution Log`、`}APQ Server Message Log Info`、`}APQ TM1 Transaction Log Analysis`。

### 为什么测试全绿

`store/codegen.py` 生成的合成模型用的是紧凑名字：

```
}APQProcessExecutionLog   ← 合成模型
}APQ Process Execution Log ← 真实企业模型
```

测试照合成模型造数据，判据也照合成模型写，两边一起错，于是对得上。而 `codegen.py` 里甚至有一句注释信誓旦旦地说「真实框架里日志 cube 名是紧凑无空格的（不是 `}APQ Process Execution Log`）」——**这句是错的**，真实库里就是带空格的。

这句注释已经改掉，并注明两种写法都要认。

### 改法

判据合并到 `hard_extract` 一处，`lineage.is_log_cube` 只做转发，删掉自己那份清单。测试里加了一条 `test_one_log_criterion_not_two`，逐样例比对两个入口的结果必须相同，并断言 `LOG_CUBE_PATTERNS` 不再存在于 lineage。

顺带修正一处反向错误：`}APQ Dimension Subsets` 原来被 lineage 判成日志，它是 APQ 的注册表，不是日志，现在归 system。

## 发现二：写入点全被收起时，页面说「没有」

`APQ.Process.Execute` 的 6 条写入点全是日志，默认范围下可见 0 条。页面当时写：

> 当前范围没有可展示的 CellPutN/S 或 CellIncrementN 写入点；其他写入机制未覆盖。

详情区写：

> 选择一个写入点，或核对子进程边界

两句都错。它写了 6 条，只是看不见；而「选择一个写入点」是让你从空列表里选。

这是 2H 修读取侧那个错误**在写入侧的同一个错误**：空结果被说成不存在。当时只修了读取，没回头看写入。

现在三态分开：

| 情况 | 列表区 | 详情区 |
|---|---|---|
| 全被收起 | `6 条写入点全部落在日志立方体上，已按页面范围收起——不是这个 TI 不写数据，而是这些写入看不见` | `这个 TI 的写入点全在日志或系统立方体上` |
| 列表为空但确有隐藏之外的原因 | `当前范围没有可展示的 …写入点；其他写入机制未覆盖` | `这个 TI 没有可解析的写入语句` |
| 正常 | 列表 | 选中项 |

## 真实库量化

只读扫描 2990 个含系统写入的 TI：

| 项 | 数量 |
|---|---:|
| 有系统写入的 TI | 2990 |
| 写入点部分被收起 | 1515 |
| 写入点**全部**被收起（页面曾说「没有写入点」） | **3** |
| 被隐藏写入点合计 | 4708 |
| 其中日志 | 4645（98.7%） |
| 其中其他系统立方体 | 63（1.3%） |

三个全收起的 TI：`APQ.Process.Execute`、`Dim.PR Base Code.Combined PR Family Code Update.Caller`、`Sys.Client.Add.Invest`。数量少，但每一个都是「页面说没写数据、实际写了 6 条」。

同时这张表回答了一个老问题：**被折叠的几乎全是日志**（98.7%）。2G 判断「两套口径的差异精确等于日志这一类」，在 2990 个 TI 的规模上成立。

## 验证

- 全量 **1270 passed**（1267 + 3 条新测试，另有一处样例重名调整）。
- 两套巡检在真实库上全绿：store 层 42 个 TI / 880 个写入点 / 146 条读取依赖 / 25 棵调用树；渲染层 21 个 TI / 10 棵调用树。
- `data/`、`collections/`、`cache/` 零改动；真实库全程 `read_only=True`。
- 提交 `2J`。

## 遗留

1. **`excluded_objects` 仍是 0 行**：demo 库没跑过 `prune-system-objects --apply`。dry-run 试算与 2D 记录一致（对象 11953 = 维度 9584 + 立方体 2096 + 进程 273；保留的引用边 8834 + 1411 + 1）。真正执行会写库，等授权。
2. **同类隐患还有两处**：`loader.py` 的 `FRAMEWORK_CUBES` 里有 `}APQProcessParametersInfo`、`}APQProcessParallelizationControl`，也是紧凑命名。真实库里这两个对象不存在（未安装并行化扩展），所以当前无影响，但同样是「按合成模型写死」。
3. **两份库并存**：`data/db`（1.44 GB）与 `data/demo/db`（1.49 GB，应用默认打开的）。巡检跑在后者。两份内容可能不同步，需要时再对账。
4. 前端点击仍未做浏览器端到端验证（环境无浏览器）。

## 一句话

前八刀修的是「这一处算错了」。这一刀修的是「**这一处按我们自己的假数据写对了，按客户的真数据算错了**」——后者单测永远抓不到。
