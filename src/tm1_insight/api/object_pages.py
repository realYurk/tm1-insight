"""Object workbench routes: one object, one URL, five answers.

Legacy `/graph` and `/architecture` entry points keep working as redirects so
old links and bookmarks land on the same state instead of a second UI stack.
"""

from __future__ import annotations

from contextlib import closing

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from tm1_insight import atlas, object_overview

router = APIRouter()


def _connect():
    from tm1_insight.api.app import _store
    return _store().connect(read_only=True)


def _templates():
    from tm1_insight.api.app import templates
    return templates


@router.get("/object", response_class=HTMLResponse)
def object_index(request: Request, q: str = Query("", max_length=200), kind: str = Query("cube", pattern="^(cube|process)$")):
    """Landing page: search one object, or start from what carries the model."""
    data = {"q": q, "kind": kind, "cubes": [], "processes": [], "counts": {}, "results": [], "error": None}
    try:
        with closing(_connect()) as con:
            data["counts"] = atlas.overview(con)
            data["cubes"] = atlas.summary(con, "cube", limit=8)["items"]
            data["processes"] = atlas.summary(con, "process", limit=6)["items"]
            if q.strip():
                data["results"] = _search(con, kind, q.strip())
    except Exception as exc:  # noqa: BLE001
        data["error"] = str(exc)
    return _templates().TemplateResponse(request, "object_index.html", data)


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _search(con, kind: str, query: str, limit: int = 30) -> list[dict]:
    table = "cubes" if kind == "cube" else "processes"
    rows = con.execute(
        f"SELECT name FROM {table} WHERE name ILIKE ? ESCAPE '\\' AND name NOT LIKE '}}%' "
        "ORDER BY length(name), name LIMIT ?",
        [_like(query), limit],
    ).fetchall()
    return [{"name": str(r[0]), "kind": kind} for r in rows]


@router.get("/object/{kind}/{name}", response_class=HTMLResponse)
def object_page(request: Request, kind: str, name: str, view: str = Query("overview", max_length=20),
                model: str = Query("", max_length=64), analyze: bool = False,
                depth: int = Query(2, ge=0, le=4), nodes: int = Query(60, ge=1, le=120)):
    if kind not in object_overview.KIND_LABELS:
        return RedirectResponse("/object", status_code=302)
    views = dict(object_overview.VIEWS[kind])
    if view not in views:
        view = "overview"
    try:
        with closing(_connect()) as con:
            item = object_overview.build(con, kind, name)
            if item is None:
                return _templates().TemplateResponse(request, "object_missing.html", {"kind": kind, "name": name}, status_code=404)
            code = object_overview.source(con, kind, name) if view == "code" else {}
            handoff = object_overview.handoff_markdown(item) if view == "handoff" else ""
    except Exception as exc:  # noqa: BLE001
        return _templates().TemplateResponse(request, "object_missing.html", {"kind": kind, "name": name, "error": str(exc)}, status_code=500)
    return _templates().TemplateResponse(request, "object.html", {
        "item": item, "kind": kind, "name": item["name"], "view": view, "views": item["views"],
        "code": code, "handoff": handoff, "model": model or "", "autostart": bool(analyze),
        "cube": item["name"] if kind == "cube" else "", "ti": item["name"] if kind == "process" else "",
        "depth": depth, "node_budget": nodes,
    })


@router.get("/api/object/{kind}/{name}")
def object_facts(kind: str, name: str):
    if kind not in object_overview.KIND_LABELS:
        return JSONResponse({"detail": "unknown object kind"}, status_code=404)
    with closing(_connect()) as con:
        item = object_overview.build(con, kind, name)
    if item is None:
        return JSONResponse({"detail": "对象不在当前本地模型中"}, status_code=404)
    item.pop("rules_text", None)
    return item


@router.get("/api/object/{kind}/{name}/handoff.md")
def object_handoff(kind: str, name: str):
    if kind not in object_overview.KIND_LABELS:
        return JSONResponse({"detail": "unknown object kind"}, status_code=404)
    with closing(_connect()) as con:
        item = object_overview.build(con, kind, name)
    if item is None:
        return JSONResponse({"detail": "对象不在当前本地模型中"}, status_code=404)
    text = object_overview.handoff_markdown(item)
    filename = f"{item['kind']}-{item['name']}.md".replace("/", "_")
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@router.get("/browse", response_class=HTMLResponse)
def browse(request: Request, kind: str = Query("cube", pattern="^(cube|dimension|process|chore)$"),
           q: str = Query("", max_length=200), page: int = Query(1, ge=1, le=1000)):
    """One catalog for the four object types; detail lives on the object page."""
    data = {"kind": kind, "q": q, "page": page, "items": [], "total": 0, "pages": 1, "error": None}
    per_page = 200
    try:
        with closing(_connect()) as con:
            if kind in ("cube", "process"):
                listing = atlas.summary(con, kind, query=q, sort="score", page=page, limit=per_page)
                data.update(items=listing["items"], total=listing["total"], pages=listing["pages"], page=listing["page"])
            else:
                data.update(_simple_catalog(con, kind, q, page, per_page))
    except Exception as exc:  # noqa: BLE001
        data["error"] = str(exc)
    return _templates().TemplateResponse(request, "browse.html", data)


def _simple_catalog(con, kind: str, query: str, page: int, per_page: int) -> dict:
    from tm1_insight.api.workbench import _like
    where, params = "", []
    if query.strip():
        where = " WHERE name ILIKE ?"
        params.append(_like(query.strip()))
    if kind == "dimension":
        total = con.execute("SELECT count(*) FROM dimensions" + where, params).fetchone()[0]
        rows = con.execute(
            "SELECT name, element_count FROM dimensions" + where + " ORDER BY element_count DESC, name LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page]).fetchall()
        items = [{"name": str(r[0]), "score": int(r[1] or 0), "notes": [f"{int(r[1] or 0)} 个元素"], "signals": {}} for r in rows]
    else:
        total = con.execute("SELECT count(*) FROM chores" + where, params).fetchone()[0]
        rows = con.execute(
            "SELECT name, process_count FROM chores" + where + " ORDER BY process_count DESC, name LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page]).fetchall()
        items = [{"name": str(r[0]), "score": int(r[1] or 0), "notes": [f"{int(r[1] or 0)} 个步骤"], "signals": {}} for r in rows]
    pages = max(1, (total + per_page - 1) // per_page)
    return {"items": items, "total": total, "pages": pages, "page": page}
