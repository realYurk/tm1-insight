"""Retired object-workbench routes.

The object page proved to be a third view of facts the Cube/TI detail pages
already answer in richer form. Cube and TI carry their own detail pages again;
what survived from the experiment is the take-away export, which the detail
pages link to. Every old address still lands on a real page instead of 404.
"""

from __future__ import annotations

from contextlib import closing
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, RedirectResponse, Response

from tm1_insight import object_overview

router = APIRouter()


def _connect():
    from tm1_insight.api.app import _store
    return _store().connect(read_only=True)


@router.get("/object/{kind}/{name}")
def object_page(kind: str, name: str, view: str = Query("overview", max_length=20),
                model: str = Query("", max_length=64)):
    """One object lived here; now it lives on the object's own detail page."""
    quoted = quote(name)
    model_q = f"?model={quote(model)}" if model else ""
    if kind == "cube":
        if view in ("graph", "lineage"):
            return RedirectResponse(f"/graph?cube={quoted}" + (f"&model={quote(model)}" if model else ""), status_code=302)
        return RedirectResponse(f"/explorer/cube/{quoted}{model_q}", status_code=302)
    if kind == "process":
        return RedirectResponse(f"/explorer/process/{quoted}{model_q}", status_code=302)
    return RedirectResponse("/cubes", status_code=302)


@router.get("/object")
def object_index():
    return RedirectResponse("/cubes", status_code=302)


@router.get("/browse")
def browse(kind: str = Query("cube", max_length=20)):
    target = {"cube": "/cubes", "process": "/processes", "chore": "/chores"}.get(kind, "/cubes")
    return RedirectResponse(target, status_code=302)


@router.get("/search")
def search(q: str = Query("", max_length=200), kind: str = Query("cube", max_length=20)):
    """One search box on the home page; each object type keeps its own list page."""
    target = {"cube": "/cubes", "process": "/processes", "chore": "/chores"}.get(kind, "/cubes")
    return RedirectResponse(f"{target}?q={quote(q)}" if q.strip() else target, status_code=302)


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
    """The take-away page: one Markdown per object, generated from the same indexes."""
    if kind not in object_overview.KIND_LABELS:
        return JSONResponse({"detail": "unknown object kind"}, status_code=404)
    with closing(_connect()) as con:
        item = object_overview.build(con, kind, name)
    if item is None:
        return JSONResponse({"detail": "对象不在当前本地模型中"}, status_code=404)
    text = object_overview.handoff_markdown(item)
    filename = f"{item['kind']}-{item['name']}.md".replace("/", "_")
    return Response(text, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-store"})
