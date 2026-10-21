# VALIDATION 3.0 — 工程资产与跨项目复用

> 环境：Windows 10 · Python 3.13.12（`.venv`）· 本地只读 DuckDB · 真实 Chrome
> 分支：`codex/engineering-asset-3`（本地，未推送）
> 时间：2026-10-21

## 1. 全量测试

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
1005 passed, 0 failed, 0 skipped  (163s)
```

| 套件 | 数量 | 说明 |
|---|---|---|
| 既有基线 | 948 | Workbench 1.0 + Visual Development 2.0 + 其他 |
| `test_codegen_safety.py` | 32 | 表达式子集、成员转义、变量碰撞、清空策略、依赖清单、预检、失效 |
| `test_assets.py` | 18 | 存储、提取、绑定、实例化、打包、导入校验 |
| `test_cross_project_reuse.py` | 7 | 同一 Blueprint 两个项目的端到端断言 + API |
| 合计 | **1005** | |

## 2. 浏览器验收（真实 Chrome + 真实鼠标）

| 脚本 | 断言 | 结果 |
|---|---|---|
| `acceptance_assets.py` | 17 | 全部通过 |
| `acceptance_workbench.py` | 37 | 全部通过（1.0 无回归） |
| `acceptance_pointer.py` | 10 | 全部通过（点/多选/平移/点边/框选） |
| `acceptance_design.py` | 24 | 全部通过（2.0 无回归） |

`acceptance_assets.py` 实际执行的链路：

1. 通过 API 准备「项目 A」工作区（汽车生产量，7 维）
2. 沙盘打开 → 设计模式 → 「提炼为 Blueprint」（真实 prompt/confirm）
3. 资产页列出 Blueprint → 打开 → 逐角色填写项目 B 绑定（快消销量）
4. 「在新项目中使用」→ 创建项目实例
5. 「生成代码草案」→ 断言 prolog 含 `SalesVolume` / `RetailSales.csv`，data 含 `vProduct = vSKU;`
6. 断言不残留 `VehicleVolume` / `VehicleCode`
7. 导出私有资产包（8 364 字节）→ 导入 → 计数
8. 刷新页面 → Blueprint 与项目仍在
9. 回到沙盘 → 原有探索可用；无页面脚本错误

## 3. Portable

| 项 | 结果 |
|---|---|
| 构建 | 成功（`release/portable-20261021-204951`） |
| 资产页与资源 | `assets.html`、`assets.js`、`assets.css` 已打包，HTTP 200 |
| 资产写入 | 在便携环境中创建 Pattern 成功，写入 `%LOCALAPPDATA%\TM1 Insight\assets\` |
| 企业数据 | 无 duckdb / parquet / .env / wal / workspaces / assets |
| `BUILD_MANIFEST` | `contains_customer_data: false` |

**未执行**：无 Python/Node 的干净 Windows 机器的"复制即用"验证。本轮只在开发机以独立数据目录启动验证。

## 4. 跨项目复用证据（核心验收）

| 项 | 项目 A（汽车） | 项目 B（快消） |
|---|---|---|
| 来源文件 | `VehicleProduction.csv` | `RetailSales.csv` |
| 字段 | VehicleCode / Plant / Period / Quantity | SKU / ChannelCode / SalesPeriod / SalesQuantity |
| 目标 Cube | `VehicleVolume` | `SalesVolume` |
| 维度顺序 | Scenario / Version / Year / Month / **Vehicle / Plant** / Measure | Scenario / Version / Year / Month / **Product / Channel** / Measure |
| 固定成员 | Forecast / Working / 2026 | Budget / Final / 2027 |
| 来源映射 | Period / VehicleCode / Plant | SalesPeriod / SKU / ChannelCode |
| 使用同一个 Blueprint | ✅ `bp3-…`（7 个维度角色） | ✅ 同一 id |
| 代码指纹 | `…`（不同） | `…`（不同） |

生成代码差异（B，节选）：

```ti
cCubTgt         = 'SalesVolume';
cSrcFile        = 'RetailSales.csv';
vProduct = vSKU;            # Product: 来源映射
vChannel = vChannelCode;    # Channel: 来源映射
CellPutN(vValue, cCubTgt, vScenario, vVersion, vYear, vMonth, vProduct, vChannel, vMeasure);
```

A 的对象名（`VehicleVolume` / `VehicleCode` / `VehicleProduction` / `Plant` / `'Forecast'`）在 B 的代码中**一个都不存在**，
该断言由 `test_same_blueprint_generates_different_code_for_two_projects` 与浏览器验收共同覆盖。

结论依据是**代码内容与维度顺序**，不是界面截图。

## 5. 安全测试

| 项 | 结果 |
|---|---|
| 表达式换行/分号注入 | 拒绝（`UNSAFE_EXPRESSION`） |
| 非白名单函数（ProcessQuit / ItemSkip） | 拒绝 |
| 固定成员含换行/控制字符 | 拒绝 |
| 成员单引号 | 转义为 `''` |
| 维度名碰撞 | 生成侧 `_2` 后缀 + 记录，不改业务名 |
| 未映射 / 未确认 | 阻断，`code=None` |
| 清空策略非法值 | `ValueError` |
| 资产包路径穿越 | 整包拒绝 |
| 资产包哈希篡改 | 该条拒绝 |
| 资产包超限 / 版本不符 | 拒绝 |
| 公开导出含受限内容 | 阻断并给出原因 |

## 6. 数据保护

| 项 | 结果 |
|---|---|
| 连接 TM1 Server | 否 |
| 读取 Cube Cell / 执行 TI / MDX | 否 |
| 修改正式 DuckDB | 否 |
| 删除 WAL | 否 |
| 上传企业数据 | 否 |
| 资产库位置 | `<user_data_root>/assets/`，已加入 `.gitignore` |

正式库哈希（开工与结束各一次，一致）：

```
<采集库> : 未变化
<运行库> : 未变化
```

## 7. 已知未验证

- 生成代码**未在 TM1 中编译或执行**；`}APQ` 与 Bedrock 依赖需目标环境自备。
- `StringToNumberEx` 的区域格式（小数/千位）未按列配置，实际行为未运行验证。
- 清空范围对真实业务数据的实际影响未验证。
- 一对多 / 聚合映射不支持，绑定阶段即被阻断。
- 未在干净 Windows 环境做 Portable 复制即用测试。
