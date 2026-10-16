"""Functional boundary and human report projection. No execution or inferred business meaning."""
from __future__ import annotations
from collections import Counter, deque
import json
from tm1_insight.learning.understanding import structure
from tm1_insight.learning.syntax import statements

RELATIONSHIPS={'invocation','read_write','structure','rule_reference','schedule'}

class Boundary:
    def __init__(self,entry,max_nodes,allowed,downstream,technical):
        if not 1<=max_nodes<=5000:raise ValueError('max_nodes must be 1..5000')
        self.entry=entry;self.max_nodes=max_nodes
        self.allowed=set(RELATIONSHIPS if allowed is None else allowed)
        if not self.allowed<=RELATIONSHIPS:raise ValueError('Unsupported relationship type')
        self.downstream=downstream;self.technical=technical

    def core_processes(self,wf):
        parsed={p['process'] for p in wf['processes']}
        found=set(getattr(self,'entry_processes',[self.entry]));pending=list(found)
        while pending:
            source=pending.pop()
            for edge in wf['execution']:
                target=edge['target']
                if edge['process']==source and target in parsed and not target.startswith('}') and target not in found:
                    found.add(target);pending.append(target)
        return found

    def expand(self,source,target,depth):
        # Inspect directly called helpers to retain their effects; do not crawl their fan-out.
        return 'invocation' in self.allowed and (source==self.entry or not source.startswith('}') or self.technical)


def datasource(parts,cubes):
    """Single-definition top-level literal/alias bindings, using the existing block parser.

    Conditions elsewhere do not invalidate a binding. Any conditional/repeated write
    to a participating variable does. Only earlier Prolog definitions may supply aliases.
    """
    roots,_,diagnostics,_=structure(parts,include_logging=True)
    if diagnostics:return None
    assignments=[t for t in statements(parts,include_logging=True) if len(t)>2 and t[0]['kind']=='id' and t[1]['value']=='=']
    counts=Counter(t[0]['value'].casefold() for t in assignments)
    last={t[0]['value'].casefold():t[0] for t in assignments}
    env={}
    for node in roots[0]:
        t=node['tokens']
        if node['kind']!='statement' or len(t)<3 or t[1]['value']!='=':continue
        name=t[0]['value'].casefold()
        # A final unconditional DataSourceType assignment overrides prior NULL guards.
        # This establishes the binding only on paths reaching this statement.
        final_type=name=='datasourcetype' and last[name]==t[0]
        if counts[name]!=1 and not final_type:continue
        rhs=[x for x in t[2:] if x['value']!=';']
        if len(rhs)!=1:continue
        token=rhs[0];value=None;locations=[]
        if token['kind']=='string':
            raw=token['value'];value=raw[1:-1].replace(raw[0]*2,raw[0])
        elif token['kind']=='id' and token['value'].casefold() in env:
            value,locations=env[token['value'].casefold()]
        if value is not None:env[name]=(value,locations+[{k:t[0][k] for k in ('section','line','column')}])
    dtype=env.get('datasourcetype',('',[]));src=env.get('datasourcenameforserver',(None,[]))
    canonical={c.casefold():c for c in cubes}
    if dtype[0].casefold() in {'odbc','characterdelimited','ascii','oledb'}:
        return dict(external_type=dtype[0].upper(),locations=dtype[1],status='STATIC_TYPE_ONLY',note='只确认数据源类型，路径/SQL/字段及行变量映射未解析；连接秘密不导出。')
    if dtype[0].casefold()!='view' or not src[0] or src[0].casefold() not in canonical:return None
    # Preserve view identity locally, not arbitrary assignment constants.
    view=env.get('datasourcecubeview',(None,[]))
    return dict(cube=canonical[src[0].casefold()],view=view[0],locations=dtype[1]+src[1]+view[1],
                status='STATIC_BINDING',note='到达 Prolog 最终顶层赋值时的静态数据源；提前退出路径、实际执行、成员筛选和行变量值流未验证。')


