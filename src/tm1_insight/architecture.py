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

VERSION='architecture-1'
REVISION=2
SECTIONS={'cubes','dimensions','processes','rules','chores','execution_relationships','data_relationships',
          'transformation_steps','evidence','unresolved_dependencies'}
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


def build(con,entry,*,progress=None,max_processes=100,max_depth=16,cache_root=None,cache_source=None):
    """Reuse workflow truth; assemble only its local model neighborhood."""
    def update(stage,index=5,current=0,total=None):
        if progress:progress(stage=stage,stage_index=index,stages_total=6,current=current,total=total)
    wf=workflow.build(con,entry,progress=progress,max_processes=max_processes,max_depth=max_depth,
                      cache_root=cache_root,cache_source=cache_source)
    result=dict(version=VERSION,engine_revision=REVISION,module=dict(name=entry,kind='process_scope',business_meaning_confirmed=False),
        entry_points=[dict(kind='process',name=entry)],input_outputs={},migration_notes=[
            '维度顺序定义多维坐标粒度，不自动假定一个 Cube 对应一张关系表。',
            '需验证层级权重、汇总、Rule/Feeder、稀疏、零值/空值、清理切面、覆盖/累加与运行顺序。',
            '静态表达式依赖不是运行时贡献；本结果未执行 TM1，也未验证迁移等价。'],
        boundary=dict(max_processes=max_processes,max_depth=max_depth,complete=False,
            note='仅覆盖已解析的静态调用范围；动态调用、运行路径、外部数据与未采集关系仍需核对。'),
        cycles=wf['cycles'],runtime_verified=False,details=wf['details'],**{s:[] for s in SECTIONS})
    evidence=result['evidence'];unresolved=result['unresolved_dependencies']
    def proof(process,location,**extra):
        if len(evidence)>=30000:raise ValueError('架构证据超过 30000 条预算，请缩小分析范围。')
        record=dict(id=f'e{len(evidence)+1}',process=process,**location,**extra)
        evidence.append(record);return record['id']
    def missing(message,process=entry,**extra):
        unresolved.append(dict(process=process,message=message,**extra))
    catalogs={k:{r[0] for r in con.execute('SELECT name FROM '+t).fetchall()} for k,t in
              [('cube','cubes'),('dimension','dimensions'),('process','processes')]}
    native={};raw_calls={};logs={};sources={};cube_refs={};source_chars=0
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
        # Accept only direct literal VIEW bindings with no alternative writes or control blocks.
        roots,controls,diagnostics,_=structure(parts,include_logging=True)
        assignments=[t for t in statements(parts,include_logging=True) if len(t)>2 and t[0]['kind']=='id' and t[1]['value']=='=']
        counts=Counter(t[0]['value'].casefold() for t in assignments)
        bindings={t[0]['value'].casefold():(literal([x for x in t[2:] if x['value']!=';']),t[0])
                  for t in assignments if t[0]['section']=='prolog' and counts[t[0]['value'].casefold()]==1}
        dtype=bindings.get('datasourcetype',(None,None))[0];src,tok=bindings.get('datasourcenameforserver',(None,None))
        if not controls and not diagnostics and dtype and dtype.casefold()=='view' and src in catalogs['cube']:
            sources[name]=dict(cube=src,evidence=[proof(name,{k:tok[k] for k in ['section','line','column']},kind='view_datasource_binding')])
            cube_refs.setdefault(src,[]).append((name,dict(operation='VIEW_DATASOURCE',target=src,section='prolog',line=tok['line'],column=tok['column']),False))
        elif 'datasourcenameforserver' in bindings:missing('视图数据源绑定含动态表达式或控制路径，尚未确认来源。',name)
    for edge in wf['execution']:
        eid=proof(edge['process'],{k:edge[k] for k in ['section','line','column']},kind='source_invocation',source_hash=edge['source_hash'])
        result['execution_relationships'].append(dict(process=edge['process'],target=edge['target'],kind='source_invocation',
            technical=technical(edge['target']),parameters=edge['bindings'],conditions=edge['control_context'],evidence=[eid],runtime_verified=False))
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
            result['data_relationships'].append(dict(process=d['process'],source=d['source_cube'],target=d['target'],
                kind='static_value_dependency',status=d['status'],evidence=ids,runtime_verified=False))
        elif d['target']:
            result['data_relationships'].append(dict(process=d['process'],target=d['target'],kind='read_write_reference',role=d['role'],
                technical=technical(d['target']) or (d['section'],d['line']) in logs.get(d['process'],set()),
                evidence=[proof(d['process'],{k:d[k] for k in ['section','line','column']},operation=d['operation'])]))
    for name,binding in sources.items():result['data_relationships'].append(dict(process=name,target=binding['cube'],kind='view_datasource_binding',role='read',technical=False,evidence=binding['evidence']))
    names=sorted(cube_refs)
    if len(names)>150:missing('关联 Cube 超过 150 个，数据模型仅组装前 150 个。')
    dim_names=set()
    for i,name in enumerate(names[:150]):
        update('加载局部 Cube 结构',current=i,total=min(150,len(names)))
        row=con.execute('SELECT dimension_count,has_rules FROM cubes WHERE name=?',[name]).fetchone()
        dims=[dict(name=d,order=o,element_count=count) for d,o,count in con.execute('SELECT r.dimension_name,r.dim_order,d.element_count FROM cube_has_dimension r LEFT JOIN dimensions d ON d.name=r.dimension_name WHERE r.cube_name=? ORDER BY r.dim_order,r.dimension_name LIMIT 257',[name]).fetchall()]
        complete=bool(row and row[0]==len(dims) and len(dims)<=256 and len({d['name'] for d in dims})==len(dims) and all(d['order']==j for j,d in enumerate(dims)))
        dim_names.update(d['name'] for d in dims[:256])
        refs=cube_refs[name];is_tech=technical(name) or all(log for _,_,log in refs)
        reads=sorted({p for p,r,_ in refs if r['operation'].casefold() in {'cellgetn','cellgets','view_datasource'}})
        writes=sorted({p for p,r,_ in refs if r['operation'].casefold() in {'cellputn','cellputs','cellincrementn'}})
        result['cubes'].append(dict(process=name,name=name,dimensions=dims[:256],complete_order=complete,technical=is_tech,
            roles=[role for role,values in [('input',reads),('output',writes)] if values],readers=reads,writers=writes,
            has_rules=bool(row and row[1]),grain='离线维度顺序定义的多维单元格坐标' if complete else '维度顺序尚未完整采集',
            upstream=sorted({d['source'] for d in result['data_relationships'] if d['kind']=='static_value_dependency' and d['target']==name}),
            downstream=sorted({d['target'] for d in result['data_relationships'] if d['kind']=='static_value_dependency' and d['source']==name and d['target']}),
            evidence=[proof(name,dict(table='cube_has_dimension',cube=name),kind='structure')]))
    for name in sorted(dim_names)[:600]:
        update('核对局部维度元数据')
        meta=dimension_store.metadata(con,name)
        result['dimensions'].append(dict(process=name,name=name,metadata=meta,hierarchies=[],
            note='独立 Hierarchy 名称、属性值与指标维角色尚未确认；按需打开维度页查看成员、属性定义和权重。',
            evidence=[proof(name,dict(table='dimensions',name=name),kind='metadata')]))
    if len(dim_names)>600:missing('关联维度超过 600 个，其余需按需查看。')
    # Find candidate Rule owners through the existing index; verify actual DB calls.
    selected=names[:150];candidates=set(selected)
    if selected:
        slots=','.join('?' for _ in selected)
        candidates.update(r[0] for r in con.execute(f'SELECT DISTINCT cube_name FROM rule_references_cube WHERE source_cube IN ({slots}) ORDER BY cube_name LIMIT 101',selected).fetchall())
    rule_chars=0
    if len(candidates)>150:missing('关联 Rule 所属 Cube 超过 150 个，仅核对前 150 个。')
    for owner in sorted(candidates)[:150]:
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
                if target not in catalogs['cube']:missing('规则中的动态或缺失 Cube 引用尚未确认。',owner);continue
                eid=proof(owner,dict(section='rule',line=token['line'],column=token['column']),source_hash=digest,kind='feeder_reference' if feeder else 'rule_read')
                references.append(dict(target=target,kind='feeder_reference' if feeder else 'rule_read',evidence=[eid]))
        if owner in selected or any(r['target'] in selected for r in references):
            result['rules'].append(dict(process=owner,cube=owner,references=references,source_hash=digest,
                note='仅确认源码 DB 引用和 Feeder 语句归属，未还原完整规则计算或汇总语义。'))
    process_names=[p['process'] for p in wf['processes']]
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
        caller=candidate['process'];update('核对入口调用方源码')
        count=con.execute("SELECT length(coalesce(prolog,''))+length(coalesce(metadata,''))+length(coalesce(data,''))+length(coalesce(epilog,'')) FROM processes WHERE name=?",[caller]).fetchone()
        if not count or count[0]>250000 or caller_chars+count[0]>1000000:
            missing('调用方目录候选超过源码预算或源码缺失，尚未验证。',caller);continue
        caller_chars+=count[0];report=inspect(con,caller,catalogs=catalogs)
        actual=[c for c in report['calls'] if c['target']==entry]
        if not actual:missing('调用方目录候选未匹配到可确认的源码调用。',caller);continue
        result['details'][caller]=report;verified_callers.append(caller)
        for call in actual:
            ids=[proof(caller,{k:call[k] for k in ['section','line','column']},source_hash=report['source_hash'],kind='verified_caller')]
            result['execution_relationships'].append(dict(process=caller,target=entry,kind='source_invocation',technical=technical(caller),parameters=[],conditions=call['control_context'],evidence=ids,runtime_verified=False))
        result['entry_points'].append(dict(kind='caller',name=caller,target=entry,scope='only_call_to_entry_verified'))
    if len(wf['callers'])>20:missing('调用方目录超过 20 个，其余尚未读取源码。')
    if verified_callers:
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
    return result


