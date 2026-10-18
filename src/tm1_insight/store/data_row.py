"""Evidence-backed datasource row symbols for the existing worksheet DAG.

Position denotes a SOURCE COLUMN, never a Cube dimension on its own. v1 can
derive a cell row only for a recorded NativeView and complete cube dimension
order, one String column per dimension and exactly one endmost value column.
MDX rowsets/properties/implicit slicers are deliberately unsupported.
"""
from __future__ import annotations
import hashlib
import json
import re

VERSION = 'data-row-1'
NATIVE_RULE = 'https://www.ibm.com/docs/en/planning-analytics/3.1.0?topic=source-define-cube-view-data'
VALUE_RULE = 'https://www.ibm.com/support/pages/change-variable-order-mdx-views-used-turbointegrator-data-source'
SECTIONS = ('prolog', 'metadata', 'data', 'epilog')


def source_hash(process):
    return hashlib.sha256(json.dumps({s: process.get(s) or '' for s in SECTIONS}, sort_keys=True).encode()).hexdigest()


def save_metadata(con, process):
    """Called only during explicit ingest/import, never read-only analysis."""
    from tm1_insight.store.schema import OBJECT_TABLES
    con.execute(OBJECT_TABLES['process_source_metadata'])
    payload = dict(schema=VERSION, source_hash=source_hash(process),
                   variables=process.get('variables'), datasource=process.get('datasource'),
                   source_view=process.get('source_view'),parameters=process.get('parameter_definitions',process.get('parameters')))
    if len(json.dumps(payload)) > 200_000:
        raise ValueError('Process metadata exceeds 200000 character budget')
    con.execute('INSERT OR REPLACE INTO process_source_metadata VALUES (?,?)',
                [process['name'], json.dumps(payload, ensure_ascii=False)])


