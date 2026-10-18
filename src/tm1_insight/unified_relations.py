"""Compact typed projection of existing architecture facts; no parser or graph engine."""
from __future__ import annotations

from collections import Counter
import hashlib
import json

VERSION = 'calculation-relations-1'
SECTIONS = {'relation_objects', 'unified_relations', 'relation_evidence', 'business_steps', 'rule_summaries'}
MAX_RELATIONS = 30000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def identity(prefix, value):
    return prefix + hashlib.sha256(canonical(value).encode()).hexdigest()


class Projection:
    def __init__(self):
        self.objects = {}
        self.relations = {}
        self.facts = {}
        self.truncated = False

    def object(self, kind, name, *, owner=None, location=None, technical=False, context_ref=None):
        key = dict(type=kind, name=name, owner=owner, location=location)
        oid = identity('o', key)
        item = self.objects.setdefault(oid, dict(id=oid, **key, technical=technical, context_refs=[]))
        item['technical'] = item['technical'] or technical
        if context_ref and context_ref not in item['context_refs']:
            item['context_refs'].append(context_ref)
        return oid

    def evidence(self, payload):
        # Never copy code, expressions, connection settings or an entire parser object.
        keys = ('process', 'section', 'line', 'line_end', 'column', 'source_hash',
                'table', 'cube', 'chore', 'target', 'step_order', 'dimension', 'dim_order', 'operation', 'kind')
        fact = {k: payload[k] for k in keys if payload.get(k) is not None}
        eid = identity('u', fact)
        self.facts.setdefault(eid, dict(id=eid, **fact))
        return eid

    def edge(self, source, target, kind, mechanism, evidence, *, owner=None,
             status='SOURCE_CONFIRMED', semantic_status='STRUCTURE_ONLY',
             reasons=(), context_refs=(), directness='DIRECT', qualifier=None, technical=False):
        if not evidence:
            status, semantic_status = 'UNKNOWN', 'UNCONFIRMED'
            reasons = list(reasons) + ['EVIDENCE_MISSING']
        # Status, mechanism and per-site qualifier are part of identity. No strongest-status merge.
        key = dict(source=source, target=target, relation_kind=kind, mechanism=mechanism,
                   owner=owner, status=status, semantic_status=semantic_status,
                   directness=directness, qualifier=qualifier)
        rid = identity('r', key)
        if rid not in self.relations and len(self.relations) >= MAX_RELATIONS:
            self.truncated = True
            return None
        item = self.relations.setdefault(rid, dict(id=rid, **key,
            source_type=self.objects[source]['type'], target_type=self.objects[target]['type'],
            source_name=self.objects[source]['name'], target_name=self.objects[target]['name'],
            direction='SOURCE_TO_TARGET', evidence=[], context_refs=[], unresolved_reasons=[],
            technical=technical or self.objects[source]['technical'] or self.objects[target]['technical'],
            runtime_verified=False, process=self.objects[owner]['name'] if owner else self.objects[source]['name']))
        for field, values in [('evidence', evidence), ('context_refs', context_refs), ('unresolved_reasons', reasons)]:
            item[field] = sorted(set(item[field]) | set(values))
        return rid


