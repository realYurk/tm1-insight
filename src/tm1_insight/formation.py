"""Cube formation projection over the existing worksheet and architecture evidence.

No TM1 execution, naming-based business purpose, read/write join or new parser.
"""
from __future__ import annotations
import hashlib
import json
from tm1_insight.workflow import confirmed_write_sources

VERSION='cube-formation-1'


def enrich(r,wf,progress=None):
    facts=r['evidence'];facts_by_id={f['id']:f for f in facts};by_payload={e['stable_id']:e['id'] for e in facts}
    def proof(process,location,kind='formation'):
        payload={**location,'process':process,'kind':kind}
        if payload.get('section'):payload['source_hash']=r['details'].get(process,{}).get('source_hash')
        stable=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if stable in by_payload:return by_payload[stable]
        if len(facts)>=30000:raise ValueError('Cube formation evidence budget exceeded; reduce scope')
        e=dict(id='e'+str(len(facts)+1),stable_id=stable,**payload);facts.append(e);facts_by_id[e['id']]=e;by_payload[stable]=e['id'];return e['id']
    def edge(kind,source,target,source_type,target_type,process,evidence,conditions=(),status='SOURCE_OBSERVED',reason=None,**extra):
        r['formation_relationships'].append(dict(process=process,source=source,target=target,source_type=source_type,target_type=target_type,
            relation_type=kind,resolution_status=status,evidence_refs=evidence,conditions=list(conditions),scope='current_architecture_slice',
            unresolved_reason=reason,runtime_verified=False,**extra))
    for d in r['data_relationships']:
        kind=d['kind']
        if kind=='static_value_dependency':
            edge('STATIC_VALUE_DEPENDENCY',d['source'],d['target'],'cube','cube',d['process'],d['evidence'],status=d['status'],reason='静态表达式依赖，不证明执行或数值贡献比例')
        elif kind=='view_datasource_binding':edge('VIEW_DATASOURCE_BINDING',d['target'],d['process'],'cube','process',d['process'],d['evidence'],reason='到达绑定语句时的静态来源；行变量和筛选仍需核对')
        elif d.get('role') in {'read','write'}:
            read=d['role']=='read'
            edge('CUBE_READ' if read else 'CUBE_WRITE',d['target'] if read else d['process'],d['process'] if read else d['target'],
                'cube' if read else 'process','process' if read else 'cube',d['process'],d['evidence'],d.get('conditions',[]),reason='对象读写观察不等于值依赖')
    for d in wf['data']:
        if d.get('relation_kind')=='source_reference' and d.get('role')=='read' and not d.get('target'):
            ids=[proof(d['process'],{k:d[k] for k in ('section','line','column')},'unresolved_read')]
            edge('UNRESOLVED_RELATION',None,d['process'],'cube','process',d['process'],ids,status='UNKNOWN',reason='动态读取目标未解析')
    for issue in r['unresolved_dependencies']:
        if issue.get('evidence'):edge('UNRESOLVED_RELATION',issue['process'],None,'object','object',issue['process'],issue['evidence'],status='UNKNOWN',reason=issue['message'])
    for e in r['execution_relationships']:edge('EXECUTION_CALL' if e['target'] else 'UNRESOLVED_RELATION',e['process'],e['target'],'process','process',e['process'],e['evidence'],e['conditions'],reason=None if e['target'] else '动态调用目标未确认')
    for c in r['chores']:edge('CHORE_SCHEDULE',c['name'],c['target'],'chore','process',c['target'],c['evidence'],reason='离线调度定义，未验证启用或运行')
    for c in r['cubes']:
        for dim in c['dimensions']:edge('STRUCTURAL_RELATION',c['name'],dim['name'],'cube','dimension',c['name'],c['evidence'])
    for rule in r['rules']:
        for g in rule['groups']:edge('RULE_REFERENCE' if g['kind']=='rule_read' else 'FEEDER_REFERENCE',rule['cube'],g['target'],'rule','cube',rule['cube'],g['evidence_refs'],reason='DB 引用；完整规则公式及稀疏语义未求值',occurrences=g['count'])
    explanations={};used_reads=set();coordinate_reads=set();control_reads=set();usage_refs={}
    for name,report in wf['details'].items():
        nodes={n['id']:n for n in report['nodes']}
        for w in report['writes']:
            for i in w.get('coordinate_read_nodes',[]):
                e=nodes[i]['evidence'];key=(name,e['section'],e['line'],e['column']);coordinate_reads.add(key);usage_refs.setdefault(key,[]).append(proof(name,w['evidence'],'coordinate_usage'))
        for c in report.get('control_reads',[]):
            e=nodes[c['read_node']]['evidence'];key=(name,e['section'],e['line'],e['column']);control_reads.add(key);usage_refs.setdefault(key,[]).append(proof(name,c['evidence'],'control_usage'))
    for index,calc in enumerate(wf['calculation']):
        if progress and index%25==0:progress(stage='解释写入坐标与值来源',stage_index=5,stages_total=6,current=index,total=len(wf['calculation']))
        name=calc['process'];report=r['details'][name];nodes={n['id']:n for n in report['nodes']}
        w=next(w for w in report['writes'] if w['id']==calc['write_id'])
        ids=[proof(name,w['evidence'],'write_formation')]
        coords=[]
        for item in w['coordinate_mapping']['items']:
            b=item.get('binding',dict(kind='UNRESOLVED',expression='坐标尚未解析',evidence=[]))
            refs=[proof(name,loc,'coordinate_definition') for loc in b.get('evidence',[])]
            coords.append(dict(dimension=item['dimension'],position=item['position'],kind=b['kind'],expression=b['expression'],
                value=b.get('value'),evidence_refs=refs,member_catalog_evidence=b.get('member_evidence')))
        source_reads=[];correspondences=[]
        confirmed_reads,_=confirmed_write_sources(w,nodes)
        confirmed_ids={read['id'] for read in confirmed_reads}
        for index in w['read_nodes']:
            read=nodes[index];used_reads.add((name,read['evidence']['section'],read['evidence']['line'],read['evidence']['column']))
            key=(name,read['evidence']['section'],read['evidence']['line'],read['evidence']['column']);usage_refs.setdefault(key,[]).extend(ids)
            if index not in confirmed_ids:continue
            rid=proof(name,read['evidence'],'value_source')
            source_coords=[]
            for item in read['coordinate_mapping']['items']:
                b=item.get('binding',{});source_coords.append(dict(dimension=item['dimension'],kind=b.get('kind','UNRESOLVED'),expression=b.get('expression','待核对'),
                    evidence_refs=[proof(name,loc,'source_coordinate') for loc in b.get('evidence',[])]))
            source_reads.append(dict(cube=read['cube'],coordinates=source_coords,evidence_refs=[rid]))
            for a in source_coords:
                for b in coords:
                    if a['kind'] in {'PARAMETER','FIXED_MEMBER','NUMBER'} and a['kind']==b['kind'] and a['expression']==b['expression']:
                        correspondences.append(dict(source_cube=read['cube'],source_dimension=a['dimension'],target_cube=w['cube'],target_dimension=b['dimension'],
                            expression=a['expression'],status='SAME_COORDINATE_EXPRESSION',evidence_refs=a['evidence_refs']+b['evidence_refs']+[rid]+ids,
                            note='源码使用同一坐标表达式；不证明业务成员映射、汇总或运行贡献。'))
        complete=calc.get('expression_status',calc['status'])=='STATIC_EXPRESSION'
        value_nodes=[]
        for index in w['unknown_nodes']:
            node=nodes[index]
            value_nodes.append(dict(variable=node.get('name'),reason=node.get('reason'),evidence_refs=[proof(name,node['evidence'],'unresolved_value')]))
        log_write=any(e['category']=='LOGGING' and any(all(facts_by_id[i].get(k)==w['evidence'][k] for k in ('section','line','column')) for i in e['evidence']) for s in r['transformation_steps'] if s['process']==name for e in s['effects'])
        x=dict(process=name,location=w['evidence'],cube=w['cube'],operation=w['operation'],write_id=w['id'],mode='INCREMENT' if w['operation'].casefold()=='cellincrementn' else 'OVERWRITE',
            target_coordinates=coords,source_reads=source_reads,coordinate_correspondences=correspondences,
            value_expression=w['value_expression'],definition_expression=w['formula_expression'],calculation=calc['reconstructed'] if complete else None,
            expression_status='SUPPORTED_STATIC' if complete else 'PARTIAL',conditions=w['control_context'],evidence_refs=ids,
            unknown_inputs=value_nodes,technical=bool(w['cube'] and w['cube'].startswith('}')) or log_write or next((p['technical'] for p in r['processes'] if p['process']==name),True),runtime_verified=False,
            source_binding=next((s['source_binding'] for s in r['transformation_steps'] if s['process']==name),None),
            data_row_binding='UNCONFIRMED',note='VIEW 绑定、显式读取、写入表达式依赖分开记录；未采集字段到行变量映射时不推导来源值。')
        row=report.get('data_row_lineage',{})
        x.update(data_row_schema=row.get('schema'),data_source_variable_bindings=row.get('data_source_variable_bindings',[]),
            source_view_binding=row.get('source_view_binding'),source_coordinate_mapping=row.get('source_coordinate_mapping',[]),
            data_row_value_dependencies=w.get('data_row_value_dependencies',[]),value_definition_chain=w.get('value_definition_chain',[]),
            target_write_binding=dict(cube=w['cube'],operation=w['operation'],location=w['evidence'],evidence_refs=ids),
            unresolved_binding_reasons=w.get('unresolved_binding_reasons',[]),data_row_binding=(w['data_row_binding_status'] if w.get('data_row_value_dependencies') else 'UNCONFIRMED'))
        if x['source_view_binding'] is None and x['source_binding']:
            # Missing row metadata must not erase an independently proven
            # Prolog datasource binding. It still proves no column or value.
            x['source_view_binding']=dict(x['source_binding'],row_layout_status='UNKNOWN',membership_status='UNKNOWN',
                note='来源绑定由独立源码证据确认；缺失 Variables 时不推导列布局或数值依赖。')
        for dep in x['data_row_value_dependencies']:
            refs=ids+[proof(name,dep['metadata_evidence'],'row_variable_metadata'),proof(name,dep['use_location'],'row_value_use')]
            dep['evidence_refs']=refs
            edge('DATA_ROW_VALUE_DEPENDENCY',dep['variable'],w['cube'],'process_variable','cube',name,refs,
                 w['control_context'],status='STATIC_DEFINITION_DEPENDENCY',source_field_status=dep['field_status'])
        r['write_explanations'].append(x);explanations[(name,w['evidence']['section'],w['evidence']['line'],w['evidence']['column'])]=x
        if not w['cube']:edge('UNRESOLVED_RELATION',name,None,'process','cube',name,ids,w['control_context'],status='UNKNOWN',reason='动态写入目标未解析')
    bound_records=[]
    for step in r['transformation_steps']:
        step['write_explanations']=[x for x in r['write_explanations'] if x['process']==step['process'] and not x.get('via') and not x['technical']]
        for e in step['effects']:
            if not e.get('via') or e['operation'].casefold() not in {'cellputn','cellputs','cellincrementn'}:continue
            originals=[x for x in r['write_explanations'] if x['process']==e['via'] and any(all(facts_by_id[i].get(k)==x['location'][k] for k in ('section','line','column')) for i in e['evidence'])]
            for original in originals:
                bound=dict(original,process=step['process'],cube=e['target'],via=e['via'],technical=step['technical'] or bool(e['target'] and e['target'].startswith('}')),
                    calculation=None,expression_status='CALLEE_CONTEXT_ONLY',conditions=e['conditions'],evidence_refs=e['evidence'],
                    note='辅助写入目标按显式参数绑定；坐标和表达式仍属被调用 TI，上下文未作跨 TI 公式替换。')
                # Avoid implying caller-bound coordinates when parameters are not substituted.
                bound['target_coordinates']=[];bound['coordinate_correspondences']=[];bound['source_reads']=[]
                bound.update(data_row_value_dependencies=[],source_coordinate_mapping=[],source_view_binding=None,
                    value_definition_chain=[],data_row_binding='CALLEE_CONTEXT_ONLY',
                    unresolved_binding_reasons=['被调用 TI 的行绑定尚未替换到调用参数上下文。'])
                step['write_explanations'].append(bound);bound_records.append(bound)
    r['write_explanations'].extend(bound_records)
    for summary in r['transformation_summaries']:
        summary['write_explanations']=next(s['write_explanations'] for s in r['transformation_steps'] if s['process']==summary['process'])
        summary['observed_reads']=[]
        for d in wf['data']:
            if d['process']!=summary['process'] or d.get('role')!='read':continue
            key=(d['process'],d.get('section'),d.get('line'),d.get('column'))
            summary['observed_reads'].append(dict(cube=d['target'],usage='VALUE_EXPRESSION' if key in used_reads else 'TARGET_COORDINATE_LOOKUP' if key in coordinate_reads else 'CONTROL_EXPRESSION' if key in control_reads else 'READ_OBSERVATION_ONLY',
                usages=[role for role,seen in [('VALUE_EXPRESSION',used_reads),('TARGET_COORDINATE_LOOKUP',coordinate_reads),('CONTROL_EXPRESSION',control_reads)] if key in seen] or ['READ_OBSERVATION_ONLY'],
                evidence_refs=[proof(d['process'],{k:d[k] for k in ('section','line','column')},'read_usage')]+usage_refs.get(key,[])))
    for relation in r['formation_relationships']:
        if relation['relation_type']=='STATIC_VALUE_DEPENDENCY':
            locations=[facts_by_id[i] for i in relation['evidence_refs'] if facts_by_id[i].get('kind')=='write_evidence']
            if locations:
                f=locations[0];x=explanations.get((f['process'],f['section'],f['line'],f['column']))
                if x:relation['conditions']=x['conditions']
    for d in r['dimension_comparisons']:d['basis']='STRUCTURE_ONLY_NOT_VALUE_MAPPING'
    for external in r['external_sources']:
        edge('UNRESOLVED_RELATION',external['process'],None,'process','external_source',external['process'],external['evidence'],status='PARTIAL',reason='已确认 '+external['external_type']+' 类型；文件/SQL/字段与值流未解析')
    for c in r['cubes']:
        c['formation_mechanisms']=dict(ti_writes=sum(x['cube']==c['name'] and not x.get('via') for x in r['write_explanations']),
            rule_declared=c['has_rules'],rule_source_recorded=c['rule_source_available'],rule_semantics='PARTIAL',consolidation='RECORDED_STRUCTURE_ONLY',
            external_or_manual_inputs='NOT_PROVEN_ABSENT',business_content='未经人工确认；这里只说明多维结构和写入事实。')
    r['formation_version']=VERSION
    r['key_questions']=[
        '核对 Data Source Variables/字段定义：未采集时，vValue 等 Data 输入不能绑定为某个 VIEW 单元格值。',
        '核对各写入点的固定成员、运行时坐标、条件及累加/覆盖；动态 Subset/MDX 未求值。',
        'Rule/Feeder 与层级权重仅保留源码/结构事实；执行路径、最终金额和迁移等价仍需隔离运行验证。']


