"""Compact human-facing views over existing Rule statements, not a parser."""
from contextlib import closing
import json


def rule_row(cube, statement, context_ref):
    lhs, rhs = statement.get('lhs', {}), statement.get('rhs', {})
    fixed = [dict(dimension=c['dimension'], value=c.get('member') or c.get('members'),
                  basis='LITERAL_RULE_REGION') for c in lhs.get('coordinates', [])
             if c.get('dimension') and c.get('dimension_resolution')=='EXPLICIT_LABEL_IN_CUBE' and c.get('kind') in {'single','set'}]
    refs = statement.get('db_references', [])
    return dict(cube=cube, line=statement.get('line_start'), line_end=statement.get('line_end'),
        target_area=lhs.get('raw',''), sources=sorted({r['cube'] for r in refs if r.get('cube_resolved') and r.get('cube')}),
        has_if=any(c.get('func','').upper()=='IF' for c in statement.get('conditions', [])),
        fixed_slices=fixed, expression=rhs.get('expression','')[:500],
        expression_truncated=len(rhs.get('expression',''))>500,
        context_ref=context_ref, details=dict(status=statement.get('status','UNKNOWN'),
            unresolved_reasons=statement.get('unresolved_reasons', []),
            unconfirmed_references=sum(not r.get('cube_resolved') for r in refs)))


def rule_page(path, offset=0, limit=25, q='', cubes=None):
    """SQLite expands existing statements; Python receives at most one compact page.

    Selecting scalar fields avoids returning each statement's potentially large AST.
    The old full Rule view and context API remain available unchanged.
    """
    from tm1_insight.workflow import connection
    where="i.section='rules' AND instr(lower(json_extract(i.payload,'$.cube')||' '||json_extract(r.value,'$.lhs.raw')||' '||json_extract(r.value,'$.rhs.expression')),?)>0"
    args=[q.casefold()]
    if cubes is not None:
        if not cubes:return dict(total=0,items=[])
        where+=" AND json_extract(i.payload,'$.cube') IN ("+','.join('?' for _ in cubes)+')'
        args.extend(sorted(cubes))
    source=" FROM items i, json_each(i.payload,'$.rule_semantics') r WHERE "+where
    with closing(connection(path)) as con:
        total=con.execute('SELECT count(*)'+source,args).fetchone()[0]
        rows=con.execute("""SELECT i.position,r.key,json_extract(i.payload,'$.cube'),json_object(
            'line_start',json_extract(r.value,'$.line_start'),'line_end',json_extract(r.value,'$.line_end'),
            'lhs',json_extract(r.value,'$.lhs'),'rhs',json_object('expression',json_extract(r.value,'$.rhs.expression')),
            'db_references',json_extract(r.value,'$.db_references'),'conditions',json_extract(r.value,'$.conditions'),
            'status',json_extract(r.value,'$.status'),'unresolved_reasons',json_extract(r.value,'$.unresolved_reasons'))"""+
            source+' ORDER BY i.position,cast(r.key AS INTEGER) LIMIT ? OFFSET ?', args+[limit,offset]).fetchall()
    return dict(total=total,items=[rule_row(cube,json.loads(value),f'/rules/{i}/rule_semantics/{j}') for i,j,cube,value in rows])


def flow(path, **options):
    from tm1_insight.functional_flow import from_artifact
    result=from_artifact(path,**options)
    rules=rule_page(path,limit=100,cubes={n['name'] for n in result['nodes'] if n['kind']=='rule'})
    result['rule_rows']=rules['items']
    result['rule_rows_total']=rules['total']
    return result
