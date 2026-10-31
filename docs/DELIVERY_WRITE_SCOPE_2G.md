# 阶段 2 第七刀：把「两套口径」的差说清楚（而不是硬拉齐）

> 触发：用户第三次「继续，该推推」。
> 上一轮我预告要「统一两套写入口径」。先做调研，然后**改了计划**——原因写在第 2 节。

## 1. 原本的判断

我以为血缘图（`process_writes_cube`）和计算检查页（`worksheet` 解析出的写入点）
是两套各自过滤的口径：一个滤 `}`，一个不滤。所以「同一个 TI 两处显示两个数」，
需要把它们拉齐。

## 2. 调研之后：不该拉齐

先看过滤判据本身：

```python
# lineage.py
LOG_CUBE_PATTERNS = ["}APQProcessExecutionLog", "}APQ Process Response Message",
                     "}Sys Process Execution Log", ...]        # 写入侧：只滤这 6 个名字
def is_framework_read(rp): return source.startswith("}")        # 读取侧：滤全部 }
```

写入侧**不是按 `}` 前缀过滤**，只滤 6 个具名日志 cube。再拿真实 TI 对账：

| TI | 计算页写入点 | 涉及 cube | 血缘表 cube |
|---|---:|---|---|
| `LOCAL.Caller` | 21 | `}APQ Process Response Message` + 18 条 UNKNOWN | 空集 |
| `Cub. Ckd Consignment Report.Update.Put` | 58 | 3 个业务 + `}APQ Process Response Message` + 23 条 UNKNOWN | 3 个业务 |

第二个样本是决定性的：**血缘表三个业务 cube 一个不少，少的只有那条日志。**

也就是说，两套口径的差异**精确等于一类东西：日志 cube**。
血缘图不追踪日志是**有意**的（每个 TI 都写日志，画进图里会把图淹掉），
计算页列出每一处 `CellPutN` 也没有错。两边都不算错。

错的是第三件事：**没有任何一处告诉使用者这个差从哪来**。
于是「把两个数字拉齐」这个目标本身就是错的——真拉齐了，血缘图反而会被日志噪音毁掉。

改成：**保留差异，把差异分类并命名。**

## 3. 做法：写入目标三分类

新增 `scope_view.target_kind(cube)`：

| 返回 | 判据 | 含义 |
|---|---|---|
| `log` | 命中 `LOG_CUBE_PATTERNS` | 执行日志。每跑一次写一条，血缘图有意不追踪 |
| `system` | `}` 前缀 | TM1 系统对象（`}Audit`、`}ElementAttributes_*` …） |
| `plain` | 其余 | 业务立方体 |

**日志优先于系统**：日志 cube 也带 `}` 前缀，但「这是日志写入」比
「这是个系统对象」对使用者有用得多。

判据不在新模块里重写：`ingest.lineage.is_log_cube`（本轮把 `is_log_write` /
`is_log_read` 里重复的两段清单匹配抽出来）与 `ingest.scope.is_system_object`
各管一头，`scope_view` 只组合。

隐藏判据随之变成 `log ∪ system`——这恰好**与血缘图的写入过滤对齐，再叠加系统对象**。
于是计算页剩下的业务目标，和血缘表的业务目标，应该是同一批。

## 4. 对齐验证（真实库，只读）

拿 60 个源码含 `CellPutN(..., '}...')` 的 TI 逐个比对「计算页可见业务 cube 集合」
与「`process_writes_cube` 集合」：

```
比对 59 个 TI：一致 49 个（83%），不一致 10 个
有「只在计算页」cube 的 TI: 0
有「只在血缘表」cube 的 TI: 10
```

**方向完全单边**：没有任何一个 TI 出现「计算页有、血缘表没有」的业务 cube。
那 10 个不一致全是血缘表更全——因为它还包括数据源声明（`DatasourceNameForServer`）
和 bedrock 参数传递的写入目标，计算页只列 `CellPutN/S/IncrementN` 语句。

