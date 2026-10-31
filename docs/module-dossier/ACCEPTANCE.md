# Module Dossier P0 — 真实离线模型只读验收方法

目的：在**不连接生产 TM1、不写入快照、不外传企业数据**的前提下，用一份真实离线模型验证 Module Dossier 是否可用。
全部命令只读；输出目录必须位于模型数据目录之外，且首次生成到空目录。

## 0. 前置条件

- 已用现有采集流程得到一份本地 DuckDB（`tm1-insight ingest` 或导入的离线副本）。
- 建议先复制一份只读副本再验收，原始快照保持不变：

```powershell
Copy-Item ".\data\db\tm1_insight.duckdb" "D:\acceptance\offline-copy.duckdb"
```

- 记录验收前后的哈希，证明未被修改：

```powershell
Get-FileHash "D:\acceptance\offline-copy.duckdb" -Algorithm SHA256
```

## 1. 选一个真实入口

```powershell
tm1-insight query "<目标 Cube>"     # 看谁在写、谁在读、维度顺序
```

从 `写入者 TI` 里选一个真实装载流程作为入口；若无明确写入者，可用 Cube 入口：

- 流程入口：`--kind process --entry "<TI 名称>" --target-cube "<目标 Cube>"`
- Cube 入口：`--kind cube --entry "<目标 Cube>"`

## 2. 先看候选，再决定范围（不生成档案）

API 预览（不落盘）：

```powershell
curl -s -X POST http://127.0.0.1:8000/api/module-dossier/discover ^
  -H "Content-Type: application/json" ^
  -d "{\"name\":\"smoke\",\"entry_kind\":\"process\",\"entry\":\"<TI>\",\"target_cube\":\"<Cube>\"}"
```

返回 `candidates`（含发现原因）与 `resolved`（预算内实际成员）。确认后再生成。

## 3. 生成档案

```powershell
tm1-insight module-dossier `
  --name "<模块名>" `
  --entry "<TI 或 Cube>" `
  --kind process `
  --target-cube "<目标 Cube>" `
  --database "D:\acceptance\offline-copy.duckdb" `
  --max-processes 8 `
  --output "D:\acceptance\dossier-01"