def artifact(report,root):return workflow.artifact(report,root,sections=SECTIONS)


def page(path,section='transformation_steps',offset=0,limit=50,q=''):
    return workflow.page(path,section,offset,limit,q=q,sections=SECTIONS,version=VERSION)


def markdown(path):
    from html import escape
    def safe(v):return escape(str(v)).replace('\n',' ').replace('`','\\`')
    header,_,_=page(path)
    yield '# 系统架构说明\n\nSchema: '+VERSION+'\n\n入口：'+safe(header['module']['name'])+'\n\n'
    yield '本资料为静态模型与源码事实，未验证实际执行或迁移等价。\n\n'
    for section,title in [('cubes','数据模型'),('transformation_steps','数据加工步骤'),('execution_relationships','调用关系'),
                          ('rules','Rule / Feeder'),('chores','调度定义'),('dimensions','技术附录：维度元数据'),
                          ('data_relationships','技术附录：分类关系'),('evidence','技术附录：源码与模型证据'),('unresolved_dependencies','待核对依赖')]:
        yield '## '+title+'\n\n';offset=0
        while True:
            _,total,items=page(path,section,offset,50)
            for item in items:
                if section=='cubes':
                    yield '- '+safe(item['name'])+('（技术辅助对象）' if item['technical'] else '')+'：'+safe(' → '.join(d['name'] for d in item['dimensions']))+'\n'
                    yield '  - '+safe(item['grain'])+'；结构顺序'+('完整' if item['complete_order'] else '待核对')+'。\n'
                elif section=='transformation_steps':
                    if item['technical'] and item['process']!=header['module']['name']:continue
                    yield '### '+safe(item['process'])+'\n\n'
                    yield safe(', '.join(item['inputs']) or '来源尚未确认')+' → 准备 / 处理 → '+safe(', '.join(item['outputs']) or '结果写入尚未确认')+'\n\n'
                    yield '输入/输出是源码观察，不据此证明所有输入均参与输出计算。\n\n'
                    for e in item['effects']:yield '- '+safe(e['label'])+'：'+safe(e['target'] or '目标待核对')+'；证据 '+safe(', '.join(e['evidence']))+'\n'
                    for c in item['calculations']:yield '- 表达式：'+safe(c['expression'])+'；证据 '+safe(', '.join(c['evidence']))+'\n'
                    if item['calculation_note']:yield '- '+safe(item['calculation_note'])+'\n'
                elif section=='execution_relationships':
                    if item['technical']:continue
                    yield '- '+safe(item['process'])+' → '+safe(item['target'] or '目标待核对')+'；证据 '+safe(', '.join(item['evidence']))+'\n'
                    for b in item['parameters']:yield '  - '+safe(b['parameter'] or '参数名待核对')+' ← '+safe(b['expression'])+'\n'
                elif section=='rules':
                    yield '- '+safe(item['cube'])+'：'+safe(item['note'])+'\n'
                    for r in item['references']:yield '  - '+safe(r['kind'])+' → '+safe(r['target'])+'；证据 '+safe(', '.join(r['evidence']))+'\n'
                elif section=='chores':yield '- '+safe(item['name'])+' → '+safe(item['target'])+'；离线步骤 '+str(item['step_order'])+'；证据 '+safe(', '.join(item['evidence']))+'\n'
                else:yield '- '+safe(json.dumps(item,ensure_ascii=False,sort_keys=True))+'\n'
            offset+=len(items)
            if offset>=total:break
        yield '\n'
    yield '## migration_notes\n\n'
    for note in header['migration_notes']:yield '- '+safe(note)+'\n'
