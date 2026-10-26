"""G1 presentation projection of existing Calculation and Rule IR; no parser."""
import hashlib
import json
import re

VERSION = 'cube-formation-answer-1'


def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def human_reason(reason):
    return re.sub(r'^[A-Z][A-Z_]+:\s*', '', str(reason))


def coordinates(mapping):
    result = []
    for c in (mapping or {}).get('items', []):
        b = c.get('binding') or {}
        kind = b.get('kind')
        state = 'FIXED' if kind == 'FIXED_MEMBER' else 'DYNAMIC' if kind in {'PARAMETER', 'DATA_ROW_VARIABLE', 'LOOKUP_COORDINATE'} else 'UNRESOLVED'
        result.append(dict(dimension=c.get('dimension'), position=c.get('position'), kind=state,
                           expression=b.get('value') if state == 'FIXED' else b.get('expression'), evidence=b.get('evidence', [])))
    return result


def match(coords, dimension='', member=''):
    if not dimension: return 'OVERVIEW'
    found = [c for c in coords if c['dimension'] == dimension]
    if not found or any(c['kind'] != 'FIXED' for c in found): return 'POSSIBLE'
    return 'MATCH' if any(str(c['expression']) == member for c in found) else 'EXCLUDED'


def ti(report, snapshot, cube, dimension='', member=''):
    nodes = {n['id']: n for n in report['nodes']}
    groups, problems = [], {}
    writes = [w for w in report['writes'] if w.get('cube') == cube]
    for w in writes[:80]:
        coords = coordinates(w.get('coordinate_mapping'))
        matching = match(coords, dimension, member)
        if matching == 'EXCLUDED': continue
        gid = key([snapshot, report['process'], w['id']])
        # Follow only the existing value subtree, not coordinate/control reads.
        seen, pending = set(), [w['value_node']]
        while pending:
            i = pending.pop()
            if i in seen: continue
            seen.add(i)
            pending.extend(nodes[i].get('children', []))
        value_nodes = [nodes[i] for i in sorted(seen)]
        bad = [n for n in value_nodes if n['kind'] == 'unknown' or n['kind'] == 'read' and n.get('resolution') != 'resolved']
        reads = [nodes[i] for i in w.get('read_nodes', []) if nodes[i].get('cube') and nodes[i].get('resolution') == 'resolved']
        rows = [d for d in w.get('data_row_value_dependencies', []) if d.get('source_cube') and (d.get('source_field') or {}).get('kind') == 'CELL_VALUE' and d.get('field_status') == 'STATIC_NATIVE_LAYOUT']
        fields = [d for d in w.get('data_row_value_dependencies', []) if d.get('source_cube') and (d.get('source_field') or {}).get('kind') == 'DIMENSION_MEMBER' and d.get('field_status') == 'STATIC_NATIVE_LAYOUT']
        row_unbound = any(n['kind'] == 'data_row' and n.get('field_status') != 'STATIC_NATIVE_LAYOUT' for n in value_nodes)
        leaf_kinds = {n['kind'] for n in value_nodes if not n.get('children')}
        external = any(n['kind'] in {'read','data_row'} for n in value_nodes)
        constant = bool(value_nodes) and leaf_kinds <= {'number', 'redacted_string'} and not bad and not external
        parameter = not bad and not external and 'parameter' in leaf_kinds and leaf_kinds <= {'parameter', 'number', 'redacted_string'}
        value_kind = 'CONSTANT' if constant else 'PARAMETER' if parameter else 'SOURCE_EXPRESSION' if reads or rows or fields else 'UNRESOLVED'
        state = 'PARTIAL' if bad or row_unbound else 'CONFIRMED_STATIC' if value_kind != 'UNRESOLVED' else 'UNRESOLVED'
        blockers = []
        reasons = list(w.get('unresolved_binding_reasons') or []) if bad or row_unbound else []
        ctx = report.get('data_row_lineage') or {}
        if (bad or row_unbound) and ctx.get('source_view_binding') and not ctx.get('data_source_variable_bindings'):
            reasons = ['缺少可用的 Process Variables 与行布局绑定；无法确认 Data 行值来源']
        if not reasons:
            reasons = sorted({n.get('reason') or '读取目标表达式尚未解析' for n in bad})
        if value_kind == 'UNRESOLVED' and not reasons: reasons = ['现有值表达式未建立可靠来源定义']
        for reason in reasons:
            pid = key([snapshot, report['process'], reason])
            blockers.append(pid)
            item = problems.setdefault(pid, dict(id=pid, object=report['process'], reason=human_reason(reason),raw_reason=reason,
                action='核对所列源码的变量定义与当前快照的 Variables / View 元数据；不根据变量名补造来源。', affected=[]))
            item['affected'].append(gid)
        sources = [dict(kind='CELL_READ', cube=n['cube'], coordinates=coordinates(n.get('coordinate_mapping')), evidence=n['evidence']) for n in reads]
        sources += [dict(kind='VIEW_VALUE', cube=d['source_cube'], view=d.get('source_view'), variable=d['variable'],
                        coordinates=ctx.get('source_coordinate_mapping', []), evidence=d.get('metadata_evidence')) for d in rows]
        sources += [dict(kind='VIEW_FIELD', cube=d['source_cube'], view=d.get('source_view'),variable=d['variable'],
                        field=d['source_field'], evidence=d.get('metadata_evidence')) for d in fields]
        groups.append(dict(id=gid, kind='TI', owner=report['process'], target=cube, coordinates=coords,
            match=matching, operation=w['operation'], expression=w.get('formula_expression') or w['value_expression'],
            value_expression=w['value_expression'], value_kind=value_kind, evidence_state=state,
            sources=sources, conditions=w.get('control_context', []), blocker_refs=blockers,
            location=w['evidence'], evidence=dict(write=w, value_nodes=value_nodes), runtime_verified=False))
    diagnostics=report.get('diagnostics',[])
    return dict(groups=groups, blockers=list(problems.values()), available=len(writes), retained=min(len(writes),80),
                source_hash=report.get('source_hash'), incomplete=bool(diagnostics),
                truncated=len(writes)>80 or any('预算' in str(d) for d in diagnostics),
                diagnostics=diagnostics,limits=report.get('limits', []))


