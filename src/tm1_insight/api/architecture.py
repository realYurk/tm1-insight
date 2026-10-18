"""Architecture is a versioned local projection of workflow and model facts."""
from __future__ import annotations

from contextlib import closing
import json
import threading
from typing import Literal, Optional
from fastapi import APIRouter,HTTPException,Query,Request
from fastapi.responses import FileResponse,JSONResponse,StreamingResponse
from tm1_insight import architecture,workflow
from tm1_insight.api.workflow import Start as WorkflowStart,source_evidence
from pydantic import Field,model_validator
from tm1_insight.architecture_extraction import RELATIONSHIPS
from tm1_insight.api.knowledge_tasks import fingerprint
from tm1_insight.config import get_settings
from tm1_insight.store.db import Store
from tm1_insight.tasks import TaskManager,TaskBusy

class Start(WorkflowStart):
    process: Optional[str] = Field(default=None,min_length=1,max_length=1000)
    cube: Optional[str] = Field(default=None,min_length=1,max_length=1000)
    entry_kind:Literal['process','cube']='process'

    @model_validator(mode='after')
    def entry_present(self):
        if self.entry_kind=='process' and not self.process:raise ValueError('Process entry required')
        if self.entry_kind=='cube' and not self.cube:raise ValueError('Cube entry required')
        return self

    max_nodes:int=Field(default=1000,ge=1,le=5000,strict=True)
    allowed_relationship_types:list[Literal['invocation','read_write','structure','rule_reference','schedule']]=Field(default_factory=lambda:sorted(RELATIONSHIPS))
    include_downstream:bool=False
    include_technical_details:bool=False

router=APIRouter();_manager=None;_lock=threading.Lock()


def manager():
    global _manager
    root=get_settings().user_data_root/'cache'/'architecture'/'results'
    with _lock:
        if _manager is None or _manager.root!=root:
            if _manager is not None:_manager.close()
            _manager=TaskManager(root,max_cache_bytes=256*1024*1024)
        return _manager


@router.get('/architecture')
def workspace(request:Request,name:str=Query('',max_length=1000),analyze:bool=False,kind:Literal['process','cube','discover']='process',view:Literal['overview','functional_flow']='overview'):
    from tm1_insight.api.app import templates
    return templates.TemplateResponse(request,'architecture.html',dict(name=name,analyze=analyze,kind=kind,initial_view=view,architecture_revision=architecture.REVISION))


@router.post('/api/architecture/tasks',status_code=202)
def start(body:Start):
    from tm1_insight.api.app import _store,_process_search_source
    store=_store();settings=store.settings.model_copy();source=fingerprint(settings)
    if body.source and body.source!=_process_search_source(settings):raise HTTPException(409,'模型已变化，请重新选择入口。')
    name=(body.cube if body.entry_kind=='cube' else body.process).strip()
    with closing(store.connect(read_only=True)) as con:
        table='cubes' if body.entry_kind=='cube' else 'processes'
        if not con.execute('SELECT name FROM '+table+' WHERE name=?',[name]).fetchone():raise HTTPException(404,'当前模型不存在这个入口对象；没有生成替代架构。')
    def work(progress):
        def guarded(**values):
            if source!=fingerprint(settings) or source!=fingerprint():raise ValueError('Model changed')
            progress(**values)
        with closing(Store(settings).connect(read_only=True)) as con:
            report=architecture.build(con,name,progress=guarded,max_processes=body.max_processes,max_depth=body.max_depth,
                cache_root=settings.user_data_root/'cache'/'workflows',cache_source=source,max_nodes=body.max_nodes,
                allowed_relationship_types=body.allowed_relationship_types,include_downstream=body.include_downstream,include_technical_details=body.include_technical_details,entry_kind=body.entry_kind)
        guarded(stage='保存局部架构与导出',stage_index=6)
        root=settings.user_data_root/'cache'/'architecture';root.mkdir(parents=True,exist_ok=True)
        artifact=architecture.artifact(report,root)
        try:guarded(stage='核对来源并发布架构',stage_index=6)
        except BaseException:artifact.cleanup();raise
        return artifact
    key=json.dumps(dict(version=architecture.VERSION,revision=architecture.REVISION,parser=workflow.CALC_VERSION,process=name,
        scope=body.model_dump(exclude={'source'})),sort_keys=True)
    try:return manager().submit(key,work,source=source)
    except TaskBusy as exc:raise HTTPException(429,str(exc)) from exc


def state(task):
    try:s=manager().state(task)
    except KeyError as exc:raise HTTPException(404,'任务已失效，请重新解析。') from exc
    if s['source']!=fingerprint():raise HTTPException(409,'本地模型已变化，请重新解析架构。')
    return s


