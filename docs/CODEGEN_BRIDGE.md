# CODEGEN BRIDGE — 设计模式与既有代码模板的衔接

> 原则：**不新建第二套代码生成器**。所有 TI 文本都由 `src/tm1_insight/store/codegen.py` 生成。

## 1. 既有能力（未改动语义）

| 函数 | 用途 | 本轮改动 |
|---|---|---|
| `data_transfer(con, src, tgt, …)` | Cube → Cube 完整 }APQ 框架 TI | 新增可选 `src_dims` / `tgt_dims` / `dim_mapping`，**旧调用行为不变** |
| `csv_to_cube(...)` | 字符分隔文件 → Cube | **新增**，复用同一套框架块 |
| `data_export` / `data_export_dim` / `dimension_maintain` / `logging_init` | 导出、维度维护、日志框架 | 未改动 |
| `/api/codegen/data-transfer` 等 5 个端点 | 既有代码模板页 | 未改动 |

`data_transfer` 的扩展点：

```python
def data_transfer(con, src_cube, tgt_cube, prefix="}APQ", ...,
                  src_dims=None, tgt_dims=None, dim_mapping=None) -> dict
```

- `src_dims` / `tgt_dims` 为空时，仍从 DuckDB 读维度（旧行为）。
- 传入时用于**尚未部署的草稿**，因此 `con` 可为 `None`。
- `dim_mapping[目标维度] = {'fixed': "'成员'"}` 或 `{'source': 'vField'}`，优先于同名自动对齐。
- 返回值新增 `unmapped`（目标维度列表），调用方必须据此阻断，不得静默生成。

## 2. CSV → Cube 模板字段

```python
csv_to_cube(tgt_cube, tgt_dims, columns, mapping, *, value_source,
            file_path="", delimiter=",", quote='"', encoding="UTF-8",
            has_header=True, operation="CellIncrementN", prefix="}APQ", ...)
```

生成内容（与 `data_transfer` 同构）：

| 段 | 关键内容 |
|---|---|
| Process Declaration | 数据源类型 CHARACTERDELIMITED、文件常量、列 → 变量清单 |
| Declare Constants | 复用 `_declare_constants`，额外 `cSrcFile` |
| ZeroOut | 复用 `_zero_out`（`}bedrock.cube.data.clear`） |
| DataSource | `DatasourceType / NameForServer / ASCIIHeaderRecords / Delimiter / QuoteCharacter` + 变量注释 |
| Data | `vValue = StringToNumberEx( v<列>, '.,' );` + 按维度顺序赋值 + `CellPutN/CellIncrementN` |
| Epilog | 恢复事务日志 + 既有 }APQ 日志块 |

未处理项会写进 `unresolved`，并由 `design.generate` 转成阻断原因：目标维度未映射、未指定数值列、数值列不在表头。

## 3. 生成编排

```
POST /api/workbench/design/generate
  { design, relation_id, snapshot_id }
→ design.validate_relation(...)          # 硬门槛
→ store.codegen.data_transfer / csv_to_cube
→ { status: ok|blocked, blockers, code{prolog,metadata,data,epilog}, summary, artifact }
```

`artifact`：

```json
{"relation_id":"rel-…","template":"csv-to-cube","template_version":"1",
 "generated_at":"…","status":"DESIGN_DRAFT","validated":true,"blockers":[],
 "summary":{"target":"SalesCost","dimensions":"Scenario → … → Measure",
            "operation":"CellPutN","write_policy":"overwrite"}}
```

`status` 恒为 `DESIGN_DRAFT`：**生成 ≠ 部署**。

## 4. Cube 创建

`POST /api/workbench/design/cube-spec` 返回 `cube_creation_spec`：

- 逐位置列出维度来源（`EXISTING_SNAPSHOT` / `DESIGN_DRAFT` + 元素数）；
- 生成人类可读步骤：先建维度草稿，再按顺序建 Cube；
- 不输出可执行脚本，也不声称「一键创建」。

## 5. 已验证 / 未验证

**已验证（离线静态校验）**

- 生成文本包含完整 prolog / metadata / data / epilog 四段；
- 写入语句参数个数与目标维度数一致，顺序与草稿声明一致；
- 固定成员、来源字段、表达式按配置写入；
- 覆盖 / 累加分别对应 `CellPutN` / `CellIncrementN`；
- 任一映射缺失即阻断，`code=null`；
- CSV 数值经 `StringToNumberEx` 转换（字符源全部为字符串）。

**未验证**

- 未在 TM1 Server 编译或执行；TM1 语法层面的最终校验需在隔离环境人工完成；
- 未验证 `}APQ` 框架对象与日志 Cube 是否在目标环境存在（模板假定已存在）；
- 未验证大数据量下的性能与 `ItemReject` 行为；
- 未做 Cube 实际创建；
- 未做一对多 / 聚合映射。