def consumers(con,r,cube,progress=None,max_nodes=1000):
    """Verify only indexed readers; never traverse their calls or other dependencies."""
    from tm1_insight.store.calculation import inspect
    rows=con.execute('SELECT DISTINCT process_name FROM process_reads_cube WHERE cube_name=? ORDER BY process_name LIMIT 201',[cube]).fetchall()
    used=len(r['details'])+len(r['cubes'])+len(r['dimensions']);remaining=min(20,max(0,max_nodes-used));chars=0
    for index,(name,) in enumerate(rows[:200]):
        if progress:progress(stage='核对 Cube 边界外消费者',stage_index=5,stages_total=6,current=index,total=min(200,len(rows)))
        record=dict(process=name,name=name,target=cube,kind='ti_reader',module_role='EXTERNAL_DEPENDENCY',status='INDEX_CANDIDATE',evidence=[])
        report=r['details'].get(name)
        if report is None and remaining>0:
            length=con.execute("SELECT length(coalesce(prolog,''))+length(coalesce(metadata,''))+length(coalesce(data,''))+length(coalesce(epilog,'')) FROM processes WHERE name=?",[name]).fetchone()
            if length and length[0]<=250000 and chars+length[0]<=1000000:
                report=inspect(con,name);chars+=length[0];remaining-=1;r['details'][name]=report
        if report:
            for d in report['observations']:
                if d['target']!=cube or d['operation'].casefold() not in {'cellgetn','cellgets'}:continue
                if len(r['evidence'])>=30000:raise ValueError('Consumer evidence budget exceeded')
                payload=dict(process=name,kind='verified_consumer',source_hash=report['source_hash'],**{k:d[k] for k in ('section','line','column')})
                e=dict(id='e'+str(len(r['evidence'])+1),stable_id=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),**payload)
                r['evidence'].append(e);record['evidence'].append(e['id'])
            if record['evidence']:record['status']='SOURCE_CONFIRMED'
        r['downstream_consumers'].append(record)
        if record['evidence']:
            r['formation_relationships'].append(dict(process=name,source=cube,target=name,source_type='cube',target_type='process',relation_type='CUBE_READ',
                resolution_status='SOURCE_OBSERVED',evidence_refs=record['evidence'],conditions=[],scope='external_consumer_only',unresolved_reason='只验证读取本 Cube；未扩展消费者内部或证明值贡献',runtime_verified=False))
    if len(rows)>200 or any(d.get('kind')=='ti_reader' and d['status']!='SOURCE_CONFIRMED' for d in r['downstream_consumers']):
        issue=dict(process=cube,message='部分消费者仍为目录候选或超过数量/源码预算；未声称消费者目录完整。')
        r['unresolved_dependencies'].append(issue);r['diagnostics'].append(dict(issue))


