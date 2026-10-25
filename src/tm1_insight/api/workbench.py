"""Local-only graph/workspace endpoints. All model access is explicitly read-only."""
from contextlib import closing
from functools import lru_cache
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from tm1_insight import design as dg
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


def visible_objects(nodes, *, type: str, q: str, include_technical: bool):
    """对象目录过滤（纯函数，便于单测）。

    规则只针对 `}` 前缀（采集层的系统命名标记）；`Sys Parameter`、`#######`
    等名称不参与任何「系统 / 业务」判定，不会被硬编码排除或改写。
    """
    found = sorted((n for n in nodes.values() if n['type'] == type and q.casefold() in n['name'].casefold()), key=lambda n:n['name'])
    if not include_technical:
        found = [n for n in found if not n['name'].startswith('}')]
    return found


@router.get('/api/workbench/objects')
def objects(q: str = Query('', max_length=200), type: str = Query('cube', pattern='^(cube|process|chore|dimension)$'),
            include_technical: bool = Query(False), limit: int = Query(40, ge=1, le=200), offset: int = Query(0, ge=0, le=100000)):
    """对象目录。系统对象（`}` 前缀）默认过滤后再分页，避免用户先看到技术辅助对象。

    - `}` 前缀是采集层使用的系统命名标记（维度属性 / 视图缓存 / 归档等），
      不是业务用途推断；仅据此做显示过滤，不据此改对象身份或语义。
    - `Sys Parameter`、`#######` 等名称不参与任何「系统 / 业务」判定，
      不会被硬编码排除或改写。
    - include_technical=True 保留旧参数与全部对象（含 `}` 前缀），分页一致。
    """
    store, snapshot = guard('')
    nodes, _ = index(str(store.settings.db_path), snapshot)
    found = visible_objects(nodes, type=type, q=q, include_technical=include_technical)
    total = len(found)
    return dict(snapshot_id=snapshot, objects=found[offset:offset + limit], total=total,
                filtered_technical=not include_technical, offset=offset, limit=limit)


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
              'data_row_value_dependencies','data_row_binding_status','unresolved_binding_reasons','value_definition_chain',
              'read_nodes','control_context')
    # Expose existing Calculation evidence, without interpreting co-access as a
    # value dependency. read_nodes on each write are the parser's value trace;
    # other reads remain standalone observations, never implied source slices.
    read_fields = ('id','cube','operation','resolution','coordinate_mapping','evidence')
    reads = [n for n in report['nodes'] if n['kind'] == 'read']
    return dict(snapshot_id=snapshot, process=process, writes=[{k:w.get(k) for k in fields} for w in report['writes'][:80]],
                reads=[{k:n.get(k) for k in read_fields} for n in reads[:160]], read_total=len(reads),
                read_scope='CALCULATION_RETAINED_NODES_NOT_ALL_PROCESS_READS',
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


# ---------------------------------------------------------------- design mode

def _existing_dims(store, names):
    """只读取维度顺序，不读取任何业务数据。"""
    from tm1_insight.store import codegen as cg
    out = {}
    if not names:
        return out
    with closing(store.connect(read_only=True)) as con:
        for name in set(names):
            dims = cg._cube_dims(con, name)
            if dims:
                out[name] = dims
    return out


class DesignBody(BaseModel):
    design: wb.Design
    relation_id: str = Field(default='', max_length=80)
    cube_id: str = Field(default='', max_length=80)
    snapshot_id: str = Field(default='', max_length=128)


def _design_context(body: DesignBody):
    store, snapshot = guard(body.snapshot_id)
    names = set()
    for rel in body.design.relations:
        for end in (rel.source, rel.target):
            if end.kind == 'cube':
                names.add(end.ref)
    return store, snapshot, _existing_dims(store, names)


@router.get('/api/workbench/design/meta')
def design_meta(snapshot_id: str = ''):
    store, snapshot = guard(snapshot_id)
    with closing(store.connect(read_only=True)) as con:
        dims = [r[0] for r in con.execute('SELECT name FROM dimensions ORDER BY name').fetchall()]
        cubes = [r[0] for r in con.execute('SELECT name FROM cubes ORDER BY name').fetchall()]
    return dict(snapshot_id=snapshot,
                dimensions=[d for d in dims if not d.startswith('}')],
                cubes=[c for c in cubes if not c.startswith('}')],
                templates=[
                    dict(id='csv-to-cube', label='CSV / 字符分隔文件 → Cube',
                         source_kind='csv', supported=True),
                    dict(id='cube-data-transfer', label='Cube → Cube 数据传输',
                         source_kind='cube', supported=True),
                ],
                template_version='1',
                limitations=['生成结果为 TI 草案，未在 TM1 Server 部署或执行。',
                             '未提供字段结构的外部来源保持未确认，不猜测列名。'])


@router.post('/api/workbench/design/validate')
def design_validate(body: DesignBody):
    from tm1_insight.design import validate_relation
    store, snapshot, dims = _design_context(body)
    report = []
    for rel in body.design.relations:
        blockers = validate_relation(body.design, rel, dims)
        report.append(dict(relation_id=rel.id, ok=not blockers, blockers=blockers))
    return dict(snapshot_id=snapshot, relations=report,
                ok=all(r['ok'] for r in report))


@router.post('/api/workbench/design/generate')
def design_generate(body: DesignBody):
    from tm1_insight.design import generate
    store, snapshot, dims = _design_context(body)
    if not body.relation_id:
        raise HTTPException(400, '请指定要生成的设计关系')
    result = generate(body.design, body.relation_id, existing_cube_dims=dims,
                      generated_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    guard(snapshot)
    payload = dict(snapshot_id=snapshot, status=result['status'], blockers=result['blockers'],
                   issues=result.get('issues', []), code=result.get('code'),
                   summary=result.get('summary'), dependencies=result.get('dependencies'),
                   process_config=result.get('process_config'),
                   warnings=result.get('warnings') or [])
    artifact = result.get('artifact')
    if artifact is not None:
        payload['artifact'] = artifact if isinstance(artifact, dict) else json.loads(artifact.model_dump_json())
    return payload


class StaleBody(BaseModel):
    design: dg.Design
    relation_ids: list[str] = Field(default_factory=list, max_length=80)


@router.post('/api/workbench/design/stale')
def design_stale(body: StaleBody):
    """判定哪些已生成的关系因设计变化而过期。"""
    return dict(stale=dg.stale_relations(body.design, body.relation_ids))


@router.post('/api/workbench/design/cube-spec')
def design_cube_spec(body: DesignBody):
    from tm1_insight.design import cube_creation_spec
    store, snapshot, _ = _design_context(body)
    if not body.cube_id:
        raise HTTPException(400, '请指定 Cube 草稿')
    result = cube_creation_spec(body.design, body.cube_id)
    if result['status'] == 'missing':
        raise HTTPException(404, 'Cube 草稿不存在')
    guard(snapshot)
    return dict(snapshot_id=snapshot, **result)


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
