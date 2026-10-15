"""FastAPI 应用：三视图 Web UI（Explorer / Graph / Audit）+ 数据 API。

纯 Jinja2 服务端渲染 + 手写 CSS，不依赖 CDN，内网离线可用。
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Literal, Optional

import shutil
import json
import io
import zipfile
from functools import lru_cache

from fastapi import Body, FastAPI, File, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from tm1_insight import __version__
from tm1_insight.config import Settings, get_settings
from tm1_insight.store.db import Store
from tm1_insight.store import queries
from tm1_insight.store.graph_adapter import dependencies_from_store
from tm1_insight.ingest.progress import INGEST_STAGES, AUDIT_STAGES, stage_progress
from tm1_insight.tasks import TaskCancelled
from tm1_insight.api.knowledge_tasks import router as knowledge_router
from tm1_insight.api.learning import router as learning_router
from tm1_insight.api.experience import router as experience_router
from tm1_insight.api.workflow import router as workflow_router
from tm1_insight.api.architecture import router as architecture_router

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
app.include_router(knowledge_router)
app.include_router(learning_router)
app.include_router(experience_router)
app.include_router(workflow_router)
app.include_router(architecture_router)


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
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
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
_ingest_state: dict = {"running": False, "done": False, "error": None, "stats": None, "progress": None}
_ingest_lock = threading.Lock()
_ingest_cancel = threading.Event()

# 内存中的前端资产扫描任务状态
_audit_state: dict = {"running": False, "done": False, "error": None, "stats": None, "progress": None}
_audit_lock = threading.Lock()
_audit_cancel = threading.Event()


# ===========================================================================
# 页面级结果缓存：重计算页面（如 /compare 需 1s 级重算）在数据未变化时
# 直接复用上次渲染结果，把切换延迟从「秒级」压到「毫秒级」。
# 失效依据：数据目录 + 主 db 文件 mtime。数据一变更（导入/重拉）即失效。
# ===========================================================================
_page_cache: dict[str, tuple[str, str]] = {}          # cache_key -> (data_fingerprint, html)
_page_cache_lock = threading.Lock()


def _data_fingerprint(settings: Settings | None = None) -> str:
    """当前数据目录下主库文件的 mtime 指纹，用于判断数据是否变化。"""
    try:
        settings = settings or get_settings()
        db = Path(settings.db_path) if settings.db_path else None
        if db and db.exists():
            st = db.stat()
            wal = db.with_suffix(db.suffix + ".wal")
            wal_state = f"{wal.stat().st_mtime_ns}:{wal.stat().st_size}" if wal.exists() else "no-wal"
            return f"{db.resolve()}:{st.st_mtime_ns}:{st.st_size}:{wal_state}"
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
        # Single-flight: simultaneous opens must not repeat the same calculation.
        html = renderer()
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


def _run_audit(settings=None) -> None:
    global _audit_state
    try:
        from tm1_insight.ingest.audit import load_audit

        def progress(phase, done, total):
            if _audit_cancel.is_set():
                raise TaskCancelled()
            with _audit_lock:
                _audit_state["progress"] = stage_progress(AUDIT_STAGES, phase, done, total)

        from tm1_insight.audit_workspace import workspace
        progress("prepare", None, None)
        scan_settings = workspace(settings or get_settings().model_copy(), initialize=True)
        stats = load_audit(scan_settings, progress=progress)
        with _audit_lock:
            _audit_state.update({"running": False, "done": True, "error": None, "stats": stats})
    except Exception as e:  # noqa: BLE001
        logger.error("本地前端扫描失败：%s", type(e).__name__)
        with _audit_lock:
            _audit_state.update({"running": False, "done": True, "cancelled": _audit_cancel.is_set(),
                "error": "扫描已取消，上次完整结果保留。" if _audit_cancel.is_set() else "扫描失败，请检查文件格式、权限和缓存目录空间。", "stats": None})


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


templates.env.globals["current_data_source"] = _data_source_status


def _process_search_source(settings: Settings | None = None) -> str:
    """Browser context key: private path is hashed, source updates invalidate locations."""
    import hashlib
    return hashlib.sha256(_data_fingerprint(settings).encode("utf-8")).hexdigest()


# ---- 页面：首页 ----
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # _store() 内部已做惰性 Demo 兜底（无本地数据时自动进入 Demo）
    store = _store()
    try:
        counts = store.all_rows()
        has_data = any(counts.get(key, 0) > 0 for key in ("cubes", "processes", "dimensions", "chores", "rules"))
    except Exception:  # noqa: BLE001
        counts, has_data = {}, False

    # 数据源状态（供 Header / 首页展示）
    data_source = _data_source_status()

    # File modification time is not proof of collection time or snapshot version.
    model_file_time = None
    try:
        if Path(store.db_path).exists():
            import datetime
            model_file_time = datetime.datetime.fromtimestamp(
                Path(store.db_path).stat().st_mtime
            ).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        model_file_time = None

    settings = get_settings()
    return templates.TemplateResponse(request, "index.html", {
        "counts": counts,
        "has_data": has_data,
        "data_source": data_source,
        "is_demo": data_source.get("type") == "demo",
        "model_file_time": model_file_time,
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
    from tm1_insight.audit_workspace import preferences
    audit_paths = preferences(store.settings)
    return templates.TemplateResponse(request, "settings.html", {
        "has_data": has_data,
        "data_source": _data_source_status(),
        # 敏感连接信息（地址/用户/命名空间）不回填到页面，避免在浏览器暴露真实服务器信息；
        # 端口与 SSL 非敏感，保留回填。
        "tm1_port": settings.tm1_port,
        "tm1_ssl": settings.tm1_ssl,
        "input_applications_dir": audit_paths["applications"],
        "input_externals_dir": audit_paths["externals"],
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
def processes_page(request: Request, q: str = Query("", max_length=1000),
                   page: int = Query(1, ge=1), scope: Literal["name", "code", "all"] = "name"):
    store = _store()
    con = store.connect(read_only=True)
    try:
        per_page = 100
        result = queries.search_process_page(con, q, scope, (page - 1) * per_page, per_page)
        total = result["total"]
        page = result["offset"] // per_page + 1
        chore_count = con.execute("SELECT count(*) FROM chores").fetchone()[0]
    finally:
        con.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(request, "processes.html", {
        "processes": result["items"],
        "chore_count": chore_count,
        "total": total,
        "q": result["q"],
        "scope": scope,
        "search_source": _process_search_source(store.settings),
        "page": page,
        "total_pages": total_pages,
    })


@app.get("/dimensions", response_class=HTMLResponse)
def dimensions_page(request: Request, q: str = Query("", max_length=1000),
                    page: int = Query(1, ge=1), name: str = Query("", max_length=1000),
                    view: Literal["elements", "edges", "attributes", "subsets", "cubes"] = "elements",
                    detail_q: str = Query("", max_length=1000), detail_page: int = Query(1, ge=1),
                    element: str = Query("", max_length=1000),
                    subset_index: Optional[int] = Query(None, ge=0),
                    source: str = Query("", max_length=64)):
    from urllib.parse import urlencode
    from tm1_insight.store import dimensions as dim_queries
    from tm1_insight.store import dimension_index
    store = _store()
    current_source = _process_search_source(store.settings)
    if source and source != current_source:
        return _error_page(request, 409, "维度来源已变化", "请重新打开维度页，再选择元素或子集；旧记录位置未用于定位。")
    con = store.connect(read_only=True)
    try:
        listing = dim_queries.search(con, q, page)
        selected_name = name or (listing["items"][0]["name"] if listing["items"] else "")
        indexed = dimension_index.cached(store.settings, selected_name, current_source) if selected_name else None
        dimension = indexed[0]["dimension"] if indexed else (dim_queries.metadata(con, selected_name) if selected_name else None)
        if name and not dimension:
            return _error_page(request, 404, "维度不存在", "当前本地模型没有这个维度，请重新搜索。")
        details = None
        subset = None
        needs_index = bool(dimension and not indexed and view in dim_queries.FIELDS and (
            dimension["fields"][view]["count"] > dimension_index.THRESHOLD or
            (view == "edges" and dimension["fields"]["elements"]["count"] > dimension_index.THRESHOLD)))
        if dimension and not needs_index:
            def record_page(field, **options):
                return (dimension_index.records(indexed[1], field, **options) if indexed else
                        dim_queries.records(con, selected_name, field, **options))
            details = (dim_queries.cubes(con, selected_name, detail_page) if view == "cubes" else
                       record_page(view, keyword=detail_q, page=detail_page, element=element))
            if view == "subsets" and subset_index is not None:
                records = record_page("subsets", index=subset_index)
                if not records["items"]:
                    return _error_page(request, 404, "子集记录不存在", "该子集位置不存在，请重新选择。")
                subset = records["items"][0]
    finally:
        con.close()
    if current_source != _process_search_source(store.settings) or current_source != _process_search_source():
        return _error_page(request, 409, "维度来源已变化", "查询期间模型已变化，请重新打开维度页。")
    def dimension_url(**updates):
        params = dict(q=q, page=listing["page"], name=selected_name, view=view,
                      detail_q=detail_q, detail_page=details["page"] if details else 1,
                      element=element, subset_index=subset_index, source=current_source)
        params.update(updates)
        return "/dimensions?" + urlencode({k: v for k, v in params.items() if v is not None}) + "#dimension-detail"
    return templates.TemplateResponse(request, "dimensions.html", {
        "listing": listing, "dimension": dimension, "details": details, "subset": subset,
        "needs_index": needs_index,
        "q": q, "view": view, "detail_q": detail_q, "element": element,
        "source": current_source, "dimension_url": dimension_url,
    })


@app.get("/api/dimensions/{name}/tree")
def api_dimension_tree(name: str, source: str = Query("", max_length=64)):
    """维度元素层级树概览：顶层元素 + 元数据，子节点懒加载。"""
    from tm1_insight.store import dimension_tree
    store = _store()
    current_source = _process_search_source(store.settings)
    if source and source != current_source:
        return JSONResponse({"error": "数据源已变化，请重新打开维度页。"}, status_code=409)
    con = store.connect(read_only=True)
    try:
        summary = dimension_tree.tree_summary(con, name)
    finally:
        con.close()
    if summary is None:
        return JSONResponse({"error": "维度不存在。"}, status_code=404)
    if current_source != _process_search_source():
        return JSONResponse({"error": "数据源已变化，请重新打开维度页。"}, status_code=409)
    summary["source"] = current_source
    return JSONResponse(summary, headers={"Cache-Control": "no-store"})


@app.get("/api/dimensions/{name}/children/{element}")
def api_dimension_children(name: str, element: str, source: str = Query("", max_length=64)):
    """某元素的直接子项（含原始权重），供元素树懒加载展开。"""
    from tm1_insight.store import dimension_tree
    store = _store()
    current_source = _process_search_source(store.settings)
    if source and source != current_source:
        return JSONResponse({"error": "数据源已变化，请重新打开维度页。"}, status_code=409)
    con = store.connect(read_only=True)
    try:
        result = dimension_tree.children(con, name, element)
    finally:
        con.close()
    if current_source != _process_search_source():
        return JSONResponse({"error": "数据源已变化，请重新打开维度页。"}, status_code=409)
    result["source"] = current_source
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.get("/api/dimensions/{name}/search")
def api_dimension_search(name: str, q: str = Query("", max_length=1000),
                         source: str = Query("", max_length=64)):
    """全维度元素搜索（覆盖全部已索引元素，非当前页），返回匹配项及祖先路径。"""
    from tm1_insight.store import dimension_tree
    store = _store()
    current_source = _process_search_source(store.settings)
    if source and source != current_source:
        return JSONResponse({"error": "数据源已变化，请重新打开维度页。"}, status_code=409)
    if not q.strip():
        return JSONResponse({"keyword": q, "matches": [], "total": 0})
    con = store.connect(read_only=True)
    try:
        result = dimension_tree.search_elements(con, name, q)
    finally:
        con.close()
    if current_source != _process_search_source():
        return JSONResponse({"error": "数据源已变化，请重新打开维度页。"}, status_code=409)
    result["source"] = current_source
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/api/dimensions/index", status_code=202)
def start_dimension_index(body: dict = Body(...)):
    from tm1_insight.store import dimensions, dimension_index
    from tm1_insight.tasks import TaskBusy
    store = _store()
    source = _process_search_source(store.settings)
    name = body.get("name")
    if not isinstance(name, str) or not name or len(name) > 1000:
        return JSONResponse({"error": "请指定有效的维度名称。"}, status_code=400)
    if body.get("source") != source:
        return JSONResponse({"error": "数据源已变化，请重新打开维度页。"}, status_code=409)
    con = store.connect(read_only=True)
    try:
        meta = dimensions.metadata(con, name)
    finally:
        con.close()
    if meta is None:
        return JSONResponse({"error": "维度不存在。"}, status_code=404)
    settings = store.settings.model_copy()
    try:
        return dimension_index.submit(settings, name, source, meta,
            lambda: _process_search_source(settings) == source)
    except TaskBusy as error:
        return JSONResponse({"error": str(error)}, status_code=429)


def _dimension_index_state(task_id):
    from tm1_insight.store.dimension_index import manager
    jobs = manager(get_settings())
    try:
        state = jobs.state(task_id)
    except KeyError:
        raise StarletteHTTPException(404, "索引任务不存在或服务已重启，请重试。") from None
    if state["source"] != _process_search_source():
        raise StarletteHTTPException(409, "数据源已变化，请重新打开维度页。")
    return jobs, state


@app.get("/api/dimensions/index/{task_id}")
def dimension_index_status(task_id: str):
    _, state = _dimension_index_state(task_id)
    return JSONResponse(state, headers={"Cache-Control": "no-store"})


@app.post("/api/dimensions/index/{task_id}/cancel")
def cancel_dimension_index(task_id: str):
    jobs, _ = _dimension_index_state(task_id)
    return jobs.cancel(task_id)


# 兼容旧入口：/explorer 重定向到 Cube 浏览
@app.get("/explorer", response_class=HTMLResponse)
def explorer(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/cubes", status_code=302)


@app.get("/explorer/process/{name}", response_class=HTMLResponse)
def explorer_process(request: Request, name: str, source: str = Query("", max_length=64)):
    store = _store()
    current_source = _process_search_source(store.settings)
    if source and source != current_source:
        return _error_page(request, 409, "源码位置已失效", "数据源或文件已变化，请返回 TI 列表重新搜索；旧行号未用于定位。")
    con = store.connect(read_only=True)
    try:
        proc = queries.get_process(con, name)
        call_tree = queries.process_call_tree(con, name) if proc else None
    finally:
        con.close()
    if not proc:
        return _error_page(request, 404, "TI 进程不存在", "未找到名为「" + name + "」的 TI 进程。它可能已被重命名或删除。")
    if source and current_source != _process_search_source():
        return _error_page(request, 409, "源码位置已失效", "数据源或文件已变化，请返回 TI 列表重新搜索；旧行号未用于定位。")
    return templates.TemplateResponse(request, "process_view.html", {
        "proc": proc, "call_tree": call_tree, "search_source": current_source})


@app.get("/explorer/chore/{name}", response_class=HTMLResponse)
def explorer_chore(request: Request, name: str):
    return chores_page(request, q="", page=1, name=name, step_page=1)


@app.get("/chores", response_class=HTMLResponse)
def chores_page(request: Request, q: str = Query("", max_length=1000),
                page: int = Query(1, ge=1), name: str = "", step_page: int = Query(1, ge=1)):
    store = _store()
    con = store.connect(read_only=True)
    try:
        result = queries.search_chore_page(con, q, (page - 1) * 50, 50)
        selected = name or (result["items"][0]["name"] if result["items"] else "")
        chore = queries.get_chore(con, selected) if selected else None
    finally:
        con.close()
    if name and not chore:
        return _error_page(request, 404, "Chore 不存在", "当前本地库未找到所选 Chore，请重新搜索。")
    step_pages = 1
    if chore:
        chore["step_total"] = len(chore["steps"])
        step_pages = max(1, (chore["step_total"] + 99) // 100)
        step_page = min(step_page, step_pages)
        chore["steps"] = chore["steps"][(step_page - 1) * 100:step_page * 100]
    return templates.TemplateResponse(request, "chore_view.html", {
        "chore": chore, "chores": result["items"], "q": result["q"],
        "total": result["total"], "page": result["offset"] // 50 + 1,
        "total_pages": max(1, (result["total"] + 49) // 50),
        "step_page": step_page, "step_pages": step_pages})


@app.get("/explorer/cube/{name}", response_class=HTMLResponse)
def explorer_cube(request: Request, name: str):
    store = _store()
    source = _process_search_source(store.settings)
    con = store.connect(read_only=True)
    try:
        cube = queries.get_cube(con, name)
        lineage = queries.cube_lineage(con, name) if cube else None
    finally:
        con.close()
    if not cube:
        return _error_page(request, 404, "Cube 不存在", "未找到名为「" + name + "」的 Cube。它可能已被重命名或删除。")
    if source != _process_search_source(store.settings) or source != _process_search_source():
        return _error_page(request, 409, "Cube 来源已变化", "请重新打开 Cube，再进入维度结构。")
    return templates.TemplateResponse(request, "cube_view.html", {"cube": cube, "lineage": lineage,
                                                               "dimension_source": source})


def _calculation_report(name, source, call=None):
    from tm1_insight.store import calculation
    store = _store()
    current = _process_search_source(store.settings)
    if source and source != current:
        raise StarletteHTTPException(409, "模型已变化，请从当前 TI 重新打开计算检查。")
    con = store.connect(read_only=True)
    try:
        if call is None:
            report = calculation.inspect(con, name)
        else:
            from tm1_insight.store.invocation import inspect_call
            report = inspect_call(con, name, call)
    finally: con.close()
    if current != _process_search_source(store.settings) or current != _process_search_source():
        raise StarletteHTTPException(409, "查询期间模型已变化，请重新打开计算检查。")
    if report is None: raise StarletteHTTPException(404, "当前模型中没有这个 TI 或调用点。")
    report['model_fingerprint'] = current
    return report


@app.get("/calculation", response_class=HTMLResponse)
def calculation_page(request: Request, name: str = Query(..., min_length=1, max_length=1000),
                     source: str = Query("", max_length=64), page: int = Query(1, ge=1),
                     write: Optional[int] = Query(None, ge=0), system: bool = False):
    from urllib.parse import urlencode
    from tm1_insight.store.calculation import node_label
    report = _calculation_report(name, source)
    items = [w for w in report['writes'] if system or not (w['cube'] or '').startswith('}')]
    pages = max(1, (len(items)+49)//50); page = min(page,pages)
    selected = next((w for w in items if w['id']==write), None) if write is not None else (items[(page-1)*50] if items else None)
    if write is not None and selected is None: raise StarletteHTTPException(404, "写入点不存在或被前缀筛选隐藏。")
    def url(**updates):
        params = dict(name=name, source=report['model_fingerprint'], page=page, write=selected['id'] if selected else None, system=system)
        params.update(updates)
        return '/calculation?'+urlencode({k:v for k,v in params.items() if v is not None})
    return templates.TemplateResponse(request, "calculation.html", dict(report=report, selected=selected,
        writes=items[(page-1)*50:page*50], hidden=len(report['writes'])-len(items), total=len(items), pages=pages, page=page,
        system=system, url=url, nodes={n['id']:n for n in report['nodes']}, node_label=node_label))


@app.get("/api/calculation/export")
def calculation_export(name: str = Query(..., min_length=1, max_length=1000),
                       source: str = Query(..., min_length=64, max_length=64), format: Literal['json','markdown']='json'):
    from fastapi.responses import Response
    from tm1_insight.store.calculation import markdown
    report = _calculation_report(name, source)
    content = markdown(report) if format=='markdown' else json.dumps(report,ensure_ascii=False,indent=2)
    suffix, media = ('md','text/markdown') if format=='markdown' else ('json','application/json')
    return Response(content, media_type=media, headers={'Content-Disposition':f'attachment; filename=TI_Calculation.{suffix}',
                                                        'Cache-Control':'no-store'})


@app.get('/invocation', response_class=HTMLResponse)
def invocation_page(request: Request, name: str = Query(..., min_length=1, max_length=1000),
                    call: int = Query(..., ge=0), source: str = Query(..., min_length=64, max_length=64)):
    from tm1_insight.store.calculation import node_label
    report = _calculation_report(name, source, call)
    return templates.TemplateResponse(request, 'invocation.html', dict(report=report,
        nodes={n['id']:n for n in report['nodes']}, node_label=node_label))


@app.get('/api/invocation/export')
def invocation_export(name: str = Query(..., min_length=1, max_length=1000), call: int = Query(..., ge=0),
                      source: str = Query(..., min_length=64, max_length=64), format: Literal['json','markdown']='json'):
    from fastapi.responses import Response
    from tm1_insight.store.invocation import markdown
    report = _calculation_report(name, source, call)
    content = markdown(report) if format=='markdown' else json.dumps(report,ensure_ascii=False,indent=2)
    suffix, media = ('md','text/markdown') if format=='markdown' else ('json','application/json')
    return Response(content, media_type=media, headers={'Content-Disposition':f'attachment; filename=TI_Invocation.{suffix}',
                                                      'Cache-Control':'no-store'})


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
@lru_cache(maxsize=2)
def _dependency_index(db_path: str, fingerprint: str):
    """Bounded, rebuildable index; never retain source code or database connections."""
    import duckdb
    from tm1_insight.lineage.engine import build_adjacency
    con = duckdb.connect(db_path, read_only=True)
    try:
        dependencies = dependencies_from_store(con)
    finally:
        con.close()
    return dependencies, build_adjacency(dependencies)


@app.get("/impact", response_class=HTMLResponse)
def impact_page(request: Request, source: Optional[str] = None):
    store = _store()
    counts = _data_source_status().get("counts", {})
    dependency_count = sum(counts.get(table, 0) for table in
                           ("process_reads_cube", "process_writes_cube", "process_calls_process", "rule_references_cube"))
    result = None
    if source:
        from tm1_insight.lineage import get_upstream, get_downstream
        dependencies, adjacency = _dependency_index(str(store.db_path), _data_fingerprint())
        upstream = get_upstream(dependencies, source, _adj=adjacency)
        downstream = get_downstream(dependencies, source, _adj=adjacency)
        result = {
            "source": source,
            "upstream": upstream,
            "downstream": downstream,
        }

    return templates.TemplateResponse(request, "impact.html", {
        "source": source,
        "result": result,
        "dependency_count": dependency_count,
    })


# ---- 页面：Compare（Snapshot Compare + Change Intelligence） ----
@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request, render: bool = False):
    if not render:
        _store()
        return templates.TemplateResponse(request, "compare_status.html", {})
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
        # 前 50 个做影响分析，避免对整模型每个对象做 upstream 遍历导致页面超时。
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
            "sampled_count": len(sampled_cubes),
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


@app.get("/knowledge", response_class=HTMLResponse)
def knowledge_page(request: Request):
    return templates.TemplateResponse(request, "knowledge.html", {})


@app.post("/api/knowledge/preview")
def knowledge_preview(body: dict = Body(...)) -> dict:
    from tm1_insight.knowledge import extract
    store = _store(); con = store.connect(read_only=True)
    try: return extract(con, body.get("prefix", ""), body.get("scope"))
    finally: con.close()


@app.post("/api/knowledge/scope")
def knowledge_scope(body: dict = Body(...)) -> dict:
    from tm1_insight.knowledge import discover_scope
    store = _store(); con = store.connect(read_only=True)
    try:
        selection = discover_scope(con, body.get("prefix", ""), body.get("scope"),
                                   include_dependencies=body.get("include_dependencies", True),
                                   match_mode=body.get("match_mode", "prefix"))
        counts = selection["matched"]
        size = sum(counts.values())
        estimate = "Small" if size < 100 else "Medium" if size < 1000 else "Large"
        return {"prefix": body.get("prefix", ""), "matched": counts,
                "estimated_analysis": estimate, "scope": selection}
    finally: con.close()


@app.post("/api/knowledge/export")
def knowledge_export(body: dict = Body(...)):
    from fastapi.responses import Response
    from tm1_insight.knowledge import extract, markdown
    store = _store(); con = store.connect(read_only=True)
    try: package = extract(con, body.get("prefix", ""), body.get("scope"))
    finally: con.close()
    md = markdown(package)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("knowledge.json", json.dumps(package,ensure_ascii=False,indent=2))
        archive.writestr("knowledge.md", md)
        archive.writestr("development_context.md", md)
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition":"attachment; filename=TM1_Knowledge.zip"})


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
    source = _process_search_source(store.settings)
    con = store.connect(read_only=True)
    try:
        src_dims = cg._cube_dims(con, src)
        tgt_dims = cg._cube_dims(con, tgt)
        if not src_dims or not tgt_dims:
            return JSONResponse({"error": "Cube 不存在或缺少维度结构，请重新选择并加载。"}, status_code=400)
        # Optional additive contract: old API clients still generate from current metadata.
        structure = body.get("structure")
        if structure is not None and structure != {
            "source": source,
            "src_dims": src_dims, "tgt_dims": tgt_dims,
        }:
            return JSONResponse({"error": "模型或维度结构已变化，请重新加载维度结构。"}, status_code=409)
        if operation not in {"CellIncrementN", "CellPutN", "CellPutS"}:
            return JSONResponse({"error": "不支持的写入操作。"}, status_code=400)
        for filters, dims in ((src_filters, src_dims), (tgt_filters, tgt_dims)):
            if not isinstance(filters, list) or any(
                not isinstance(f, dict) or f.get("dim") not in dims for f in filters
            ):
                return JSONResponse({"error": "筛选维度不属于所选 Cube，请重新加载结构。"}, status_code=400)
        result = cg.data_transfer(con, src, tgt, prefix,
                                  src_filters=src_filters,
                                  tgt_filters=tgt_filters,
                                  params=params,
                                  operation=operation)
        if source != _process_search_source(store.settings) or source != _process_search_source():
            return JSONResponse({"error": "数据源在生成期间已变化，请重新加载维度结构。"}, status_code=409)
        return result
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
    source = _process_search_source(store.settings)
    con = store.connect(read_only=True)
    try:
        dims = cg._cube_dims(con, cube)
        if not dims:
            return JSONResponse({"error": "Cube 不存在或缺少维度结构。"}, status_code=400)
        if source != _process_search_source(store.settings) or source != _process_search_source():
            return JSONResponse({"error": "数据源在加载期间已变化，请重新加载维度结构。"}, status_code=409)
        return {"cube": cube, "dims": dims, "source": source}
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
def audit(request: Request, asset_q: str = Query("", max_length=1000),
          mapping_q: str = Query("", max_length=1000),
          risk: Literal["", "高", "中", "低"] = "", tm1: bool = False, broken: bool = False,
          asset_page: int = Query(1, ge=1), mapping_page: int = Query(1, ge=1),
          source: str = ""):
    store = _store()
    from tm1_insight.audit_workspace import workspace, preferences
    settings = store.settings
    local = workspace(settings)
    if local.db_path.exists():
        store = Store(local)
    # Both the model and its independently replaced scan result define the page context.
    import hashlib
    current_source = hashlib.sha256((_process_search_source(settings) +
                                    _process_search_source(store.settings)).encode()).hexdigest()
    if source and source != current_source:
        return _error_page(request, 409, "资产来源已变化", "请重新打开前端资产页，再搜索或翻页。")
    con = store.connect(read_only=True)
    try:
        assets = queries.audit_page(con, kind="assets", keyword=asset_q, risk=risk,
                                    only_tm1=tm1, only_broken=broken, page=asset_page)
        mappings = queries.audit_page(con, kind="mappings", keyword=mapping_q, page=mapping_page)
        summary = queries.audit_summary(con)
    finally:
        con.close()
    def page_urls(result, key, anchor):
        return {direction: str(request.url.include_query_params(
            **{key: result["page"] + delta, "source": current_source})) + anchor
                for direction, delta in (("previous", -1), ("next", 1))}
    return templates.TemplateResponse(request, "audit.html", {
        "assets": assets["items"], "asset_result": assets,
        "mappings": mappings["items"], "mapping_result": mappings,
        "asset_urls": page_urls(assets, "asset_page", "#assets"),
        "mapping_urls": page_urls(mappings, "mapping_page", "#mappings"),
        "asset_q": asset_q, "mapping_q": mapping_q, "risk": risk,
        "only_tm1": tm1, "only_broken": broken, "audit_source": current_source,
        "summary": summary,
        "applications_dir": preferences(settings)["applications"],
        "externals_dir": preferences(settings)["externals"],
        "audit_work_dir": preferences(settings)["work_dir"],
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
    return JSONResponse(_data_source_status(), headers={"Cache-Control": "no-store"})


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


@app.get("/api/datasource/discover")
def api_datasource_discover() -> dict:
    """Find the usual project data folder so importing does not require browsing demo subfolders."""
    from tm1_insight import datasource as ds
    settings = get_settings()
    # Prefer the project's actual data directory over the currently active source;
    # otherwise clicking Local while Demo is active would rediscover Demo itself.
    candidates = [settings.user_data_root / "data", settings.project_root / "data"]
    try:
        remembered = (settings.user_data_root / "last_local_source.txt").read_text(encoding="utf-8").strip()
        if remembered:
            candidates.insert(0, Path(remembered))
    except OSError:
        pass
    if settings.data_dir.resolve() != ds._demo_data_dir().resolve():
        candidates.insert(0, settings.db_path)
    seen = set()
    found = []
    for candidate in candidates:
        try:
            key = candidate.resolve()
            if key in seen:
                continue
            seen.add(key)
            detected = ds.detect_directory(str(key))
            if detected.valid and detected.db_path not in {item["path"] for item in found}:
                found.append({"path": detected.db_path, "counts": detected.counts, "db_size": detected.db_size})
        except OSError:
            continue
    return {"found": bool(found), "candidates": found, **(found[0] if len(found) == 1 else {})}


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
        try:
            ds.load_demo_data()
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
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
        previous = get_settings().database_file or get_settings().data_dir
        set_data_dir(det.db_path)
        # 重新检测确认
        st = ds.detect_current_source()
        if not st.has_data:
            set_data_dir(previous)
            return JSONResponse({"error": "该目录未包含有效数据。"}, status_code=400)
        try:
            (get_settings().user_data_root / "last_local_source.txt").write_text(det.db_path, encoding="utf-8")
        except OSError:
            logger.warning("数据源已保存；快捷位置保存失败。")
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
    """Validate in a new private import directory; never overwrite the active model."""
    import tempfile
    from starlette.concurrency import run_in_threadpool
    from tm1_insight.config import set_data_dir
    from tm1_insight.ingest.import_package import prepare_import

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".duckdb", ".zip"}:
        return JSONResponse({"error": "请上传 .duckdb 或 .zip 文件。"}, status_code=400)
    root = get_settings().user_data_root / "imports"
    root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="model-", dir=root))
    upload = folder / ("upload" + suffix)
    destination = folder / "db" / "tm1_insight.duckdb"
    succeeded = False
    try:
        with upload.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                target.write(chunk)
        await run_in_threadpool(prepare_import, upload, destination, zipped=suffix == ".zip")
        set_data_dir(destination)
        succeeded = True
        try:
            (get_settings().user_data_root / "last_local_source.txt").write_text(str(destination), encoding="utf-8")
        except OSError:
            logger.warning("导入数据源已保存；快捷位置保存失败。")
        return {"ok": True, "db_path": str(destination), "status": _data_source_status()}
    except (ValueError, zipfile.BadZipFile) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        logger.error("本地数据包导入失败；原数据源保持不变。")
        return JSONResponse({"error": "导入失败，请检查文件格式与磁盘空间。"}, status_code=400)
    finally:
        upload.unlink(missing_ok=True)
        if not succeeded:
            destination.unlink(missing_ok=True)
            if destination.parent.exists():
                destination.parent.rmdir()
            folder.rmdir()


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


@app.get("/api/processes/search")
def api_process_search(q: str = Query("", max_length=1000),
                       scope: Literal["name", "code", "all"] = "name",
                       offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    store = _store()
    source = _process_search_source(store.settings)
    con = store.connect(read_only=True)
    try:
        result = queries.search_process_page(con, q, scope, offset, limit)
    finally:
        con.close()
    if source != _process_search_source():
        return JSONResponse({"error": "数据源已变化，请刷新页面后重新搜索。"}, status_code=409)
    return JSONResponse({**result, "source": source}, headers={"Cache-Control": "no-store"})


@app.get("/api/search-all")
def api_search_all(q: str = Query(max_length=1000), limit: int = Query(20, ge=1, le=50)) -> dict:
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


def _run_ingest(settings: Settings) -> None:
    """Build a fresh model, validate, then atomically select it. Never rebuild the active DB."""
    try:
        import tempfile
        from tm1_insight.ingest.exporter import Exporter
        from tm1_insight.ingest.loader import Loader
        from tm1_insight.config import activate_collected_source

        def progress(phase, done=None, total=None):
            if _ingest_cancel.is_set():
                raise TaskCancelled()
            with _ingest_lock:
                _ingest_state["progress"] = stage_progress(INGEST_STAGES, phase, done, total)

        root = settings.user_data_root / "collections"
        root.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="model-", dir=root))
        staged = settings.model_copy(update={"data_dir": folder, "database_file": None,
            "tm1_skip_existing": False, "input_applications_dir": folder / "inputs" / "applications",
            "input_externals_dir": folder / "inputs" / "externals",
            "input_process_dir": folder / "inputs" / "process", "input_rux_dir": folder / "inputs" / "rux"})
        exported = Exporter(staged, progress=progress, strict=True).export_all()
        stats = Loader(staged, progress=progress, strict=True).load(drop=True)
        progress("validate")
        actual = Store(staged).all_rows()
        if not actual.get("cubes") or any(actual.get(key, 0) != exported[key]
                                         for key in ("cubes", "processes", "dimensions", "chores")):
            raise ValueError("Collected object counts did not reconcile")
        progress("activate")
        activate_collected_source(staged.db_path, settings.db_path)
        with _ingest_lock:
            _ingest_state.update({"running": False, "done": True, "error": None, "stats": stats})
    except Exception as e:  # noqa: BLE001
        logger.error("采集失败，原数据源未被重建 (%s)", type(e).__name__)
        with _ingest_lock:
            _ingest_state.update({"running": False, "done": True,
                "cancelled": _ingest_cancel.is_set(),
                "error": "采集已取消，未切换数据源，原模型保留。" if _ingest_cancel.is_set() else "采集或校验未完成，未切换数据源。原模型保留；请检查连接、权限、磁盘空间及是否中途换库。",
                "stats": None})


@app.post("/api/ingest")
def api_ingest(payload: Optional[dict] = Body(default=None)):
    """触发后台拉取（长任务）。可选携带登录凭据覆盖默认连接。"""
    creds = _coerce_creds(payload or {})
    with _ingest_lock:
        if _ingest_state.get("running"):
            return JSONResponse({"error": "已有拉取任务在运行"}, status_code=409)
        # Reserve before starting the worker: simultaneous clicks cannot create two jobs.
        settings = _settings_with_creds(creds).model_copy()
        _ingest_cancel.clear()
        _ingest_state.update({"running": True, "done": False, "error": None, "stats": None,
                              "cancelled": False, "cancel_requested": False,
                              "progress": stage_progress(INGEST_STAGES, "enumerate")})
    try:
        threading.Thread(target=_run_ingest, args=(settings,), daemon=True).start()
    except RuntimeError:
        with _ingest_lock:
            _ingest_state.update({"running": False, "done": True, "error": "无法启动采集任务。"})
        return JSONResponse({"error": "无法启动采集任务。"}, status_code=503)
    return {"started": True}


@app.get("/api/ingest/status")
def api_ingest_status() -> dict:
    with _ingest_lock:
        return JSONResponse(dict(_ingest_state), headers={"Cache-Control": "no-store"})


@app.post("/api/ingest/cancel")
def cancel_ingest():
    with _ingest_lock:
        if _ingest_state.get("running"):
            _ingest_cancel.set()
            _ingest_state["cancel_requested"] = True
    return {"cancel_requested": _ingest_cancel.is_set()}


@app.get("/api/audit/config")
def api_audit_config():
    from tm1_insight.audit_workspace import preferences
    return preferences(get_settings())


@app.post("/api/audit/config")
def api_save_audit_config(body: dict = Body(...)):
    from tm1_insight.audit_workspace import save_preferences
    with _audit_lock:
        if _audit_state.get("running"):
            return JSONResponse({"error":"扫描进行中，请完成后修改路径。"}, status_code=409)
        try: return save_preferences(get_settings(), body)
        except (ValueError, OSError):
            return JSONResponse({"error":"路径无效：来源必须是可读目录；缓存目录必须可写。支持任意盘符的绝对路径。"}, status_code=400)


@app.post("/api/audit")
def api_audit(body: Optional[dict] = Body(default=None)) -> dict:
    """触发前端 Excel 资产扫描（本地，异步后台执行，通过 /api/audit/status 轮询进度）。"""
    with _audit_lock:
        if _audit_state.get("running"):
            return JSONResponse({"error": "已有扫描任务在运行"}, status_code=409)
        from tm1_insight.audit_workspace import save_preferences, preferences
        from tm1_insight.api.knowledge_tasks import fingerprint
        settings = get_settings().model_copy()
        try:
            save_preferences(settings, body or preferences(settings))
        except (ValueError, OSError):
            return JSONResponse({"error":"请指定存在的扫描目录和可写缓存目录；外部仓库可以留空。"}, status_code=400)
        _audit_cancel.clear()
        _audit_state.update({"running": True, "done": False, "error": None, "stats": None,
            "cancelled": False, "cancel_requested": False,
            "source": fingerprint(settings), "progress": stage_progress(AUDIT_STAGES, "prepare")})
    try:
        threading.Thread(target=_run_audit, args=(settings,), daemon=True).start()
    except RuntimeError:
        with _audit_lock:
            _audit_state.update({"running": False, "done": True, "error": "无法启动扫描任务。"})
        return JSONResponse({"error": "无法启动扫描任务。"}, status_code=503)
    return {"started": True}


@app.get("/api/audit/status")
def api_audit_status() -> dict:
    with _audit_lock:
        from tm1_insight.api.knowledge_tasks import fingerprint
        if _audit_state.get("source") and _audit_state["source"] != fingerprint():
            message = "另一数据源的扫描仍在执行，请等待完成后重新开始。" if _audit_state.get("running") else "数据源已切换，旧扫描结果仅保存在原模型的独立工作区。"
            return JSONResponse({"error": message}, status_code=409)
        return JSONResponse(dict(_audit_state), headers={"Cache-Control": "no-store"})


@app.post("/api/audit/cancel")
def cancel_audit():
    with _audit_lock:
        if _audit_state.get("running"):
            _audit_cancel.set()
            _audit_state["cancel_requested"] = True
    return {"cancel_requested": _audit_cancel.is_set()}