def path(task):
    s=state(task)
    if s['status']!='completed':raise HTTPException(409,'架构尚未就绪。')
    try:return manager().result_path(task,source=s['source'])
    except (OSError,ValueError) as exc:raise HTTPException(410,'架构缓存已过期，请重新解析。') from exc


@router.get('/api/architecture/tasks/{task}')
def status(task:str):return state(task)


@router.post('/api/architecture/tasks/{task}/cancel')
def cancel(task:str):
    state(task);return manager().cancel(task)


@router.get('/api/architecture/tasks/{task}/result')
def result(task:str,view:str='transformation_steps',offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100),q:str=Query('',max_length=1000),include_technical:bool=False,target_cube:str=Query('',max_length=1000),relation_group:Literal['','execution','data','rule','feeder','structure']='',confirmed_only:bool=False):
    if view not in architecture.SECTIONS:raise HTTPException(422,'无效架构视图。')
    artifact=path(task)
    if view in {'write_explanations','unified_relations'}:
        header,_,_=architecture.page(artifact,view,0,1)
        where="section=? AND instr(search,?)>0";args=[view,q.casefold()]
        if not include_technical:
            where+=" AND coalesce(json_extract(payload,'$.technical'),0)=0"
            if view=='write_explanations':where+=" AND json_extract(payload,'$.cube') IS NOT NULL"
            else:where+=" AND json_extract(payload,'$.status')!='UNKNOWN' AND coalesce(json_extract(payload,'$.detail_only'),0)=0"
        if target_cube and view=='write_explanations':where+=" AND json_extract(payload,'$.cube')=?";args.append(target_cube)
        if view=='unified_relations' and relation_group:
            groups={'execution':['PROCESS_CALL','EXECUTION_REACHABILITY','CHORE_SCHEDULE'],
                    'data':['CUBE_READ','CUBE_WRITE','TI_WRITE_SLICE','VIEW_DATASOURCE','STATIC_VALUE_DEPENDENCY','CANDIDATE_FORMATION'],
                    'rule':['RULE_TARGET','RULE_DB_REFERENCE'],'feeder':['FEEDER_OWNER','FEEDER_DB_REFERENCE'],
                    'structure':['CUBE_DIMENSION']}
            kinds=groups[relation_group]
            where+=" AND json_extract(payload,'$.relation_kind') IN ("+','.join('?' for _ in kinds)+')';args.extend(kinds)
        with closing(workflow.connection(artifact)) as con:
            total=con.execute('SELECT count(*) FROM items WHERE '+where,args).fetchone()[0]
            items=[json.loads(row[0]) for row in con.execute('SELECT payload FROM items WHERE '+where+' ORDER BY position LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()]
    elif view=='downstream_consumers' and confirmed_only:
        header,_,_=architecture.page(artifact,view,0,1)
        with closing(workflow.connection(artifact)) as con:
            where="section=? AND json_extract(payload,'$.status')='SOURCE_CONFIRMED' AND instr(search,?)>0"
            args=[view,q.casefold()]
            total=con.execute('SELECT count(*) FROM items WHERE '+where,args).fetchone()[0]
            items=[json.loads(row[0]) for row in con.execute('SELECT payload FROM items WHERE '+where+' ORDER BY position LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()]
    else:header,total,items=architecture.page(artifact,view,offset,limit,q)
    state(task)
    return JSONResponse(dict(header=header,total=total,items=items),headers={'Cache-Control':'no-store'})


@router.get('/api/architecture/tasks/{task}/relation-fact')
def relation_fact(task:str,id:str=Query(...,pattern=r'^u[0-9a-f]{64}$')):
    with closing(workflow.connection(path(task))) as con:
        row=con.execute("SELECT payload FROM items WHERE section='relation_evidence' AND json_extract(payload,'$.id')=?",[id]).fetchone()
    if row is None:raise HTTPException(404,'关系证据不存在。')
    state(task)
    return JSONResponse(json.loads(row[0]),headers={'Cache-Control':'no-store'})


@router.get('/api/architecture/tasks/{task}/relation-context')
def relation_context(task:str,ref:str=Query(...,pattern=r'^/(rules/[0-9]+/(rule_semantics|feeder_semantics)/[0-9]+|write_explanations/[0-9]+)$')):
    """One existing statement/write resource on demand, never duplicate it on every edge."""
    parts=ref.strip('/').split('/')
    _,_,items=architecture.page(path(task),parts[0],int(parts[1]),1)
    try:
        context=items[0] if parts[0]=='write_explanations' else items[0][parts[2]][int(parts[3])]
    except (IndexError,KeyError) as exc:raise HTTPException(404,'该证据上下文不存在。') from exc
    state(task)
    return JSONResponse(context,headers={'Cache-Control':'no-store'})


@router.get('/api/architecture/tasks/{task}/implementation')
def implementation(task:str,process:str=Query(...,max_length=1000)):
    report=workflow.detail(path(task),process)
    if report is None:raise HTTPException(404,'该过程不在解析范围内。')
    state(task);return JSONResponse(report,headers={'Cache-Control':'no-store'})


@router.get('/api/architecture/tasks/{task}/functional-flow')
def functional_flow(task:str,max_nodes:int=Query(48,ge=3,le=100),max_edges:int=Query(160,ge=1,le=300),include_context:bool=False):
    from tm1_insight.functional_flow import from_artifact
    result=from_artifact(path(task),max_nodes=max_nodes,max_edges=max_edges,include_context=include_context)
    state(task)
    return JSONResponse(result,headers={'Cache-Control':'no-store'})


@router.get('/api/architecture/tasks/{task}/fact')
def fact(task:str,id:str=Query(...,pattern=r'^e[1-9][0-9]{0,6}$')):
    with closing(workflow.connection(path(task))) as con:
        row=con.execute("SELECT payload FROM items WHERE section='evidence' AND position=?",[int(id[1:])-1]).fetchone()
    if row is None:raise HTTPException(404,'证据不存在。')
    state(task);return JSONResponse(json.loads(row[0]),headers={'Cache-Control':'no-store'})


@router.get('/api/architecture/tasks/{task}/dimension')
def dimension(task:str,name:str=Query(...,max_length=1000),field:Literal['elements','attributes','edges','subsets']='elements',page:int=Query(1,ge=1)):
    from tm1_insight.store import dimensions
    _,total,_=workflow.page(path(task),'dimensions',process=name,sections=architecture.SECTIONS,version=architecture.VERSION)
    if not total:raise HTTPException(404,'维度不在本次架构范围内。')
    with closing(Store(get_settings()).connect(read_only=True)) as con:
        records=dimensions.records(con,name,field,page=page)
    state(task);return JSONResponse(records,headers={'Cache-Control':'no-store'})


@router.get('/api/architecture/tasks/{task}/evidence')
def evidence(task:str,process:str=Query(...,max_length=1000),section:Literal['prolog','metadata','data','epilog']='prolog',
             start:int=Query(1,ge=1),limit:int=Query(80,ge=1,le=200)):
    return source_evidence(path(task),lambda:state(task),process,section,start,limit)


@router.get('/api/architecture/tasks/{task}/export')
def export(task:str,format:Literal['json','markdown','zip','evidence','diagnostics','relations','flow-json','flow-markdown','mermaid']='json',include_context:bool=False):
    artifact=path(task)
    if format in {'flow-json','flow-markdown','mermaid'}:
        from tm1_insight.functional_flow import from_artifact,markdown,mermaid
        flow=from_artifact(artifact,include_context=include_context)
        state(task)
        content=json.dumps(flow,ensure_ascii=False) if format=='flow-json' else mermaid(flow) if format=='mermaid' else markdown(flow)
        filename={'flow-json':'FunctionalFlow.json','flow-markdown':'FunctionalFlow.md','mermaid':'FunctionalFlow.mmd'}[format]
        media={'flow-json':'application/json','flow-markdown':'text/markdown','mermaid':'text/plain'}[format]
        return StreamingResponse(iter([content]) if isinstance(content,str) else content,media_type=media,headers={'Content-Disposition':'attachment; filename='+filename,'Cache-Control':'no-store'})
    if format=='relations':
        from tm1_insight.unified_relations import json_export
        return StreamingResponse(json_export(artifact),media_type='application/json',headers={'Content-Disposition':'attachment; filename=UnifiedRelations.json','Cache-Control':'no-store'})
    if format=='json':return FileResponse(artifact,media_type='application/json',filename='Architecture.json',headers={'Cache-Control':'no-store'})
    if format in {'zip','evidence','diagnostics'}:
        from tm1_insight.architecture_extraction import package, json_section
        stream=package(artifact) if format=='zip' else json_section(artifact,'evidence' if format=='evidence' else 'diagnostics')
        filename={'zip':'Architecture.zip','evidence':'Evidence.json','diagnostics':'Diagnostics.json'}[format]
        return StreamingResponse(stream,media_type='application/zip' if format=='zip' else 'application/json',headers={'Content-Disposition':'attachment; filename='+filename,'Cache-Control':'no-store'})
    return StreamingResponse(architecture.markdown(artifact),media_type='text/markdown',headers={'Content-Disposition':'attachment; filename=Architecture.md','Cache-Control':'no-store'})
