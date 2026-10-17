# TM1 Insight — Python 跨版本兼容性治理 1.0

> 状态：已实施。目标：解决不同电脑使用不同 Python 版本导致的启动失败。

## 1. 故障根因（已确认）

另一台电脑启动 Web 时失败：

```
TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
位置：src/tm1_insight/api/architecture.py:18
```

**根因**：`api/architecture.py` 中的 Pydantic 模型子类 `Start(WorkflowStart)` 使用了
PEP 604 联合类型 `str | None`，且该文件**缺少** `from __future__ import annotations`。
因此在类定义时注解被**立即求值**。运行该代码的解释器低于 Python 3.10，`type.__or__(NoneType)`
未定义，直接抛错，Web 服务尚未启动。

而项目 `pyproject.toml` 声明 `requires-python = ">=3.9"`、ruff `target-version = "py39"`，
但代码与锁定的依赖实际要求 ≥3.10（部分 ≥3.11），声明与实现不一致。

## 2. 两阶段根因

| 层次 | 问题 | 证据 |
|---|---|---|
| 语法层 | PEP 604 联合类型在缺 future import 的 Pydantic 模型中被立即求值 | `api/architecture.py:18-19` |
| 依赖层 | 锁定的 pandas 3.0.6 / numpy 2.5.4 / pyarrow 26 要求 ≥3.11；fastapi 0.143 / duckdb 1.5.6 要求 ≥3.10 | `importlib.metadata` 查询各包 `Requires-Python` |

仅修语法不足以保证 3.9 可运行——依赖在 3.9 上根本无法安装。

## 3. 兼容性矩阵（本轮确定）

- **最低支持 Python 版本**：3.9
- **推荐开发版本**：3.11+
- **已验证版本**：3.13（本机实测）；3.9（依赖 requires-python 静态验证，未实测运行）
- **暂不支持**：< 3.9（PEP 604 / 内置泛型 / 依赖均不满足）

### 各依赖版本范围（同时满足 Python 3.9 与 3.13）

| 包 | 声明范围 | 3.9 内解析到 | requires-python |
|---|---|---|---|
| fastapi | `>=0.110,<0.129` | 0.128.8 | >=3.9 |
| uvicorn[standard] | `>=0.29,<0.40` | 0.39.0 | >=3.9 |
| typer | `>=0.12,<0.24` | 0.23.2 | >=3.9 |
| pydantic | `>=2.6,<2.14` | 2.13.5 | >=3.9 |
| pydantic-settings | `>=2.2,<2.12` | 2.11.0 | >=3.9 |
| TM1py | `>=2.0,<2.5` | 2.4.1 | >=3.7 |
| duckdb | `>=1.0,<1.5` | 1.4.5 | >=3.9 |
| pyarrow | `>=15.0,<22` | 21.0.0 | >=3.9 |
| pandas | `>=2.2,<2.4` | 2.3.3 | >=3.9 |
| numpy | 见下（环境标记分流） | 3.9→1.26.4；3.10+→2.1.x | 分界 |

### numpy 的硬性分界（重要）

numpy 存在一个无法用单一版本同时满足的约束：

| numpy 版本 | 支持 Python | 二进制轮子 |
|---|---|---|
| `< 2.1`（如 1.26.4 / 2.0.2） | >=3.9 | 仅 cp39–cp312，**无 cp313** |
| `>= 2.1`（如 2.1.x / 2.2.x） | >=3.10 | 有 cp313，但**弃用 3.9** |

因此用环境标记按 Python 版本分流：

```
numpy>=1.26,<2.1; python_version < "3.10"
numpy>=2.1,<2.3; python_version >= "3.10"
```

> 这是 numpy 上游的分界，非本项目可绕过；其余依赖（pandas 2.3.3、pyarrow 21.0.0、
> duckdb 1.4.5）均同时提供 cp39 与 cp313 轮子，无需分流。
| openpyxl | `>=3.1,<3.2` | 3.1.5 | >=3.8 |
| jinja2 | `>=3.1,<3.2` | 3.1.6 | >=3.7 |
| python-multipart | `>=0.0.9,<0.0.21` | 0.0.20 | >=3.8 |
| httpx | `>=0.27,<0.29` | 0.28.1 | >=3.8 |

