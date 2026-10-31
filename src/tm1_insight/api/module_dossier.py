"""Module Dossier: bounded, read-only export of one business module.

Reuses the existing task manager, snapshot fingerprint guard and read-only
DuckDB connection. No TM1 client, no write path, no new graph engine.
"""
from __future__ import annotations

from contextlib import closing
import json
import threading

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse

from tm1_insight import module_dossier as dossier, workflow
from tm1_insight.api.knowledge_tasks import fingerprint
from tm1_insight.api.workbench import guard
from tm1_insight.config import get_settings
from tm1_insight.store.db import Store
from tm1_insight.tasks import TaskBusy, TaskManager

router = APIRouter()
_manager = None
_lock = threading.Lock()


def manager():
    root = get_settings().user_data_root / 'cache' / 'module-dossiers'
    with _lock:
        global _manager
        if _manager is None or _manager.root != root:
            if _manager is not None:
                _manager.close()
            _manager = TaskManager(root, max_cache_bytes=128 * 1024 * 1024)
        return _manager


@router.post('/api/module-dossier/discover')
def discover(body: dossier.Scope):
    """Candidate list only; nothing is analyzed or persisted."""
    store, snapshot = guard(body.snapshot_id)
    with closing(Store(store.settings).connect(read_only=True)) as con:
        result = dossier.discover(con, body)
        result['resolved'] = dossier.resolve_membership(body, result)
    guard(snapshot)
    return JSONResponse(dict(snapshot_id=snapshot, **result), headers={'Cache-Control': 'no-store'})


@router.post('/api/module-dossier/tasks', status_code=202)
def start(body: dossier.Scope):
    store, snapshot = guard(body.snapshot_id)
    scope = body.model_copy(update={'snapshot_id': snapshot})
    settings = store.settings.model_copy()
    checks = [(scope.entry_kind, scope.entry)] + [(r.type, r.name) for r in scope.include]
    if scope.target_cube:
        checks.append(('cube', scope.target_cube))
    with closing(Store(settings).connect(read_only=True)) as con:
        for kind, name in checks:
            table = 'cubes' if kind == 'cube' else 'processes'
            if not con.execute('SELECT name FROM ' + table + ' WHERE name=?', [name]).fetchone():
                raise HTTPException(404, '当前模型不存在对象：' + name)

    def work(progress):
        def guarded(**event):
            if fingerprint(settings) != snapshot or fingerprint() != snapshot:
                raise ValueError('Model changed')
            progress(**event)
        with closing(Store(settings).connect(read_only=True)) as con:
            return dossier.build(con, scope, guarded)

    key = json.dumps(dict(version=dossier.VERSION, revision=dossier.REVISION,
                          parser=workflow.CALC_VERSION, scope=scope.model_dump(exclude={'snapshot_id'})),
                     sort_keys=True, ensure_ascii=False)
    try:
        return manager().submit(key, work, source=snapshot)
    except TaskBusy as exc:
        raise HTTPException(429, '已有档案正在生成，请等待或取消。') from exc


def state(task: str):
    try:
        value = manager().state(task)
    except KeyError as exc:
        raise HTTPException(404, '任务已失效，请重新生成。') from exc
    guard(value['source'])
    return value


def artifact(task: str):
    info = state(task)
    if info['status'] != 'completed':
        raise HTTPException(409, '档案尚未就绪。')
    try:
        path = manager().result_path(task, source=info['source'])
        model = json.loads(path.read_text(encoding='utf-8'))
        if model.get('schema_version') != dossier.VERSION:
            raise ValueError('Version mismatch')
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(410, '档案缓存无效，请重新生成。') from exc
    state(task)
    return model


@router.get('/api/module-dossier/tasks/{task}')
def status(task: str):
    return state(task)


@router.post('/api/module-dossier/tasks/{task}/cancel')
def cancel(task: str):
    state(task)
    return manager().cancel(task)


@router.get('/api/module-dossier/tasks/{task}/result')
def result(task: str,
           format: str = Query('json', pattern='^(json|markdown|questions)$'),
           section: str = Query('', max_length=64),
           offset: int = Query(0, ge=0),
           limit: int = Query(50, ge=1, le=200),
           download: bool = False):
    model = artifact(task)
    headers = {'Cache-Control': 'no-store'}
    if format == 'markdown':
        headers['Content-Disposition'] = 'attachment; filename="Module.md"'
        return Response(dossier.markdown(model), media_type='text/markdown; charset=utf-8', headers=headers)
    if format == 'questions':
        headers['Content-Disposition'] = 'attachment; filename="Questions.md"'
        return Response(dossier.questions(model), media_type='text/markdown; charset=utf-8', headers=headers)
    if not section:
        if download:
            headers['Content-Disposition'] = 'attachment; filename="Module.json"'
        return JSONResponse(model, headers=headers)
    if section not in dossier.SECTIONS:
        raise HTTPException(422, '无效的档案分区。')
    rows = model.get(section) or []
    return JSONResponse(dict(section=section, total=len(rows), offset=offset, limit=limit,
                             items=rows[offset:offset + limit],
                             coverage=model['coverage']), headers=headers)


@router.get('/api/module-dossier/tasks/{task}/export')
def export(task: str, format: str = Query('zip', pattern='^(zip|markdown|json|evidence|diagnostics|questions)$')):
    model = artifact(task)
    if format == 'zip':
        return StreamingResponse(iter([dossier.package(model)]), media_type='application/zip',
                                 headers={'Content-Disposition': 'attachment; filename=Module.zip',
                                          'Cache-Control': 'no-store'})
    if format == 'markdown':
        body, media, filename = dossier.markdown(model), 'text/markdown', 'Module.md'
    elif format == 'questions':
        body, media, filename = dossier.questions(model), 'text/markdown', 'Questions.md'
    elif format == 'json':
        body, media, filename = dossier.dumps(model).decode('utf-8'), 'application/json', 'Module.json'
    elif format == 'evidence':
        body = json.dumps(dict(schema_version=dossier.VERSION, module=model['module']['name'],
                               snapshot_ref=model['snapshot_ref'], runtime_verified=False,
                               statements=model['statements'], items=model['evidence']),
                          ensure_ascii=False, sort_keys=True, indent=2)
        media, filename = 'application/json', 'Evidence.json'
    else:
        body = json.dumps(dossier.diagnostics_document(model), ensure_ascii=False, sort_keys=True, indent=2)
        media, filename = 'application/json', 'Diagnostics.json'
    return StreamingResponse(iter([body]), media_type=media + ('; charset=utf-8' if 'json' not in media else ''),
                             headers={'Content-Disposition': 'attachment; filename=' + filename,
                                      'Cache-Control': 'no-store'})
