"""FastAPI 应用：三视图 Web UI（Explorer / Graph / Audit）+ 数据 API。

纯 Jinja2 服务端渲染 + 手写 CSS，不依赖 CDN，内网离线可用。
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Optional

import shutil

from fastapi import Body, FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from tm1_insight import __version__
from tm1_insight.config import Settings, get_settings
from tm1_insight.store.db import Store
from tm1_insight.store import queries
from tm1_insight.store.graph_adapter import dependencies_from_store

logger = logging.getLogger(__name__)

def _resource_dir() -> Path:
    """templates/static 所在目录。

    源码运行：src/tm1_insight/api/。
    PyInstaller onedir/onefile：解压目录 _MEIPASS 下的 tm1_insight/api/。
    """
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "tm1_insight" / "api"
    return Path(__file__).parent


BASE_DIR = _resource_dir()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _hash_color(name: str, palette: int = 10) -> str:
    """给字符串（如 cube 名）算一个稳定的颜色索引，用于「不同源头 cube 用不同颜色区分」。

    返回 "src-c0" ~ "src-c9" 中的某个类名，同名 cube 恒得到同一颜色。
    """
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return f"src-c{h % palette}"


templates.env.filters["hash_color"] = _hash_color

app = FastAPI(title="TM1 Insight", version=__version__)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ---- 全局异常处理：任何未捕获异常都返回友好错误页，而非白屏 500 ----
def _error_page(request: Request, status_code: int, title: str, detail: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": status_code, "title": title, "detail": detail},
        status_code=status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # 404 与其它 HTTP 错误走友好错误页
    if exc.status_code == 404:
        return _error_page(request, 404, "页面不存在", "你访问的页面不存在，或已被移动。请从左侧导航重新进入。")
    return _error_page(request, exc.status_code, "请求出错", str(exc.detail) or "请求处理失败。")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未捕获异常: %s %s", request.method, request.url.path)
    # API 接口返回 JSON，页面返回 HTML
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "服务器内部错误，请查看日志。"}, status_code=500)
    return _error_page(request, 500, "服务器内部错误", "处理请求时出现意外错误，请查看服务端日志排查。")


# 内存中的 ingest 任务状态（单进程内）
_ingest_state: dict = {"running": False, "done": False, "error": None, "stats": None}
_ingest_lock = threading.Lock()

# 内存中的前端资产扫描任务状态
_audit_state: dict = {"running": False, "done": False, "error": None, "stats": None, "progress": None}
_audit_lock = threading.Lock()


# ===========================================================================
# 页面级结果缓存：重计算页面（如 /compare 需 1s 级重算）在数据未变化时
# 直接复用上次渲染结果，把切换延迟从「秒级」压到「毫秒级」。
# 失效依据：数据目录 + 主 db 文件 mtime。数据一变更（导入/重拉）即失效。
# ===========================================================================
_page_cache: dict[str, tuple[str, str]] = {}          # cache_key -> (data_fingerprint, html)
_page_cache_lock = threading.Lock()


def _data_fingerprint() -> str:
    """当前数据目录下主库文件的 mtime 指纹，用于判断数据是否变化。"""
    try:
        settings = get_settings()
        db = Path(settings.db_path) if settings.db_path else None
        if db and db.exists():
            st = db.stat()
            return f"{db.resolve()}:{st.st_mtime_ns}:{st.st_size}"
    except Exception:
        pass
    return "no-db"


def _cached_page(key: str, renderer) -> HTMLResponse:
    """若数据未变则返回缓存 HTML，否则调 renderer() 重新渲染并缓存。

    renderer 返回 HTML 字符串。cache_key 用于区分不同页面。
    """
    fp = _data_fingerprint()
    with _page_cache_lock:
        hit = _page_cache.get(key)
        if hit and hit[0] == fp:
            return HTMLResponse(hit[1])
    html = renderer()
    with _page_cache_lock:
        _page_cache[key] = (fp, html)
    return HTMLResponse(html)


def _ensure_demo_available() -> None:
    """惰性 Demo 兜底：访问任意数据页面时，若无本地数据则写入 Demo。

    ensure_demo_if_empty 本身幂等且快速：有数据时只做一次轻量检测直接返回，
    无数据时才写一次 Demo 目录。因此无需额外标志缓存，直接每次调用即可，
    避免「测试/多请求间状态泄漏」。
    """
    from tm1_insight.datasource import ensure_demo_if_empty
    ensure_demo_if_empty()


def _run_audit() -> None:
    global _audit_state
    try:
        from tm1_insight.ingest.audit import load_audit

        def progress(phase, done, total):
            with _audit_lock:
                _audit_state["progress"] = {"phase": phase, "done": done, "total": total}

        stats = load_audit(get_settings(), progress=progress)
        with _audit_lock:
            _audit_state.update({"running": False, "done": True, "error": None, "stats": stats})
    except Exception as e:  # noqa: BLE001
        logger.exception("audit 扫描失败")
        with _audit_lock:
            _audit_state.update({"running": False, "done": True, "error": str(e), "stats": None})


def _coerce_creds(raw: dict) -> dict:
    """把表单/JSON 里的字符串字段整理成 Settings 可用的类型。"""
    out: dict = {}
    for k in ("tm1_address", "tm1_user", "tm1_password", "tm1_namespace"):
        if raw.get(k):
            out[k] = str(raw[k]).strip()
    if raw.get("tm1_port") not in (None, ""):
        try:
            out["tm1_port"] = int(raw["tm1_port"])
        except (TypeError, ValueError):
            pass
    if "tm1_ssl" in raw and raw["tm1_ssl"] not in (None, ""):
        out["tm1_ssl"] = str(raw["tm1_ssl"]).lower() in ("1", "true", "yes", "on")
    return out


def _settings_with_creds(creds: dict | None) -> Settings:
    """空字段回退到默认配置，实现「登录后覆盖连接，其余沿用 .env」。"""
    base = get_settings()
    overrides = _coerce_creds(creds or {})
    return base.model_copy(update=overrides) if overrides else base


def _store() -> Store:
    # 惰性 Demo 兜底：无本地数据时自动进入 Demo（产品底线：不打开空壳）
    _ensure_demo_available()
    return Store(get_settings())


# ===========================================================================
# 数据源状态（Task 19：本地数据优先 / Demo 兜底 / Import Local Data）
# ===========================================================================

def _data_source_status() -> dict:
    """返回当前数据源状态（供首页 / Header / Settings 复用）。"""
    from tm1_insight.datasource import detect_current_source

    status = detect_current_source()
    return {
        "type": status.type.value,
        "label": status.type.label,
        "ready": status.ready,
        "location": status.location,
        "counts": status.counts,
        "db_path": status.db_path,
        "db_size": status.db_size,
        "has_data": status.has_data,
        "error": status.error,
    }


# ---- 页面：首页 ----
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # _store() 内部已做惰性 Demo 兜底（无本地数据时自动进入 Demo）
    store = _store()
    try:
        counts = store.all_rows()
        has_data = counts.get("cubes", 0) > 0
    except Exception:  # noqa: BLE001
        counts, has_data = {}, False

    # 数据源状态（供 Header / 首页展示）
    data_source = _data_source_status()

    # Snapshots 计数：优先读 SnapshotStore（若已建立快照目录），否则为 0
    snapshots_count = 0
    try:
        from tm1_insight.snapshot import SnapshotStore
        snap_root = get_settings().data_dir / "snapshots"
        if snap_root.exists():
            snapshots_count = len(SnapshotStore(snap_root).list_snapshots())
    except Exception:  # noqa: BLE001
        snapshots_count = 0

    # 数据快照时间：取 duckdb 文件 mtime（无单独元数据表，用它近似「上次拉取」时间）
    snapshot_time = None
    try:
        if store.db_path.exists():
            import datetime
            snapshot_time = datetime.datetime.fromtimestamp(
                store.db_path.stat().st_mtime
            ).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        snapshot_time = None

    settings = get_settings()
    return templates.TemplateResponse(request, "index.html", {
        "counts": counts,
        "has_data": has_data,
        "data_source": data_source,
        "is_demo": data_source.get("type") == "demo",
        "snapshots_count": snapshots_count,
        "snapshot_time": snapshot_time,
        "tm1_address": settings.tm1_address,
        "tm1_port": settings.tm1_port,
        "tm1_user": settings.tm1_user,
        "tm1_namespace": settings.tm1_namespace,
        "input_applications_dir": str(settings.input_applications_dir),
        "input_externals_dir": str(settings.input_externals_dir),
        "ingest_state": _ingest_state,
    })


# ---- 页面：连接 / 设置 ----
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    settings = get_settings()
    store = _store()
    try:
        counts = store.all_rows()
        has_data = counts.get("cubes", 0) > 0
    except Exception:  # noqa: BLE001
        counts, has_data = {}, False
    return templates.TemplateResponse(request, "settings.html", {
        "has_data": has_data,
        "data_source": _data_source_status(),
        "tm1_address": settings.tm1_address,
        "tm1_port": settings.tm1_port,
        "tm1_user": settings.tm1_user,
        "tm1_namespace": settings.tm1_namespace,
        "tm1_ssl": settings.tm1_ssl,
        "input_applications_dir": str(settings.input_applications_dir),
        "input_externals_dir": str(settings.input_externals_dir),
        "ingest_state": _ingest_state,
    })


# ---- 页面：Explorer（拆分为 Cube / TI 独立浏览） ----
@app.get("/cubes", response_class=HTMLResponse)
def cubes_page(request: Request, q: str = "", page: int = 1):
    store = _store()
    con = store.connect(read_only=True)
    try:
        per_page = 100
        offset = max(0, (page - 1)) * per_page
        result = queries.search_cubes(con, q, offset=offset, limit=per_page)
    finally:
        con.close()
    total_pages = max(1, (result["total"] + per_page - 1) // per_page)
    return templates.TemplateResponse(request, "cubes.html", {
        "cubes": result["items"],
        "total": result["total"],
        "q": q,
        "page": page,
        "total_pages": total_pages,
    })


@app.get("/processes", response_class=HTMLResponse)
def processes_page(request: Request, q: str = "", page: int = 1):
    store = _store()
    con = store.connect(read_only=True)
    try:
        if q.strip():
            # 服务端搜索（含代码全文）
            all_procs = queries.search_processes(con, q, limit=500)
            total = len(all_procs)
            per_page = 100
            offset = max(0, (page - 1)) * per_page
            processes = all_procs[offset:offset + per_page]
            chores = []
        else:
            per_page = 100
            offset = max(0, (page - 1)) * per_page
            processes = [r[0] for r in con.execute(
                "SELECT name FROM processes ORDER BY name LIMIT ? OFFSET ?",
                [per_page, offset]).fetchall()]
            total = con.execute("SELECT count(*) FROM processes").fetchone()[0]
            chores = queries.list_chores(con)
    finally:
        con.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(request, "processes.html", {
        "processes": processes,
        "chores": chores,
        "total": total,
        "q": q,
        "page": page,
        "total_pages": total_pages,
    })


@app.get("/dimensions", response_class=HTMLResponse)
def dimensions_page(request: Request, q: str = "", page: int = 1):
    store = _store()
    con = store.connect(read_only=True)
    try:
        per_page = 100
        offset = max(0, (page - 1)) * per_page
        if q.strip():
            like = f"%{q.strip()}%"
            total = con.execute(
                "SELECT count(*) FROM dimensions WHERE name ILIKE ?", [like]
            ).fetchone()[0]
            dims = [r[0] for r in con.execute(
                "SELECT name FROM dimensions WHERE name ILIKE ? ORDER BY name LIMIT ? OFFSET ?",
                [like, per_page, offset],
            ).fetchall()]
        else:
            total = con.execute("SELECT count(*) FROM dimensions").fetchone()[0]
            dims = [r[0] for r in con.execute(
                "SELECT name FROM dimensions ORDER BY name LIMIT ? OFFSET ?",
                [per_page, offset],
            ).fetchall()]
    finally:
        con.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(request, "dimensions.html", {
        "dimensions": dims,
        "total": total,
        "q": q,
        "page": page,
        "total_pages": total_pages,
    })


# 兼容旧入口：/explorer 重定向到 Cube 浏览
@app.get("/explorer", response_class=HTMLResponse)
def explorer(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/cubes", status_code=302)


@app.get("/explorer/process/{name}", response_class=HTMLResponse)
def explorer_process(request: Request, name: str):
    store = _store()
    con = store.connect(read_only=True)
    try:
        proc = queries.get_process(con, name)
        call_tree = queries.process_call_tree(con, name) if proc else None
    finally:
        con.close()
    if not proc:
        return _error_page(request, 404, "TI 进程不存在", "未找到名为「" + name + "」的 TI 进程。它可能已被重命名或删除。")
    return templates.TemplateResponse(request, "process_view.html", {"proc": proc, "call_tree": call_tree})


@app.get("/explorer/chore/{name}", response_class=HTMLResponse)
def explorer_chore(request: Request, name: str):
    store = _store()
    con = store.connect(read_only=True)
    try:
        chore = queries.get_chore(con, name)
    finally:
        con.close()
    if not chore:
        return _error_page(request, 404, "Chore 不存在", "未找到名为「" + name + "」的 Chore。它可能已被重命名或删除。")
    return templates.TemplateResponse(request, "chore_view.html", {"chore": chore})


@app.get("/explorer/cube/{name}", response_class=HTMLResponse)
def explorer_cube(request: Request, name: str):
    store = _store()
    con = store.connect(read_only=True)
    try:
        cube = queries.get_cube(con, name)
        lineage = queries.cube_lineage(con, name) if cube else None
    finally:
        con.close()
    if not cube:
        return _error_page(request, 404, "Cube 不存在", "未找到名为「" + name + "」的 Cube。它可能已被重命名或删除。")
    return templates.TemplateResponse(request, "cube_view.html", {"cube": cube, "lineage": lineage})


# ---- 页面：Graph（知识图谱：以 TI 为中心的操作 cube + 调用链） ----
@app.get("/graph", response_class=HTMLResponse)
def graph(request: Request, ti: Optional[str] = None):
    store = _store()
    con = store.connect(read_only=True)
    try:
        graph_data = queries.process_graph_rich(con, ti) if ti else None
        # 中心 TI 的写入切面（核心：它往哪个 cube 的哪个切面写数据）
        slices = queries.ti_write_slices(con, ti) if ti else None
    finally:
        con.close()
    return templates.TemplateResponse(request, "graph.html", {
        "ti": ti, "graph": graph_data, "slices": slices,
    })


# ---- 页面：Impact（依赖 / 影响分析，复用 impact 引擎） ----
@app.get("/impact", response_class=HTMLResponse)
def impact_page(request: Request, source: Optional[str] = None):
    store = _store()
    con = store.connect(read_only=True)
    try:
        all_processes = [r[0] for r in con.execute(
            "SELECT name FROM processes ORDER BY name").fetchall()]
        all_cubes = [r[0] for r in con.execute(
            "SELECT name FROM cubes ORDER BY name").fetchall()]
        dependencies = dependencies_from_store(con)
    finally:
        con.close()

    result = None
    if source:
        from tm1_insight.impact import analyze_impact
        from tm1_insight.lineage import get_upstream, get_downstream

        impacts = analyze_impact(dependencies, source)
        upstream = get_upstream(dependencies, source)
        downstream = get_downstream(dependencies, source)
        result = {
            "source": source,
            "impacts": impacts,
            "upstream": upstream,
            "downstream": downstream,
        }

    return templates.TemplateResponse(request, "impact.html", {
        "source": source,
        "result": result,
        "all_processes": all_processes,
        "all_cubes": all_cubes,
        "dependency_count": len(dependencies),
    })


# ---- 页面：Compare（Snapshot Compare + Change Intelligence） ----
@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request):
    # 重计算页面（约 1s）：数据未变化时复用缓存结果，切换延迟压到毫秒级。
    def _render() -> str:
        store = _store()
        con = store.connect(read_only=True)
        try:
            from tm1_insight.store.graph_adapter import snapshot_payload_from_store
            payload = snapshot_payload_from_store(con)
            dependencies = dependencies_from_store(con)
        finally:
            con.close()

        # 当前只有一份数据（单快照），Compare 需要 before/after。
        # 这里用「空快照 vs 当前入库数据」演示对象级 Compare + Change Intelligence
        # 能力链；未来接入多快照历史后再提供真实 before/after 选择。
        from tm1_insight.compare import compare_snapshots
        from tm1_insight.change_intelligence import analyze_changes

        empty = {"processes": [], "rules": [], "cubes": [], "dimensions": []}
        compare_result = compare_snapshots(empty, payload)

        # Change Intelligence 做「有界采样」：只对「有入边（会被依赖）」的 cube 中
        # 前 50 个做影响分析，避免对全部 19763 个对象做 upstream 遍历导致页面超时。
        # 这是 Web MVP 的体验取舍，真实多快照 Compare 需接入快照数据 + 引擎性能优化。
        indegree: dict[str, int] = {}
        for d in dependencies:
            indegree[d.target] = indegree.get(d.target, 0) + 1
        sampled_cubes = [c for c in payload["cubes"] if c["name"] in indegree][:50]
        sampled_payload = {"processes": [], "rules": [], "cubes": sampled_cubes, "dimensions": []}
        ci_result = analyze_changes(empty, sampled_payload, dependencies)

        return templates.get_template("compare.html").render({
            "request": request,
            "compare": compare_result,
            "ci": ci_result,
            "sampled": True,
            "sampled_total": len(payload["cubes"]),
            "sampled_note": "影响分析对「会被依赖的 Cube」采样前 50 个做预览演示；完整分析需接入多快照历史或后台索引引擎。",
        })

    return _cached_page("compare", _render)


# ---- 页面：代码生成 ----
@app.get("/codegen", response_class=HTMLResponse)
def codegen(request: Request):
    store = _store()
    con = store.connect(read_only=True)
    try:
        cubes = [c["name"] for c in queries.list_cubes(con)]
    finally:
        con.close()
    return templates.TemplateResponse(request, "codegen.html", {"cubes": cubes})


# ---- 代码生成 API ----
@app.post("/api/codegen/data-transfer")
def api_codegen_data_transfer(body: dict = Body(...)) -> dict:
    """数据传输 A→B：读源/目标 cube 维度做对齐，返回生成的 TI 代码。"""
    from tm1_insight.store import codegen as cg

    src = (body.get("src_cube") or "").strip()
    tgt = (body.get("tgt_cube") or "").strip()
    prefix = (body.get("prefix") or "}APQ").strip()
    if not src or not tgt:
        return JSONResponse({"error": "请填写源 cube 和目标 cube"}, status_code=400)

    src_filters = body.get("src_filters") or []
    tgt_filters = body.get("tgt_filters") or []
    params = body.get("params") or []
    operation = (body.get("operation") or "CellIncrementN").strip()

    store = _store()
    con = store.connect(read_only=True)
    try:
        return cg.data_transfer(con, src, tgt, prefix,
                                src_filters=src_filters,
                                tgt_filters=tgt_filters,
                                params=params,
                                operation=operation)
    finally:
        con.close()


@app.post("/api/codegen/data-export")
def api_codegen_data_export(body: dict = Body(...)) -> dict:
    """数据导出：读源 cube 生成 CSV 导出 TI 代码。"""
    from tm1_insight.store import codegen as cg

    src = (body.get("src_cube") or "").strip()
    prefix = (body.get("prefix") or "}APQ").strip()
    if not src:
        return JSONResponse({"error": "请填写源 cube"}, status_code=400)

    store = _store()
    con = store.connect(read_only=True)
    try:
        return cg.data_export(con, src, prefix=prefix)
    finally:
        con.close()


@app.post("/api/codegen/data-export-dim")
def api_codegen_data_export_dim(body: dict = Body(...)) -> dict:
    """维度导出：读维度生成 SUBSET 导出 TI 代码（复刻 Sys.DWI.Data.Export.Dim）。"""
    from tm1_insight.store import codegen as cg

    dim = (body.get("dim") or "").strip()
    prefix = (body.get("prefix") or "}APQ").strip()
    if not dim:
        return JSONResponse({"error": "请填写维度名"}, status_code=400)

    params = body.get("params") or []

    store = _store()
    con = store.connect(read_only=True)
    try:
        return cg.data_export_dim(con, dim, prefix, params=params)
    finally:
        con.close()


@app.get("/api/codegen/dim-list")
def api_codegen_dim_list() -> dict:
    """返回全部维度名（供维度导出/维度维护下拉选择）。"""
    store = _store()
    con = store.connect(read_only=True)
    try:
        rows = con.execute("SELECT name FROM dimensions ORDER BY name").fetchall()
        return {"dims": [r[0] for r in rows]}
    finally:
        con.close()


@app.post("/api/codegen/cube-dims")
def api_codegen_cube_dims(body: dict = Body(...)) -> dict:
    """返回指定 cube 的维度列表（供前端展示维度结构做筛选）。"""
    from tm1_insight.store import codegen as cg

    cube = (body.get("cube") or "").strip()
    if not cube:
        return JSONResponse({"error": "请填写 cube"}, status_code=400)
    store = _store()
    con = store.connect(read_only=True)
    try:
        dims = cg._cube_dims(con, cube)
        return {"cube": cube, "dims": dims}
    finally:
        con.close()


@app.post("/api/codegen/logging-init")
def api_codegen_logging_init(body: dict = Body(...)) -> dict:
    """日志框架初始化：可自定义前缀，返回建对象 + 标准 TI 骨架。"""
    from tm1_insight.store import codegen as cg

    prefix = (body.get("prefix") or "}APQ").strip()
    y_start = body.get("year_start") or 2020
    y_end = body.get("year_end") or 2030
    try:
        y_start = int(y_start)
        y_end = int(y_end)
    except (TypeError, ValueError):
        y_start, y_end = 2020, 2030
    return cg.logging_init(prefix, y_start, y_end)


@app.post("/api/codegen/dimension-maintain")
def api_codegen_dimension_maintain(body: dict = Body(...)) -> dict:
    """维度维护 TI 代码生成。"""
    from tm1_insight.store import codegen as cg

    dim = (body.get("dim") or "").strip()
    prefix = (body.get("prefix") or "}APQ").strip()
    if not dim:
        return JSONResponse({"error": "请填写维度名"}, status_code=400)
    return cg.dimension_maintain(dim, prefix)



# ---- 页面：Audit（阶段 3：Excel 资产 → Cube 映射） ----
@app.get("/audit", response_class=HTMLResponse)
def audit(request: Request):
    store = _store()
    con = store.connect(read_only=True)
    try:
        assets = queries.list_audit_assets(con)
        mappings = queries.list_audit_mappings(con)
        # 汇总统计（供顶部统计卡片与筛选）
        summary = {
            "total_assets": len(assets),
            "total_mappings": len(mappings),
            "with_tm1": sum(1 for a in assets if a.get("has_tm1")),
            "risk_high": sum(1 for a in assets if a.get("risk") == "高"),
            "risk_mid": sum(1 for a in assets if a.get("risk") == "中"),
            "risk_low": sum(1 for a in assets if a.get("risk") == "低"),
            "broken_link": sum(1 for a in assets if a.get("asset_type") in ("Broken Link", "Invalid Blob")),
            "formula_total": sum(a.get("formula_count") or 0 for a in assets),
        }
    finally:
        con.close()
    settings = get_settings()
    return templates.TemplateResponse(request, "audit.html", {
        "assets": assets,
        "mappings": mappings,
        "summary": summary,
        "applications_dir": str(settings.input_applications_dir),
        "externals_dir": str(settings.input_externals_dir),
    })


# ---- API ----
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/api/status")
def status() -> dict:
    store = _store()
    try:
        return {"db_path": store.db_path, "tables": store.all_rows()}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=500)


# ---- 数据源 API（Task 19） ----

@app.get("/api/datasource/status")
def api_datasource_status() -> dict:
    """返回当前数据源状态（Local / Demo / Empty）。"""
    return _data_source_status()


@app.post("/api/datasource/detect")
def api_datasource_detect(body: dict = Body(...)) -> dict:
    """检测用户选择的数据目录，返回结构化的检测结果（有实时反馈）。"""
    from tm1_insight.datasource import detect_directory

    path = (body.get("path") or "").strip()
    if not path:
        return JSONResponse({"error": "请提供一个目录路径。"}, status_code=400)

    result = detect_directory(path)
    return {
        "path": result.path,
        "valid": result.valid,
        "error": result.error,
        "has_duckdb": result.has_duckdb,
        "has_parquet": result.has_parquet,
        "has_raw": result.has_raw,
        "counts": result.counts,
        "db_size": result.db_size,
        "partial": result.partial,
    }


@app.post("/api/datasource/use")
def api_datasource_use(body: dict = Body(...)) -> dict:
    """切换数据源。

    支持：
      - {"source": "demo"}               → 切换到内置 Demo 数据
      - {"source": "local", "path": ...} → 切换到用户选择的数据目录
      - {"source": "reset"}              → 清除覆盖，回到默认用户数据目录

    切换后清空配置缓存，前端刷新即可看到新数据。绝不复制数据（方案 A）。
    """
    from tm1_insight import datasource as ds
    from tm1_insight.config import set_data_dir

    source = (body.get("source") or "").strip().lower()

    if source == "demo":
        # load_demo_data 内部已 set_data_dir(demo_dir)，无需再次设置
        ds.load_demo_data()
        return {"ok": True, "status": _data_source_status()}

    if source == "local":
        path = (body.get("path") or "").strip()
        if not path:
            return JSONResponse({"error": "请提供一个数据目录路径。"}, status_code=400)
        det = ds.detect_directory(path)
        if not det.valid:
            return JSONResponse(
                {"error": det.error or "数据目录无效。"},
                status_code=400,
            )
        # 记录覆盖目录（不复制数据）。若给的是 .duckdb 文件，取其父目录。
        from pathlib import Path as _P
        _pp = _P(path)
        data_dir = str(_pp.parent) if _pp.is_file() else path
        set_data_dir(data_dir)
        # 重新检测确认
        st = ds.detect_current_source()
        if not st.has_data:
            set_data_dir(None)
            return JSONResponse({"error": "该目录未包含有效数据。"}, status_code=400)
        return {"ok": True, "status": _data_source_status()}

    if source == "reset":
        set_data_dir(None)
        return {"ok": True, "status": _data_source_status()}

    return JSONResponse(
        {"error": "未知的数据源类型，支持 demo / local / reset。"},
        status_code=400,
    )


@app.post("/api/import")
async def api_import(file: UploadFile = File(...)) -> dict:
    """导入数据包：接收一个 .duckdb 文件，替换用户数据目录里的库文件。

    支持：
      - *.duckdb：直接作为 tm1_insight.duckdb 使用
      - *.zip：解压出 data/db/tm1_insight.duckdb（或根下的 tm1_insight.duckdb）后导入
    导入后前端刷新即可看到数据，无需联网、无需重新拉取 TM1。
    """
    import io
    import zipfile

    filename = (file.filename or "").lower()
    settings = get_settings()
    settings.ensure_dirs()

    # 目标库文件路径（用户数据目录）
    dst = settings.db_dir / "tm1_insight.duckdb"
    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        if filename.endswith(".duckdb"):
            # 直接写入（分块避免大文件一次性读入内存）
            with open(dst, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    out.write(chunk)
        elif filename.endswith(".zip"):
            data = await file.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                # 找 data/db/tm1_insight.duckdb 或根下 tm1_insight.duckdb
                candidates = [
                    n for n in zf.namelist()
                    if n.endswith("tm1_insight.duckdb")
                ]
                if not candidates:
                    return JSONResponse(
                        {"error": "压缩包里没有找到 tm1_insight.duckdb 文件"},
                        status_code=400,
                    )
                # 优先精确的 data/db/tm1_insight.duckdb
                exact = next((n for n in candidates if n.endswith("data/db/tm1_insight.duckdb")), candidates[0])
                with zf.open(exact) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out)
        else:
            return JSONResponse(
                {"error": "不支持的文件类型，请上传 .duckdb 或 .zip 文件"},
                status_code=400,
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("导入数据包失败")
        return JSONResponse({"error": f"导入失败：{e}"}, status_code=500)

    # 导入成功后清空内存缓存，避免旧连接缓存旧数据
    try:
        get_settings.cache_clear()
    except Exception:  # noqa: BLE001
        pass

    return {"ok": True, "db_path": str(dst)}


@app.get("/api/cube/{cube}")
def api_cube(cube: str) -> dict:
    store = _store()
    con = store.connect(read_only=True)
    try:
        return queries.cube_summary(con, cube)
    finally:
        con.close()


@app.get("/api/cube/{cube}/lineage")
def api_cube_lineage(cube: str) -> dict:
    store = _store()
    con = store.connect(read_only=True)
    try:
        return queries.cube_lineage(con, cube)
    finally:
        con.close()


@app.get("/api/search")
def api_search(q: str, limit: int = 50) -> dict:
    store = _store()
    con = store.connect(read_only=True)
    try:
        return {"results": queries.search_processes(con, q, limit)}
    finally:
        con.close()


@app.get("/api/search-all")
def api_search_all(q: str, limit: int = 20) -> dict:
    """统一搜索 Cube + TI，返回带类型的结果（工作台全局搜索用）。"""
    store = _store()
    con = store.connect(read_only=True)
    try:
        return queries.search_objects(con, q, limit)
    finally:
        con.close()


@app.get("/api/trace")
def api_trace(cube: Optional[str] = None, mdx: Optional[str] = None) -> dict:
    """「值从哪里来」排查：给定 Cube（可选 MDX 反解交叉点），返回可能写入该交叉点的 TI。

    - 只传 mdx：从 MDX 反解 cube + 维度元素交叉点，返回命中的写入点。
    - 只传 cube：返回该 cube 所有写入点候选（含上游源头 + 前端输入标记）。
    """
    store = _store()
    con = store.connect(read_only=True)
    try:
        members = None
        if mdx:
            parsed = queries.parse_mdx(mdx)
            if not cube:
                cube = parsed["cube"]
            members = parsed["members"] or None
        if not cube:
            return {"cube": None, "dimensions": [], "members": {}, "candidates": [], "matched_count": 0, "relaxed": False}
        return queries.trace_cell_value(con, cube, members)
    finally:
        con.close()


def _run_ingest(creds: dict | None = None) -> None:
    global _ingest_state
    with _ingest_lock:
        _ingest_state = {"running": True, "done": False, "error": None, "stats": None}
    try:
        from tm1_insight.ingest.exporter import Exporter
        from tm1_insight.ingest.loader import Loader

        settings = _settings_with_creds(creds)
        Exporter(settings).export_all()
        stats = Loader(settings).load(drop=True)
        with _ingest_lock:
            _ingest_state = {"running": False, "done": True, "error": None, "stats": stats}
    except Exception as e:  # noqa: BLE001
        logger.exception("ingest 失败")
        with _ingest_lock:
            _ingest_state = {"running": False, "done": True, "error": str(e), "stats": None}


@app.post("/api/ingest")
def api_ingest(payload: Optional[dict] = Body(default=None)):
    """触发后台拉取（长任务）。可选携带登录凭据覆盖默认连接。"""
    creds = _coerce_creds(payload or {})
    with _ingest_lock:
        if _ingest_state.get("running"):
            return JSONResponse({"error": "已有拉取任务在运行"}, status_code=409)
    thread = threading.Thread(target=_run_ingest, args=(creds,), daemon=True)
    thread.start()
    return {"started": True}


@app.get("/api/ingest/status")
def api_ingest_status() -> dict:
    with _ingest_lock:
        return dict(_ingest_state)


@app.post("/api/audit")
def api_audit() -> dict:
    """触发前端 Excel 资产扫描（本地，异步后台执行，通过 /api/audit/status 轮询进度）。"""
    with _audit_lock:
        if _audit_state.get("running"):
            return JSONResponse({"error": "已有扫描任务在运行"}, status_code=409)
        _audit_state.update({"running": True, "done": False, "error": None, "stats": None, "progress": {"phase": "准备中", "done": 0, "total": 0}})
    thread = threading.Thread(target=_run_audit, daemon=True)
    thread.start()
    return {"started": True}


@app.get("/api/audit/status")
def api_audit_status() -> dict:
    with _audit_lock:
        return dict(_audit_state)