def enrich(report, progress=None):
    """Adapt already verified facts. Indirect paths/cycles come from existing extraction."""
    p = Projection()
    def update(current=0, total=None):
        if progress:
            progress(stage='统一关系与证据引用', stage_index=5, stages_total=6, current=current, total=total)
    update()
    def obj(kind, name, **kw):
        return p.object(kind, name, technical=bool(name and name.startswith('}')), **kw)
    legacy = {f['id']: p.evidence(f) for f in report.get('evidence', [])}
    def refs(ids):
        return sorted({legacy[i] for i in ids if i in legacy})
    for i, process in enumerate(report.get('processes', [])):
        p.object('process', process['process'], technical=process.get('technical', False), context_ref=f'/processes/{i}')
    for i, cube in enumerate(report.get('cubes', [])):
        source = obj('cube', cube['name'], context_ref=f'/cubes/{i}')
        for dimension in cube['dimensions']:
            target = obj('dimension', dimension['name'])
            evidence = p.evidence(dict(table='cube_has_dimension', cube=cube['name'],
                dimension=dimension['name'], dim_order=dimension['order']))
            p.edge(source, target, 'CUBE_DIMENSION', 'RECORDED_DIMENSION_ORDER', [evidence],
                   qualifier=dimension['order'], context_refs=[f'/cubes/{i}/dimensions'])
    calls = {}
    for i, e in enumerate(report.get('execution_relationships', [])):
        source = obj('process', e['process'])
        known = bool(e['target'])
        target = obj('process', e['target']) if known else p.object('unresolved', '未确认调用目标', owner=source, location=refs(e['evidence']))
        rid = p.edge(source, target, 'PROCESS_CALL', 'SOURCE_INVOCATION', refs(e['evidence']),
            owner=source, status='SOURCE_CONFIRMED' if known else 'UNKNOWN',
            reasons=[] if known else ['DYNAMIC_CALL_TARGET'], context_refs=[f'/execution_relationships/{i}'],
            technical=e.get('technical', False))
        calls.setdefault((e['process'], e['target']), []).append(rid)
    # Reuse the already computed bounded module paths; do not compute another closure.
    for m in report.get('module_objects', []):
        path = m.get('relation_path', [])
        if m.get('object_type') != 'process' or len(path) < 2:
            continue
        if any(not calls.get((e['source'], e['target'])) for e in path):
            continue
        source, target = obj('process', path[0]['source']), obj('process', path[-1]['target'])
        rid = p.edge(source, target, 'EXECUTION_REACHABILITY', 'EXISTING_MODULE_PATH',
            refs([eid for e in path for eid in e.get('evidence', [])]),
            directness='INDIRECT', qualifier=[(e['source'], e['target']) for e in path],
            reasons=['STATIC_REACHABILITY_NOT_EXECUTION_ORDER'])
        if rid:
            p.relations[rid]['path_relation_ids'] = [call for e in path for call in sorted(set(calls[(e['source'], e['target'])])) if call]
    for i, c in enumerate(report.get('chores', [])):
        p.edge(obj('chore', c['name']), obj('process', c['target']), 'CHORE_SCHEDULE', 'RECORDED_SCHEDULE',
            refs(c['evidence']), qualifier=c['step_order'], context_refs=[f'/chores/{i}'],
            reasons=['ENABLEMENT_AND_RUNTIME_NOT_VERIFIED'])
    # Formation already handles verified consumers, helper bindings and static value dependencies.
    mapping = {'CUBE_READ': 'CUBE_READ', 'CUBE_WRITE': 'CUBE_WRITE',
               'VIEW_DATASOURCE_BINDING': 'VIEW_DATASOURCE', 'STATIC_VALUE_DEPENDENCY': 'STATIC_VALUE_DEPENDENCY'}
    for i, r in enumerate(report.get('formation_relationships', [])):
        if i % 250 == 0:
            update(i, len(report['formation_relationships']))
        if r['relation_type'] == 'UNRESOLVED_RELATION':
            ids = refs(r.get('evidence_refs', []))
            owner = obj(r['source_type'], r['source']) if r.get('source') else obj(r['target_type'], r['target']) if r.get('target') else None
            unknown = p.object('unresolved', '未确认依赖', owner=owner, location=ids)
            if owner:
                p.edge(owner, unknown, 'UNRESOLVED_DEPENDENCY', 'EXISTING_FORMATION_UNKNOWN', ids,
                       owner=owner, status='UNKNOWN', semantic_status='UNCONFIRMED',
                       reasons=[r.get('unresolved_reason') or 'UNRESOLVED_DEPENDENCY'],
                       context_refs=[f'/formation_relationships/{i}'])
            continue
        if r['relation_type'] not in mapping or not r.get('source') or not r.get('target'):
            continue
        owner = obj('process', r['process'])
        kind = mapping[r['relation_type']]
        status = 'SOURCE_CONFIRMED'
        if kind == 'STATIC_VALUE_DEPENDENCY':
            # Only the existing worksheet's supported expression dependency receives this status.
            status = 'STATIC_DEPENDENCY_CONFIRMED' if r['resolution_status'] == 'STATIC_EXPRESSION_DEPENDENCY' else 'PARTIAL'
        p.edge(obj(r['source_type'], r['source']), obj(r['target_type'], r['target']), kind,
            'EXISTING_FORMATION_' + r['relation_type'], refs(r.get('evidence_refs', [])), owner=owner,
            status=status, semantic_status='STATIC_DEPENDENCY' if status=='STATIC_DEPENDENCY_CONFIRMED' else 'STRUCTURE_ONLY',
            reasons=[r['unresolved_reason']] if r.get('unresolved_reason') else [],
            context_refs=[f'/formation_relationships/{i}'])
    for i, w in enumerate(report.get('write_explanations', [])):
        if not w.get('cube') or w.get('via'):
            continue  # Callee coordinates must not be substituted into caller context.
        source = obj('process', w['process'])
        location = {k: w['location'].get(k) for k in ('section', 'line', 'column')}
        p.edge(source, obj('cube', w['cube']), 'TI_WRITE_SLICE', 'EXISTING_WRITE_EXPLANATION',
            refs(w['evidence_refs']), owner=source, qualifier=location,
            semantic_status='PARTIAL', context_refs=[f'/write_explanations/{i}'], technical=w['technical'],
            reasons=['COORDINATES_AND_VALUE_REQUIRE_INDIVIDUAL_BINDING_STATUS'])
    # Candidate pairing comes only from existing structural comparisons, never becomes value flow.
    for i, d in enumerate(report.get('dimension_comparisons', [])):
        source, target = obj('cube', d['source']), obj('cube', d['target'])
        related = [r for r in report.get('data_relationships', []) if r.get('process')==d['process'] and
                   ((r.get('target')==d['source'] and r.get('role')=='read') or
                    (r.get('target')==d['target'] and r.get('role')=='write'))]
        if {r.get('role') for r in related} != {'read','write'}:
            continue
        p.edge(source, target, 'CANDIDATE_FORMATION', 'CO_OBSERVED_ACCESS',
            refs([eid for r in related for eid in r.get('evidence', [])]), owner=obj('process', d['process']),
            status='CANDIDATE', semantic_status='UNCONFIRMED', context_refs=[f'/dimension_comparisons/{i}'],
            reasons=['CO_READ_WRITE_DOES_NOT_PROVE_VALUE_OR_CELL_MAPPING'])
    for index, owner in enumerate(report.get('rules', [])):
        update(index, len(report['rules']))
        cube = obj('cube', owner['cube'])
        for field, kind in [('rule_semantics', 'rule'), ('feeder_semantics', 'feeder')]:
            for j, statement in enumerate(owner.get(field, [])):
                context = f'/rules/{index}/{field}/{j}'
                location = dict(source_hash=owner['source_hash'], line=statement['line_start'], line_end=statement['line_end'])
                node = obj(kind, f"{owner['cube']} · {kind} L{statement['line_start']}", owner=cube, location=location, context_ref=context)
                eid = p.evidence(dict(process=owner['cube'], cube=owner['cube'], section='rule', kind=kind, **location))
                p.edge(node, cube, 'RULE_TARGET' if kind=='rule' else 'FEEDER_OWNER', 'DECLARED_IN_RULE_SOURCE', [eid],
                    owner=node, semantic_status=statement['status'], context_refs=[context],
                    reasons=statement.get('unresolved_reasons', []))
                for db in statement.get('db_references', []):
                    fact = p.evidence(dict(process=owner['cube'], section='rule', line=db['line'], column=db['column'],
                                           source_hash=owner['source_hash'], kind='rule_db' if kind=='rule' else 'feeder_db'))
                    known = db['cube_resolved']
                    other = obj('cube', db['cube']) if known else p.object('unresolved', '未确认 Cube 引用', owner=node,
                        location=dict(line=db['line'], column=db['column']))
                    # Feeder is a declared reference only, not a numerical source/target formula.
                    source, target = (other, node) if kind=='rule' else (node, other)
                    p.edge(source, target, 'RULE_DB_REFERENCE' if kind=='rule' else 'FEEDER_DB_REFERENCE',
                        'DB_CALL', [fact], owner=node, status='SOURCE_CONFIRMED' if known else 'UNKNOWN',
                        semantic_status=db['status'], reasons=db.get('unresolved_reasons', []) +
                            (['FEEDER_TARGET_MAPPING_NOT_PROVEN'] if kind=='feeder' else []), context_refs=[context])
                if kind=='feeder':
                    # No evidence associates a Feeder to one numerical Rule statement.
                    p.objects[node]['rule_association'] = 'OWNER_CUBE_ONLY'
    # Drop unused facts; report raw sources and expression trees remain in their existing resources.
    used = {e for r in p.relations.values() for e in r['evidence']}
    original_facts = {f['id']: f for f in report.get('evidence', [])}
    read_usages = {}
    for summary in report.get('transformation_summaries', []):
        for read in summary.get('observed_reads', []):
            for eid in read.get('evidence_refs', []):
                fact = original_facts.get(eid, {})
                if fact.get('kind') != 'read_usage':
                    continue
                key = tuple(fact.get(k) for k in ('process','section','line','column'))
                read_usages.setdefault(key, set()).update(read.get('usages', []))
    for r in p.relations.values():
        usages = set().union(*(read_usages.get(tuple(p.facts[e].get(k) for k in ('process','section','line','column')), set()) for e in r['evidence']))
        r['detail_only'] = r['technical'] or r['status']=='UNKNOWN' or (
            r['relation_kind']=='CUBE_READ' and bool(usages) and
            usages <= {'CONTROL_EXPRESSION','TARGET_COORDINATE_LOOKUP'})
    report['relation_objects'] = sorted(p.objects.values(), key=lambda o: (o['type'], o['name'], o['id']))
    for o in report['relation_objects']:
        o['context_refs'].sort()
    order = {kind: i for i,kind in enumerate(('CUBE_WRITE','TI_WRITE_SLICE','STATIC_VALUE_DEPENDENCY',
        'CUBE_READ','VIEW_DATASOURCE','RULE_TARGET','RULE_DB_REFERENCE','CHORE_SCHEDULE','PROCESS_CALL',
        'EXECUTION_REACHABILITY','CANDIDATE_FORMATION','FEEDER_OWNER','FEEDER_DB_REFERENCE','CUBE_DIMENSION'))}
    report['unified_relations'] = sorted(p.relations.values(), key=lambda r: (r['detail_only'], order.get(r['relation_kind'],99), r['source_name'], r['target_name'], r['id']))
    report['relation_evidence'] = sorted((p.facts[e] for e in used), key=lambda f: f['id'])
    report['unified_model'] = dict(schema=VERSION, context_document='Architecture.json', runtime_verified=False,
        objects=len(p.objects), relations=len(p.relations), evidence=len(used), truncated=p.truncated,
        relation_kinds=dict(sorted(Counter(r['relation_kind'] for r in p.relations.values()).items())),
        statuses=dict(sorted(Counter(r['status'] for r in p.relations.values()).items())),
        cycles=report.get('cycles', []), indirect_scope='existing bounded module paths, not all-pairs closure',
        note='对象读写、Rule 引用、Feeder、结构及静态值依赖分别保留；未执行或证明逐单元格传输。')
    business_backbone(report, legacy)