> 上界值经 PyPI 官方 `requires-python` 元数据逐一验证：每个上界都 ≤ 该包最后支持
> 3.9 的版本。选择「上界」而非「锁定 ==」：保留小版本安全更新空间，同时防止 pip
> 解析到 3.9 不兼容的新版。

## 4. 修改文件清单

| 文件 | 变更 |
|---|---|
| `src/tm1_insight/api/architecture.py` | 加 `from __future__ import annotations`；`str \| None` → `Optional[str]`（真实修复，Pydantic 运行时求值需要） |
| `src/tm1_insight/python_compat.py` | 新增：版本检查 / 横幅 / 中文错误（纯标准库，3.9 可解析） |
| `src/tm1_insight/cli.py` | `web` 命令与 `main()` 调用 `check()` 并打印横幅 |
| `launcher.py` | Portable 双击 / `web` 入口调用 `check()` 并打印横幅 |
| `start.bat` | 打印解释器路径与版本；< 3.9 提前退出中文错误 |
| `pyproject.toml` | 依赖加 3.9 兼容上界；`requires-python` 保持 `>=3.9` |
| `requirements.txt` | 与 pyproject 同步上界；numpy 按版本分流 |
| `docs/PYTHON_COMPATIBILITY_1_0.md` | 本文档 |
| `tests/test_python_compat.py` | 新增：核心模块导入 / Pydantic 模型 / 版本检查 / 横幅 |

## 5. 关键设计说明

### 为何 25 个文件的 PEP 604 未逐一改写

除 `architecture.py` 外，其余 25 个使用 `X | None` 的文件**均已**包含
`from __future__ import annotations`（PEP 563，3.7+ 可用）。该特性把注解转为字符串，
运行时不求值，因此 `str | None` 等写法在 3.9 上是安全的。

唯一的例外是 Pydantic 模型：Pydantic 需要**运行时求值**注解以构建 schema，
因此模型内的联合类型必须真实改写为 `Optional` / `Union`。本项目唯一命中此情况的
是 `api/architecture.py` 的 `Start` 模型（`workflow.py` 的基类 `Start` 不含 PEP 604）。

### 运行时联合类型

经 AST 扫描，项目中无 `isinstance(x, A | B)` 等运行时联合求值；命中的 `|` 均为
合法的 set 并集（`set() | set()`）或 `re.IGNORECASE | re.DOTALL` 标志位运算，
在所有 Python 版本语义一致。

## 6. 验证结果

- 638 个既有测试全部通过（本机 Python 3.13，语法修复后）。
- `architecture.Start` 模型可正常构建与校验。
- 依赖上界经 PyPI `requires-python` 元数据逐一验证。
- **3.9 运行期未实测**：本机无 3.9 解释器，无法声称跨版本实测通过。

## 7. 尚未验证的风险

1. **3.9 实际运行**：依赖声明已对齐，但未在真实 3.9 环境启动验证。
2. **pandas 2.3.x + numpy 2.0.x + pyarrow 21 组合**：已确认各版本 supports 3.9，
   但组合运行未在 3.9 实测。
3. **Portable 是否需要重建**：见下文。

## 8. Portable 策略

本轮未改 Portable 打包逻辑。Portable 已内置 Python 运行时，不依赖目标机系统 Python，
天然规避「不同电脑版本不一致」问题，是长期推荐方案。

但若 Portable 打包时用了当前锁定依赖（pandas 3.0.6 等），其内部运行时已是 3.13，
**无需因本轮语法修复而重建**（打包版不受目标机系统 Python 影响）。仅当需要让
Portable 也统一到 3.9 兼容依赖集时才重建——目前无此必要。

## 9. 供另一台电脑执行的版本检查命令

（在报错机器上直接复制执行）

```bat
python --version
python -c "import sys; print(sys.executable); print(sys.version)"
```

预期：若低于 3.9，请先升级 Python；若为 3.9/3.10/3.11，安装依赖时会自动解析到
3.9 兼容版本（本轮已加依赖上界）。
