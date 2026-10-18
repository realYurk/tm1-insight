"""Human-facing projection of existing Architecture facts, never a semantic engine.

Read/write arrows describe access, not value transfer. Rule groups preserve the
underlying independent statements and their evidence references. No database writes.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from html import escape
import json
import re

from tm1_insight.unified_relations import identity

VERSION = 'functional-flow-1'
LABELS = {'CUBE_READ': '读取', 'VIEW_DATASOURCE': '读取（VIEW）',
          'CUBE_WRITE': '写入', 'TI_WRITE_SLICE': '写入',
          'RULE_DB_REFERENCE': '规则引用', 'RULE_TARGET': '按规则计算',
          'PROCESS_CALL': '调用子程序', 'CHORE_SCHEDULE': '调度'}
NOTE = '箭头表示已记录的读取、写入、调用或规则引用，不代表执行先后或逐单元格值传输。业务用途需人工确认。'


def slice_summary(coordinates):
    """At most six recorded coordinates. Never infer dimension from position/name."""
    items = []
    for c in coordinates:
        if not c.get('dimension'):
            continue
        kind = c.get('kind')
        fixed = kind == 'FIXED_MEMBER'
        expression = str(c.get('expression') or '')
        variable = bool(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', expression))
        value = expression if fixed else ('变量 · ' + expression if variable else '待确认')
        items.append(dict(dimension=c['dimension'], value=value, fixed=fixed,
                          kind=kind, expression=expression))
    return sorted(items, key=lambda c: (not c['fixed'], c['dimension']))[:6]


def assemble(report, *, max_nodes=48, max_edges=160, include_context=False):
    """Project verified typed relations; retain unknowns/helpers only in evidence layer."""
    objects = {o['id']: o for o in report.get('relation_objects', [])}
    cubes = {c['name']: c for c in report.get('cubes', [])}
    steps = {s['process']: s for s in report.get('business_steps', [])}
    rule_summaries = {s['cube']: s for s in report.get('rule_summaries', [])}
    writes = report.get('_write_contexts')
    if writes is None:
        writes = {f'/write_explanations/{i}': w for i, w in enumerate(report.get('write_explanations', []))}
    nodes, edges = {}, {}
    hidden = Counter()
    root = report.get('module', {}).get('name', '')
    cube_entry = report.get('module', {}).get('kind') == 'cube_scope'
    primary_processes = {s['process'] for s in steps.values() if s.get('write_sites')}
    primary_processes.update(e['name'] for e in report.get('entry_points', []) if e.get('kind')=='producer')
    if not cube_entry:
        primary_processes.update(steps)
        primary_processes.add(root)
    rule_owners = {root} if cube_entry else {name for s in steps.values() for name in s.get('outputs', [])}

    def node(oid):
        o = objects.get(oid)
        if not o or o.get('technical') or (o['type']=='cube' and cubes.get(o['name'], {}).get('technical')) or o['type'] not in {'cube', 'process', 'rule', 'chore'}:
            return None
        name, kind = o['name'], o['type']
        if kind == 'rule':
            owner = objects.get(o.get('owner'), {})
            name = owner.get('name')
            if not name:
                return None
        nid = identity('f', [kind, name])
        nodes.setdefault(nid, dict(id=nid, kind=kind, name=name, title=name + (' · Rule' if kind=='rule' else ''),
            role='', summary='', inputs=[], outputs=[], slices=[], context_refs=[], object_ids=[],
            dimension_count=len(cubes.get(name, {}).get('dimensions', [])) if name in cubes else None,
            dimensions=[d['name'] for d in cubes.get(name, {}).get('dimensions', [])],
            selected_entry=name == root and kind != 'rule'))
        if oid not in nodes[nid]['object_ids']:
            nodes[nid]['object_ids'].append(oid)
        return nid

    # Root first, including empty/disconnected objects; no manufactured edge.
    for oid, o in objects.items():
        if o['name'] == root and o['type'] in {'cube', 'process'}:
            node(oid)
    for r in report.get('unified_relations', []):
        kind = r['relation_kind']
        if r.get('technical'):
            hidden['technical'] += 1
            continue
        if r['status'] in {'UNKNOWN', 'CANDIDATE'} or not r.get('evidence'):
            hidden['unconfirmed'] += 1
            continue
        if r.get('detail_only') or kind not in LABELS:
            hidden['supporting'] += 1
            continue
        if not include_context:
            process_names = {r[k+'_name'] for k in ('source','target') if r[k+'_type']=='process'}
            rule_nodes = [objects.get(r[k], {}) for k in ('source','target') if r[k+'_type']=='rule']
            outside_rule = any(objects.get(o.get('owner'), {}).get('name') not in rule_owners for o in rule_nodes)
            if outside_rule or (process_names and not process_names <= primary_processes):
                hidden['context'] += 1
                continue
        a, b = node(r['source']), node(r['target'])
        if not a or not b:
            hidden['supporting'] += 1
            continue
        # Access and write-site observations share one display action only. All
        # distinct source relations survive as references, not a new value edge.
        action = 'write' if kind in {'CUBE_WRITE', 'TI_WRITE_SLICE'} else 'read' if kind in {'CUBE_READ','VIEW_DATASOURCE'} else kind
        eid = identity('a', [a, b, action])
        e = edges.setdefault(eid, dict(id=eid, source=a, target=b, action=action, label=LABELS[kind],
            relation_ids=[], evidence_refs=[], context_refs=[], slices=[], unresolved_reasons=[],
            note='仅确认源 Cube 引用；坐标、条件和完整公式需核对。' if kind=='RULE_DB_REFERENCE' else NOTE))
        for field, values in [('relation_ids', [r['id']]), ('evidence_refs', r['evidence']),
                              ('context_refs', r.get('context_refs', [])),
                              ('unresolved_reasons', r.get('unresolved_reasons', []))]:
            e[field] = sorted(set(e[field]) | set(values))
        if kind == 'TI_WRITE_SLICE':
            for ref in r.get('context_refs', []):
                w = writes.get(ref)
                if not w:
                    continue
                summary = slice_summary(w.get('target_coordinates', []))
                key = [(c['dimension'], c['kind'], c['expression']) for c in summary]
                group = next((s for s in e['slices'] if s['_key']==key), None)
                if group is None:
                    group = dict(_key=key, coordinates=summary, write_sites=0, context_refs=[], conditional=False)
                    e['slices'].append(group)
                group['write_sites'] += 1
                group['conditional'] |= bool(w.get('conditions'))
                group['context_refs'].append(ref)

    # Bound display deterministically, prioritising entry neighbours and data actions.
    ranked = sorted(edges.values(), key=lambda e: (
        not (nodes[e['source']]['selected_entry'] or nodes[e['target']]['selected_entry']),
        e['action'] not in {'read','write'}, nodes[e['source']]['name'], nodes[e['target']]['name'], e['id']))
    selected = {n['id'] for n in nodes.values() if n['selected_entry']}
    kept = []
    for e in ranked:
        if len(selected | {e['source'], e['target']}) > max_nodes or len(kept) >= max_edges:
            hidden['budget'] += 1
            continue
        selected.update([e['source'], e['target']])
        for s in e['slices']:
            s.pop('_key')
        kept.append(e)
    nodes = {nid: nodes[nid] for nid in sorted(selected)}
    for n in nodes.values():
        incoming = [e for e in kept if e['target']==n['id']]
        outgoing = [e for e in kept if e['source']==n['id']]
        n['inputs'] = sorted({nodes[e['source']]['name'] for e in incoming})
        n['outputs'] = sorted({nodes[e['target']]['name'] for e in outgoing})
        n['context_refs'] = sorted({ref for e in incoming+outgoing for ref in e['context_refs']})
        if n['kind']=='cube':
            written = any(e['action'] in {'write','RULE_TARGET'} for e in incoming)
            read = any(e['action'] in {'read','RULE_DB_REFERENCE'} for e in outgoing)
            n['role'] = '中间数据' if written and read else '结果数据' if written else '源数据' if read else '数据对象'
            n['summary'] = f"{n['dimension_count']} 个已记录维度；" if n['dimension_count'] is not None else ''
            n['summary'] += '在当前范围内被读取并形成结果。' if written and read else '在当前范围内接收写入或规则定义。' if written else '为当前处理或规则提供读取对象。' if read else '当前入口的数据结构。'
        elif n['kind']=='process':
            s = steps.get(n['name'], {})
            reads = [nodes[e['source']]['name'] for e in incoming if e['action']=='read']
            outputs = [nodes[e['target']]['name'] for e in outgoing if e['action']=='write']
            n['role'] = '数据处理' if reads and outputs else '写入' if outputs else '调度' if any(e['action']=='PROCESS_CALL' for e in outgoing) else '程序'
            n['summary'] = ('读取 ' + '、'.join(reads[:2]) + (' 等对象' if len(reads)>2 else '') + '；' if reads else '')
            modes = s.get('modes', {})
            n['summary'] += '、'.join(('累加' if m=='INCREMENT' else '覆盖')+f' {v} 处' for m,v in modes.items()) or ('写入 '+str(len(outputs))+' 个对象' if outputs else '按源码调用子程序。' if any(e['action']=='PROCESS_CALL' for e in outgoing) else '当前范围仅确认读取，其他处理见源码证据。')
            n['slices'] = [dict(target=nodes[e['target']]['name'], **sl) for e in outgoing for sl in e['slices']]
        elif n['kind']=='rule':
            s = rule_summaries.get(n['name'], {})
            n['role'] = '规则'
            n['summary'] = f"{s.get('rule_count', len(n['object_ids']))} 条 Rule；按区域与表达式计算，完整语义见证据。"
        else:
            n['role'], n['summary'] = '调度', '本地已记录的 Chore 调度定义，未证明启用或运行。'

    proof_ids = {i for e in kept for i in e['evidence_refs']}
    return dict(schema=VERSION, entry=report.get('module', {}), note=NOTE,
        model_fingerprint=report.get('source_fingerprint'), runtime_verified=False,
        nodes=sorted(nodes.values(), key=lambda n:(n['kind'], n['name'], n['id'])),
        edges=kept, evidence=[f for f in report.get('relation_evidence', []) if f['id'] in proof_ids],
        statistics=dict(nodes=len(nodes), edges=len(kept), folded=dict(sorted(hidden.items())),
                        truncated=bool(hidden['budget'] or report.get('_truncated') or report.get('unified_model', {}).get('truncated'))),
        context_document='Architecture.json', include_context=include_context,
        limitations=['业务角色仅基于当前范围内的读写事实，非人工确认的业务用途。',
                     'Rule 归组便于阅读；独立语句、条件与未确认坐标保留在证据层。',
                     'Data 行值来源和运行贡献未因展示投影获得额外确认。'])


def from_artifact(path, **options):
    """Read compact existing SQLite sections. Never load all source or Rule trees."""
    from tm1_insight import workflow
    report = {}
    with closing(workflow.connection(path)) as con:
        report.update(json.loads(con.execute("SELECT payload FROM meta WHERE key='header'").fetchone()[0]))
        for section, limit in [('relation_objects',12000), ('unified_relations',30000), ('cubes',1000),
                               ('business_steps',500), ('rule_summaries',1000), ('relation_evidence',30000)]:
            rows = con.execute('SELECT payload FROM items WHERE section=? ORDER BY position LIMIT ?', [section,limit+1]).fetchall()
            report[section] = [json.loads(r[0]) for r in rows[:limit]]
            report['_truncated'] = report.get('_truncated', False) or len(rows)>limit
        # Only compact write coordinates, not nested definition DAGs / expressions.
        rows = con.execute("SELECT position,json_extract(payload,'$.target_coordinates'),json_extract(payload,'$.conditions') FROM items WHERE section='write_explanations' ORDER BY position LIMIT 2001").fetchall()
        report['_write_contexts'] = {f'/write_explanations/{i}':dict(target_coordinates=json.loads(coords or '[]'),conditions=json.loads(conditions or '[]')) for i,coords,conditions in rows[:2000]}
        report['_truncated'] |= len(rows)>2000
    return assemble(report, **options)


def mermaid(flow):
    # Numeric character entities prevent quotes/brackets/newlines injecting syntax.
    def label(value):
        return ''.join(c if c.isalnum() or c in ' .·' else f'#{ord(c)};' for c in str(value))
    lines = ['flowchart LR']
    ids = {n['id']:f'n{i}' for i,n in enumerate(flow['nodes'])}
    for n in flow['nodes']:
        lines.append(f'  {ids[n["id"]]}["{label(n["title"])} · {label(n["role"])}"]')
    for e in flow['edges']:
        arrow = '-.->' if e['action'] in {'PROCESS_CALL','CHORE_SCHEDULE'} else '-->'
        lines.append(f'  {ids[e["source"]]} {arrow}|"{label(e["label"])}"| {ids[e["target"]]}')
    return '\n'.join(lines)+'\n'


def markdown(flow):
    def safe(v):
        return escape(str(v)).replace('|','\\|').replace('\n',' ').replace('`','\\`')
    yield '# 业务流程图 / Functional Flow\n\n' + safe(flow['entry'].get('name','')) + '\n\n'+flow['note']+'\n\n'
    if flow['statistics']['truncated']:
        yield '**范围达到展示预算，图不完整；请缩小入口范围或查看完整架构导出。**\n\n'
    yield '```mermaid\n'+mermaid(flow)+'```\n\n## 对象与作用\n\n|对象|角色|作用摘要|\n|---|---|---|\n'
    for n in flow['nodes']:
        yield '|'+ '|'.join(safe(n[k]) for k in ('title','role','summary'))+'|\n'
    names = {n['id']:n['title'] for n in flow['nodes']}
    yield '\n## 动作与关键切面\n\n'
    for e in flow['edges']:
        yield '- '+safe(names[e['source']])+' → '+safe(e['label'])+' → '+safe(names[e['target']])+'\n'
        for s in e['slices']:
            yield '  - '+safe('；'.join(c['dimension']+' = '+c['value'] for c in s['coordinates']))+f'（{s["write_sites"]} 个写入点'+('；含条件' if s['conditional'] else '')+'）\n'
    yield '\n<details><summary>技术证据与限制（默认折叠）</summary>\n\n'
    for f in flow['evidence']:
        yield '- '+safe(f.get('process') or f.get('cube') or f.get('chore') or '')+' / '+safe(f.get('section') or f.get('table') or '')+':'+str(f.get('line',''))+' · '+f['id']+'\n'
    for e in flow['edges']:
        if e['unresolved_reasons']:
            yield '- '+safe(names[e['source']])+' → '+safe(names[e['target']])+': '+safe('; '.join(e['unresolved_reasons']))+'\n'
    yield '\n关联语句与写入点使用 JSON 的 context_refs 对应 Architecture.json；请配套保留。\n\n'
    yield '\n'.join('- '+safe(s) for s in flow['limitations'])+'\n\n</details>\n'
