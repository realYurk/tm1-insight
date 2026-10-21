"""Local-only graph/workspace endpoints. All model access is explicitly read-only."""
from contextlib import closing
from functools import lru_cache
import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from tm1_insight import workbench as wb
from tm1_insight.api.knowledge_tasks import fingerprint
from tm1_insight.config import get_settings
from tm1_insight.store.db import Store

router = APIRouter()


def source():
    from tm1_insight.api.app import _store
    return _store()


def guard(snapshot):
    store = source()
    current = fingerprint(store.settings)
    if snapshot and snapshot != current:
        raise HTTPException(409, '工作区绑定的模型已变化；未按名称自动重绑。请切回原模型或新建工作区。')
    return store, current


@lru_cache(maxsize=2)
def index(db_path, snapshot):
    from pathlib import Path
    settings = source().settings.model_copy(update={'database_file': Path(db_path)})
    with closing(Store(settings).connect(read_only=True)) as con:
        return wb.indexed_graph(con, snapshot)


@router.post('/api/workbench/graph')
async def graph(body: wb.GraphQuery, request: Request):
    store, snapshot = guard(body.snapshot_id)
    base = await run_in_threadpool(index,str(store.settings.db_path), snapshot)
    # Use the broad index solely to discover a bounded set of candidate owners.
    # It never leaves this endpoint as confirmed Rule / Feeder semantics.
    preliminary = await run_in_threadpool(wb.query_graph,base,body.model_copy(update={'relation_types':[], 'depth':max(0,body.depth-1)}),snapshot,discovery=True)
    nearby={n['id'] for n in preliminary['nodes']}
    owners=sorted({base[0][e['target']]['name'] for e in base[1] if e['kind']=='RULE_SOURCE_REFERENCE'
                   and (e['target'] in nearby or (body.depth>0 and e['source'] in nearby))})
    entries={o.name for o in body.objects if o.type=='cube'}
    owners.sort(key=lambda name:(name not in entries,name))
    refs=[];skipped=0
    for cube in owners[:12]:
        if await request.is_disconnected():raise HTTPException(499,'本次局部查询已取消。')
        edges,complete=await run_in_threadpool(rule_edges,str(store.settings.db_path),snapshot,cube)
        refs += edges
        skipped += not complete
    if await request.is_disconnected():raise HTTPException(499,'本次局部查询已取消。')
    result = await run_in_threadpool(wb.query_graph,(base[0],base[1]+refs),body,snapshot)
    result['rule_scope']=dict(owners_considered=len(owners),owners_analyzed=min(12,len(owners)),owners_skipped=skipped,
                              complete=len(owners)<=12 and not skipped)
    # Rule 分析预算不足是「分析范围」限制，不是「图被截断」；分开标注，
    # 避免把局部视图常态误报成结果截断。
    result['limits']['rule_scope_complete']=result['rule_scope']['complete']
    if not result['rule_scope']['complete']:
        result['limitations'].append('部分 Rule 文件超出本次 12 个所属 Cube / 每文件 256k 字符预算；未把未分类引用当成计算关系。')
    guard(snapshot)
    return result


@lru_cache(maxsize=48)
def rule_edges(db_path,snapshot,cube):
    from tm1_insight.workbench_rules import project
    from tm1_insight.store.queries import cube_rule_semantics
    from pathlib import Path
    settings=source().settings.model_copy(update={'database_file':Path(db_path)})
    with closing(Store(settings).connect(read_only=True)) as con:
        row=con.execute('SELECT length(rules) FROM cubes WHERE name=?',[cube]).fetchone()
        if not row or (row[0] or 0)>256000:return [],False
        parsed=cube_rule_semantics(con,cube)
    if parsed.get('error'):return [],False
    return project(parsed,snapshot),True


@router.get('/api/workbench/objects')
def objects(q: str = Query('', max_length=200), type: str = Query('cube', pattern='^(cube|process|chore|dimension)$')):
    store, snapshot = guard('')
    nodes, _ = index(str(store.settings.db_path), snapshot)
    found = sorted((n for n in nodes.values() if n['type'] == type and q.casefold() in n['name'].casefold()), key=lambda n:n['name'])
    return dict(snapshot_id=snapshot, objects=found[:40], total=len(found))


