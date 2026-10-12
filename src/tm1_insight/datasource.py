"""数据源状态管理：识别当前数据来自哪里（真实本地 / Demo / TM1 Server / 空）。

Task 19 引入，落实产品底线「本地数据优先、Demo 数据兜底」：

- 开发机无法连接真实 TM1 Server 时，本地 data/ 必须是一等公民；
- 新电脑没有任何本地数据时，自动提供一套**小型 Demo 模型**，
  保证第一次打开产品就能看到完整能力，而不是空白页。

本模块**只做状态识别与 Demo 数据生成**，不重写 DuckDB / Parser /
Dependency / Lineage / Impact / Compare / Health / Collector / 任何引擎。

数据源类型：

- REAL_LOCAL：本地用户数据目录存在真实 DuckDB（有 cube 数据）。
- DEMO：没有任何本地数据，使用内置 Demo 模型。
- TM1_SERVER：未来连接 TM1 Server 采集（当前阶段标记为可配置但不阻塞本地使用）。
- EMPTY：无任何数据（理论上被 DEMO 兜底，仅作枚举完备性保留）。

设计约束（对齐 Task 19）：

- 绝不硬编码开发机的绝对路径（D:\\06_Backup\\...）。
- 检测只读，不修改、不删除、不迁移真实数据。
- Demo 数据写入**用户数据目录**（可写），与真实数据分离。
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from tm1_insight.config import get_settings
from tm1_insight.store.db import Store
from tm1_insight.store.schema import ALL_TABLES

logger = logging.getLogger(__name__)

# Demo 建库的进程级锁：保证多请求并发触发兜底时只建一次库，
# 避免 DuckDB 多连接同时 DROP/CREATE 同一表导致事务冲突。
_demo_lock = threading.Lock()
_source_cache: tuple[str, DataSourceStatus] | None = None



class DataSourceType(str, Enum):
    """数据源类型。"""

    REAL_LOCAL = "real_local"      # 本地存在真实 TM1 数据
    DEMO = "demo"                  # 内置示例模型
    TM1_SERVER = "tm1_server"      # 连接 TM1 Server（未来）
    EMPTY = "empty"                # 无数据（被 Demo 兜底前）

    @property
    def label(self) -> str:
        return {
            DataSourceType.REAL_LOCAL: "Local TM1 Data",
            DataSourceType.DEMO: "Demo Mode",
            DataSourceType.TM1_SERVER: "TM1 Server",
            DataSourceType.EMPTY: "No Data",
        }[self]


@dataclass
class DataSourceStatus:
    """当前数据源状态（供首页 / Settings / Header 展示）。"""

    type: DataSourceType
    location: str = ""             # 数据目录路径（REAL_LOCAL 时）
    ready: bool = False            # 数据是否可读
    counts: dict[str, int] = field(default_factory=dict)  # cubes/processes/... 行数
    db_path: str = ""              # DuckDB 路径
    db_size: int = 0               # 字节数
    error: str = ""                # 检测/加载失败原因

    @property
    def has_data(self) -> bool:
        return self.counts.get("cubes", 0) > 0


def _is_real_db(db_path: Path) -> bool:
    """判断一个 DuckDB 文件是否为「真实 TM1 数据」：文件存在且 cubes 表非空。"""
    if not db_path.exists():
        return False
    try:
        import duckdb
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            cnt = con.execute("SELECT count(*) FROM cubes").fetchone()[0]
            return cnt > 0
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return False


def _demo_data_dir() -> Path:
    """Demo 数据的独立目录，与真实数据物理分离。

    放在用户数据根目录的 data/demo 下（源码模式 = 项目根 data/demo，被
    .gitignore 的 data/ 规则覆盖；Portable = LOCALAPPDATA\\TM1 Insight\\data\\demo）。
    这样 demo 数据不会被误当作真实数据，也不污染项目根目录。
    """
    from tm1_insight.config import _USER_DATA_ROOT
    return _USER_DATA_ROOT / "data" / "demo"


def detect_current_source() -> DataSourceStatus:
    """检测当前数据目录的数据状态。

    规则：
      1. 当前数据目录 == demo 目录 且 cubes 非空 → DEMO
      2. 当前数据目录 db/tm1_insight.duckdb 存在且 cubes 非空 → REAL_LOCAL
      3. 否则 → EMPTY（由上层决定是否落入 Demo 模式）

    只读检测，不写库、不自动生成 Demo。
    """
    global _source_cache
    settings = get_settings()
    db_path = settings.db_path
    try:
        st = db_path.stat()
        fp = f"{db_path.resolve()}:{st.st_mtime_ns}:{st.st_size}"
        if _source_cache and _source_cache[0] == fp:
            cached = _source_cache[1]
            return DataSourceStatus(type=cached.type, location=cached.location, ready=cached.ready,
                                    counts=dict(cached.counts), db_path=cached.db_path,
                                    db_size=cached.db_size, error=cached.error)
    except OSError:
        fp = f"{db_path.resolve()}:missing"
    status = DataSourceStatus(type=DataSourceType.EMPTY, db_path=str(db_path))

    # 识别 Demo 目录（数据目录指针指向 demo/ 时标记为 Demo）
    try:
        is_demo_dir = settings.data_dir.resolve() == _demo_data_dir().resolve()
    except OSError:
        is_demo_dir = False

    if _is_real_db(db_path):
        store = Store(settings)
        try:
            counts = store.all_rows()
        except Exception as e:  # noqa: BLE001
            status.error = str(e)
            return status
        status.type = DataSourceType.DEMO if is_demo_dir else DataSourceType.REAL_LOCAL
        status.ready = True
        status.counts = counts
        status.location = str(settings.data_dir)
        try:
            status.db_size = db_path.stat().st_size
        except OSError:
            pass

    _source_cache = (fp, DataSourceStatus(type=status.type, location=status.location, ready=status.ready,
                                          counts=dict(status.counts), db_path=status.db_path,
                                          db_size=status.db_size, error=status.error))
    return status


@dataclass
class DirectoryDetection:
    """用户选择目录的检测结果（Import Local Data 用）。"""

    path: str = ""
    valid: bool = False
    error: str = ""                # 不可读/不存在等硬错误
    has_duckdb: bool = False
    has_parquet: bool = False
    has_raw: bool = False          # TM1 metadata（raw json）
    counts: dict[str, int] = field(default_factory=dict)
    db_size: int = 0
    partial: bool = False          # 结构不完整但部分可用


def detect_directory(path: str) -> DirectoryDetection:
    """检测一个用户指定的本地数据目录，返回结构化的检测结果。

    支持两种目录形态：
      - data/ 目录（含 db/tm1_insight.duckdb、parquet/、raw/）
      - 直接指向一个 .duckdb 文件

    只读检测，绝不修改目标目录。返回的 counts 从 DuckDB 动态读取。
    """
    result = DirectoryDetection(path=path)

    p = Path(path).expanduser()
    if not p.exists():
        result.error = "目录不存在，请检查路径是否正确。"
        return result

    if p.is_file():
        # 直接给了一个 duckdb 文件
        if p.suffix.lower() != ".duckdb":
            result.error = "不是有效的 .duckdb 文件。"
            return result
        db_path = p
        data_dir = p.parent
    else:
        db_path = p / "db" / "tm1_insight.duckdb"
        data_dir = p

    # DuckDB 检测
    if db_path.exists():
        result.has_duckdb = True
        try:
            result.db_size = db_path.stat().st_size
        except OSError:
            pass
        try:
            import duckdb
            con = duckdb.connect(str(db_path), read_only=True)
            try:
                for t in ("cubes", "processes", "dimensions", "chores"):
                    try:
                        result.counts[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                    except Exception:  # noqa: BLE001  # 表不存在则跳过
                        pass
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            result.error = f"无法读取 DuckDB：{e}"
            result.valid = False
            return result

    # Parquet 检测
    parquet_dir = data_dir / "parquet"
    result.has_parquet = parquet_dir.is_dir() and any(parquet_dir.glob("*.parquet"))

    # raw（TM1 metadata）检测
    raw_dir = data_dir / "raw"
    result.has_raw = raw_dir.is_dir() and any(raw_dir.rglob("*.json"))

    # 综合判定
    if result.counts.get("cubes", 0) > 0:
        result.valid = True
        result.partial = not (result.has_parquet and result.has_raw)
    elif result.has_duckdb:
        # 有 db 文件但 cubes 为空：结构不完整
        result.valid = False
        result.error = "DuckDB 存在但未包含有效的 Cube 数据（可能不是 TM1 Insight 数据目录）。"
    else:
        result.valid = False
        result.error = "未找到支持的 DuckDB 数据库。请选择 TM1 Insight 的 data 目录（含 db/tm1_insight.duckdb）。"

    return result


# ---------------------------------------------------------------------------
# Demo 数据
# ---------------------------------------------------------------------------

DEMO_MODEL: dict[str, Any] = {
    "cubes": [
        {"name": "Sales", "dimensions": ["Version", "Time", "Product", "Region"],
         "rules": "[Sales]=N:[Sales Input]*['Sales Rate'];\nFEEDERS;\n['Sales Input']=>['Sales Rate'];",
         "has_rules": True},
        {"name": "Finance", "dimensions": ["Version", "Time", "Cost Center"],
         "rules": "", "has_rules": False},
        {"name": "Inventory", "dimensions": ["Version", "Time", "Product", "Warehouse"],
         "rules": "", "has_rules": False},
    ],
    "dimensions": [
        {"name": "Version", "elements": ["Actual", "Budget", "Forecast"]},
        {"name": "Time", "elements": ["2024", "2025", "Q1", "Q2", "Q3", "Q4"]},
        {"name": "Product", "elements": ["P001", "P002", "P003"]},
        {"name": "Region", "elements": ["North", "South", "East", "West"]},
        {"name": "Cost Center", "elements": ["CC100", "CC200", "CC300"]},
        {"name": "Warehouse", "elements": ["WH1", "WH2"]},
    ],
    "processes": [
        {
            "name": "Load_Sales",
            "prolog": "# Load raw sales data",
            "metadata": "",
            "data": "DataSourceASCIIQuoteCharacter='\"';\nDataSourceNameForServer='sales.csv';\nCellPutN(vVal, 'Sales', vVersion, vTime, vProduct, vRegion);",
            "epilog": "",
        },
        {
            "name": "Calc_Finance",
            "prolog": "# Calculate finance figures",
            "metadata": "",
            "data": "vRevenue = CellGetN('Sales', 'Actual', '2025', 'P001', 'North');\nCellPutN(vRevenue, 'Finance', 'Actual', '2025', 'CC100');",
            "epilog": "",
        },
        {
            "name": "Update_Inventory",
            "prolog": "",
            "metadata": "",
            "data": "vQty = CellGetN('Inventory', 'Actual', '2025', 'P001', 'WH1');\nCellPutN(vQty, 'Inventory', 'Forecast', '2025', 'P001', 'WH1');",
            "epilog": "",
        },
    ],
    "chores": [
        {"name": "Daily_Load", "processes": ["Load_Sales", "Calc_Finance"]},
        {"name": "Weekly_Inventory", "processes": ["Update_Inventory"]},
    ],
}


def load_demo_data() -> DataSourceStatus:
    """把内置 Demo 模型写入**独立的 demo 数据目录**，返回数据源状态。

    关键设计：Demo 数据写入用户数据目录下的 ``demo/`` 子目录，**绝不覆盖
    真实 data/ 目录**。通过 ``set_data_dir(demo_dir)`` 让当前数据目录指向它。
    这样 Demo / Local 切换是「切换数据目录指针」，而非「覆盖数据文件」。
    """
    from tm1_insight.config import set_data_dir

    demo_dir = _demo_data_dir()
    demo_dir.mkdir(parents=True, exist_ok=True)

    # 直接用 duckdb 在 demo 目录建库（不经过 Store，避免依赖 data_dir 指针）
    import duckdb
    from tm1_insight.store.schema import ALL_TABLES

    # 与 Store.db_path 约定一致：<data_dir>/db/tm1_insight.duckdb
    db_path = demo_dir / "db" / "tm1_insight.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        # 幂等：先删旧表再重建（避免重复调用报 already exists）
        for name in ALL_TABLES:
            con.execute(f"DROP TABLE IF EXISTS {name}")
        for ddl in ALL_TABLES.values():
            con.execute(ddl)
        _write_demo_rows(con)
    finally:
        con.close()

    # 让当前数据目录指向 demo 目录
    set_data_dir(demo_dir)

    status = DataSourceStatus(
        type=DataSourceType.DEMO,
        location=str(demo_dir),
        ready=True,
        db_path=str(db_path),
    )
    try:
        status.db_size = db_path.stat().st_size
    except OSError:
        pass

    # 读取 counts
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        for t in ("cubes", "processes", "dimensions", "chores"):
            try:
                status.counts[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            except Exception:  # noqa: BLE001
                pass
    finally:
        con.close()
    return status


def _write_demo_rows(con) -> None:
    """把 Demo 模型的 rows 写入已建好 schema 的连接。"""
    cubes = DEMO_MODEL["cubes"]
    processes = DEMO_MODEL["processes"]
    chores = DEMO_MODEL["chores"]
    dims = DEMO_MODEL["dimensions"]

    for c in cubes:
        con.execute(
            "INSERT INTO cubes VALUES (?, ?, ?, ?, ?)",
            [c["name"], json.dumps(c["dimensions"]), c.get("rules", ""),
             c.get("has_rules", False), len(c["dimensions"])],
        )
    for p in processes:
        code = "\n".join([p.get("prolog", ""), p.get("metadata", ""),
                          p.get("data", ""), p.get("epilog", "")])
        con.execute(
            "INSERT INTO processes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [p["name"], p.get("prolog", ""), p.get("metadata", ""),
             p.get("data", ""), p.get("epilog", ""),
             json.dumps([]), json.dumps(None), len(code)],
        )
    for ch in chores:
        con.execute(
            "INSERT INTO chores VALUES (?, ?, ?)",
            [ch["name"], json.dumps(ch["processes"]), len(ch["processes"])],
        )
    for d in dims:
        con.execute(
            "INSERT INTO dimensions VALUES (?, ?, ?, ?, ?, ?, ?)",
            [d["name"], False, len(d["elements"]),
             json.dumps(d["elements"]), json.dumps({}), json.dumps([]), json.dumps([])],
        )

    # 关系表（依赖：让 Graph / Impact / Lineage 有内容可展示）
    con.execute("INSERT INTO process_writes_cube VALUES (?, ?)", ["Load_Sales", "Sales"])
    con.execute("INSERT INTO process_writes_cube VALUES (?, ?)", ["Calc_Finance", "Finance"])
    con.execute("INSERT INTO process_writes_cube VALUES (?, ?)", ["Update_Inventory", "Inventory"])
    con.execute("INSERT INTO process_reads_cube VALUES (?, ?)", ["Calc_Finance", "Sales"])
    con.execute("INSERT INTO process_reads_cube VALUES (?, ?)", ["Update_Inventory", "Inventory"])
    for i, d in enumerate(cubes[0]["dimensions"]):
        con.execute("INSERT INTO cube_has_dimension VALUES (?, ?, ?)", ["Sales", d, i])
    for i, d in enumerate(cubes[1]["dimensions"]):
        con.execute("INSERT INTO cube_has_dimension VALUES (?, ?, ?)", ["Finance", d, i])
    for i, d in enumerate(cubes[2]["dimensions"]):
        con.execute("INSERT INTO cube_has_dimension VALUES (?, ?, ?)", ["Inventory", d, i])
    con.execute("INSERT INTO rule_references_cube VALUES (?, ?)", ["Sales", "Sales"])
    for i, p in enumerate(chores[0]["processes"]):
        con.execute("INSERT INTO chore_runs_process VALUES (?, ?, ?)", [chores[0]["name"], p, i])
    for i, p in enumerate(chores[1]["processes"]):
        con.execute("INSERT INTO chore_runs_process VALUES (?, ?, ?)", [chores[1]["name"], p, i])


def ensure_demo_if_empty() -> DataSourceStatus:
    """首次启动兜底：无本地数据时自动写入 Demo 数据并返回状态。

    这是「新用户不能打开空壳」的产品底线。只在**当前数据目录为空**时
    才生成 Demo；一旦用户导入真实数据，后续启动走 REAL_LOCAL 分支。

    并发安全：demo 建库是「写一次、后续复用」的操作，用模块级锁保证
    多请求同时触发时只有一个真正建库，其余等待后复用已建好的库，
    避免 DuckDB 事务冲突（多连接同时 DROP/CREATE 同一表）。
    """
    status = detect_current_source()
    if status.type in (DataSourceType.REAL_LOCAL, DataSourceType.DEMO):
        return status
    # 空数据 → 兜底 Demo（持锁，防并发重复建库）
    with _demo_lock:
        # 双检：拿到锁后再次检测，可能已被其他请求建好
        status = detect_current_source()
        if status.type in (DataSourceType.REAL_LOCAL, DataSourceType.DEMO):
            return status
        logger.info("无本地数据，自动进入 Demo 模式")
        return load_demo_data()