def rule(parsed, snapshot, cube, dimension='', member=''):
    groups, problems = [], []
    for r in parsed.get('rules', [])[:80]:
        coords = [dict(dimension=c.get('dimension'), position=i+1,
                       kind='FIXED' if c.get('dimension') and c.get('member') is not None else 'UNRESOLVED',
                       expression=c.get('member') or c.get('raw') or str(c.get('members', [])))
                  for i,c in enumerate((r.get('lhs') or {}).get('coordinates', []))]
        matching = match(coords, dimension, member)
        if matching == 'EXCLUDED': continue
        gid = key([snapshot, cube, r.get('line_start'), r.get('raw')])
        reasons = r.get('unresolved_reasons', [])
        ids = []
        for reason in reasons:
            pid = key([snapshot,cube,reason]); ids.append(pid)
            existing = next((p for p in problems if p['id']==pid),None)
            if existing: existing['affected'].append(gid)
            else: problems.append(dict(id=pid,object=cube,reason=human_reason(reason),raw_reason=reason,action='核对 Rule 源码、成员归属及 DB 参数；保留已确认引用。',affected=[gid]))
        groups.append(dict(id=gid,kind='RULE',owner=cube,target=cube,coordinates=coords,area=(r.get('lhs') or {}).get('raw'),
            match=matching,operation='RULE',expression=(r.get('rhs') or {}).get('expression'),value_kind='RULE_EXPRESSION',
            evidence_state='CONFIRMED_STATIC' if r.get('status')=='PARSED' else 'UNRESOLVED' if r.get('status')=='UNKNOWN' else 'PARTIAL',
            sources=[dict(kind='RULE_DB',cube=d['cube'],coordinates=d.get('coordinates'),evidence=d) for d in r.get('db_references',[]) if d.get('cube_resolved')],
            conditions=r.get('conditions',[]),blocker_refs=ids,location=dict(section='Rule',line=r.get('line_start'),column=1),evidence=r,runtime_verified=False))
    return dict(groups=groups,blockers=problems,available=len(parsed.get('rules',[])),retained=min(80,len(parsed.get('rules',[]))),
                truncated=len(parsed.get('rules',[]))>80,feeder_count=len(parsed.get('feeders',[])))