def context(con, name, parts, catalogs, parameters):
    from tm1_insight.learning.calculation import SENSITIVE
    from tm1_insight.architecture_extraction import datasource
    from tm1_insight.learning.syntax import statements
    result = dict(schema=VERSION, process=name, source_hash=source_hash(dict(zip(SECTIONS, parts))),
                  runtime_verified=False, data_source_variable_bindings=[], source_view_binding=None,
                  source_coordinate_mapping=[], unresolved_binding_reasons=[])
    reasons = result['unresolved_binding_reasons']
    if not con.execute("SELECT 1 FROM information_schema.tables WHERE table_name='process_source_metadata'").fetchone():
        reasons.append('MISSING_VARIABLE_METADATA: 旧快照未保存 Process Variables；请仅补采该 Process。')
        return result, {}
    row = con.execute('SELECT payload FROM process_source_metadata WHERE process_name=? AND length(payload)<=200000', [name]).fetchone()
    try: meta = json.loads(row[0]) if row else {}
    except (ValueError, TypeError): meta = {}
    if not isinstance(meta,dict):meta = {}
    if meta.get('source_hash') != result['source_hash']:
        reasons.append('METADATA_SOURCE_MISMATCH: 元数据缺失或与当前四段源码不一致，不能绑定。')
        return result, {}
    variables = meta.get('variables')
    if not isinstance(variables, list) or len(variables) > 512:
        reasons.append('MISSING_VARIABLE_METADATA: Variables 缺失或超过 512 项预算。')
        return result, {}
    evidence = dict(table='process_source_metadata', process=name, source_hash=result['source_hash'], schema=VERSION)
    binding = datasource(parts, catalogs['cube'])
    critical = {'datasourcetype','datasourcenameforserver','datasourcecubeview'}
    overrides = any(t[0]['value'].casefold() in critical and len(t)>1 and t[1]['value']=='='
                    for t in statements(parts, include_logging=True))
    ds = meta.get('datasource') if isinstance(meta.get('datasource'),dict) else {}
    if not binding and not overrides and str(ds.get('type','')).casefold() in {'view','tm1cubeview'} and isinstance(ds.get('cube'),str) and ds['cube'] in catalogs['cube']:
        binding = dict(cube=ds['cube'], view=ds.get('view'), status='RECORDED_DATASOURCE', locations=[])
    if binding and binding.get('cube'):
        result['source_view_binding'] = dict(cube=binding['cube'], view=binding.get('view'),
            status=binding['status'], code_locations=binding.get('locations',[]), metadata_evidence=evidence,
            runtime_verified=False)
    else:
        reasons.append('SOURCE_BINDING_UNKNOWN: 当前 VIEW Cube/View 绑定缺失、动态、外部或被源码覆盖。')
    view = meta.get('source_view') if isinstance(meta.get('source_view'),dict) else {}
    actual = result['source_view_binding']
    recorded_native = bool(actual and actual['view'] and view.get('cube')==actual['cube'] and
        view.get('name')==actual['view'] and view.get('type')=='NativeView')
    # Saved view metadata cannot prove a view rebuilt by this process/helper.
    mutable_view = any(t['value'].casefold() in {'viewcreate','viewcreatebymdx','viewdestroy','executeprocess','runprocess'}
                       for tokens in statements(parts,include_logging=True) for t in tokens if t['kind']=='id')
    if mutable_view: recorded_native = False
    dims = []
    if actual:
        dims = con.execute('SELECT dimension_name,dim_order FROM cube_has_dimension WHERE cube_name=? ORDER BY dim_order', [actual['cube']]).fetchall()
        count = con.execute('SELECT dimension_count FROM cubes WHERE name=?',[actual['cube']]).fetchone()
        if not count or count[0]!=len(dims) or not dims or [d[1] for d in dims]!=list(range(len(dims))) or len({d[0] for d in dims})!=len(dims) or any(d[0] not in catalogs['dimension'] for d in dims):
            dims = []
    # Incremental metadata may be newer than the local Cube. Do not attach a
    # fresh view to stale dimension positions merely because TI code matches.
    recorded_native = recorded_native and view.get('dimension_order')==[d[0] for d in dims]
    def get(v,k): return v.get(k,v.get(k[0].lower()+k[1:]))
    names = [get(v,'Name') for v in variables if isinstance(v,dict)]
    positions = [get(v,'Position') for v in variables if isinstance(v,dict)]
    valid = bool(len(names)==len(variables) and all(isinstance(n,str) and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',n) for n in names)
                 and len({n.casefold() for n in names})==len(names) and all(type(p) is int and p>0 for p in positions)
                 and len(set(positions))==len(positions) and all(isinstance(get(v,'Type'),str) for v in variables)
                 and not {n.casefold() for n in names}.intersection(x.casefold() for x in parameters))
    if not valid:
        reasons.append('INVALID_VARIABLE_METADATA: 变量名或位置缺失/重复；不生成可复用定义。')
        return result, {}
    ordered = sorted(variables,key=lambda v:get(v,'Position'))
    layout = bool(recorded_native and dims and len(ordered)==len(dims)+1 and
                  sorted(positions)==list(range(1,len(ordered)+1)) and
                  all(get(v,'Type')=='String' for v in ordered[:-1]) and
                  get(ordered[-1],'Type') in {'Numeric','String'} and not any(SENSITIVE.search(n) for n in names))
    if not layout:
        reasons.append('ROW_LAYOUT_UNKNOWN: 需匹配且未重建的 NativeView、完整 Cube 顺序、连续列位置和唯一末列值；MDX/多值列不按维度位置猜测。')
    if actual:
        actual.update(view_kind=view.get('type','UNKNOWN'), row_layout_status='NATIVE_CELL_ROW' if layout else 'UNKNOWN',
                      membership_status='UNKNOWN', note='行布局不证明 Subset 成员、筛选结果或实际执行。')
    symbols = {}
    for v in ordered:
        n,p,typ = get(v,'Name'),get(v,'Position'),get(v,'Type')
        if SENSITIVE.search(n): continue
        b = dict(name=n,type=typ,position=p,start_byte=get(v,'StartByte'),end_byte=get(v,'EndByte'),
                 definition_status='RECORDED',position_status='RECORDED_SOURCE_COLUMN',
                 source_field_status='UNKNOWN',source_field=None,evidence=evidence)
        if layout:
            field = dict(kind='DIMENSION_MEMBER',dimension=dims[p-1][0]) if p<=len(dims) else dict(kind='CELL_VALUE')
            b.update(source_field_status='STATIC_NATIVE_LAYOUT',source_field=field,semantic_basis=[NATIVE_RULE,VALUE_RULE])
            if p<=len(dims):
                result['source_coordinate_mapping'].append(dict(dimension=dims[p-1][0],variable=n,source_column=p,
                    basis='NATIVE_VIEW_EXTRACTION_AND_RECORDED_CUBE_ORDER',evidence=evidence))
        result['data_source_variable_bindings'].append(b)
        if n.casefold() not in {x.casefold() for x in parameters} and typ in {'Numeric','String'}:
            symbols[n.casefold()] = dict(name=n,binding=b,source_cube=actual['cube'] if actual and layout else None,
                source_view=actual['view'] if actual and layout else None,
                field_kind=b['source_field']['kind'] if b['source_field'] else 'UNKNOWN',
                field_status=b['source_field_status'],source_coordinates=[])
    for symbol in symbols.values():
        if layout: symbol['source_coordinates'] = result['source_coordinate_mapping']
    return result, symbols


def attach(report, ctx):
    """Trace only the existing value DAG, never coordinate/control-only uses."""
    report['data_row_lineage'] = ctx
    nodes = {n['id']:n for n in report['nodes']}
    for write in report['writes']:
        seen, pending, inputs, uses = set(), [(write['value_node'],None)], [], {}
        while pending:
            i, use = pending.pop()
            if i in seen: continue
            seen.add(i); n = nodes[i]
            if n['kind']=='data_row': inputs.append(i); uses[i]=use; continue
            if n['kind'] in {'unknown','read'}: continue
            pending.extend((child,n['evidence'] if n['kind']=='variable' else use) for child in reversed(n['children']))
        write['data_row_value_dependencies'] = [dict(variable=nodes[i]['name'],node=i,
            field_status=nodes[i]['field_status'],source_cube=nodes[i]['source_cube'],source_view=nodes[i]['source_view'],
            source_field=nodes[i]['binding']['source_field'],metadata_evidence=nodes[i]['binding']['evidence'],
            use_location=uses[i] or write['evidence'],runtime_verified=False) for i in inputs]
        write['value_definition_chain'] = [dict(variable=nodes[i]['variable'],expression=nodes[i]['expression'],location=nodes[i]['evidence'])
                                          for i in write['definition_nodes']]
        write['data_row_binding_status'] = ('STATIC_CELL_VALUE_DEPENDENCY' if inputs and all(nodes[i]['field_kind']=='CELL_VALUE' for i in inputs)
                                            else 'VARIABLE_DEPENDENCY_ONLY' if inputs else 'NO_CONFIRMED_ROW_DEPENDENCY')
        write['unresolved_binding_reasons'] = list(ctx['unresolved_binding_reasons']) if inputs or any(nodes[i].get('name') for i in write['unknown_nodes']) else []