这条结论比「83% 一致」更重要：**计算页不会凭空多出业务目标**，
多出来的只可能是日志，而日志现在有名字了。

## 5. 用户看到的变化

之前（`LOCAL.Caller`）：

> 另有 3 条 } 前缀写入点未显示 · 包含它们

现在：

> 另有 3 条写入点未显示（3 条日志写入）：}APQ Process Response Message。
> 血缘图同样不追踪日志写入

导出 Markdown 的「收录范围」段相应变成：

```markdown
- 范围：业务对象（不含 } 前缀与日志立方体），另有 3 条记录未包含在本文件内。
  - 构成：3 条日志写入。
  - 被隐藏的记录指向：`}APQ Process Response Message`。
  - 日志写入是每跑一次就写一条的执行记录，血缘图有意不追踪；它不代表业务数据流向。
  - 需要全量：同一地址加 `system=1`，本段会随之变成「全量」。
```

「日志」和「系统对象」分开计数、分开措辞。合并成「3 条系统记录」是省字，
但把两种完全不同的解释糊成一种。

## 6. 改了什么

| 文件 | 改动 |
|---|---|
| `ingest/lineage.py` | 新增 `is_log_cube(name)`；`is_log_write` / `is_log_read` 复用它（删掉两处重复的清单匹配） |
| `store/scope_view.py` | 新增 `target_kind` / `is_hidden_target`；隐藏判据 `log ∪ system`；`info` 增加 `log` / `system` / `log_cubes`；新增 `hidden_text()` 生成一句话；`scope_lines()` 分开陈述两类 |
| `api/app.py` | 两个页面上下文传 `scope_note` |
| `api/templates/calculation.html` | 状态条用 `scope_note`；导出卡措辞改为「日志或系统目标」；全量按钮改「含日志与系统对象」 |
| `api/templates/invocation.html` | 同上；参数卡片警告改为「日志或系统立方体」 |
| `tests/test_export_scope_parity.py` | 新增 2 条；5 处文案/结构断言更新 |
| `tests/test_calculation_api.py` | `scope_view` 断言补齐新键 |

## 7. 测试

```bash
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_export_scope_parity.py -q
# 13 passed, 1 warning

PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest -q
# 1255 passed, 1 warning in 158.97s
```

新增两条：

1. `target_kind` 的纯函数用例：`}` 前缀的 `}Audit` 是 `system`，
   同样带 `}` 的 `}APQ Process Response Message` 是 `log`，
   不带 `}` 的 `Sys Process Execution Log` 也是 `log`（子串匹配，与血缘侧一致）；
2. 页面级：日志写入被隐藏时，状态条说「1 条日志写入」而**不是**「指向系统立方体」，
   Markdown 含「日志写入是每跑一次就写一条的执行记录」，`scope_view.log == 1`。

## 8. 性能

`target_kind` 是 6 次子串匹配 + 1 次前缀判断，对每个写入点调用一次；
实测 `Cub. Ckd Consignment Report.Update.Put`（58 个写入点）无可测差异。
无新增 SQL、无新增连接。

## 9. 剩余限制

1. **读取侧仍不对称**：写入侧只滤日志，读取侧 `is_framework_read` 滤**全部** `}`。
   计算页的读取依赖没有同样的分类，所以「这个 TI 读了哪些 cube」在两处仍可能不同。
   本轮只处理写入侧，读取侧留待下一刀（要动 `process_reads_cube` 的生产口径）。
2. **83% 一致的另外 17% 没解释到页面**：血缘表多出的那 10 个 TI 差异来自
   数据源声明与 bedrock 参数传递，计算页确实不列这些。两边都合理，
   但页面上没有说明「血缘图看到的写入并不都来自 CellPutN 语句」。
3. `hidden_text()` 的文案把最多 3 个 cube 名塞进一句话，cube 名很长时状态条会换行变高；
   没有做截断或 tooltip。
4. 暗色主题下新增文案的观感仍未截图确认。
