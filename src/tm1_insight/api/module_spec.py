"""Local research definitions and bounded reconstruction jobs. No TM1 client."""
from contextlib import closing
import json
import threading

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from tm1_insight import module_spec as ms, workflow
from tm1_insight.api.workbench import guard, index
from tm1_insight.api.knowledge_tasks import fingerprint
from tm1_insight.config import get_settings
from tm1_insight.store.db import Store
from tm1_insight.tasks import TaskManager, TaskBusy

router=APIRouter()
_manager=None
_lock=threading.Lock()


def root():return get_settings().user_data_root/'module-studies'


def manager():
    global _manager
    path=get_settings().user_data_root/'cache'/'module-specifications'
    with _lock:
        if _manager is None or _manager.root!=path:
            if _manager is not None:_manager.close()
            _manager=TaskManager(path,max_cache_bytes=64*1024*1024)
    return _manager


@router.get('/module-reconstruction')
def page(request:Request,kind:str=Query('cube',pattern='^(cube|process)$'),name:str=Query('',max_length=1000),model:str=Query('',max_length=128),selection:str=Query('',max_length=20000)):
    from tm1_insight.api.app import templates
    return templates.TemplateResponse(request,'module_reconstruction.html',dict(kind=kind,name=name,model=model,selection=selection))


@router.post('/api/module-spec/preview')
def preview(body:ms.Definition):
    store,snapshot=guard(body.snapshot_id)
    result=ms.propose(index(str(store.settings.db_path),snapshot),body)
    guard(snapshot)
    return result


@router.get('/api/module-spec/definitions')
def definitions():
    items=[]
    for p in sorted(root().glob('*.json'))[:200]:
        try:
            d=ms.load_definition(root(),p.stem)
            items.append(dict(id=p.stem,name=d.name,snapshot_id=d.snapshot_id))
        except (ValueError,OSError):continue
    return dict(items=items,limit=200)


@router.post('/api/module-spec/definitions')
def save(body:ms.Definition):
    _,snapshot=guard(body.snapshot_id)
    if not body.members:raise HTTPException(422,'先确认模块成员，再保存研究定义。')
    key=ms.save_definition(root(),body)
    guard(snapshot)
    return dict(id=key,snapshot_id=snapshot)


@router.get('/api/module-spec/definitions/{key}')
def definition(key:str):
    try:d=ms.load_definition(root(),key)
    except FileNotFoundError as exc:raise HTTPException(404,'研究定义不存在。') from exc
    except (ValueError,OSError) as exc:raise HTTPException(422,'研究定义格式或校验无效；原文件保留。') from exc
    guard(d.snapshot_id)
    return d.model_dump(mode='json')


@router.post('/api/module-spec/tasks',status_code=202)
def start(body:ms.Definition):
    store,snapshot=guard(body.snapshot_id)
    if not body.members:raise HTTPException(422,'先预览并勾选确认模块成员。')
    settings=store.settings.model_copy()
    base=index(str(settings.db_path),snapshot)
    def work(progress):
        def guarded(**event):
            if fingerprint(settings)!=snapshot or fingerprint()!=snapshot:raise ValueError('Model changed')
            progress(**event)
        scratch=settings.user_data_root/'cache'/'module-spec-scratch'
        with closing(Store(settings).connect(read_only=True)) as con:
            result=ms.build(con,body,base,scratch,guarded)
        guarded(stage='完成规格与证据引用',stage_index=6,stages_total=6)
        return result
    key=ms.canonical(dict(revision=ms.REVISION,definition=ms.normalized(body),workflow=workflow.CACHE_REVISION))
    try:return manager().submit(key,work,source=snapshot)
    except TaskBusy as exc:raise HTTPException(429,'已有模块分析正在进行，请等待或取消。') from exc


def state(task):
    try:s=manager().state(task)
    except KeyError as exc:raise HTTPException(404,'任务已失效，请重新生成。') from exc
    guard(s['source'])
    return s


@router.get('/api/module-spec/tasks/{task}')
def status(task:str):return state(task)


@router.post('/api/module-spec/tasks/{task}/cancel')
def cancel(task:str):
    state(task)
    return manager().cancel(task)


@router.get('/api/module-spec/tasks/{task}/result')
def result(task:str,format:str=Query('json',pattern='^(json|markdown)$'),download:bool=False):
    s=state(task)
    if s['status']!='completed':raise HTTPException(409,'模块规格尚未就绪。')
    try:
        path=manager().result_path(task,source=s['source'])
        spec=json.loads(path.read_text(encoding='utf-8'))
        if spec['schema_version']!=ms.VERSION:raise ValueError('Version mismatch')
    except (ValueError,OSError,KeyError) as exc:raise HTTPException(410,'规格缓存无效，请重新生成。') from exc
    state(task)
    name='module_reconstruction_'+spec['module']['id'][:12]
    headers={'Cache-Control':'no-store'}
    if format=='markdown':
        headers['Content-Disposition']='attachment; filename="'+name+'.md"'
        return Response(ms.markdown(spec),media_type='text/markdown; charset=utf-8',headers=headers)
    if download:headers['Content-Disposition']='attachment; filename="'+name+'.json"'
    return JSONResponse(spec,headers=headers)
