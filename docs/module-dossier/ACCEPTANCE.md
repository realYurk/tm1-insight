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

Rule 源码需要按 Cube 采集（当前采集器未覆盖），是下一步最高价值的补采项。