def business_backbone(report, stable_evidence):
    """Human-facing bounded projection of existing CORE steps, never inferred purpose."""
    entry = report.get('module', {}).get('name')
    cube_entry = report.get('module', {}).get('kind')=='cube_scope'
    steps = []
    for index, step in enumerate(report.get('transformation_steps', [])):
        if step.get('technical'):
            continue
        writes = [(i,w) for i,w in enumerate(report.get('write_explanations', []))
                  if w['process']==step['process'] and not w['technical'] and not w.get('via') and
                  (not cube_entry or w['cube']==entry)]
        # Common slice is purely the intersection of already exposed bindings, not inferred grain.
        coordinates = [{c['dimension']:(c['kind'],c['expression']) for c in w['target_coordinates'] if c['dimension']}
                       for _,w in writes]
        common = {k:v for k,v in coordinates[0].items() if all(c.get(k)==v for c in coordinates[1:])} if coordinates else {}
        contexts = [f'/write_explanations/{i}' for i,_ in writes]
        summary = step.get('summary', {})
        primary = {read['cube'] for read in summary.get('observed_reads', [])
                   if read.get('cube') and 'VALUE_EXPRESSION' in read.get('usages', [])}
        binding = step.get('source_binding') or {}
        if binding.get('cube'):
            primary.add(binding['cube'])
        steps.append(dict(process=step['process'], inputs=step['inputs'], outputs=step['outputs'],
            primary_inputs=sorted(primary), supporting_inputs=sorted(set(step['inputs'])-primary),
            write_sites=len(writes), modes=dict(sorted(Counter(w['mode'] for _,w in writes).items())),
            common_target_coordinates=[dict(dimension=d,kind=kind,expression=expr) for d,(kind,expr) in common.items()],
            source_view={k:v for k,v in (step.get('source_binding') or {}).items() if k in {'cube','view','status'}},
            confirmed_static_formulas=sum(bool(w['calculation']) for _,w in writes),
            conditional_writes=sum(bool(w['conditions']) for _,w in writes),
            row_binding_gaps=sorted({reason for _,w in writes for reason in w.get('unresolved_binding_reasons', [])}),
            write_context_refs=contexts, context_ref=f'/transformation_steps/{index}',
            calls=step['business_calls'], helper_calls=len(step.get('technical_calls', [])),
            evidence=sorted({stable_evidence[eid] for _,w in writes for eid in w['evidence_refs'] if eid in stable_evidence}),
            note='读取与写入为观察；仅已确认的静态表达式可支持值依赖，不证明实际数值传输。'))
    report['business_steps'] = sorted(steps, key=lambda s:s['process'])
    report['rule_summaries'] = [dict(process=r['cube'], cube=r['cube'],
        rule_count=len(r.get('rule_semantics', [])), feeder_count=len(r.get('feeder_semantics', [])),
        groups=[{k:g[k] for k in ('kind','target','count')} for g in r.get('groups', [])],
        context_ref=f'/rules/{i}') for i,r in enumerate(report.get('rules', []))]
    report['workflow_spec'] = dict(schema='workflow-specification-1', entry=entry,
        purpose_status='HUMAN_CONFIRMATION_REQUIRED',
        purpose='业务用途尚未人工确认；以下只解释已有模型结构、源码读写及计算证据。',
        main_inputs=sorted({name for s in steps for name in s['primary_inputs']}),
        supporting_inputs=sorted({name for s in steps for name in s['supporting_inputs']}),
        processing_steps=len(steps), direct_write_sites=sum(s['write_sites'] for s in steps),
        schedule_rows=len(report.get('chores', [])),
        schedule_note='离线定义不证明启用或运行。' if report.get('chores') else '当前局部范围未确认 Chore 调度，不代表模型不存在调度。',
        interpretation_order=['入口结构','输入与处理','目标切面','Rule 计算','调用与消费','证据缺口'],
        note='展示顺序用于阅读，不是 TI 执行顺序；Data 行元数据缺失不会阻止工作流构建。')


