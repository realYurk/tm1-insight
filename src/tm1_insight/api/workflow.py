"""One workflow workspace, scoped cancellable jobs and indexed private results."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import sqlite3
import threading
from typing import Literal

from fastapi import APIRouter,HTTPException,Query,Request
from fastapi.responses import FileResponse,JSONResponse,StreamingResponse
from pydantic import BaseModel,Field

from tm1_insight import workflow
from tm1_insight.api.knowledge_tasks import fingerprint
from tm1_insight.config import get_settings
from tm1_insight.learning.syntax import SECTIONS
from tm1_insight.store.db import Store
from tm1_insight.tasks import TaskBusy,TaskManager

router=APIRouter()
_manager=None
_lock=threading.Lock()


def manager():
    global _manager
    root=get_settings().user_data_root/'cache'/'workflows'/'results'
    with _lock:
        if _manager is None or _manager.root!=root:
            if _manager is not None:_manager.close()
            _manager=TaskManager(root,max_cache_bytes=256*1024*1024)
        return _manager


class Start(BaseModel):
    process:str=Field(min_length=1,max_length=1000)
    max_processes:int=Field(default=200,ge=1,le=500,strict=True)
    max_depth:int=Field(default=32,ge=0,le=64,strict=True)
    source:str=Field(default='',max_length=64)


@router.get('/workflow')
def workspace(request:Request,name:str=Query('',max_length=1000),source:str=Query('',max_length=64),analyze:bool=False):
    from tm1_insight.api.app import templates
    return templates.TemplateResponse(request,'workflow.html',dict(name=name,source=source,analyze=analyze))


@router.post('/api/workflow/tasks',status_code=202)
def start(body:Start):
    from tm1_insight.api.app import _store,_process_search_source
    store=_store();settings=store.settings.model_copy();source=fingerprint(settings)
    if body.source and body.source!=_process_search_source(settings):raise HTTPException(409,'模型已变化，请重新选择当前 TI。')
    name=body.process.strip()
    with closing(store.connect(read_only=True)) as con:
        row=con.execute('SELECT name FROM processes WHERE name=?',[name]).fetchone()
    if not row:raise HTTPException(404,'当前本地模型不存在该 TI；未生成替代分析。')
    if source!=fingerprint():raise HTTPException(409,'选择期间数据源已变化，请重试。')
    def work(progress):
        def guarded(**values):
            if source!=fingerprint(settings) or source!=fingerprint():raise ValueError('Model changed')
            progress(**values)
        with closing(Store(settings).connect(read_only=True)) as con:
            report=workflow.build(con,name,max_processes=body.max_processes,max_depth=body.max_depth,progress=guarded,
                cache_root=settings.user_data_root/'cache'/'workflows',cache_source=source)
        guarded(stage='核对当前模型来源',stage_index=5)
        report['source_fingerprint']=source
        root=settings.user_data_root/'cache'/'workflows';root.mkdir(parents=True,exist_ok=True)
        artifact=workflow.artifact(report,root)
        try:guarded(stage='发布工作流检索结果',stage_index=6)
        except BaseException:artifact.cleanup();raise
        return artifact
    key=json.dumps(dict(version=workflow.VERSION,revision=workflow.CACHE_REVISION,parser=workflow.CALC_VERSION,process=name,max_processes=body.max_processes,max_depth=body.max_depth),sort_keys=True)
    try:return manager().submit(key,work,source=source)
    except TaskBusy as exc:raise HTTPException(429,str(exc)) from exc


def state(task):
    try:s=manager().state(task)
    except KeyError as exc:raise HTTPException(404,'任务不存在或服务已重启，请重新解析。') from exc
    if s['source']!=fingerprint():raise HTTPException(409,'当前模型已变化，请重新解析工作流。')
    return s


def path(task):
    s=state(task)
    if s['status']!='completed':raise HTTPException(409,'工作流尚未就绪。')
    try:return manager().result_path(task,source=s['source'])
    except (ValueError,FileNotFoundError) as exc:raise HTTPException(410,'结果已过期，请重新解析。') from exc


@router.get('/api/workflow/tasks/{task}')
def task_state(task:str):return state(task)


@router.post('/api/workflow/tasks/{task}/cancel')
def cancel(task:str):
    state(task)
    return manager().cancel(task)


@router.get('/api/workflow/tasks/{task}/result')
def result(task:str,view:Literal['processes','execution','data','calculation','unknowns','structure','callers']='processes',
           offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),process:str=Query('',max_length=1000),q:str=Query('',max_length=1000)):
    try:header,total,items=workflow.page(path(task),view,offset,limit,process,q)
    except (sqlite3.Error,OSError,ValueError,TypeError) as exc:raise HTTPException(410,'工作流检索缓存不可用，请重新解析。') from exc
    if header['source_fingerprint']!=fingerprint():raise HTTPException(409,'读取期间模型已变化，请重新解析。')
    return JSONResponse(dict(header=header,total=total,offset=offset,items=items),headers={'Cache-Control':'no-store'})


@router.get('/api/workflow/tasks/{task}/process')
def process_detail(task:str,process:str=Query(...,min_length=1,max_length=1000)):
    try:report=workflow.detail(path(task),process)
    except (sqlite3.Error,OSError) as exc:raise HTTPException(410,'TI 检索缓存不可用，请重新解析。') from exc
    if report is None:raise HTTPException(404,'该 TI 不在已解析范围内。')
    state(task)
    return JSONResponse(report,headers={'Cache-Control':'no-store'})


@router.get('/api/workflow/tasks/{task}/evidence')
def evidence(task:str,process:str=Query(...,min_length=1,max_length=1000),
             section:Literal['prolog','metadata','data','epilog']='data',start:int=Query(1,ge=1),limit:int=Query(80,ge=1,le=200)):
    return source_evidence(path(task),lambda:state(task),process,section,start,limit)


def source_evidence(artifact,guard,process,section,start,limit):
    report=workflow.detail(artifact,process)
    if report is None:raise HTTPException(404,'该 TI 不在已解析范围内。')
    if not report.get('source_hash'):raise HTTPException(409,'该 TI 超过分析预算，没有已核对的源码证据。请单独解析或使用原 TI 浏览。')
    with closing(Store(get_settings()).connect(read_only=True)) as con:
        row=con.execute("SELECT prolog,metadata,data,epilog FROM processes WHERE name=?",[process]).fetchone()
    if row is None:raise HTTPException(404,'原始 TI 已不存在。')
    parts=tuple(p or '' for p in row)
    digest=hashlib.sha256(json.dumps(dict(zip(SECTIONS,parts)),sort_keys=True).encode()).hexdigest()
    if digest!=report['source_hash']:raise HTTPException(409,'原始代码与分析证据不匹配，请重新解析。')
    guard()
    lines=parts[SECTIONS.index(section)].splitlines()
    if start>max(len(lines),1):raise HTTPException(404,'原代码没有该行。')
    return JSONResponse(dict(process=process,section=section,source_hash=digest,total=len(lines),start=start,
        lines=[dict(line=i+1,code=lines[i]) for i in range(start-1,min(len(lines),start-1+limit))]),headers={'Cache-Control':'no-store'})


@router.get('/api/workflow/tasks/{task}/export')
def export(task:str,format:Literal['json','markdown']='json'):
    artifact=path(task)
    if format=='json':return FileResponse(artifact,media_type='application/json',filename='Workflow.json',headers={'Cache-Control':'no-store'})
    return StreamingResponse(workflow.markdown(artifact),media_type='text/markdown',headers={'Content-Disposition':'attachment; filename=Workflow.md','Cache-Control':'no-store'})


@router.get('/api/workflow/tasks/{task}/review')
def review(task:str, format:Literal['json','markdown']='json', download:bool=False):
    """Readable projection of the existing scoped artifact; no new parsing."""
    from tm1_insight import workflow_review
    artifact=path(task)
    header,_,_=workflow.page(artifact,limit=1)
    schedule_missing=False
    with closing(Store(get_settings()).connect(read_only=True)) as con:
        declaration=workflow_review.source_declaration(con,header['root'])
        tables={r[0] for r in con.execute('SHOW TABLES').fetchall()}
        if 'chore_runs_process' not in tables:
            rows=[];schedule_missing=True
        else:
            columns={r[1] for r in con.execute("PRAGMA table_info('chores')").fetchall()} if 'chores' in tables else set()
            fields=','.join('c.'+field if field in columns else 'NULL' for field in ('active','start_time','frequency'))
            join='LEFT JOIN chores c ON c.name=r.chore_name' if 'name' in columns else ''
            rows=con.execute(f'''SELECT r.chore_name,r.step_order,{fields}
                FROM chore_runs_process r {join}
                WHERE r.process_name=? ORDER BY r.chore_name,r.step_order LIMIT 101''',[header['root']]).fetchall()
    schedules=[dict(zip(('chore','step_order','active','start_time','frequency'),r)) for r in rows[:100]]
    for item in schedules:
        item['evidence']=dict(table='chore_runs_process',chore=item['chore'],process=header['root'],step_order=item['step_order'])
    try:report=workflow_review.build(artifact,schedules,declaration)
    except (sqlite3.Error,OSError,KeyError,ValueError) as exc:raise HTTPException(410,'局部报告不可用，请重新解析。') from exc
    if len(rows)>100:report['limitations'].append('直接调度仅展示前 100 项')
    if schedule_missing:report['limitations'].append('旧快照缺少 Chore 调度索引；未推断入口')
    state(task)
    if format=='markdown':
        return StreamingResponse(iter([workflow_review.markdown(report)]),media_type='text/markdown',
            headers={'Content-Disposition':'attachment; filename=TI-Reconstruction.md','Cache-Control':'no-store'})
    headers={'Cache-Control':'no-store'}
    if download:headers['Content-Disposition']='attachment; filename=TI-Reconstruction.json'
    return JSONResponse(report,headers=headers)
