"""Evidence-backed presentation of an existing bounded workflow, not an execution engine."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from tm1_insight import workflow
from tm1_insight.learning.syntax import statements, calls, expression, SECTIONS as TI_SECTIONS
from tm1_insight.learning.understanding import analyze, structure
from tm1_insight.ingest.hard_extract import LOG_REGION_START, LOG_REGION_END, LOG_REGION_FINAL_START, LOG_REGION_FINAL_END
from tm1_insight.store import dimensions as dimension_store
from tm1_insight.learning.rule_semantics import parse_rule_semantics

VERSION='architecture-1'
REVISION=14
SECTIONS={'cubes','dimensions','processes','rules','chores','execution_relationships','data_relationships',
          'transformation_steps','evidence','unresolved_dependencies','transformation_summaries','dimension_comparisons','module_objects','downstream_consumers','diagnostics','formation_relationships','write_explanations','external_sources',
          'relation_objects','unified_relations','relation_evidence','business_steps','rule_summaries'}
OPERATIONS={
    'viewzeroout':'CLEAR','cubecleardata':'CLEAR',
    'viewcreate':'VIEW_PREPARATION','viewsubsetassign':'VIEW_PREPARATION',
    'viewextractskipzeroesset':'VIEW_PREPARATION','viewextractskipcalcsset':'VIEW_PREPARATION',
    'viewextractskiprulevaluesset':'VIEW_PREPARATION','viewtitleelementset':'VIEW_PREPARATION',
    'subsetcreate':'SUBSET_PREPARATION','subsetcreatebymdx':'SUBSET_PREPARATION','subsetelementinsert':'SUBSET_PREPARATION',
    'viewdestroy':'CLEANUP','subsetdestroy':'CLEANUP',
    'dimensionelementinsert':'DIMENSION_MAINTENANCE','dimensionelementcomponentadd':'DIMENSION_MAINTENANCE',
    'cellputn':'DATA_TRANSFORMATION','cellputs':'DATA_TRANSFORMATION','cellincrementn':'DATA_TRANSFORMATION',
    'asciioutput':'OTHER','textoutput':'OTHER','logoutput':'LOGGING',
    'cellgetn':'OTHER','cellgets':'OTHER',
}
LABELS={'CLEAR':'清理数据','VIEW_PREPARATION':'准备视图与筛选','SUBSET_PREPARATION':'准备成员子集',
        'COPY':'复制','TRANSFER':'传输','DATA_TRANSFORMATION':'写入或计算','DIMENSION_MAINTENANCE':'维护维度',
        'LOGGING':'技术输出','CLEANUP':'清理临时对象','OTHER':'其他实现'}


def technical(name):
    # TM1 system namespace is a UI grouping convention, never a business-purpose inference.
    return bool(name and name.startswith('}'))


def literal(tokens):
    if len(tokens)!=1 or tokens[0]['kind']!='string':return None
    raw=tokens[0]['value'];return raw[1:-1].replace(raw[0]*2,raw[0])


def _rule_semantics(code, cube, dimensions, cube_catalog):
    """解析一段 Rule 源码为语义 IR；解析失败时返回空结构并保留未知标记。

    纯本地解析，不连接服务器；无法证明的部分由 rule_semantics 层标记 UNKNOWN。
    """
    try:
        return parse_rule_semantics(code, cube, dimensions, cube_catalog)
    except Exception:
        # 解析器对未知语法必须降级为空结构，而不是中断整个架构构建。
        return {"rules": [], "feeders": [], "directives": [], "unknowns": [
            {"reason": "Rule 语义解析器异常，源码未结构化；请核对源码。", "cube": cube}]}


def log_lines(parts):
    found=set()
    for section,code in zip(TI_SECTIONS,parts):
        inside=False;pending=set()
        for line,text in enumerate(code.splitlines(),1):
            if LOG_REGION_START.search(text) or LOG_REGION_FINAL_START.search(text):inside=True;pending=set()
            if inside:pending.add((section,line))
            if LOG_REGION_END.search(text) or LOG_REGION_FINAL_END.search(text):
                if inside:found.update(pending)
                inside=False;pending=set()
    return found


def build(con,entry,*,progress=None,max_processes=100,max_depth=16,cache_root=None,cache_source=None, max_nodes=1000, allowed_relationship_types=None, include_downstream=False, include_technical_details=False, entry_kind='process'):
    """Reuse workflow truth; assemble only its local model neighborhood."""
    def update(stage,index=5,current=0,total=None):
        if progress:progress(stage=stage,stage_index=index,stages_total=6,current=current,total=total)
    from tm1_insight.architecture_extraction import Boundary, datasource, enrich
    policy=Boundary(entry,max_nodes,allowed_relationship_types,include_downstream,include_technical_details)
    if entry_kind not in {'process','cube'}:raise ValueError('Unsupported entry kind')
    roots=None;discovery=[];truncated_producers=False
    if entry_kind=='cube':
        if not con.execute('SELECT name FROM cubes WHERE name=?',[entry]).fetchone():raise KeyError(entry)
        discovery=[r[0] for r in con.execute('SELECT DISTINCT process_name FROM process_writes_cube WHERE cube_name=? ORDER BY process_name LIMIT 501',[entry]).fetchall()]
        count=min(max_processes,max(0,max_nodes-1))
        truncated_producers=len(discovery)>count
        existing={r[0] for r in con.execute('SELECT name FROM processes').fetchall()}
        roots=[n for n in discovery if n in existing][:count]
    wf=workflow.build(con,entry,progress=progress,max_processes=min(max_processes,max_nodes),max_depth=max_depth,
                      cache_root=cache_root,cache_source=cache_source,expand_calls=policy.expand,roots=roots,accept_root=(lambda r:any(w['cube']==entry for w in r['writes'])) if entry_kind=='cube' else None)
    policy.entry_processes=wf['accepted_roots'] if entry_kind=='cube' else [entry]
    core_process_names=policy.core_processes(wf)
    result=dict(version=VERSION,engine_revision=REVISION,module=dict(name=entry,kind=entry_kind+'_scope',business_meaning_confirmed=False),
        entry_points=[dict(kind=entry_kind,name=entry)]+([dict(kind='producer',name=n,target=entry) for n in wf['accepted_roots']] if entry_kind=='cube' else []),input_outputs={},migration_notes=[
            '维度顺序定义多维坐标粒度，不自动假定一个 Cube 对应一张关系表。',
            '需验证层级权重、汇总、Rule/Feeder、稀疏、零值/空值、清理切面、覆盖/累加与运行顺序。',
            '静态表达式依赖不是运行时贡献；本结果未执行 TM1，也未验证迁移等价。'],
        boundary=dict(max_processes=max_processes,max_depth=max_depth,complete=False,
            note='仅覆盖已解析的静态调用范围；动态调用、运行路径、外部数据与未采集关系仍需核对。'),
        cycles=wf['cycles'],runtime_verified=False,details=wf['details'],**{s:[] for s in SECTIONS})
    evidence=result['evidence'];unresolved=result['unresolved_dependencies'];proof_ids={}
    def proof(process,location,**extra):
        if len(evidence)>=30000:raise ValueError('架构证据超过 30000 条预算，请缩小分析范围。')
        payload=dict(process=process,**location,**extra)
        if payload.get('section') and 'source_hash' not in payload:
            payload['source_hash']=result['details'].get(process,{}).get('source_hash')
        stable=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
        if stable in proof_ids:return proof_ids[stable]
        record=dict(id=f'e{len(evidence)+1}',stable_id=stable,**payload)
        evidence.append(record);proof_ids[stable]=record['id'];return record['id']
    def missing(message,process=entry,**extra):
        unresolved.append(dict(process=process,message=message,**extra))
    if truncated_producers:missing('生产者候选超过 TI / 节点预算；请扩大范围后重新验证。', omitted=len(discovery)-len(roots))
    result['producer_discovery']=[dict(process=n,status='SOURCE_CONFIRMED' if n in wf['accepted_roots'] else 'UNVERIFIED_CANDIDATE',target=entry) for n in discovery]
    if entry_kind=='cube':
        for n in discovery:
            if n not in existing:missing('Cube 写入索引引用的 TI 源码缺失，不能验证生产者。',n)
    catalogs={k:{r[0] for r in con.execute('SELECT name FROM '+t).fetchall()} for k,t in
              [('cube','cubes'),('dimension','dimensions'),('process','processes')]}
    native={};raw_calls={};logs={};sources={};cube_refs=({entry:[(entry,dict(operation='ENTRY_CUBE',target=entry),False)]} if entry_kind=='cube' else {});source_chars=0
    for i,p in enumerate(wf['processes']):
        name=p['process'];update('组装数据加工步骤',current=i,total=len(wf['processes']))
        if not p['source_hash']:missing('该过程超过分析预算，未解析实现。',name);continue
        row=con.execute('SELECT prolog,metadata,data,epilog FROM processes WHERE name=?',[name]).fetchone()
        parts=tuple(v or '' for v in row);source_chars+=sum(map(len,parts));logs[name]=log_lines(parts)
        report=wf['details'][name]
        observed=analyze(parts,catalogs,report['parameter_names'],include_logging=True)
        assigned={t[0]['value'].casefold() for t in statements(parts,include_logging=True)
                  if len(t)>2 and t[0]['kind']=='id' and t[1]['value']=='='}
        refs={(r['section'],r['line'],r['column']):r for r in observed['references']}
        native[name]=[];raw_calls[name]={}
        for tokens in statements(parts,include_logging=True):
            for token,args in calls(tokens):
                pos={k:token[k] for k in ['section','line','column']};op=token['value'].casefold()
                raw_calls[name][(token['section'],token['line'],token['column'])]=args
                ref=refs.get((token['section'],token['line'],token['column']),{})
                if ref.get('kind')=='cube' and ref.get('target'):
                    cube_refs.setdefault(ref['target'],[]).append((name,ref,(token['section'],token['line']) in logs[name]))
                if op not in OPERATIONS:continue
                kind='LOGGING' if (token['section'],token['line']) in logs[name] else OPERATIONS[op]
                native[name].append(dict(category=kind,label='读取数据' if op in {'cellgetn','cellgets'} and kind!='LOGGING' else '外部文本输出（用途待核对）' if op in {'asciioutput','textoutput'} and kind!='LOGGING' else LABELS[kind],operation=token['value'],target=ref.get('target'),
                    target_parameter=ref['expression'] if ref.get('status')=='parameter' and ref['expression'].casefold() not in assigned else None,
                    arguments=[expression(a)[:300] for a in args],conditions=ref.get('control_context',[]),
                    evidence=[proof(name,pos,operation=token['value'],source_hash=p['source_hash'])]))
        binding=datasource(parts,catalogs['cube'])
        recorded_binding=report.get('data_row_lineage',{}).get('source_view_binding')
        if not binding and recorded_binding:
            binding=dict(cube=recorded_binding['cube'],view=recorded_binding['view'],status=recorded_binding['status'],locations=[])
        if binding and binding.get('external_type'):
            ids=[proof(name,loc,kind='external_datasource_type') for loc in binding.pop('locations')]
            result['external_sources'].append(dict(process=name,**binding,evidence=ids))
        elif binding:
            ids=[proof(name,loc,kind='view_datasource_binding') for loc in binding.pop('locations')]
            if not ids and recorded_binding:
                ids=[proof(name,{k:v for k,v in recorded_binding['metadata_evidence'].items() if k!='process'},kind='view_datasource_metadata')]
            sources[name]=dict(**binding,evidence=ids)
            cube_refs.setdefault(binding['cube'],[]).append((name,dict(operation='VIEW_DATASOURCE',target=binding['cube']),False))
        elif any(t[0]['value'].casefold()=='datasourcenameforserver' for t in statements(parts,include_logging=True)):
            missing('视图来源赋值存在多定义、条件赋值或动态表达式；请核对 DataSourceNameForServer 及其变量定义。',name)
    for edge in wf['execution']:
        eid=proof(edge['process'],{k:edge[k] for k in ['section','line','column']},kind='source_invocation',source_hash=edge['source_hash'])
        result['execution_relationships'].append(dict(process=edge['process'],target=edge['target'],kind='source_invocation',
            technical=technical(edge['target']) or (technical(edge['process']) and edge['process']!=entry),parameters=edge['bindings'],conditions=edge['control_context'],evidence=[eid],runtime_verified=False))
        if not edge['target']:missing('有一个调用目标由运行时表达式决定。',edge['process'],evidence=[eid])
    for p in wf['processes']:
        name=p['process'];effects=list(native.get(name,[]));helpers=[]
        for edge in wf['execution']:
            if edge['process']!=name or not technical(edge['target']):continue
            helper=dict(name=edge['target'],parameters=edge['bindings'],effects=[],conditions=edge['control_context'])
            args=raw_calls.get(name,{}).get((edge['section'],edge['line'],edge['column']),[])
            actual={literal(args[i]):literal(args[i+1]) for i in range(1,len(args)-1,2)}
            for effect in native.get(edge['target'],[]):
                mapped=dict(effect)
                if not mapped['target'] and mapped['target_parameter']:
                    declared=next((b['parameter'] for b in edge['bindings'] if b['parameter'] and
                        b['parameter'].casefold()==mapped['target_parameter'].casefold() and b['binding_status']=='EXPLICIT_NAME_BINDING'),None)
                    value=next((v for k,v in actual.items() if k and declared and k.casefold()==declared.casefold()),None)
                    allowed=catalogs['dimension'] if mapped['category'] in {'SUBSET_PREPARATION','DIMENSION_MAINTENANCE'} else catalogs['cube']
                    mapped['target']=value if value in allowed else None
                mapped['via']=edge['target'];mapped['conditions']=edge['control_context']+mapped['conditions']
                mapped['evidence']=mapped['evidence']+[proof(name,{k:edge[k] for k in ['section','line','column']},kind='helper_binding')]
                helper['effects'].append(mapped)
                if mapped['target'] in catalogs['cube']:
                    cube_refs.setdefault(mapped['target'],[]).append((name,dict(operation=mapped['operation'],target=mapped['target']),mapped['category']=='LOGGING'))
                    role='read' if mapped['operation'].casefold() in {'cellgetn','cellgets'} else 'write' if mapped['operation'].casefold() in {'cellputn','cellputs','cellincrementn'} else 'reference'
                    result['data_relationships'].append(dict(process=name,target=mapped['target'],kind='bound_helper_reference',role=role,
                        technical=technical(mapped['target']) or mapped['category']=='LOGGING',evidence=mapped['evidence'],via=edge['target']))
            helpers.append(helper);effects.extend(helper['effects'])
        refs=[d for d in wf['data'] if d['process']==name and d['relation_kind']=='source_reference' and d['target']]
        def visible(d):return not technical(d['target']) and (d['section'],d['line']) not in logs.get(name,set())
        inputs=sorted({d['target'] for d in refs if d['role']=='read' and visible(d)}|({sources[name]['cube']} if name in sources else set()))
        outputs=sorted({d['target'] for d in refs if d['role']=='write' and visible(d)})
        inputs=sorted(set(inputs)|{e['target'] for e in effects if e['target'] and not technical(e['target']) and e['category']!='LOGGING' and e['operation'].casefold() in {'cellgetn','cellgets'}})
        outputs=sorted(set(outputs)|{e['target'] for e in effects if e['target'] and not technical(e['target']) and e['category']!='LOGGING' and e['operation'].casefold() in {'cellputn','cellputs','cellincrementn'}})
        calcs=[c for c in wf['calculation'] if c['process']==name and not technical(c['cube']) and
               (c['evidence']['section'],c['evidence']['line']) not in logs.get(name,set())]
        expressions=[dict(expression=c['reconstructed'],evidence=[proof(name,c['evidence'],kind='calculation')],
                          coordinate_mapping=c['coordinate_mapping']) for c in calcs if c['status']=='STATIC_EXPRESSION' and 'UNKNOWN' not in c['reconstructed']]
        step=dict(process=name,title=name,inputs=inputs,outputs=outputs,technical=technical(name),
            business_calls=[e['target'] for e in wf['execution'] if e['process']==name and e['target'] and not technical(e['target'])],
            source_binding=sources.get(name),effects=effects,technical_calls=helpers,calculations=expressions,
            calculation_note='存在尚未完整还原的写入表达式，可在实现中核对。' if len(expressions)<len(calcs) else '',
            stages=['源数据观察','准备与筛选','加载或计算','结果写入'],
            note='阶段用于组织源码事实，不代表已经验证了运行时顺序或输入对输出的贡献。')
        result['transformation_steps'].append(step)
        result['processes'].append(dict(process=name,technical=technical(name),inputs=inputs,outputs=outputs,
            parameters=wf['details'][name].get('parameter_names',[]),source_hash=p['source_hash']))
    for d in wf['data']:
        if d['relation_kind']=='static_value_dependency':
            ids=[proof(d['process'],d[k],kind=k) for k in ['read_evidence','write_evidence']]
            if d.get('row_use_evidence'):ids.append(proof(d['process'],d['row_use_evidence'],kind='row_value_use'))
            result['data_relationships'].append(dict(process=d['process'],source=d['source_cube'],target=d['target'],
                kind='static_value_dependency',status=d['status'],evidence=ids,runtime_verified=False))
        elif d['target']:
            result['data_relationships'].append(dict(process=d['process'],target=d['target'],kind='read_write_reference',role=d['role'],
                technical=technical(d['target']) or (d['section'],d['line']) in logs.get(d['process'],set()),conditions=d.get('control_context',[]),
                evidence=[proof(d['process'],{k:d[k] for k in ['section','line','column']},operation=d['operation'])]))
    for name,binding in sources.items():result['data_relationships'].append(dict(process=name,target=binding['cube'],kind='view_datasource_binding',role='read',technical=False,evidence=binding['evidence']))
    names=sorted(cube_refs, key=lambda n:(n!=entry,technical(n) or all(log for _,_,log in cube_refs[n]),n))
    available=max(0,max_nodes-len(wf['processes']))
    if len(names)>available:missing('max_nodes 节点预算不足；部分 Cube 结构未展开，原始关系仍保留。', omitted=len(names)-available)
    names=names[:available] if 'read_write' in policy.allowed else []
    if len(names)>150:missing('关联 Cube 超过 150 个，数据模型仅组装前 150 个。')
    dim_names=set()
    for i,name in enumerate(names[:150]):
        update('加载局部 Cube 结构',current=i,total=min(150,len(names)))
        row=con.execute('SELECT dimension_count,has_rules,length(coalesce(rules,'')) FROM cubes WHERE name=?',[name]).fetchone()
        dims=[dict(name=d,order=o,element_count=count) for d,o,count in con.execute('SELECT r.dimension_name,r.dim_order,d.element_count FROM cube_has_dimension r LEFT JOIN dimensions d ON d.name=r.dimension_name WHERE r.cube_name=? ORDER BY r.dim_order,r.dimension_name LIMIT 257',[name]).fetchall()]
        complete=bool(row and row[0]==len(dims) and len(dims)<=256 and len({d['name'] for d in dims})==len(dims) and all(d['order']==j for j,d in enumerate(dims)))
        dim_names.update(d['name'] for d in dims[:256])
        refs=cube_refs[name];is_tech=technical(name) or all(log for _,_,log in refs)
        reads=sorted({p for p,r,_ in refs if r['operation'].casefold() in {'cellgetn','cellgets','view_datasource'}})
        writes=sorted({p for p,r,_ in refs if r['operation'].casefold() in {'cellputn','cellputs','cellincrementn'}})
        result['cubes'].append(dict(process=name,name=name,dimensions=dims[:256],complete_order=complete,technical=is_tech,
            roles=[role for role,values in [('input',reads),('output',writes)] if values],readers=reads,writers=writes,
            has_rules=bool(row and row[1]),rule_source_available=bool(row and row[2]),grain='离线维度顺序定义的多维单元格坐标' if complete else '维度顺序尚未完整采集',
            upstream=sorted({d['source'] for d in result['data_relationships'] if d['kind']=='static_value_dependency' and d['target']==name}),
            downstream=sorted({d['target'] for d in result['data_relationships'] if d['kind']=='static_value_dependency' and d['source']==name and d['target']}),
            evidence=[proof(name,dict(table='cube_has_dimension',cube=name),kind='structure')]))
    dimension_budget=min(600,max(0,max_nodes-len(wf['processes'])-len(result['cubes']))) if 'structure' in policy.allowed else 0
    target_dims={d['name'] for c in result['cubes'] if c['name']==entry or (not c['technical'] and any(p in core_process_names for p in c['writers'])) for d in c['dimensions']}
    has_hierarchy_table=bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='dimension_metadata'").fetchone()[0])
    for name in sorted(dim_names)[:dimension_budget]:
        update('核对局部维度元数据')
        meta=dimension_store.metadata(con,name)
        hierarchies=[];hierarchy_count=None
        if has_hierarchy_table:
            hierarchy_count=con.execute('SELECT json_array_length(try_cast(hierarchy_names AS JSON)) FROM dimension_metadata WHERE name=?',[name]).fetchone()
            hierarchy_count=hierarchy_count[0] if hierarchy_count else None
            hierarchies=[r[0] for r in con.execute("SELECT json_extract_string(e.value,'$') FROM json_each((SELECT CASE WHEN json_type(try_cast(hierarchy_names AS JSON))='ARRAY' THEN hierarchy_names ELSE '[]' END FROM dimension_metadata WHERE name=?)) e LIMIT 50",[name]).fetchall()]
        result['dimensions'].append(dict(process=name,name=name,metadata=meta,hierarchies=hierarchies,hierarchy_count=hierarchy_count,
            consolidation_sample=dimension_store.records(con,name,'edges',page=1) if name in target_dims and meta and meta['fields']['edges']['status']=='recorded' else None,
            note='层级名仅展示已采集记录（前 50 项）；属性值与指标维角色不推断。成员、直接汇总及权重按需分页。',
            evidence=[proof(name,dict(table='dimensions',name=name),kind='metadata')]))
    if 'structure' in policy.allowed and len(dim_names)>dimension_budget:missing('节点或维度预算不足，其余维度结构未展开。', omitted=len(dim_names)-dimension_budget)
    # Find candidate Rule owners through the existing index; verify actual DB calls.
    selected=[c['name'] for c in result['cubes'] if not c['technical'] and (c['name']==entry or any(p in core_process_names for p in c['readers']+c['writers']))]
    candidates=set(selected) if 'rule_reference' in policy.allowed else set()
    if selected and 'rule_reference' in policy.allowed:
        slots=','.join('?' for _ in selected)
        rows=con.execute(f'SELECT DISTINCT cube_name,source_cube FROM rule_references_cube WHERE source_cube IN ({slots}) ORDER BY cube_name,source_cube LIMIT 1001',selected).fetchall()
        for owner,target in rows[:1000]:
            if owner in selected:continue
            result['downstream_consumers'].append(dict(process=owner,cube=owner,target=target,module_role='EXTERNAL_DEPENDENCY',
                status='INDEX_CANDIDATE',evidence=[proof(owner,dict(table='rule_references_cube',cube=owner,target=target),kind='downstream_index')]))
            if include_downstream:candidates.add(owner)
        if len(rows)>1000:missing('下游索引候选超过 1000 条；未自动纳入核心模块。')
    rule_chars=0
    if len(candidates)>150:missing('关联 Rule 所属 Cube 超过 150 个，仅核对前 150 个。')
    external_rule_nodes=0
    for owner in sorted(candidates)[:150]:
        if owner not in selected:
            if len(result['processes'])+len(result['cubes'])+len(result['dimensions'])+external_rule_nodes>=max_nodes:
                missing('max_nodes 预算不足；外部 Rule 消费者源码未展开。',owner);continue
            external_rule_nodes+=1
        update('核对局部 Rule 与调度')
        row=con.execute('SELECT length(rules) FROM cubes WHERE name=?',[owner]).fetchone()
        if not row or not row[0]:continue
        if row[0]>250000 or rule_chars+row[0]>5000000:missing('规则文本超过单对象或全范围预算，未解析。',owner);continue
        rule_chars+=row[0]
        code=con.execute('SELECT rules FROM cubes WHERE name=?',[owner]).fetchone()[0]
        digest=hashlib.sha256(code.encode()).hexdigest();references=[]
        for tokens in statements((code,'','',''),include_logging=True):
            feeder=any(a['value']=='=' and b['value']=='>' for a,b in zip(tokens,tokens[1:]))
            for token,args in calls(tokens):
                if token['value'].casefold()!='db':continue
                target=literal(args[0]) if args else None
                if target not in catalogs['cube']:
                    unknown_id=proof(owner,dict(section='rule',line=token['line'],column=token['column']),source_hash=digest,kind='unresolved_rule_reference')
                    missing('规则中的动态或缺失 Cube 引用尚未确认。',owner,evidence=[unknown_id]);continue
                eid=proof(owner,dict(section='rule',line=token['line'],column=token['column']),source_hash=digest,kind='feeder_reference' if feeder else 'rule_read')
                references.append(dict(target=target,kind='feeder_reference' if feeder else 'rule_read',evidence=[eid]))
        if owner in selected or any(r['target'] in selected for r in references):
            rule_entry=dict(process=owner,cube=owner,references=references,source_hash=digest,module_role='CORE' if owner in selected else 'EXTERNAL_DEPENDENCY',
                note='已解析 Rule/Feeder 计算语义（目标区域、表达式、跨 Cube 引用、条件与属性查询），未执行规则、未验证稀疏计算结果。')
            # Rule / Feeder 语义 IR：把可解析源码结构化，供 Cube 进入后读懂计算逻辑。
            owner_dims=[r[0] for r in con.execute('SELECT dimension_name FROM cube_has_dimension WHERE cube_name=? ORDER BY dim_order,dimension_name',[owner]).fetchall()]
            semantics=_rule_semantics(code,owner,owner_dims,catalogs['cube'])
            rule_entry['rule_semantics']=semantics['rules']
            rule_entry['feeder_semantics']=semantics['feeders']
            rule_entry['rule_directives']=semantics['directives']
            rule_entry['rule_unknowns']=semantics['unknowns']
            result['rules'].append(rule_entry)
    process_names=[p['process'] for p in wf['processes'] if p['process'] in core_process_names and 'schedule' in policy.allowed]
    if process_names:
        slots=','.join('?' for _ in process_names)
        rows=con.execute(f'SELECT chore_name,process_name,step_order FROM chore_runs_process WHERE process_name IN ({slots}) ORDER BY chore_name,step_order,process_name LIMIT 501',process_names).fetchall()
        for chore,name,order in rows[:500]:
            result['chores'].append(dict(process=chore,name=chore,target=name,step_order=order,kind='recorded_schedule',
                evidence=[proof(chore,dict(table='chore_runs_process',chore=chore,step_order=order,target=name),kind='schedule')],
                note='离线调度定义，不证明已启用或实际执行。'))
        if len(rows)>500:missing('调度关系超过 500 条，仅组装前 500 条。')
    # Caller index is only a candidate source. Verify a bounded set in actual code.
    verified_callers=[];caller_chars=0
    from tm1_insight.store.calculation import inspect
    for candidate in wf['callers'][:20]:
        if len(result['processes'])+len(result['cubes'])+len(result['dimensions'])+len(verified_callers)+external_rule_nodes>=max_nodes:
            missing('max_nodes 预算不足；入口调用方候选源码未展开。');break
        caller=candidate['process'];update('核对入口调用方源码')
        count=con.execute("SELECT length(coalesce(prolog,''))+length(coalesce(metadata,''))+length(coalesce(data,''))+length(coalesce(epilog,'')) FROM processes WHERE name=?",[caller]).fetchone()
        if not count or count[0]>250000 or caller_chars+count[0]>1000000:
            missing('调用方目录候选超过源码预算或源码缺失，尚未验证。',caller);continue
        caller_chars+=count[0];report=inspect(con,caller,catalogs=catalogs)
        target_entry=candidate['target']
        actual=[c for c in report['calls'] if c['target']==target_entry]
        if not actual:missing('调用方目录候选未匹配到可确认的源码调用。',caller);continue
        result['details'][caller]=report;verified_callers.append(caller)
        for call in actual:
            ids=[proof(caller,{k:call[k] for k in ['section','line','column']},source_hash=report['source_hash'],kind='verified_caller')]
            result['execution_relationships'].append(dict(process=caller,target=target_entry,kind='source_invocation',technical=technical(caller),parameters=workflow.bindings(call,wf['details'].get(target_entry)),conditions=call['control_context'],evidence=ids,runtime_verified=False))
        result['entry_points'].append(dict(kind='caller',name=caller,target=target_entry,scope='only_call_to_entry_verified'))
    if len(wf['callers'])>20:missing('调用方目录超过 20 个，其余尚未读取源码。')
    if verified_callers and 'schedule' in policy.allowed:
        slots=','.join('?' for _ in verified_callers)
        for chore,name,order in con.execute(f'SELECT chore_name,process_name,step_order FROM chore_runs_process WHERE process_name IN ({slots}) ORDER BY chore_name,step_order,process_name LIMIT 100',verified_callers).fetchall():
            result['chores'].append(dict(process=chore,name=chore,target=name,step_order=order,kind='recorded_schedule',
                evidence=[proof(chore,dict(table='chore_runs_process',chore=chore,step_order=order,target=name),kind='schedule')],note='离线调度定义，未验证运行。'))
    counts=Counter((u['process'],u['reason']) for u in wf['unknowns'])
    for (name,reason),count in sorted(counts.items()):missing('有待核对的源码依赖或计算表达式。',name,count=count,diagnostic=reason)
    result['input_outputs']=dict(inputs=sorted({c for s in result['transformation_steps'] if not s['technical'] or s['process']==entry for c in s['inputs']}),
        outputs=sorted({c for s in result['transformation_steps'] if not s['technical'] or s['process']==entry for c in s['outputs']}))
    result['boundary']['static_call_scope_complete']=all(e['target'] and e['expansion']=='IN_SCOPE' for e in wf['execution']) and all(p['source_hash'] for p in wf['processes'])
    result['performance']=dict(parsed_processes=wf['summary']['parsed'],source_characters=source_chars)
    result['source_fingerprint']=cache_source or 'synthetic'
    missing('外部文件/SQL 数据源、视图实际成员、独立层级及运行结果尚未完整还原。')
    result['diagnostics']=wf['unknowns']+[dict(u) for u in unresolved]
    enrich(result,wf,policy)
    from tm1_insight.formation import enrich as explain_formation
    explain_formation(result,wf,progress)
    if entry_kind=='cube':
        from tm1_insight.formation import consumers
        consumers(con,result,entry,progress,max_nodes)
    from tm1_insight.unified_relations import enrich as unify
    unify(result, progress)
    return result


def artifact(report,root):
    import sqlite3
    from contextlib import closing
    result=workflow.artifact(report,root,sections=SECTIONS)
    try:
        with closing(sqlite3.connect(workflow.index_path(result.path))) as con:
            con.execute("CREATE INDEX formation_target ON items(section,json_extract(payload,'$.cube'),json_extract(payload,'$.technical'))")
            con.execute("CREATE INDEX unified_id ON items(section,json_extract(payload,'$.id'))")
            con.executemany("UPDATE items SET search=? WHERE section='unified_relations' AND position=?",[
                (' '.join([r['source_name'],r['target_name'],r['relation_kind'],r.get('process','')]).casefold(),i)
                for i,r in enumerate(report.get('unified_relations',[]))])
            con.commit()
        return result
    except BaseException:result.cleanup();raise


def page(path,section='transformation_steps',offset=0,limit=50,q=''):
    return workflow.page(path,section,offset,limit,q=q,sections=SECTIONS,version=VERSION)


def markdown(path):
    from tm1_insight.architecture_extraction import markdown as readable
    yield from readable(path)
    from tm1_insight.unified_relations import markdown as relationships
    yield from relationships(path)
