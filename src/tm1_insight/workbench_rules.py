"""Cube-first presentation of the existing Unified Relations Rule/Feeder facts."""
from tm1_insight import unified_relations
from tm1_insight.workbench import stable_id


def project(parsed, snapshot):
    if not parsed.get('available'): return []
    cube=parsed['cube']
    report={'rules':[dict(cube=cube,source_hash=parsed['source_hash'],
                         rule_semantics=parsed['rules'],feeder_semantics=parsed['feeders'])]}
    unified_relations.enrich(report)
    objects={o['id']:o for o in report['relation_objects']}
    evidence={e['id']:e for e in report['relation_evidence']}
    grouped={}
    for relation in report['unified_relations']:
        rk=relation['relation_kind']
        if rk not in {'RULE_DB_REFERENCE','FEEDER_DB_REFERENCE'} or relation['status']!='SOURCE_CONFIRMED':continue
        is_rule=rk=='RULE_DB_REFERENCE'
        other=objects[relation['source'] if is_rule else relation['target']]['name']
        source,target=(other,cube) if is_rule else (cube,other)
        kind='RULE_REFERENCE' if is_rule else 'FEEDER_REFERENCE'
        # Confirmation of a Cube reference does not confirm its complete formula.
        semantic=relation['semantic_status']
        key=(source,target,kind,semantic)
        edge=grouped.setdefault(key,dict(id=stable_id(snapshot,*key),source=stable_id(snapshot,'cube',source),target=stable_id(snapshot,'cube',target),
            kind=kind,label='规则引用' if is_rule else 'Feeder 支持（非值流）',provenance='STATIC_ANALYSIS',
            status='SOURCE_CONFIRMED',semantic_status=semantic,runtime_verified=False,evidence=[],unresolved_reasons=[]))
        edge['evidence'] += [evidence[e] for e in relation['evidence']]
        edge['unresolved_reasons'] += relation['unresolved_reasons']
        edge['unresolved_reasons'].append('已确认 Cube 引用；完整公式、坐标和运行结果仍须核对。' if is_rule else 'Feeder 仅表示稀疏计算支持，不是普通数值计算或值传输。')
    for e in grouped.values():
        e['evidence']=sorted({v['id']:v for v in e['evidence']}.values(),key=lambda v:v['id'])
        e['unresolved_reasons']=sorted(set(e['unresolved_reasons']))
    return sorted(grouped.values(),key=lambda e:e['id'])
