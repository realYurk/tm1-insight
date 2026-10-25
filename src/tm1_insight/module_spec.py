"""Bounded composition of existing model/workflow facts; not a semantic engine."""
from __future__ import annotations

from datetime import date
from html import escape
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from tm1_insight import workbench as wb, workflow, workflow_review
from tm1_insight.architecture import OPERATIONS, LABELS
from tm1_insight.store import dimensions as dimension_store
from tm1_insight.store.queries import cube_rule_semantics

VERSION = 'module-reconstruction-1'
REVISION = 1


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class Ref(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['cube', 'process'] = 'cube'
    name: str = Field(min_length=1, max_length=1000)


class Notes(BaseModel):
    model_config = ConfigDict(extra='forbid')
    objective: str = Field(default='', max_length=4000)
    inputs: str = Field(default='', max_length=4000)
    outputs: str = Field(default='', max_length=4000)
    order: str = Field(default='', max_length=4000)
    remarks: str = Field(default='', max_length=4000)
    confirmed_rules: str = Field(default='', max_length=4000)


class Definition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['module-study-1'] = 'module-study-1'
    name: str = Field(min_length=1, max_length=200)
    snapshot_id: str = Field(min_length=1, max_length=128)
    analysis_date: date = Field(default_factory=date.today)
    entries: list[Ref] = Field(min_length=1, max_length=8)
    # Explicitly approved membership, not another set of recursive seeds.
    members: list[Ref] = Field(default_factory=list, max_length=60)
    excluded: list[Ref] = Field(default_factory=list, max_length=60)
    expand_calls: bool = False
    expand_access: bool = True
    depth: int = Field(default=1, ge=0, le=4, strict=True)
    node_budget: int = Field(default=24, ge=2, le=60, strict=True)
    edge_budget: int = Field(default=80, ge=1, le=200, strict=True)
    process_budget: int = Field(default=12, ge=1, le=20, strict=True)
    rule_budget: int = Field(default=8, ge=0, le=12, strict=True)
    notes: Notes = Field(default_factory=Notes)

    @model_validator(mode='after')
    def membership(self):
        for key in ('entries', 'members', 'excluded'):
            values=getattr(self,key)
            if len({(x.type,x.name) for x in values})!=len(values):
                raise ValueError('Duplicate object reference')
        if {(r.type,r.name) for r in self.members} & {(r.type,r.name) for r in self.excluded}:
            raise ValueError('Included and excluded overlap')
        if len(self.members)>self.node_budget:raise ValueError('Members exceed node budget')
        return self


def normalized(d):
    value=d.model_dump(mode='json')
    for field in ('entries','members','excluded'):
        value[field]=sorted(value[field],key=lambda r:(r['type'],r['name']))
    return value


def identity(d):
    return hashlib.sha256(canonical(normalized(d)).encode()).hexdigest()


def save_definition(root: Path, definition: Definition):
    """Immutable, content-addressed user asset, outside all model stores."""
    root.mkdir(parents=True,exist_ok=True)
    key=identity(definition);path=root/(key+'.json')
    payload=canonical(normalized(definition)).encode('utf-8')
    if path.exists():
        if path.read_bytes()!=payload:raise ValueError('Definition identity conflict')
        return key
    fd,name=tempfile.mkstemp(dir=root,suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(payload)
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)
    return key


def load_definition(root, key):
    if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Invalid definition id')
    path=root/(key+'.json')
    if path.stat().st_size>100000:raise ValueError('Definition exceeds size budget')
    result=Definition.model_validate_json(path.read_bytes())
    if identity(result)!=key:raise ValueError('Definition checksum mismatch')
    return result


def propose(index, definition):
    """Existing graph traversal, excludes applied before expansion. No Rule claims."""
    d=definition;snapshot=d.snapshot_id
    excluded={wb.stable_id(snapshot,r.type,r.name) for r in d.excluded}
    nodes={k:n for k,n in index[0].items() if k not in excluded}
    kinds=['TI_READ','TI_WRITE'] if d.expand_access else []
    if d.expand_calls:kinds.append('CALL')
    raw=[e for e in index[1] if e['kind'] in kinds and e['source'] in nodes and e['target'] in nodes]
    refs={(r.type,r.name):r for r in d.entries+d.members if wb.stable_id(snapshot,r.type,r.name) not in excluded}
    query=wb.GraphQuery(snapshot_id=snapshot,objects=[wb.ObjectRef(**r.model_dump()) for r in refs.values()],
        depth=d.depth,node_budget=d.node_budget,edge_budget=d.edge_budget,view='objects',include_technical=True,
        relation_types=kinds)
    result=wb.query_graph((nodes,raw),query,snapshot)
    result['nodes']=[n for n in result['nodes'] if n['type'] in {'cube','process'}]
    result['note']='候选范围；确认后只分析勾选成员。Rule 所属 Cube 可手动加入；文件索引不被当成已确认 Rule 关系。'
    return result


def build(con, d: Definition, index, scratch: Path, progress=None):
    """Only approved members are analyzed. References outside remain interfaces."""
    d=Definition.model_validate(normalized(d))
    snapshot=d.snapshot_id
    def update(stage,current=0,total=None):
        if progress:progress(stage=stage,stage_index=3,stages_total=6,current=current,total=total)
    update('检查已确认模块范围')
    members=sorted(d.members,key=lambda r:(r.type,r.name))
    if not members:raise ValueError('Confirm module membership first')
    ids={wb.stable_id(snapshot,r.type,r.name) for r in members}
    excluded={wb.stable_id(snapshot,r.type,r.name) for r in d.excluded}
    if ids & excluded:raise ValueError('Excluded member')
    objects=[];evidence={};unknowns={};valid=[]
    def proof(kind,obj,payload):
        item=dict(snapshot_id=snapshot,kind=kind,object=obj,**payload)
        key='e'+hashlib.sha256(canonical(item).encode()).hexdigest()
        evidence[key]=dict(id=key,**item)
        return [key]
    def unknown(obj,reason,impact,verify,refs=()):
        item=dict(object=obj,reason=reason,impact=impact,verification=verify,evidence_refs=list(refs),status='UNCONFIRMED')
        key=hashlib.sha256(canonical(item).encode()).hexdigest();unknowns[key]=dict(id='u'+key,**item)
    for r in members:
        key=wb.stable_id(snapshot,r.type,r.name);n=index[0].get(key)
        present=bool(n and n.get('in_snapshot'))
        objects.append(dict(id=key,snapshot_id=snapshot,**r.model_dump(),in_snapshot=present))
        if present:valid.append(r)
        else:unknown(r.name,'当前 Snapshot 缺少该对象','成员无法核对','切回绑定 Snapshot 或核对采集范围')
    raw=[e for e in index[1] if e['source'] in ids or e['target'] in ids]
    # Exclude the legacy Rule file index from confirmed relationships entirely.
    raw=[e for e in raw if e['kind']!='RULE_SOURCE_REFERENCE']
    boundary=[];relations=[];relation_total=0;boundary_total=0
    for e in sorted(raw,key=lambda e:e['id']):
        internal=e['source'] in ids and e['target'] in ids
        if internal:relation_total+=1
        else:boundary_total+=1
        destination=relations if internal else boundary
        if len(destination)>=d.edge_budget:continue
        a=index[0][e['source']];b=index[0][e['target']]
        refs=proof('INDEX_OBSERVATION',a['name'],dict(relation_kind=e['kind'],source=a['name'],target=b['name'],records=e['evidence']))
        item=dict(id=e['id'],source=a['name'],target=b['name'],source_type=a['type'],target_type=b['type'],kind=e['kind'],status='INDEX_OBSERVATION',evidence_refs=refs,runtime_verified=False)
        destination.append(item)
    dropped=max(0,relation_total-len(relations))
    if dropped:unknown(d.name,'索引关系超过边预算','部分索引关系未展示','提高边预算或缩小成员范围')
    if boundary_total:unknown(d.name,f'存在 {boundary_total} 条范围外索引依赖','当前规格不覆盖这些依赖的实现','核对范围外接口；必要时显式纳入对象')
    processes=[r.name for r in valid if r.type=='process'];cubes=[r.name for r in valid if r.type=='cube']
    inputs=[];outputs=[];calls=[];steps=[];calculations=[];models=[];rules=[];feeders=[];schedules=[];process_reports=[]
    analyzed=[];unreviewed=processes[d.process_budget:]
    chosen=processes[:d.process_budget]
    wf=None
    if chosen:
        # One existing multi-root workflow. No new traversal or implicit callee load.
        wf=workflow.build(con,chosen[0],roots=chosen,max_processes=d.process_budget,max_depth=0,
                          expand_calls=lambda *args:False,progress=progress)
        wf['source_fingerprint']=snapshot
        scratch.mkdir(parents=True,exist_ok=True)
        artifact=workflow.artifact(wf,scratch)
        try:
            for i,name in enumerate(chosen):
                update('组装 TI 输入、写入与调用',i,len(chosen))
                detail=wf['details'].get(name,{})
                if not detail.get('source_hash'):
                    unreviewed.append(name);unknown(name,'源码超过现有 Workflow 预算或未解析','该 TI 实现尚未核对','缩小范围后单独研究该 TI');continue
                analyzed.append(name)
                schedule_rows=con.execute('SELECT chore_name,step_order FROM chore_runs_process WHERE process_name=? ORDER BY chore_name,step_order LIMIT 101',[name]).fetchall() if any(e['kind']=='SCHEDULE' and e['target']==wb.stable_id(snapshot,'process',name) for e in raw) else []
                for chore,order in schedule_rows[:100]:
                    refs=proof('CHORE_DEFINITION',chore,dict(table='chore_runs_process',process=name,step_order=order))
                    schedules.append(dict(chore=chore,process=name,step_order=order,evidence_refs=refs,scope='recorded_step_not_runtime'))
                if len(schedule_rows)>100:unknown(name,'调度定义超过 100 项','其余调度入口未展示','按 Chore 单独核对')
                review=workflow_review.build(artifact.path,declaration=workflow_review.source_declaration(con,name),process=name)
                hash_ref=proof('PROCESS_SOURCE',name,dict(source_hash=detail['source_hash'],sections=review['sections']))
                process_reports.append(dict(process=name,parameters=review['parameters'],behaviors=review['summary']['behaviors'],evidence_refs=hash_ref))
                for cube in review['summary']['reads']:
                    reads=[x for x in detail.get('observations',[]) if x.get('target')==cube and x.get('operation','').casefold() in {'cellgetn','cellgets'}]
                    refs=proof('CELL_READ',name,dict(source_hash=detail['source_hash'],locations=reads))
                    inputs.append(dict(kind='CELL_READ',process=name,name=cube,grain='按源码坐标访问单元格',structure='见 Cube 维度顺序；未据此确认目标值依赖',status='SOURCE_OBSERVED',evidence_refs=refs))
                src=review['sources'];decl=src['declaration'];view=src['view_binding'] or {}
                if decl.get('type') not in {None,'UNKNOWN',''} or view:
                    refs=proof('DATASOURCE',name,dict(declaration=decl,source_hash=detail['source_hash']))
                    inputs.append(dict(kind='DATASOURCE',process=name,name=view.get('cube') or '外部/未确认来源',view=view.get('view'),source_type=decl.get('type'),status=decl.get('status'),variables=src['variables'],coordinates=src['coordinates'],unresolved_reasons=src['reasons'],grain='已记录字段/布局，不证明每行写入',evidence_refs=refs))
                for p in review['parameters']:
                    inputs.append(dict(kind='PARAMETER',process=name,name=p,status='DECLARED_NOT_EVALUATED',evidence_refs=hash_ref))
                for why in src['reasons']:
                    unknown(name,str(why),'数据行字段与写入值可能无法对应','取得同一源码版本的 Variables 与 NativeView 行布局后重新核对',hash_ref)
                if view and not src['variables']:
                    unknown(name,'VIEW 来源已记录，但缺少可用 Process Variables 定义','不能确认 Data 行字段顺序或值列来源','补充与当前源码哈希匹配的 Variables 和 View 布局；不得凭 vValue 名称推定',hash_ref)
                for why in review['limitations']:
                    unknown(name,why,'本 TI 报告有未展示的分析记录','提高相应范围或拆分研究，并核对逐项报告',hash_ref)
                for c in review['calls']:
                    refs=proof('SOURCE_CALL',name,{k:c.get(k) for k in ('section','line','column','source_hash')})
                    item=dict(caller=name,callee=c.get('target'),parameters=c.get('bindings',[]),conditions=c.get('control_context',[]),evidence_refs=refs,
                              in_scope=bool(c.get('target') in chosen),relation='DIRECT_CALL',runtime_verified=False)
                    calls.append(item)
                    if not c.get('target'):unknown(name,'动态调用目标未确认','无法确定调用契约与副作用','核对此位置的目标表达式及调用参数来源',refs)
                    elif c['target'] not in chosen:unknown(name,'被调用 TI 在已分析范围外：'+c['target'],'被调用实现及参数约束未核对','显式纳入该 TI 或定义外部调用契约',refs)
                    if c.get('target') and c['target'] not in processes:
                        boundary_total+=1
                        if len(boundary)<d.edge_budget:
                            boundary.append(dict(id=wb.stable_id(snapshot,name,c['target'],refs),source=name,target=c['target'],source_type='process',target_type='process',kind='SOURCE_CALL',status='SOURCE_OBSERVED',evidence_refs=refs,runtime_verified=False))
                read_by_id={n['id']:n for n in review['writes']['reads']}
                for w in review['writes']['writes']:
                    refs=proof('TI_WRITE',name,dict(source_hash=detail['source_hash'],**(w.get('evidence') or {})))
                    target=w.get('cube');coords=w.get('coordinate_mapping') or {}
                    row=dict(id=wb.stable_id(snapshot,name,w['id']),kind='TI_WRITE',process=name,target_cube=target,operation=w['operation'],value_expression=w.get('value_expression'),
                             coordinates=coords,preconditions=w.get('control_context',[]),evidence_refs=refs,trace_status=w.get('trace_status'),runtime_verified=False)
                    outputs.append(row)
                    reads=[read_by_id[k] for k in w.get('read_nodes',[]) if k in read_by_id]
                    deps=w.get('data_row_value_dependencies') or []
                    confirmed_rows=[x for x in deps if x.get('source_cube') and w.get('data_row_binding_status')=='STATIC_CELL_VALUE_DEPENDENCY']
                    calculations.append(dict(write_id=row['id'],process=name,target_cube=target,formula=w.get('formula_expression'),value_definition_chain=w.get('value_definition_chain'),
                        source_reads=reads,data_row_dependencies=deps,status='STATIC_VALUE_DEPENDENCY' if reads or confirmed_rows else 'NO_CONFIRMED_SOURCE_VALUE_DEPENDENCY',evidence_refs=refs,runtime_verified=False))
                    if w.get('unresolved_binding_reasons'):
                        unknown(name,'；'.join(map(str,w['unresolved_binding_reasons'])),'写入值或坐标存在静态缺口','核对此写入的变量定义链、来源字段和对应成员',refs)
                    if target not in cubes:unknown(name,'写入目标未纳入核心 Cube：'+str(target),'输出结构不完整','显式纳入该 Cube 以核对维度顺序',refs)
                    if w.get('control_context'):unknown(name,'写入条件/迭代次数未求值','不能确认实际写入次数与累加结果','用覆盖条件分支的授权测试夹具验证可达性及循环次数',refs)
                    if any((c.get('binding') or {}).get('kind')!='FIXED_MEMBER' for c in coords.get('items',[])):
                        unknown(name,'存在动态或未确认目标坐标','实际输出成员范围尚未确定','列举运行参数和变量映射的合法成员边界',refs)
                # Existing observation/operator classifications, never name-based effects.
                effects=[]
                for o in detail.get('observations',[]):
                    category=OPERATIONS.get(o.get('operation','').casefold())
                    if category in {'CLEAR','VIEW_PREPARATION','SUBSET_PREPARATION','CLEANUP'}:
                        refs=proof('IMPLEMENTATION_OBSERVATION',name,dict(source_hash=detail['source_hash'],observation=o))
                        effects.append(dict(category=category,label=LABELS[category],target=o.get('target'),evidence_refs=refs))
                steps.append(dict(process=name,behaviors=review['summary']['behaviors'],effects=effects,evidence_refs=hash_ref,
                                  order_status='EXPLANATORY_GROUP_NOT_GLOBAL_EXECUTION_ORDER',helper_details_folded=False))
                for g in review['critical_unknowns']:
                    unknown(name,g['reason'],'部分调用、表达式或运行前提未确认','按附带源码位置核对具体表达式与参数',proof('WORKFLOW_UNKNOWN',name,dict(source_hash=detail['source_hash'],evidence=g.get('evidence'))))
        finally:artifact.cleanup()
    for name in unreviewed:unknown(name,'未完成 TI 核对（预算或解析边界）','报告不覆盖其实现','提高 TI 预算或缩小范围')
    tables={r[0] for r in con.execute('SHOW TABLES').fetchall()}
    rule_owners=[];rule_skipped=[];rule_count=feeder_count=0
    for i,cube in enumerate(cubes):
        update('组装 Cube 结构和 Rule',i,len(cubes))
        dims=[r[0] for r in con.execute('SELECT dimension_name FROM cube_has_dimension WHERE cube_name=? ORDER BY dim_order',[cube]).fetchall()]
        refs=proof('CUBE_STRUCTURE',cube,dict(table='cube_has_dimension',dimension_order=dims))
        dimensions=[]
        for dim in dims:
            meta=dimension_store.metadata(con,dim);hier=[]
            if 'dimension_metadata' in tables:
                hier=[r[0] for r in con.execute("SELECT json_extract_string(e.value,'$') FROM json_each((SELECT CASE WHEN json_type(try_cast(hierarchy_names AS JSON))='ARRAY' THEN hierarchy_names ELSE '[]' END FROM dimension_metadata WHERE name=?)) e LIMIT 50",[dim]).fetchall()]
            dimensions.append(dict(name=dim,metadata=meta,hierarchies=hier,hierarchy_scope='recorded_first_50',type='NOT_COLLECTED'))
        row=con.execute('SELECT dimension_count,length(coalesce(rules,\'\')) FROM cubes WHERE name=?',[cube]).fetchone()
        complete=bool(row and row[0]==len(dims) and len(set(dims))==len(dims))
        models.append(dict(name=cube,dimension_order=dims,dimensions=dimensions,complete_order=complete,evidence_refs=refs))
        if not complete:unknown(cube,'Cube 维度顺序未完整采集','无法确认写入坐标粒度','核对 Cube 维度顺序与数量',refs)
        if not row or not row[1]:continue
        if len(rule_owners)>=d.rule_budget or row[1]>256000:
            rule_skipped.append(cube);unknown(cube,'Rule 所属 Cube 或 256k 源码预算截断','Rule/Feeder 结构未核对','单独缩小 Rule 研究范围',refs);continue
        parsed=cube_rule_semantics(con,cube);rule_owners.append(cube)
        if parsed.get('error'):
            rule_skipped.append(cube);unknown(cube,'Rule 解析失败','不可声明计算结构完整','定位此 Cube 的本地 Rule 语法');continue
        for kind,destination in [('rules',rules),('feeders',feeders)]:
            items=parsed.get(kind,[])
            if kind=='rules':rule_count+=len(items)
            else:feeder_count+=len(items)
            if len(items)>80:unknown(cube,f'{kind} 超过 80 条展示预算','其余语义记录未输出','拆分计算区域后重新研究',refs)
            for item in items[:80]:
                er=proof('RULE' if kind=='rules' else 'FEEDER',cube,dict(source_hash=parsed['source_hash'],section='rule',line=item['line_start'],line_end=item['line_end']))
                record={k:v for k,v in item.items() if k not in {'raw'}}
                record.update(evidence_refs=er,runtime_verified=False);destination.append(record)
                if kind=='rules':outputs.append(dict(kind='RULE_TARGET',target_cube=cube,area=item.get('lhs'),expression=(item.get('rhs') or {}).get('expression'),status=item['status'],evidence_refs=er))
                for db in item.get('db_references',[]):
                    inputs.append(dict(kind='RULE_REFERENCE' if kind=='rules' else 'FEEDER_SUPPORT_NOT_VALUE_FLOW',process=cube,name=db.get('cube'),status='SOURCE_CONFIRMED' if db.get('cube_resolved') else 'UNKNOWN',coordinates=db.get('coordinates'),evidence_refs=er))
                    if not db.get('cube_resolved') or db.get('cube') not in cubes:
                        unknown(cube,'动态或范围外 Rule/Feeder 引用：'+str(db.get('cube')),'依赖接口或坐标尚未完整覆盖','核对 DB 参数；必要时显式纳入来源 Cube',er)
                for why in item.get('unresolved_reasons',[]):unknown(cube,why,'完整计算/区域语义尚未确认','按 Rule 行号核对成员归属、动态坐标和函数支持范围',er)
        for u in parsed.get('unknowns',[]):
            unknown(cube,u.get('reason','Rule 未解析结构'),'可能遗漏 Rule 或 Feeder','核对此 Cube 的 Rule 源码定位',proof('RULE_UNKNOWN',cube,dict(source_hash=parsed['source_hash'],line=u.get('line'))))
    unknown(d.name,'未验证跨独立 TI 的全局执行顺序与重复执行/清空范围','不能推出最终数值或幂等性','在授权测试环境对调用参数、清空成员范围、重复累加和 Rule/Feeder 交互建立金标测试')
    validations=[]
    for w in outputs:
        if w['kind']!='TI_WRITE':continue
        validations.append(dict(id='v'+w['id'],status='NOT_RUN',object=w['process'],requirement='核对目标切面、条件、参数与'+('重复执行累加' if w['operation']=='CellIncrementN' else '覆盖边界及清空范围'),evidence_refs=w['evidence_refs']))
    validations.append(dict(id='v-module',status='NOT_RUN',object=d.name,requirement='交叉核对多 TI 写入区域、Rule 区域、调度及外部依赖；用合成/授权金标测试验证，静态规格不证明等价',evidence_refs=[]))
    # Derive bounded path observations using the existing lineage traversal over
    # SOURCE calls only. No name/index-only target becomes a confirmed invocation.
    from tm1_insight.domain.model import Dependency, DependencyKind
    from tm1_insight.lineage.engine import get_downstream
    deps=[Dependency(DependencyKind.OTHER,c['caller'],c['callee']) for c in calls if c['callee'] and c['in_scope']]
    call_paths=[]
    for entry in d.entries:
        if entry.type!='process':continue
        for path in get_downstream(deps,entry.name,max_depth=d.depth,max_nodes=d.node_budget):
            if len(call_paths)>=100:break
            call_paths.append(dict(entry=entry.name,target=path.target,path=list(path.path),status='STATIC_CALL_PATH_NOT_RUNTIME_ORDER'))
    ordered=lambda rows:sorted(rows,key=canonical)
    return dict(schema_version=VERSION,revision=REVISION,module=dict(id=identity(d),name=d.name,analysis_date=d.analysis_date.isoformat()),
        snapshot_ref=snapshot,runtime_verified=False,title='已分析范围内的模块规格',
        user_interpretation=dict(provenance='USER_DESCRIPTION',**d.notes.model_dump()),
        scope=dict(entries=[r.model_dump() for r in d.entries],members=[r.model_dump() for r in members],excluded=[r.model_dump() for r in d.excluded],
                   policy={k:normalized(d)[k] for k in ('expand_calls','expand_access','depth','node_budget','edge_budget','process_budget','rule_budget')},
                   membership_frozen=True,outside_dependencies=boundary,outside_dependency_total=boundary_total,unresolved_objects=sum(not o['in_snapshot'] for o in objects)),
        objects=objects,inputs=ordered(inputs),outputs=ordered(outputs),process_calls=ordered(calls),call_paths=ordered(call_paths),caller_index=[r for r in boundary if r['kind']=='CALL'],schedules=ordered(schedules),
        transformation_steps=ordered(steps),process_summaries=ordered(process_reports),calculations=ordered(calculations),rules=ordered(rules),feeders=ordered(feeders),data_models=models,
        indexed_relationships=relations,evidence=sorted(evidence.values(),key=lambda e:e['id']),unknowns=sorted(unknowns.values(),key=lambda e:e['id']),validation_requirements=validations,
        coverage=dict(cubes_included=len(cubes),processes_included=len(processes),processes_analyzed=len(analyzed),processes_unreviewed=sorted(unreviewed),
                      writes_analyzed=sum(w['kind']=='TI_WRITE' for w in outputs),rule_owners_analyzed=rule_owners,rule_owners_skipped=rule_skipped,rules_available=rule_count,feeders_available=feeder_count,
                      rules_retained=len(rules),feeders_retained=len(feeders),calls_outside=sum(not c['in_scope'] for c in calls),relations_omitted=dropped,outside_relations_omitted=max(0,boundary_total-len(boundary)),
                      source_characters=wf.get('summary',{}).get('source_characters') if wf else 0,complete_reconstruction=False),
        engineering_advice=dict(provenance='ENGINEERING_RECOMMENDATION',items=['保留已记录输入、参数、维度顺序及独立写入契约。','未知映射与执行前提应先转为明确的验证问题。','按逐写入点、声明式 Rule 与外部调用接口划分候选实现边界；不得直接据此声称运行等价。']))


def markdown(spec):
    """Human report projected from the same serialized spec as the API."""
    def cell(v):
        if isinstance(v,(dict,list)):v=canonical(v)
        return escape(str(v if v is not None else '待确认')).replace('|','\\|').replace('\n',' ')
    lines=['# '+cell(spec['module']['name'])+' · 模块重构规格','',spec['title'], '',
           'Snapshot：'+cell(spec['snapshot_ref'])+'；分析日期：'+cell(spec['module']['analysis_date']),
           '', 'Schema：'+spec['schema_version'], '', '静态事实不等于运行验证。步骤分组和表格排序不代表跨 TI 执行顺序。','']
    def table(title,heads,rows):
        lines.extend(['## '+title,'','| '+' | '.join(heads)+' |','|'+'|'.join('---' for _ in heads)+'|'])
        lines.extend('| '+' | '.join(cell(c) for c in row)+' |' for row in rows);lines.append('')
    names=lambda rows:'；'.join(r['type']+'：'+r['name'] for r in rows) or '无'
    coverage=spec['coverage']
    table('模块概览与用户描述',['项目','内容'],[['入口',names(spec['scope']['entries'])],['已确认成员',names(spec['scope']['members'])],['用户排除',names(spec['scope']['excluded'])],['覆盖度',f"Cube {coverage['cubes_included']}；TI 已分析 {coverage['processes_analyzed']} / {coverage['processes_included']}；独立写入 {coverage['writes_analyzed']}；Rule {coverage['rules_retained']} / {coverage['rules_available']}；未确认 {len(spec['unknowns'])}"],*[[f'用户描述：{k}',v] for k,v in spec['user_interpretation'].items() if k!='provenance' and v]])
    table('通俗功能说明',['处理程序','已观察行为','证据'],[[r['process'],'；'.join(r['behaviors']),r['evidence_refs']] for r in spec['process_summaries']])
    labels={'DATASOURCE':'数据源声明（不等于值流）','PARAMETER':'声明参数（未求值）','CELL_READ':'显式单元格读取','RULE_REFERENCE':'Rule 声明式引用','FEEDER_SUPPORT_NOT_VALUE_FLOW':'Feeder 支持（非普通值流）'}
    table('输入契约',['来源','使用者','来源类型','确定性与结构','证据'],[[r.get('name'),r.get('process'),labels.get(r['kind'],r['kind']),('View '+str(r.get('view') or '待确认')+'；已记录变量 '+str(len(r.get('variables',[])))+' 个；字段与值依赖见附录') if r['kind']=='DATASOURCE' else r.get('grain','参数值或坐标详见结构化附录'),r['evidence_refs']] for r in spec['inputs']])
    table('输出契约',['目标','处理机制','值/Rule表达式','切面/条件','证据'],[[r.get('target_cube'),r.get('process',r['kind']),r.get('value_expression',r.get('expression')),r.get('coordinates',r.get('area')),r['evidence_refs']] for r in spec['outputs']])
    table('处理步骤（解释分组）',['程序','动作','实现观察','证据'],[[r['process'],r['behaviors'],r['effects'],r['evidence_refs']] for r in spec['transformation_steps']])
    table('计算与映射',['程序/目标','表达式','来源（变量链详见附录）','确认边界'],[[r['process']+' → '+str(r['target_cube']),r['formula'],'；'.join(sorted({str(x.get('cube')) for x in r['source_reads']}|{str(x.get('source_cube')) for x in r['data_row_dependencies'] if x.get('source_cube')})) or '未确认源值依赖','存在静态值依赖，运行未验证' if r['status']=='STATIC_VALUE_DEPENDENCY' else '未确认源值依赖；可能为常量或未知表达式'] for r in spec['calculations']])
    table('TI 调用与调度',['调用方/Chore','被调用方','参数/步骤','条件与证据'],[[r['caller'],r['callee'],r['parameters'],dict(conditions=r['conditions'],evidence_refs=r['evidence_refs'])] for r in spec['process_calls']]+[[r['chore'],r['process'],r['step_order'],r['evidence_refs']] for r in spec['schedules']])
    table('核心 Cube 数据模型',['Cube','维度顺序','完整性','证据'],[[r['name'],r['dimension_order'],r['complete_order'],r['evidence_refs']] for r in spec['data_models']])
    states={'PARSED':'当前结构已解析；非运行验证','PARTIAL':'存在未确认计算或坐标','UNKNOWN':'关键结构未确认'}
    table('Rule 与 Feeder（不同语义）',['类别','所属 Cube / 行','区域/表达式','确认边界'],[['Rule',str(r['cube'])+':'+str(r['line_start']),str((r.get('lhs') or {}).get('raw'))+' = '+str((r.get('rhs') or {}).get('expression')),states.get(r['status'],r['status'])] for r in spec['rules']]+[['Feeder（非值流）',str(r['cube'])+':'+str(r['line_start']),str((r.get('source_area') or {}).get('raw'))+' => '+str((r.get('target_area') or {}).get('raw')),states.get(r['status'],r['status'])] for r in spec['feeders']])
    table('未确认事项',['对象','具体原因','重构影响','验证方式','证据'],[[r['object'],r['reason'],r['impact'],r['verification'],r['evidence_refs']] for r in spec['unknowns']])
    table('重构实现建议（非旧系统事实）',['性质','建议'],[['工程建议',v] for v in spec['engineering_advice']['items']])
    table('待执行验证契约',['对象','验收要求','状态','证据'],[[r['object'],r['requirement'],r['status'],r['evidence_refs']] for r in spec['validation_requirements']])
    table('范围外依赖',['来源','目标','关系','证据'],[[r['source'],r['target'],r['kind'],r['evidence_refs']] for r in spec['scope']['outside_dependencies']])
    lines.extend(['## 证据附录','','未默认包含完整 TI/Rule 源码。证据包含身份、哈希和必要局部结构。','','<details><summary>展开证据引用、变量链、输入字段与 Rule 表达式树</summary>','','```json',json.dumps(dict(evidence=spec['evidence'],calculations=spec['calculations'],inputs=spec['inputs'],rules=spec['rules'],feeders=spec['feeders'],scope=spec['scope'],coverage=spec['coverage']),ensure_ascii=False,sort_keys=True,indent=2),'```','','</details>',''])
    return '\n'.join(lines)
