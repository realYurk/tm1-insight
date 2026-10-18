# 紧急 Bug Fix — 下划线开头 Process 被静默丢弃（3442 → 3437）

## 一、根因（已确凿验证）

`src/tm1_insight/ingest/loader.py` 的 `_load_json_dir()` 存在以下过滤：

```python
if not fn.suffix == ".json" or fn.name.startswith("_"):
    continue
```

它把所有「下划线开头」的 JSON 文件当作保留元数据跳过。但 **TM1 的合法 Process 名称可以下划线开头**，导致以下 5 个 Process 被静默丢弃：

- `_CubeProcessFeeders`
- `_New_Process_Template`
- `_New_Process_Template_Aruis`
- `_New_Template_2`
- `_New_Template_Alan_2`

`processes` 因此从 3442（服务器枚举）掉到 3437（实际入库），触发最终校验拒绝切换数据源。

**决定性证据链**（本机 `data/raw/_index.json` + `data/raw/processes/` 已交叉验证）：

1. `_index.json` 枚举清单 `processes: 3442`，与任务报告的「期望 3442」完全一致。
2. 枚举清单中下划线开头的 Process **恰好 5 个**，正是任务报告缺失的 5 个。
3. 这 5 个文件在磁盘上**真实存在**、可正常解析、`name` 字段与预期**完全一致**。
4. 旧逻辑 `startswith("_")` 精确跳过了这 5 个文件 → 3442 - 5 = 3437。

## 二、修复

引入精确的保留元数据文件名集合，**不再按下划线前缀排除**：

```python
RESERVED_METADATA_FILES = frozenset({
    "_index.json",
    "_manifest.json",
    "_reconcile.json",
})
```

三处过滤（`_load_json_dir` + `_stream_insert_dimensions` 的 `glob` 与循环内）统一改为：

```python
fn.name not in RESERVED_METADATA_FILES
```

保留元数据文件都写在 `raw_dir` **根目录**，不在对象子目录（`processes/`、`dimensions/` 等）内，因此对象子目录中的任何 `.json`（含下划线开头）都是合法业务对象。

## 三、修改文件

| 文件 | 改动 |
|---|---|
| `src/tm1_insight/ingest/loader.py` | 新增 `RESERVED_METADATA_FILES`；`_load_json_dir` 与 `_stream_insert_dimensions` 两处改为精确名排除 |
| `src/tm1_insight/ingest/storage.py` | 更正注释（描述精确名排除，不再声称按下划线前缀跳过） |
| `tests/test_underscore_process.py` | 新增 13 项回归测试 |
| `scripts/restore_staged_model.py` | 新增离线恢复脚本（复用原始 JSON，独立暂存目录重建，不连服务器） |

## 四、测试结果

- 专项 `test_underscore_process.py`：**13 passed**（5 个下划线 Process 参数化加载、保留文件排除、同名不覆盖、损坏不静默、3442 通过 / 3437 拒绝等）。
- 相关对账/长路径/校验测试：44 passed。
- 全量回归：**691 passed / 0 failed**（上轮 678，本轮新增 13 项）。

## 五、离线验证（本机 data/raw）

- 修复前旧逻辑加载 3823 个 Process，错误丢弃 **18 个**下划线开头合法对象。
- 修复后加载 3841 个（含 18 个下划线对象 + 目标 5 个），0 读取失败。
- 名称级对账 `missing: []`，5 个下划线 Process 全部不再缺失。

> 注：本机 `data/raw/processes` 是历史多次采集累积（3841 个文件 > 枚举 3442），非单次干净快照，故不能在本机做精确「3442 全量入库」验证。精确 3442 对账需在拥有 `model-m4j1_j1w` 临时目录的机器上执行恢复脚本。

## 六、安全边界

- **未**连接 TM1 Server、未重新采集、未执行 TI、未碰 Cube。
- **未**覆盖正式 DuckDB / WAL。
- 临时目录 `model-m4j1_j1w` 位于另一台电脑，本机不可访问，未删除、未改动。
- 恢复脚本使用独立 `staged_rebuild/` 子目录，成功后原临时目录与证据保留。

## 七、在另一台电脑补齐完整 3442 对账

```bash
python scripts/restore_staged_model.py D:/3.PA_Software/2.tools/tm1-insight-codex-cube-centric-reverse-engineering/collections/model-m4j1_j1w
```

脚本会复用原始 JSON、独立暂存目录重建，输出 `processes` / `ti_summary` 计数与对账结果；若仍有缺失则非零退出并列出缺失名。