def write_markdown(items):
    """Compact per-Cube coordinate contracts; write sites/conditions remain independent."""
    def safe(v):return str(v).replace('\n',' ').replace('<','&lt;').replace('>','&gt;').replace('`','\\`')
    groups={}
    for x in items:
        if not x['cube'] or x['technical']:continue
        groups.setdefault(x['cube'],[]).append(x)
    for cube,writes in groups.items():
        yield '- 写入 **'+safe(cube)+'**：'+str(len(writes))+' 个独立写入点。\n'
        common_reasons=set(writes[0].get('unresolved_binding_reasons',[]))
        for w in writes[1:]:common_reasons.intersection_update(w.get('unresolved_binding_reasons',[]))
        for reason in sorted(common_reasons):yield '  - 行绑定共同缺口：'+safe(reason)+'\n'
        maps=[{c['dimension']:(c['kind'],c['expression']) for c in w['target_coordinates'] if c['dimension']} for w in writes]
        common={k:v for k,v in maps[0].items() if all(m.get(k)==v for m in maps[1:])}
        if common:yield '  - 公共目标坐标：'+safe('；'.join(k+' = '+v[1]+('（固定成员）' if v[0]=='FIXED_MEMBER' else '（参数）' if v[0]=='PARAMETER' else '（运行时/待解析）' if v[0]=='UNRESOLVED' else '') for k,v in common.items()))+'。\n'
        for w,m in zip(writes,maps):
            loc=w['location'];where=loc['section']+':'+str(loc['line'])+':'+str(loc['column'])
            differences='；'.join(k+' = '+v[1]+('（固定成员）' if v[0]=='FIXED_MEMBER' else '') for k,v in m.items() if k not in common)
            yield '  - '+safe(where)+' · '+('累加' if w['mode']=='INCREMENT' else '覆盖')+' · 值表达式 `'+safe(w['value_expression'])+'`'+('；'+safe(differences) if differences else '')+'。\n'
            if w['conditions']:yield '    - 条件路径：'+safe(' / '.join(c['kind']+' '+c['condition']+' [分支 '+str(c.get('branch','循环'))+']' for c in w['conditions']))+'；未验证执行。\n'
            if w['calculation']:yield '    - 已还原静态表达式：`'+safe(w['calculation'])+'`。\n'
            elif w.get('via'):yield '    - 由辅助 TI '+safe(w['via'])+' 写入；参数上下文未完整替换。\n'
            else:yield '    - 值来源/部分坐标仍待确认；原始定义链和未知原因保存在此写入点 JSON。\n'
            for dep in w.get('data_row_value_dependencies',[]):
                yield '    - Data 行值依赖：`'+safe(dep['variable'])+'` → 写入值；来源字段 '+safe(dep['field_status'])+(' · '+safe(dep['source_cube'])+' / '+safe(dep['source_view']) if dep['source_cube'] else '')+'。\n'
            for definition in w.get('value_definition_chain',[]):
                e=definition['location']
                yield '    - 定义链：`'+safe(definition['variable'])+' = '+safe(definition['expression'])+'` · '+safe(e['section'])+':'+str(e['line'])+'。\n'
            for reason in w.get('unresolved_binding_reasons',[]):
                if reason not in common_reasons:yield '    - 行绑定未确认原因：'+safe(reason)+'\n'
            for c in w['coordinate_correspondences']:
                yield '    - 坐标表达式对应：'+safe(str(c['source_cube'])+'.'+str(c['source_dimension']))+' / '+safe(str(c['target_cube'])+'.'+str(c['target_dimension']))+' 使用 `'+safe(c['expression'])+'`；不据此证明汇总或成员变换。\n'
