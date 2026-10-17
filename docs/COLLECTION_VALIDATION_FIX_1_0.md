# TM1 Insight — Collection Validation Failure Diagnosis 1.0

## 1. ValueError 的准确发生位置和原因

**位置**：`src/tm1_insight/api/app.py` 的 `_run_ingest()` 中，`progress("validate")`
之后、`progress("activate")` 之前的计数校验（原第 1357-1359 行）：

```python
actual = Store(staged).all_rows()
if not actual.get("cubes") or any(actual.get(key, 0) != exported[key]
                                 for key in ("cubes", "processes", "dimensions", "chores")):
    raise ValueError("Collected object counts did not reconcile")
```

**原因**：校验把 `Exporter.export_all()` 返回的**枚举总数**（`len(names[key])`）与
`Store.all_rows()` 返回的**实际入库数**（DuckDB 各表行数）直接比较。只要有任何对象
采集或入库不完整（例如长名称 Process 因 Windows MAX_PATH 超限导致 `FileNotFoundError`
导出失败，3442 枚举 vs 3440 入库），两者就不一致，抛 `ValueError`。

**代码证据链**：
1. `exporter.py` `export_all()` 返回 `"processes": len(names["processes"])` —— 枚举总数，非成功数。
2. `store/db.py` `all_rows()` 返回 `"processes": SELECT COUNT(*) FROM processes` —— 实际入库数。
3. 两个失败名称长度 139/140 字符，在 `collections/model-jzjmylfc` 根路径下完整路径
   261/262 字符，超 Windows `MAX_PATH=260`，`save_json` 的 `open()` 抛 `FileNotFoundError`。
4. 失败对象未落盘 → 未入库 → 计数不一致 → `ValueError`。

**原异常处理缺陷**：`except` 只执行 `logger.error("采集失败...(%s)", type(e).__name__)`，
只打印异常类名 `ValueError`，**无堆栈、无阶段名、无具体哪个 key 不一致、无缺失对象名**。

## 2. 修复前后行为

**修复前**：`ValueError` 只显示类型名，无法定位是哪个对象类型、缺多少、缺哪些对象。

**修复后**：
- 校验失败抛出的 `ValueError` 带精确信息，例如：
  `采集对象计数不一致（processes: 期望 3442 实际 3440）；processes 缺失(2): <两个长名称>`
- 异常捕获改用 `logger.exception(...)`，打印完整堆栈 + 当前阶段名。
- 保持「校验失败 → 不切换数据源」的安全语义（`activate_collected_source` 不会被调用）。

## 3. 修改文件列表

| 文件 | 变更 |
|---|---|
| `src/tm1_insight/api/app.py` | 抽出 `_validate_collected_model()`，精确报告不一致 key 与缺失对象；`except` 改用 `logger.exception` + 阶段名 |
| `tests/test_collection_validation.py` | **新增**：7 个测试 |

## 4. 离线复现是否成功

**是**。用 mock 数据离线复现了根因链路（3442 枚举 vs 3440 入库 → `ValueError`），
并确认修复后的报错信息精确定位到 `processes` 与两个缺失的长名称对象。
未连接 TM1 Server、未重新采集、未生成整批 Process JSON。

## 5. 测试结果

- 专项测试 `tests/test_collection_validation.py`：**7 passed**。
- 专项测试 `tests/test_long_path_storage.py`：**13 passed**（长路径兼容性独立回归）。
- 全量回归：**667 passed / 0 failed / 0 skipped**（原 660 + 新增 7）。

## 6. 是否改变正式 DuckDB/WAL

**否**。测试全部使用临时目录 / mock，未读写 `data/db` 下的正式 DuckDB 与 WAL。

## 7. 是否连接 TM1 / 执行 TI / 请求 Cube 单元格

**否**。全程离线，未连接 TM1 Server、未执行 TI、未读写 Cube 单元格。

## 8. 长路径兼容性是否得到独立验证

**是**。在真实长根路径语义下验证了两个长名称 Process：
- 原名路径长度 261/262（超 260），`resolve_object_path` 正确触发短名，
  映射到 `p_1c2fb299afd76e82.json` / `p_92ad2efa21f09b60.json`，路径长度降至 140。
- loader 读回的名称与原始名称逐字符一致，完整保留。

## 9. 是否提交 / Push / 合并

**否**。本轮改动保留在工作区，未提交、未推送，等待验收。

## 10. 遗留说明

- 临时目录 `collections/model-jzjmylfc` 位于另一台电脑（本机不可访问），
  无法直接读取其 Parquet/manifest 做字节级复现；但根因已通过代码证据链 + mock 离线复现确认。
- `_index.json` 中记录的 processes=3442 与本机 raw 累积数据一致，进一步佐证根因。
