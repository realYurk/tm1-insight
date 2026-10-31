# 阶段 2 第四刀：采集时就不收系统对象（但把「没收」记成账）

> 触发：用户「采集时就不收 `}` 对象，其余继续」。
> 上一轮只是把系统对象从默认视图里折叠，数据和采集范围没变；这一轮动的是**范围本身**。

## 1. 解决的用户问题

`}` 开头的对象（`}bedrock.*`、`}APQ.*`、`}ElementAttributes_*` …）占了本机模型的绝大部分：
3 437 个进程里 273 个、2 096 个立方体里 2 096 个、9 584 个维度里 9 584 个。

它们不该出现在使用者的日常视图里，也不该占用采集时间与磁盘。但**「不收」和「不存在」是两件事**：
如果只把对象删掉，下游会把这些对象判成「目录中不存在」——用新的假事实换掉旧的噪音，
比噪音更糟。所以这一轮的目标是：**对象不收，名字留账，边一条不删**。

## 2. 证据与根因（先量，再改）

只读试算（`data/demo`，`scope_prune.survey`，未做任何修改）：

```json
{
  "objects": {"processes": 273, "cubes": 2096, "dimensions": 9584},
  "object_total": 11953,
  "already_excluded": 0,
  "referencing_edges": {
    "process_calls_process": 1411,
    "ti_business_calls": 1,
    "ti_framework_calls": 8834
  }
}
```

构成（按前缀分组）：

| 表 | 总量 | 主要构成 |
|---|---:|---|
| processes | 273 | `}APQ*` 113 · `}bedrock*` 91 · `}Drill_*` 等 69 |
| cubes | 2 096 | `}ElementAttributes_*` 1 573 · `}APQ*` 64 · `}Cube*` 23 · `}Stats*` 7 |
| dimensions | 9 584 | `}ElementAttributes_*` 1 575 · `}APQ*` 137 · `}Hierarchies_*` 等 |

结论：**83% 的对象是系统对象**。真正的根因不是「视图没过滤」，而是「采集范围与使用者关心的范围不一致」。

## 3. 复用的能力

- `store.calls`：分类口径（literal / framework / missing / dynamic）+ 来源标记，本轮只加了一列 `in_catalog`。
- `process_call_tree` 的 `include_system` 折叠与 `hidden_system` 报数，行为未变。
- `_call_tree.html` 的节点渲染，新增一个 catalog 分支，其余复用。
- `_reconcile_names` 的名称级对账，新增「按范围跳过不算缺失」。

## 4. 修改文件与兼容

| 文件 | 改动 | 兼容性 |
|---|---|---|
| `config.py` | 新增 `tm1_include_system_objects: bool = False` | 默认不收；设为 `true` 恢复旧行为 |
| `ingest/scope.py`（新增） | `is_system_object` / `split_by_scope` / `EXCLUDED_REASON` | 采集规则的**唯一实现**，exporter 与 collector 都只调用它 |
| `ingest/exporter.py` | 枚举后按范围裁剪，写 `raw/_excluded.json`，`_index.json` 增加 `excluded` 段 | 旧 raw 包没有该文件时按「未排除」处理 |
| `collector.py` | `collect_snapshot(..., include_system=False)`，payload 带 `excluded` | 调用方不传参时行为改变（默认不收）——这是本轮的本意 |
| `ingest/loader.py` | 导入时同样跳过（否则旧 raw 一重导就全回来）；跳过的不算「缺失」；合并两份排除清单写表 | 需 `--include-system` 才能导入系统对象 |
| `store/schema.py` | 新增 `excluded_objects(name, kind, reason)` | `CREATE TABLE IF NOT EXISTS`，旧库自动补 |
| `store/calls.py` | CTE 增加 `in_catalog` 列；`excluded_names()`；`callees[*].in_catalog` | 旧库无 `excluded_objects` 时返回空集，行为与改造前一致 |
| `store/queries.py` | 树节点增加 `catalog`（included/excluded/missing）与 `catalog_counts` | 旧数据无 `catalog` 字段时模板按 `kind` 兜底 |
| `api/templates/_call_tree.html` | 未收录节点灰字标「未收录」，不给链接；图例报未收录数 | 纯展示，无接口变化 |
| `api/templates/processes.html` | 收敛后改为「另有 N 个系统对象按采集范围未收录」 | 文案按数据是否存在切换 |
| `api/app.py` | 列表页统计 `excluded_objects` | 旧库无该表时计 0 |
| `store/scope_prune.py`（新增） | `survey` / `prune(apply=False)` / `excluded_targets` | 默认 dry-run，一行不改 |
| `cli.py` | `prune-system-objects [--apply]` | 新命令，无副作用除非显式 `--apply` |

