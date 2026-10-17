# TM1 Insight — Windows 长路径兼容性修复 1.0

## 1. 根因（有代码证据）

两个 Process 采集失败，异常均为 `FileNotFoundError`，完整路径长度 261 / 262 字符。

**代码证据链**：

1. `src/tm1_insight/tm1/client.py` 的 `safe_filename()`（第 47 行）**只替换非法字符**（`/ \ : * ? " < > |`），**不处理长度**。
2. `src/tm1_insight/ingest/exporter.py` 的 `_export_one()`（修复前）用
   `filepath = raw_dir / obj_type / f"{safe_filename(name)}.json"` 生成完整路径。
3. 两个失败名称长度为 139 / 140 字符，加 `.json` 后缀后，配合
   `D:\3.PA_Software\2.tools\tm1-insight-codex-cube-centric-reverse-engineering\collections\model-6q3gk8k1`
   这一 102 字符根路径，完整路径达到 **261 / 262 字符**，超过 Windows `MAX_PATH=260`。
4. `save_json()` 的 `open(filepath, "w", ...)` 因此抛出 `FileNotFoundError`。

**结论**：失败发生在**本地文件保存阶段**（`save_json` → `open`），**不是 TM1py 读取阶段**。
这是代码级的路径长度问题，不是 TM1 Server 或权限问题。

验证（实测）：
```
name1 len=139, full path len=261, exceeds 260=True
name2 len=140, full path len=262, exceeds 260=True
```

## 2. 修改的文件

| 文件 | 变更 |
|---|---|
| `src/tm1_insight/ingest/storage.py` | **新增**：短名生成 + manifest 管理（核心） |
| `src/tm1_insight/ingest/exporter.py` | `_export_one` / `recollect_dimension` 接入短名；区分 TM1 读取 vs 文件保存错误；`export_all` 末尾写 manifest |
| `tests/test_long_path_storage.py` | **新增**：13 个测试，覆盖命名/写入/读取全链路 |

**未修改**（确认无需改动）：
- `loader.py`：`_load_json_dir` / `_stream_insert_dimensions` 已用 `fn.name.startswith("_")`
  跳过索引文件，且从 JSON 内容读 `name` 字段，天然兼容短名文件。
- `collector.py`：直接从 TM1 采集，不落盘本地文件，不受影响。

## 3. 新旧文件格式兼容性

**新格式（超长名称）**：`{type_prefix}_{sha256(name)[:16]}.json`，如 `p_1c2fb299afd76e82.json`。

**旧格式（普通名称 / 历史文件）**：`{safe_filename(name)}.json`（原名）。

- **只在完整路径可能超限（>240 字符）时才用短名**；普通名称保持原名，人类可读。
- 原始名称**始终完整保留**在 JSON 内容的 `name` 字段（`fetch_process` 已含），
  以及 manifest 的 entries 中，**不截断业务名称**。
- 旧版长名文件无需迁移/重命名：loader 扫描目录、从 JSON 内容读名称，短名与长名文件混存互不影响。
- manifest 文件名为 `_manifest.json`（`_` 前缀），loader 已跳过，不会被误当普通 Process。

## 4. 两个失败名称的测试结果

- `...Analysis.Caller` → 触发短名，完整路径 ≤ 240 字符，可正常落盘与读回。
- `...Analysis.Compare` → 同上。
- 两名称短名不同，互不覆盖。
- loader 读回的名称与原始名称逐字符一致（长度 139 / 140 完整保留）。

## 5. 测试结果

- 针对性测试 `tests/test_long_path_storage.py`：**13 passed**。
- 全量回归：**660 passed / 0 failed / 0 skipped**（原 647 + 新增 13）。

## 6. 是否触碰数据库 / TM1 Server / 历史采集数据

- **未连接 TM1 Server**（测试全部用 mock / 本地临时目录）。
- **未执行 TI、未读写 Cube 单元格**。
- **未修改 DuckDB / WAL**。
- **未删除或清理临时目录** `collections/model-6q3gk8k1`。
- **未修改系统 Python、环境变量、注册表**，无需管理员权限。

## 7. 是否 Push / 合并 / 发布

**否**。本轮改动未提交、未推送，保留在工作区等待验收。

## 8. 未解决的问题与建议

- 两个失败名称的**真实 TM1 环境重新采集**未执行（任务禁止连接真实 Server），
  需在真实环境重跑采集验证短名方案在实际 TM1py 数据下同样成立（逻辑已由 mock 端到端验证）。
- 若后续对象名称中出现 sha256 前 16 位 hex 碰撞（概率极低，64 bit），已实现 manifest 冲突检测，
  会明确抛 `RuntimeError`，不会静默覆盖。
- `failed_*.txt` 失败清单的错误码由 `{err}` 变为 `{tm1_fetch|file_save}:{err}`，
  该文件仅作人工诊断用、无程序读取，属增强性改动。