def enrich(r,wf,policy):
    entry=policy.entry
    core=set(policy.entry_processes);paths={n:[] for n in core};queue=deque(sorted(core))
    while queue:
        source=queue.popleft()
        for e in r['execution_relationships']:
            target=e['target']
            if e['process']!=source or not target or target.startswith('}') or target in core:continue
            # Only already parsed forward invocations, never callers or index candidates.
            if target not in {p['process'] for p in r['processes']}:continue
            core.add(target);paths[target]=paths[source]+[dict(source=source,target=target,kind='source_invocation',evidence=e['evidence'])];queue.append(target)
    roles={}
    for p in r['processes']:
        name=p['process'];role='CORE' if name in core else 'TECHNICAL_SUPPORT'
        p['module_role']=role;p['technical']=role=='TECHNICAL_SUPPORT';roles[name]=role
        incoming=[e for e in r['execution_relationships'] if e['target']==name]
        path=paths.get(name) or ([dict(source=incoming[0]['process'],target=name,kind='source_invocation',evidence=incoming[0]['evidence'])] if incoming else [])
        r['module_objects'].append(dict(process=name,name=name,object_type='process',module_role=role,relation_path=path,
            reason='选定入口或已解析的向前业务调用路径' if role=='CORE' else '调用路径中的系统命名空间辅助实现；不按名称推断操作效果'))
    for c in r['cubes']:
        refs=[d for d in r['data_relationships'] if d.get('target')==c['name'] and d.get('role') in {'read','write'}]
        c['module_role']='TECHNICAL_SUPPORT' if c['technical'] else 'CORE' if c['name']==entry or any(d['process'] in core for d in refs) else 'EXTERNAL_DEPENDENCY'
        r['module_objects'].append(dict(process=c['name'],name=c['name'],object_type='cube',module_role=c['module_role'],
            relation_path=[dict(source=d['process'],target=c['name'],kind=d['kind'],evidence=d['evidence']) for d in refs],evidence=c['evidence'],
            reason='当前调用范围内的源码读写/数据源关系；角色不代表业务含义'))
    for d in r['dimensions']:
        owners=[c for c in r['cubes'] if any(x['name']==d['name'] for x in c['dimensions'])]
        d['module_role']='EXTERNAL_DEPENDENCY'
        r['module_objects'].append(dict(process=d['name'],name=d['name'],object_type='dimension',module_role='EXTERNAL_DEPENDENCY',
            relation_path=[dict(source=c['name'],target=d['name'],kind='cube_dimension',evidence=c['evidence']) for c in owners],
            reason='共享结构元数据；不沿该维度扩展其他 Cube'))
    facts_by_location={}
    for f in r['evidence']:
        facts_by_location.setdefault((f.get('process'),f.get('section'),f.get('line'),f.get('column')),[]).append(f['id'])
    # Configuration reads remain explicit; names such as Sys/Info never decide a business role.
    for s in r['transformation_steps']:
        s['module_role']=roles[s['process']];s['technical']=s['module_role']!='CORE'
        if s['module_role']!='CORE':continue
        name=s['process'];effects=[e for e in s['effects'] if e['category']!='LOGGING']
        reads=[e for e in effects if e['operation'].casefold() in {'cellgetn','cellgets'}]
        writes=[e for e in effects if e['operation'].casefold() in {'cellputn','cellputs','cellincrementn'}]
        prep=[e for e in effects if e['category'] in {'CLEAR','VIEW_PREPARATION','SUBSET_PREPARATION','CLEANUP'}]
        groups={}
        for e in prep:
            key=(e['category'],e['target'],json.dumps(e['conditions'],sort_keys=True))
            group=groups.setdefault(key,dict(category=e['category'],label=e['label'],target=e['target'],condition=e['conditions'],count=0,evidence_refs=[]))
            group['count']+=1;group['evidence_refs'].extend(e['evidence'])
        calculations=[]
        for calc in [c for c in wf['calculation'] if c['process']==name]:
            location=(name,calc['evidence']['section'],calc['evidence']['line'],calc['evidence']['column'])
            ids_at_location=set(facts_by_location.get(location,[]))
            if not any(ids_at_location.intersection(e['evidence']) for e in writes if not e.get('via')):continue
            report=wf['details'][name];nodes={n['id']:n for n in report['nodes']}
            read_nodes=[nodes[i] for i in calc['read_nodes']]
            evidence=facts_by_location.get(location,[])
            calculations.append(dict(operation=calc['operation'],source_cubes=sorted({n['cube'] for n in read_nodes if n.get('cube')}),target_cube=calc['cube'],
                expression=calc['reconstructed'] if calc['status']=='STATIC_EXPRESSION' else None,
                resolution_status=calc['status'],condition=calc['control_context'],execution_context=calc['evidence'],
                source_slice=[dict(cube=n.get('cube'),coordinates=n['coordinate_mapping']) for n in read_nodes],target_slice=calc['coordinate_mapping'],
                evidence_refs=evidence,write_id=calc['write_id'],unresolved_inputs=sorted({nodes[i].get('name','表达式') for i in calc['unknown_nodes']}),note='每个写入点保留独立公式、坐标、条件与定义链；不将不同切面合并。'))
        ids=sorted({x for e in effects for x in e['evidence']}|set((s['source_binding'] or {}).get('evidence',[])),key=lambda x:int(x[1:]))
        summary=dict(process=name,source_cubes=s['inputs'],target_cubes=s['outputs'],read_operations=reads,write_operations=writes,
            preparation_operations=list(groups.values()),transformation_type='STATIC_CALCULATION' if any(c['expression'] for c in calculations) else 'OBSERVED_READ_WRITE',
            source_slice=s['source_binding'],target_slice=[c['target_slice'] for c in calculations],condition='各写入点分别保留',
            execution_context='TI 四个 Section 的静态源码；未执行',dimension_mapping=[c['target_slice'] for c in calculations],calculation_summary=calculations,
            evidence_refs=ids,resolution_status='PARTIAL',
            description='该 TI 读取 '+('、'.join(s['inputs']) or '待确认来源')+'，并写入 '+('、'.join(s['outputs']) or '待确认目标')+'；仅下列已还原表达式支持对应值依赖，其余读写关联不证明数据传输。')
        if not s['inputs'] and not s['outputs']:
            summary['description']='该 TI 未观察到直接 Cube 读写；已确认调用：'+('、'.join(s['business_calls']) or '暂无确定业务调用')+'。动态调用及实现边界另行保留。'
        r['transformation_summaries'].append(summary);s['summary']=summary
        models={c['name']:c for c in r['cubes']}
        for source in s['inputs']:
            for target in s['outputs']:
                if source==target or source not in models or target not in models:continue
                a,b=models[source],models[target];ad=[d['name'] for d in a['dimensions']];bd=[d['name'] for d in b['dimensions']]
                r['dimension_comparisons'].append(dict(process=name,source=source,target=target,shared=[d for d in ad if d in bd],
                    source_only=[d for d in ad if d not in bd],target_only=[d for d in bd if d not in ad],possible_measure_dimensions=[],
                    structure_complete=a['complete_order'] and b['complete_order'],evidence_refs=a['evidence']+b['evidence'],
                    mapping_status='UNCONFIRMED',note='结构比较不证明值流、成员对应、相同粒度或自动汇总；指标维角色未确认。'))
    for rule in r['rules']:
        groups={}
        for ref in rule['references']:
            g=groups.setdefault((ref['kind'],ref['target']),dict(kind=ref['kind'],target=ref['target'],count=0,evidence_refs=[]))
            g['count']+=1;g['evidence_refs'].extend(ref['evidence'])
        rule['groups']=list(groups.values())
    for c in r['chores']:
        c['module_role']='EXTERNAL_DEPENDENCY'
        r['module_objects'].append(dict(process=c['name'],name=c['name'],object_type='chore',module_role='EXTERNAL_DEPENDENCY',relation_path=[dict(source=c['name'],target=c['target'],kind='recorded_schedule',evidence=c['evidence'])]))
    for rule in r['rules']:
        r['module_objects'].append(dict(process=rule['cube'],name=rule['cube'],object_type='rule',module_role=rule['module_role'],relation_path=[dict(source=rule['cube'],target=g['target'],kind=g['kind'],evidence=g['evidence_refs']) for g in rule['groups']]))
    r['boundary'].update(max_nodes=policy.max_nodes,allowed_relationship_types=sorted(policy.allowed),include_downstream=policy.downstream,
        include_technical_details=policy.technical,policy_version='functional-module-2',node_budget_scope='已展开 TI（含验证 Caller）、Cube、Dimension 和额外 Rule 源码；边界引用与离线调度行保留，不代表已展开对象',
        note='仅沿已确认向前调用展开业务 TI；直接辅助源码保留效果，默认停止辅助内部调用扩展。Rule 消费者在边界外，Chore 仅按核心 TI / 已验证入口 Caller 关联。')
    r['input_outputs']=dict(inputs=sorted({c for s in r['transformation_summaries'] for c in s['source_cubes']}),outputs=sorted({c for s in r['transformation_summaries'] for c in s['target_cubes']}))
    r['extraction_version']='architecture-extraction-2'
    r['key_questions']=[
        '核对 VIEW/Subset 的实际成员和 Data 行变量，再验证记录来源到写入值的映射。',
        '分别核对覆盖、累加及清理切面；静态源码不能证明本次执行路径或执行顺序。',
        '核对未解析的调用目标与边界外辅助调用；完整诊断保存在 Diagnostics.json。']