## 5. 前后效果（真实数据核算，未执行）

| 场景 | 改前 | 改后 |
|---|---|---|
| 新采集的对象表 | 11 953 个系统对象全量入盘 | 0 个（名字进 `excluded_objects`） |
| 调用边 | 8 834 条指向系统对象 | **不变**，仍是 8 834 条 |
| `}bedrock.cube.data.clear` 的调用方 | 1 996（可点开） | 1 996（灰字「未收录」，不可点） |
| 详情页 `/explorer/process/}bedrock.*` | 可打开源码 | 404（对象不在目录） |
| 列表页 | 「其中 273 个是系统对象」 | 「另有 273 个系统对象按采集范围未收录」 |

**代价要说清**：`}bedrock.*` 的源码从此看不到（除非把配置改回 `true` 重新导入）。
`raw/` 下的 JSON 文件仍在，`prune` 只动库、不动 raw，所以这是可逆的。

## 6. 测试命令与精确结果

```bash
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest tests/test_collection_scope.py -q
# 17 passed, 1 warning
```

覆盖：

1. 只看前缀：`A}B` 不算系统对象，`APQ.*` 也不算（不猜名字形状）；
2. collector 默认不拉 `}` 对象，payload 带 `excluded`；`include_system=True` 时全收；
3. loader 读清单建表、清单缺失不报错、跨类同名只插一次；
4. **框架目标不在目录时仍是 framework，不降级成 missing**（这是本轮最关键的一条）；
5. 非 `}` 目标不在目录才是 missing —— 两类必须分开；
6. 树节点文案是「未收录」而不是「目录中无此 TI」，且不给会 404 的链接；
7. 收敛（`prune --apply`）后：对象移出、名字登记、**调用边一条不少**；
8. dry-run 一个字节不改；
9. 重复执行幂等；
10. 列表页在对象表为空时仍报「另有 N 个未收录」。

## 7. 性能

- 采集：少拉 11 953 个对象正文，其中 9 584 个维度文件是最贵的一块（本机维度目录近 1 GB），
  预计采集与入库时间显著下降。**本轮未实测采集耗时**（不能连企业 TM1，无真实采集窗口）。
- 查询：`in_catalog` 复用已有的 `LEFT JOIN processes`，零额外查询；树仍是一条 SQL。
- `excluded_objects` 只有千级行，`excluded_names()` 一次全取，内存 set 查找。

## 8. 全量回归

```bash
PYTHONPATH=src ./.venv/Scripts/python.exe -m pytest -q
# 1242 passed, 1 warning
```

## 9. 剩余限制

1. **未在真实 1.4 GB 库上执行 `--apply`**：只读试算给出的是数字，实际收敛由使用者决定
   （安全边界：不擅自改正式 DuckDB）。
2. **未实测采集耗时**：禁止连企业 TM1，只能给出「少 11 953 个对象」的静态结论。
3. `}ElementAttributes_*` 维度被移除后，维度属性分析（属性存在性、层级定义）会缺失；
   `}Hierarchies_*` 移除后，多层级（alternate hierarchy）分析同样缺失。这两块目前
   没有页面在展示，但属于「将来要用就没有了」的取舍。
4. `cube_has_dimension` / `process_reads_cube` 中的系统对象引用会变成悬空引用，
   与调用边同理：保留事实，但目标不可打开。
5. 导出（`/api/invocation/export`、`/api/calculation/export`）仍未跟随范围参数，
   与本轮无关但仍是已知不一致。

## 10. 下一阶段最小任务（建议，未开工）

把范围变成一个可见的「采集配置」面板：显示当前是否收录系统对象、排除多少个、按类型分布，
并提供「重新导入以改变范围」的说明。现在这条规则藏在 `.env` 里，使用者只能靠猜。
