# Process Count Reconciliation 1.0 — 取证与根因修复报告

## 一、结论（3442 vs 3437）

- `expected = 3442` 是**服务器枚举数**：`Exporter.export_all()` 返回的 `processes = len(names["processes"])`，来自 `TM1Client.list_all_names()` → `tm1.processes.get_all_names()`。
- `actual = 3437` 是**实际入库行数**：`Store(staged).all_rows()["processes"]` → `SELECT COUNT(*) FROM processes`。
- 差异 **5 个** Process，发生在「枚举 → 落盘 → 读回 → 入库」链条中，而非校验逻辑本身算错。

## 二、根因：三个可导致对象丢失的环节

代码层面确认存在三个会让「枚举数 > 入库数」的环节，且旧实现都无法精确说出「少了谁」：

### 环节 A —— 导出失败未落盘（已确认，上一轮已见 2 例）
`Exporter._export_one` 三次重试仍失败时，对象**不落盘**，仅写 `failed_processes.txt`。
阶段标识分 `tm1_fetch`（TM1 读取失败）与 `file_save`（本地文件保存失败，如 Windows MAX_PATH=260 超限 → `FileNotFoundError`）。
上一轮已确认两个长名称 Process 走 `file_save:FileNotFoundError`。

### 环节 B —— Loader 静默跳过读不回的文件（本轮修复）
旧 `_load_json_dir` 用 `except Exception: logger.warning(...); continue`，把「文件写入成功但读不回」（损坏 JSON、权限、编码）**静默吞掉**，不进任何失败清单。结果就是「文件在磁盘上、但入库少一个」，且无法追溯名字。

### 环节 C —— 文件名碰撞静默覆盖（本轮修复）
`safe_filename` 把 `/ \ : * ? " < > |` 统一替换为 `_`。两个不同名称（如 `a/b` 与 `a_b`）映射到**同一文件名** `a_b.json`，后写覆盖先写，静默丢失 1 个对象。
此碰撞**不进** `failed_processes.txt`（save_json 均"成功"），也不触发 PRIMARY KEY 报错（JSON 内 `name` 字段仍不同，只是磁盘文件同名），是隐蔽的丢失点。

> 说明：`processes.name` 为 PRIMARY KEY，但 `INSERT INTO ... VALUES` 遇重名会抛 `Constraint Error` 直接中断，而非静默少 5 个。日志显示「入库完成」正常打印，说明本轮 5 个差异**不是** PRIMARY KEY 覆盖导致，而是环节 A/B/C 中的「未落盘」或「读不回」或「文件名碰撞」。

## 三、证据缺口（必须如实说明）

临时目录 `D:\3.PA_Software\2.tools\tm1-insight-codex-cube-centric-reverse-engineering\collections\model-9pmjh8jx` 位于**另一台电脑**，本机不可访问。因此：

- **无法离线读出这 5 个 Process 的确切名称**（`_index.json`、`failed_processes.txt`、`raw/processes/*.json` 均不在本机）。
- 不伪造缺失名单，不重新连接 TM1 Server 补齐证据。

本轮交付的是：**把「说不出少了谁」的结构性缺陷修复掉**，使下次采集（或在有临时目录的机器上运行离线对账脚本）能**精确输出缺失对象名 + 丢失环节**。

## 四、修改文件与说明

### 1. `src/tm1_insight/ingest/loader.py`
- `_load_json_dir` 返回 `(对象列表, 读取失败文件名列表)`，不再静默吞掉读失败。
- 新增 `_index_names()`：读取 exporter 写的 `raw/_index.json` 枚举名清单（权威来源）。
- 新增 `_reconcile_names()`：名称级对账，产出 `{expected_count, actual_unique, actual_rows, missing, duplicates, read_failures}`。
- `load()` 中对 cubes/processes/chores 做名称级对账，写入 `raw/_reconcile.json`，并 `logger.warning` 缺失/重复/读失败明细。
- 新增 `Loader._write_reconcile()` 落盘对账结果。

### 2. `src/tm1_insight/api/app.py`
- `_validate_collected_model` 优先读 `raw/_reconcile.json` 做**名称级**缺失报告（缺失对象名 + 重复名）；无该文件时回退到 `failed_<type>.txt`（向后兼容）。
- 报错信息现在包含具体缺失对象名，而非仅数量差。

### 3. `src/tm1_insight/ingest/storage.py`
- `Manifest.register` 对**原名文件**也做碰撞检测：`safe_filename` 规整后同名（如 `a/b` vs `a_b`）立即 `RuntimeError("原名文件冲突")`，不再静默覆盖。
- 保留短名哈希冲突检测。

### 4. 测试
- `tests/test_long_path_storage.py`：适配新签名；新增 `test_plain_name_collision_raises`。
- `tests/test_name_reconciliation.py`（新增 10 项）：覆盖枚举读取、缺失定位、重复定位、读失败定位、校验层名称级报告、failed 回退、长名称完整链路对账。

## 五、测试结果

- 专项：`test_name_reconciliation.py` + `test_collection_validation.py` + `test_long_path_storage.py` → **31 passed**。
- 全量回归：**678 passed, 0 failed**（较上一会话 667 增加 11 项新测试）。

## 六、安全边界确认

- 正式 DuckDB（`data/db/tm1_insight.duckdb`）**未改动**。
- **未**连接 TM1 Server、未执行任何 TI、未读/写任何 Cube 单元格、未重新采集。
- **未**提交、未 Push、未合并。
- 未删除临时目录；未触碰工作区其他未提交改动（README.md、collector.py、formation.py 等 metadata-recovery 相关遗留）。

## 七、后续（在有临时目录的机器上补齐证据）

在拥有 `model-9pmjh8jx` 的机器上运行以下离线对账，即可输出 5 个确切缺失名：

```bash
python -c "
import sys, json
sys.path.insert(0, 'src')
from pathlib import Path
from tm1_insight.ingest.loader import _index_names, _load_json_dir, _reconcile_names
raw = Path(r'D:/3.PA_Software/2.tools/tm1-insight-codex-cube-centric-reverse-engineering/collections/model-9pmjh8jx')
rows, fails = _load_json_dir(raw, 'processes')
rec = _reconcile_names(raw, 'processes', rows, fails)
print(json.dumps(rec, ensure_ascii=False, indent=2))
"
```

或直接查看该目录下的 `failed_processes.txt`（导出失败）与 `_reconcile.json`（本轮新增的对账结果，若重新运行采集则已生成）。
