"""资产地图页面：先看重要对象，再决定深挖哪一个。

所有状态（类型、搜索、排序、页码、是否含系统对象）都在 URL 上，
刷新、分享、返回都不会丢视图。服务端渲染，无额外前端框架依赖。
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from tm1_insight import atlas

router = APIRouter()


def _load(kind: str, query: str, sort: str, limit: int, page: int, include_system: bool) -> dict:
    from tm1_insight.api.app import _store

    store = _store()
    con = store.connect(read_only=True)
    try:
        data = atlas.summary(con, kind, query=query, sort=sort, limit=limit,
                            page=page, include_system=include_system)
        data["overview"] = atlas.overview(con, include_system)
        data["gaps"] = atlas.gaps(con, include_system, limit=12)
    finally:
        con.close()
    return data


@router.get('/atlas', response_class=HTMLResponse)
def atlas_page(request: Request,
               kind: Literal['cube', 'process', 'dimension', 'chore'] = 'cube',
               q: str = Query('', max_length=200),
               sort: str = Query('score', max_length=40),
               limit: int = Query(50, ge=10, le=500),
               page: int = Query(1, ge=1),
               system: bool = Query(False)):
    from tm1_insight.api.app import templates

    data = _load(kind, q, sort, limit, page, system)
    return templates.TemplateResponse(request, 'atlas.html', data)


@router.get('/api/atlas/summary')
def atlas_summary(kind: Literal['cube', 'process', 'dimension', 'chore'] = 'cube',
                  q: str = Query('', max_length=200),
                  sort: str = Query('score', max_length=40),
                  limit: int = Query(50, ge=10, le=500),
                  page: int = Query(1, ge=1),
                  system: bool = Query(False)) -> dict:
    return _load(kind, q, sort, limit, page, system)


@router.get('/api/atlas/export')
def atlas_export(kind: Literal['cube', 'process', 'dimension', 'chore'] = 'cube',
                 limit: int = Query(100, ge=10, le=500),
                 system: bool = Query(False)):
    """导出人类可直接带走的资产清单（Markdown）。"""
    from tm1_insight.api.app import _store

    store = _store()
    con = store.connect(read_only=True)
    try:
        content = atlas.export_markdown(con, kind, limit=limit, include_system=system)
    finally:
        con.close()
    filename = f'asset-inventory-{kind}.md'
    return Response(content, media_type='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"',
                             'Cache-Control': 'no-store'})