def records(path,section):
    from tm1_insight.architecture import page
    offset=0
    while True:
        _,total,items=page(path,section,offset,100)
        yield from items
        offset+=len(items)
        if offset>=total:break


def markdown(path):
    from tm1_insight.architecture import page
    def safe(value):return str(value).replace('\r',' ').replace('\n',' ').replace('|','\\|').replace('<','&lt;').replace('>','&gt;')
    def names(values):return '、'.join(map(safe,values)) or '无已记录项'
    h,_,_=page(path);core=[c for c in records(path,'cubes') if c['module_role']=='CORE']
    yield '# 模块架构说明\n\n## 1. 模块概览\n\n'
    yield ('入口 Cube：**' if h['module']['kind']=='cube_scope' else '入口 TI：**')+safe(h['module']['name'])+'**\n\n'
    yield h['boundary']['note']+'\n\n'
    yield '核心 Cube：'+names(c['name'] for c in core)+'。\n\n读取对象：'+names(h['input_outputs']['inputs'])+'。\n\n写入对象：'+names(h['input_outputs']['outputs'])+'。\n\n'
    yield '本报告为静态源码与模型事实，不证明运行结果。逐项证据见 Architecture.json 对应摘要的 evidence_refs 和 Evidence.json；原始诊断见 Diagnostics.json。\n\n'
    yield '## 2. 数据模型\n\n'
    for c in core:
        yield '- **'+safe(c['name'])+'**（'+str(len(c['dimensions']))+' 维）：'+names(d['name'] for d in c['dimensions'])+'。'+('维度顺序完整。' if c['complete_order'] else '维度顺序未完整采集。')+'\n'
    for d in records(path,'dimensions'):
        fields=(d.get('metadata') or {}).get('fields',{})
        yield '- Dimension '+safe(d['name'])+'：已采集层级 '+(names(d.get('hierarchies',[])) if d.get('hierarchy_count') is not None else '元数据未采集')+'；直接汇总边 '+(str(fields['edges']['count'])+' 条' if fields.get('edges',{}).get('status')=='recorded' else '未采集')+'。原始权重按需分页核对，不推断运行时汇总结果。\n'
    yield '\n源 / 目标结构比较（不证明成员映射或数据传输）：\n\n'
    compared=set()
    for d in records(path,'dimension_comparisons'):
        pair=(d['source'],d['target'])
        if pair in compared:continue
        compared.add(pair)
        yield '- '+safe(d['source'])+' / '+safe(d['target'])+'：共享 '+names(d['shared'])+'；仅源端 '+names(d['source_only'])+'；仅目标端 '+names(d['target_only'])+'。'+('' if d['structure_complete'] else '结构采集不完整，差异仅为当前记录。')+'\n'
    yield '\n同名维度不证明同粒度；目标新增维度不代表自动汇总。指标维和成员映射仍需坐标/属性证据。\n\n## 3. 数据加工流程\n\n'
    for s in records(path,'transformation_summaries'):
        yield '### '+safe(s['process'])+'\n\n'+safe(s['description'])+'\n\n'
        roles={'VALUE_EXPRESSION':'写入值表达式依赖','TARGET_COORDINATE_LOOKUP':'目标坐标查找','CONTROL_EXPRESSION':'控制条件依赖','READ_OBSERVATION_ONLY':'只确认读取，用途未追溯'}
        uses={}
        for read in s.get('observed_reads',[]):
            if not read['cube']:continue
            for role in read['usages']:uses.setdefault((read['cube'],role),0);uses[(read['cube'],role)]+=1
        for (cube,role),count in uses.items():yield '- '+safe(cube)+'：'+roles[role]+'（'+str(count)+' 处）。\n'
        if s['source_slice']:yield '- VIEW 记录来源：'+safe(s['source_slice']['cube'])+'；视图 '+safe(s['source_slice'].get('view') or '未确认')+'。成员筛选和行变量值流仍需核对。\n'
        yield '- 显式读取 '+str(len(s['read_operations']))+' 处，写入 '+str(len(s['write_operations']))+' 处（'+names(k+' × '+str(v) for k,v in Counter(e['operation'] for e in s['write_operations']).items())+'）。\n'
        presentation={}
        for p in s['preparation_operations']:
            key=(p['label'],p['target']);presentation[key]=presentation.get(key,0)+p['count']
        for (label,target),count in presentation.items():yield '- '+safe(label)+'：'+safe(target or '目标待确认')+'（'+str(count)+' 处观察；各条件分组在 JSON 独立保留）。\n'
        complete=[c for c in s['calculation_summary'] if c['expression']]
        for c in complete:yield '- 已还原表达式：`'+safe(c['expression']).replace('`','\\`')+'`\n'
        pending=[c for c in s['calculation_summary'] if not c['expression']]
        if pending:
            yield '- '+str(len(pending))+' 个写入点的公式/坐标或条件尚未完整解析；位置：'+names(str(c['execution_context']['section'])+':'+str(c['execution_context']['line']) for c in pending)+'。各写入点在 JSON 独立保留。\n'
            variables=sorted({v for c in pending for v in c['unresolved_inputs']})
            if variables:yield '- 待追溯的变量 / 表达式：'+names(variables)+'；需核对 Data Source 字段、赋值或属性查询定义。\n'
        if not complete and s['write_operations']:yield '- 当前没有可完整展示的值计算公式；需核对 Data 行变量、属性查询及参数来源。\n'
        if s.get('write_explanations'):
            from tm1_insight.formation import write_markdown
            yield from write_markdown(s['write_explanations'])
        yield '\n'
    for external in records(path,'external_sources'):yield '- '+safe(external['process'])+' 的外部数据源类型：'+safe(external['external_type'])+'；文件/SQL/字段值流仍待确认。\n'
    yield '## 4. 执行与调度\n\n'
    for e in records(path,'execution_relationships'):
        if e['technical']:continue
        yield '- '+safe(e['process'])+' → '+safe(e['target'] or '动态调用目标待确认')+('（条件/循环内）' if e['conditions'] else '')+'。\n'
        if e['parameters']:yield '  - 显式参数：'+names((b['parameter'] or '参数名待确认')+' ← '+b['expression'] for b in e['parameters'])+'。\n'
    chores=list(records(path,'chores'))
    for c in chores:yield '- Chore '+safe(c['name'])+' → '+safe(c['target'])+'，离线步骤 '+str(c['step_order'])+'；未验证启用或实际运行。\n'
    if not chores:yield '- 当前范围未确认 Chore 调度记录，不代表服务器没有调度。\n'
    yield '\n通用辅助调用默认折叠；实际读取、写入、清理效果保留于加工摘要。源码调用位置不保证运行完成顺序。\n\n## 5. Rule 与计算关系\n\n'
    count=0
    for r in records(path,'rules'):
        if r['module_role']!='CORE':continue
        for g in r['groups']:
            count+=1
            yield '- '+safe(r['cube'])+' '+('Rule 引用 ' if g['kind']=='rule_read' else 'Feeder 引用 ')+safe(g['target'])+'：'+str(g['count'])+' 处。\n'
    if not count:yield '- 当前核心 Cube 源码未确认可展示的跨 Cube DB 引用；本工具尚未还原完整 Rule 公式。\n'
    yield '\nFeeder 属于稀疏计算支持关系，不直接产生业务数据值。外部规则消费者只列为边界依赖，不成为核心计算。\n\n## 6. 模块边界与迁移关注点\n\n'
    external=[c for c in records(path,'cubes') if c['module_role']!='CORE']
    yield '- 外部 / 技术 Cube：'+names(c['name'] for c in external)+'。\n'
    _,total,_=page(path,'downstream_consumers');yield '- 边界外消费者记录 '+str(total)+' 条；仅按标明的源码读取或目录候选理解，不扩展为其他核心模块。\n'
    for q in h['key_questions']+h['migration_notes']:yield '- '+safe(q)+'\n'
    issues=[u for u in records(path,'unresolved_dependencies') if not u.get('diagnostic') and not u['process'].startswith('}') and any(x in u['message'] for x in ('预算','超过','动态','数据源','赋值'))]
    for u in issues:yield '- '+safe(u['process'])+'：'+safe(u['message'])+'\n'
    yield '\nJava 重构需保留维度顺序、各写入点的坐标/条件/覆盖或累加契约、调用参数和 Rule/Feeder 边界；尚无等价运行证据，不能据此宣称迁移完成。\n'


def json_section(path,section):
    yield '{"schema":"architecture-extraction-2","items":['
    first=True
    for record in records(path,section):
        if not first:yield ','
        yield json.dumps(record,ensure_ascii=False,sort_keys=True);first=False
    yield ']}'


def package(path):
    """Disk-spooled ZIP; evidence streamed from index, never decode whole model."""
    import tempfile
    import zipfile
    import shutil
    def entry(name):
        info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;return info
    with tempfile.TemporaryFile() as out:
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
            with z.open(entry('Architecture.json'),'w',force_zip64=True) as dest,open(path,'rb') as source:
                shutil.copyfileobj(source,dest,length=65536)
            for name,chunks in [('Architecture.md',markdown(path)),('Evidence.json',json_section(path,'evidence')),('Diagnostics.json',json_section(path,'diagnostics'))]:
                with z.open(entry(name),'w',force_zip64=True) as f:
                    for chunk in chunks:f.write(chunk.encode('utf-8'))
        out.seek(0)
        while chunk:=out.read(65536):yield chunk