@router.get('/api/workbench/detail')
def detail(snapshot_id: str, type: str = Query(pattern='^(cube|process|chore|dimension)$'), name: str = Query(max_length=1000)):
    store, snapshot = guard(snapshot_id)
    from tm1_insight.store import queries
    with closing(store.connect(read_only=True)) as con:
        if type == 'process':
            # Exactly one process. Existing query exposes source, datasource and
            # operations; no request can execute TI or read cell values.
            item = queries.get_process(con, name)
            if item:
                from tm1_insight.workbench_export import sanitize
                item = {k:item[k] for k in ('name','prolog','metadata','data','epilog','reads_cubes','writes_cubes','datasource')}
                ds=sanitize(item['datasource']) or {}
                dtype=str(ds.get('type',ds.get('Type','UNKNOWN')))
                declaration=dict(type=dtype,schema_status='UNKNOWN',fields=[],metadata_origin='SNAPSHOT')
                if dtype.casefold() in {'view','tm1cubeview'}:
                    declaration.update(cube=ds.get('cube'),view=ds.get('view'))
                elif dtype.casefold() in {'ascii','characterdelimited'}:
                    import ntpath
                    declared=ds.get('cube')
                    if isinstance(declared,str):declaration['declared_file']=ntpath.basename(declared)
                # ODBC connection names, query text, credentials and server
                # addresses are not needed to show a schema-unknown declaration.
                item['datasource'] = declaration
        elif type == 'cube':
            item = queries.get_cube(con, name)
        elif type == 'dimension':
            row = con.execute('SELECT name,element_count,is_system FROM dimensions WHERE name=?',[name]).fetchone()
            item = dict(zip(('name','element_count','is_system'),row)) if row else None
        else:
            row = con.execute('SELECT name,processes,start_time,frequency,active FROM chores WHERE name=?',[name]).fetchone()
            item = dict(name=row[0],processes=json.loads(row[1]) if row[1] else [],start_time=row[2],frequency=row[3],active=row[4]) if row else None
    if item is None: raise HTTPException(404, '对象不在当前本地模型中')
    guard(snapshot)
    return dict(snapshot_id=snapshot, object=item, provenance='MODEL_FACT', runtime_verified=False)


@router.get('/api/workbench/writes')
def writes(snapshot_id: str, process: str = Query(max_length=1000)):
    store, snapshot = guard(snapshot_id)
    from tm1_insight.store.calculation import inspect
    with closing(store.connect(read_only=True)) as con:
        if not con.execute('SELECT 1 FROM processes WHERE name=?',[process]).fetchone():
            raise HTTPException(404, '当前本地模型没有这个 TI')
        report = inspect(con, process)
    guard(snapshot)
    fields = ('id','operation','cube','coordinate_mapping','value_expression','formula_expression','evidence','trace_status',
              'data_row_value_dependencies','data_row_binding_status','unresolved_binding_reasons','value_definition_chain')
    return dict(snapshot_id=snapshot, process=process, writes=[{k:w.get(k) for k in fields} for w in report['writes'][:80]],
                total=len(report['writes']), limitations=report.get('limits',[]), runtime_verified=False)


@router.get('/api/workbench/rules')
def rules(snapshot_id: str, cube: str = Query(max_length=1000)):
    store, snapshot = guard(snapshot_id)
    from tm1_insight.store.queries import cube_rule_semantics
    with closing(store.connect(read_only=True)) as con:
        result = cube_rule_semantics(con,cube)
    guard(snapshot)
    return result


def root():
    return get_settings().user_data_root / 'workspaces'


class Save(BaseModel):
    workspace: wb.Workspace
    revision: str = Field(default='', max_length=64)


@router.get('/api/workbench/workspaces')
def listing():
    _, snapshot = guard('')
    items = []
    for path in sorted(root().glob('*.json'))[:200]:
        try:
            item, revision = wb.load_workspace(root(), path.stem)
            items.append(dict(id=path.stem, name=item.name, compatible=item.snapshot_id == snapshot, revision=revision))
        except (ValueError, OSError):
            items.append(dict(id=path.stem, name='不可读取的工作区（原文件保留）', compatible=False))
    return dict(snapshot_id=snapshot, workspaces=items)


@router.get('/api/workbench/workspaces/{key}')
def load(key: str):
    try: item, revision = wb.load_workspace(root(), key)
    except FileNotFoundError as exc: raise HTTPException(404, '工作区不存在') from exc
    except (ValueError, OSError) as exc: raise HTTPException(422, '工作区损坏或格式不支持；原文件保留。') from exc
    guard(item.snapshot_id)
    return dict(id=key, revision=revision, workspace=item.model_dump())


@router.post('/api/workbench/workspaces')
def create(body: Save):
    return save(uuid4().hex, body)


@router.put('/api/workbench/workspaces/{key}')
def save(key: str, body: Save):
    store, snapshot = guard(body.workspace.snapshot_id)
    nodes, _ = index(str(store.settings.db_path), snapshot)
    if any(not nodes.get(wb.stable_id(snapshot,o.type,o.name),{}).get('in_snapshot') for o in body.workspace.objects):
        raise HTTPException(422, '工作区有不在当前快照中的对象引用；请保留为设计草稿，不得当成模型事实保存。')
    try: revision = wb.save_workspace(root(), key, body.workspace, body.revision)
    except FileExistsError as exc: raise HTTPException(409, str(exc)) from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    return dict(id=key, revision=revision)