```

输出五个文件：`Module.md`、`Module.json`、`Evidence.json`、`Diagnostics.json`、`Questions.md`。

如需人工排除辅助程序（排除后仍会保留依赖告警）：

```powershell
--exclude "process:}bedrock.cube.data.clear"
```

## 4. 只读验收（按顺序做，逐条记录）

**A. 结构与来源**

1. `Module.md` §2 的维度顺序与 `tm1-insight query "<Cube>"` 输出**逐位一致**。
2. §1 的「数据源类型 / Cube / View」能在该 TI 的 Prolog 中按标注行号找到。
3. 行变量表的位置与列含义一致；若显示「未采集到可用定义」，说明该快照缺 Variables，属预期，不要手工补。

**B. 转换与结果**

4. 任选一处写入：§4 的 `data:<行>:<列>` 能定位到源码中的 `CellPutN/CellIncrementN`。
5. 值定义链与源码中的赋值语句一致；动态函数（如 `AttrS`）应显示为「未确认」而不是猜出的成员。
6. 字段映射表的每一行都能在 Variables 记录与目标维度顺序中找到依据；不得出现按位置硬凑的映射。

**C. Rule / Feeder**

7. §5 的 Rule 行号与 Rule 源码行号一致；`Feeder` 单独成表，且没有出现在 TI 写入列表里。
8. 动态 `DB(pCube, …)` 显示为「未解析」，并且没有产生一条确定的跨 Cube 依赖。

**D. 诚实性检查**

9. §0 的「运行验证：0 项」保持不变；全文不应出现「已验证运行」之类表述。
10. §7 的每条缺口都有「原因 / 影响 / 如何确认」三列；`Questions.md` 条数与缺口数一致。
11. `Evidence.json` 中每个 `EV-xxxx` 都能回指对象 + 表/行；`Diagnostics.json` 的 `coverage` 与 `Module.json` 一致。

**E. 边界与安全**

12. `Get-FileHash` 与验收前一致（只读，无写入）。
13. `Module.md` 不含完整 TI/Rule 源码块、连接串、凭据或单元格数值。
14. 分享前确认：档案含真实对象名与成员，属于企业数据，按内部规定管控。

## 5. 通过标准

一名没参与过该项目的人，只读 `Module.md`，应能回答：

- 数据从哪个 Cube/视图、哪些字段进来；
- 经过哪个流程、什么条件、什么公式，写到哪个 Cube 的哪些坐标、用什么写入模式；
- 结果如何被 Rule 补全、Feeder 只做什么；
- 哪些成员、执行顺序、数值贡献仍未被证明，下一步该补采什么。

若第 4 项出现「按名称猜出的来源」或「把 Rule 当成 TI 写入」，本次验收不通过。

## 6. 性能与规模观察（只记录，不承诺）

在真实模型上记录：入口 TI 数、写入点数、Rule 条数、生成耗时、`Module.md` 大小、`Diagnostics.json` 截断项。
默认预算：进程 8（上限 20）、写入点 20/TI（上限 80）、Rule 40/Cube（上限 120）、证据 4000（上限 20000）。
超过预算会在 `Diagnostics.json` 与 §7 中显式说明，不会静默省略。

## 7. 本次只读验收记录（2026-10-31，仅聚合数字，无对象名）

在仓库内现有离线库上执行同一流程（`read_only=True`，单模块默认预算）：

| 项 | 值 |
| --- | --- |
| 模型规模 | Cube 3660、Process 3823、Dimension 12280 |
| 记录到 Rule 源码的 Cube | 0（该快照未采集 Rule） |
| 本次模块 | 4 个 TI、2 个 Cube、31 处写入 |
| 写入模式 | 覆盖文本 23、覆盖数值 8 |
| 坐标确认度 | `PARTIAL` 19、`UNKNOWN` 12 |
| 缺口 | 51 项（含 `SOURCE_NOT_RECORDED` 4、`RULE_SOURCE_NOT_RECORDED` 2、`CALL_TARGET_OUTSIDE_SCOPE` 14） |
| 证据 | 274 条 |
| `Module.md` | 57 KB |
| 生成耗时 | 0.67 s |
| 库文件 SHA-256 | 前后一致（未被修改） |

这次验收暴露的真实边界（是采集缺口，不是推断缺陷）：

1. 旧快照的 `processes.datasource` 为空、`process_source_metadata` 无记录，因此所有 TI 的数据源显示「未记录」，写入值来源标记 `SOURCE_NOT_RECORDED`。
2. 全库 0 个 Cube 有 Rule 源码，档案显示「本快照未记录 Rule 源码」，而不是断言「没有 Rule」。
3. 多个调用目标在模块范围外，按 `CALL_TARGET_OUTSIDE_SCOPE` 保留，不扩成大模块。

补采后即可把上述 `UNKNOWN` 收敛为可解释事实：

```powershell
tm1-insight collect-process-metadata --process "<入口 TI>" --process "<装载 TI>" --output "meta.json"
tm1-insight import-process-metadata --bundle "meta.json" --database "D:\acceptance\offline-copy.duckdb"
```

Rule 源码**不需要新开发**。`tm1/client.py::read_cube_rules` 已经实现了三级回退
（`cube.rules` → `cubes.get_rules` → REST `?$select=Rules`），并在 `fetch_cube` 里
返回 `rules_status: available|unavailable`，导出器也把它原样落盘。

本次库之所以是 0，是因为 `data/raw/cubes/*.json` 是**旧格式**——只有
`name/dimensions/rules/has_rules`，没有 `rules_status`。缺了它，`rules: ""` 无法区分
「这个 Cube 确实没有 Rule」和「这次采集没读到 Rule」，而 `data/raw` 的 3661 个文件
全部是 `has_rules: false`，不可能全对。

`exporter._export_one` 已经考虑到这种情况（`ingest/exporter.py:58`）：带
`rules_status == "available"` 的旧文件会被跳过，其余会在下一次采集时重新读取。所以
把同一份采集配置再跑一次，`cubes` 表就会有 Rule 源码，档案第 5 节随之从空变满，
不需要改任何档案代码。

---

## 8. 有 Rule 的库上的规模验收（2026-10-31）

前一轮验收用的是 Rule 全空的库，于是「第 5 节永远是空的」被当成产品缺陷看了半天。
换到仓库内另一份带 Rule 的离线库（`data/demo`）后暴露的真实问题是**可读性**，
不是缺数据。

| 项 | 值 |
| --- | --- |
| 模型规模 | Cube 3338，其中 1339 个有 Rule 源码（最大 616 KB） |
| 本次模块 | 2 个 TI、5 个 Cube、40 处写入、84 条 Rule、75 条 Feeder |
| 逐行缺口 / 合并后 | 1035 处 → 86 组 |
| `Module.md` | 335 K 字符 → **75 K 字符**（规则段 187 K → 15 K，缺口段 106 K → 18 K） |
| `Questions.md` | 174 K → 30 K 字符 |
| 生成耗时 | 2.5 s |
| 库文件 SHA-256 | 前后一致（未被修改） |

处理前后的差别不是「大一点小一点」：335 K 的 Markdown 里，缺口段 660 行有 614 行
在重复同一句话，真正不同的 12 类缺口被埋掉了。合并后一眼能看到「81 条区域坐标
未确认、71 条表达式语义未还原、60 条用了 ATTRS」。

完整规模记录与判定标准见 `SCALE.md`。
