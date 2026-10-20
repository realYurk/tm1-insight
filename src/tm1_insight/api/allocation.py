"""可配置分摊方案 API（合成数据原型）。

方案保存在本地 JSON 文件目录（默认 data_dir/allocation_schemes），
不写入任何 DuckDB / 真实模型数据。执行计算只用请求体内的合成数据。
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from tm1_insight.allocation_engine import VERSION, allocate, reconcile, validate_config

router = APIRouter()
_lock = threading.Lock()


@router.get('/allocation')
def allocation_page(request: Request):
    from tm1_insight.api.app import templates
    return templates.TemplateResponse(request, 'allocation.html', {})


def _schemes_dir():
    from tm1_insight.config import get_settings
    base = Path(get_settings().data_dir) / 'allocation_schemes'
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_name(name: str) -> str:
    if not name or len(name) > 100 or not re.fullmatch(r'[\w\u4e00-\u9fff\- ]+', name):
        raise HTTPException(422, '方案名只能包含中文、字母、数字、下划线、连字符和空格，最长 100 字。')
    return name


@router.post('/api/allocation/run')
def run_allocation(config: dict = Body(...)):
    """对请求体内的合成数据执行分摊并返回结果与对账。不写任何持久数据。"""
    errors = validate_config(config)
    if errors:
        return JSONResponse(status_code=422, content={'ok': False, 'errors': errors})
    result = allocate(config)
    rec = reconcile(config, result) if result.get('ok') else None
    return dict(result=result, reconcile=rec, engine=VERSION)


@router.get('/api/allocation/schemes')
def list_schemes():
    d = _schemes_dir()
    items = []
    for p in sorted(d.glob('*.json')):
        try:
            doc = json.loads(p.read_text(encoding='utf-8'))
            items.append(dict(name=doc.get('name'), saved_at=doc.get('saved_at'),
                              group_dimensions=doc.get('config', {}).get('group_dimensions'),
                              allocation_dimensions=doc.get('config', {}).get('allocation_dimensions')))
        except Exception:
            continue
    return dict(schemes=items)


@router.get('/api/allocation/schemes/{name}')
def load_scheme(name: str):
    _safe_name(name)
    p = _schemes_dir() / f'{name}.json'
    if not p.exists():
        raise HTTPException(404, '方案不存在。')
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        raise HTTPException(500, f'方案文件损坏：{e}')


@router.put('/api/allocation/schemes/{name}')
def save_scheme(name: str, body: dict = Body(...)):
    _safe_name(name)
    config = body.get('config')
    if not isinstance(config, dict):
        raise HTTPException(422, '缺少 config。')
    from datetime import datetime
    doc = dict(name=name, saved_at=datetime.now().isoformat(timespec='seconds'),
               config=config, note=body.get('note', ''))
    p = _schemes_dir() / f'{name}.json'
    with _lock:
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(saved=True, name=name, path=str(p))


@router.delete('/api/allocation/schemes/{name}')
def delete_scheme(name: str):
    _safe_name(name)
    p = _schemes_dir() / f'{name}.json'
    if p.exists():
        with _lock:
            p.unlink()
        return dict(deleted=True)
    raise HTTPException(404, '方案不存在。')