def json_export(path):
    """Stream existing section index; contexts reference the companion Architecture.json."""
    from tm1_insight import architecture
    from tm1_insight.architecture_extraction import records
    header, _, _ = architecture.page(path, 'unified_relations', 0, 1)
    yield '{"schema":' + json.dumps(VERSION) + ',"statistics":' + canonical(header.get('unified_model', {}))
    yield ',"context_document":"Architecture.json"'
    yield ',"workflow_spec":' + canonical(header.get('workflow_spec', {}))
    for key, section in [('objects','relation_objects'), ('relations','unified_relations'), ('evidence','relation_evidence'), ('business_steps','business_steps')]:
        yield ',"' + key + '":['
        for i, record in enumerate(records(path, section)):
            yield (',' if i else '') + canonical(record)
        yield ']'
    yield '}'


def markdown(path):
    from tm1_insight import architecture
    from tm1_insight.architecture_extraction import records
    header, _, _ = architecture.page(path, 'unified_relations', 0, 1)
    summary = header.get('unified_model')
    if not summary:
        return  # Old artifacts remain readable.
    def safe(value):
        return str(value).replace('|', '\\|').replace('\n', ' ').replace('<', '&lt;').replace('>', '&gt;')
    yield '\n## 统一计算关系与证据\n\n'
    yield summary['note'] + f" 对象 {summary['objects']}；关系 {summary['relations']}；证据 {summary['evidence']}。\n\n"
    yield '|类型|方向|确认状态|依据|未确认项|\n|---|---|---|---|---|\n'
    facts = {f['id']: f for f in records(path, 'relation_evidence')}
    def position(eid):
        f = facts[eid]
        return str(f.get('process', f.get('cube', ''))) + ' / ' + (
            str(f['section'])+':'+str(f.get('line','?'))+':'+str(f.get('column','?'))
            if f.get('section') else str(f.get('table','已记录定义')))
    groups = {}
    for r in records(path, 'unified_relations'):
        if r.get('detail_only', r['technical'] or r['status']=='UNKNOWN'):
            continue
        key = (r['relation_kind'], r['status'])
        g = groups.setdefault(key, dict(sample=r, count=0))
        g['count'] += 1
    for (kind, status), group in sorted(groups.items()):
        r = group['sample']
        yield '|' + '|'.join(map(safe, [kind+' · '+str(group['count'])+' 条', r['source_name']+' → '+r['target_name']+'（示例）',
            status+' / '+r['semantic_status'], '; '.join(position(e) for e in r['evidence'][:2]), '; '.join(r['unresolved_reasons'])])) + '|\n'
    yield '\n此表按类型汇总并各列一个示例，不合并 JSON 中的独立 Rule、写入点或证据。完整清单见 UnifiedRelations.json。\n'
    yield '技术辅助和未确认目标留在 UnifiedRelations.json；Rule/写入切面的 context_refs 指向 Architecture.json 中唯一资源。\n'
    if summary['truncated']:
        yield '\n关系达到预算，清单不完整。\n'
