"""Selected-process worksheet adapter; no whole-model graph construction."""
from __future__ import annotations
import json
from tm1_insight.learning.calculation import worksheet


def inspect(con, name, *, catalogs=None):
    row = con.execute("SELECT prolog,metadata,data,epilog,parameters FROM processes WHERE name=?", [name]).fetchone()
    if row is None: return None
    if catalogs is None:
        catalogs = {kind: {r[0] for r in con.execute(f"SELECT name FROM {table}").fetchall()}
                    for kind,table in (("cube","cubes"),("process","processes"),("dimension","dimensions"))}
    try: parameters = json.loads(row[4]) if row[4] else []
    except (ValueError, TypeError): parameters = []
    names = [p.get('Name',p.get('name','')) if isinstance(p,dict) else p for p in parameters] if isinstance(parameters,list) else []
    names = [p for p in names if isinstance(p,str) and p]
    from tm1_insight.store.data_row import context, attach
    parts = tuple(value or '' for value in row[:4])
    row_context, row_symbols = context(con, name, parts, catalogs, names)
    result = worksheet(name, parts, catalogs, names, retain_constants=True, row_symbols=row_symbols)
    constants=result.pop('_constant_values',{})
    from tm1_insight.learning.calculation import SENSITIVE
    result['parameter_names'] = [p for p in names if not SENSITIVE.search(p)]
    cubes = {w['cube'] for w in result['writes'] if w['cube']}
    cubes.update(node['cube'] for node in result['nodes'] if node['kind']=='read' and node['cube'])
    structures = {}
    if cubes:
        placeholders = ','.join('?' for _ in cubes)
        rows = con.execute(f"""SELECT cube.name,cube.dimension_count,rel.dimension_name,rel.dim_order,dim.name IS NOT NULL
            FROM cubes cube LEFT JOIN cube_has_dimension rel ON rel.cube_name=cube.name
            LEFT JOIN dimensions dim ON rel.dimension_name=dim.name
            WHERE cube.name IN ({placeholders}) ORDER BY cube.name,rel.dim_order""", sorted(cubes)).fetchall()
        for cube, count, dim, order, exists in rows:
            info = structures.setdefault(cube, dict(dimensions=[], declared_count=count))
            if dim is not None: info['dimensions'].append(dict(name=dim, order=order, exists=exists))
        for info in structures.values():
            dims = info['dimensions']
            info['complete_order'] = bool(dims and info['declared_count']==len(dims) and
                len({d['name'] for d in dims})==len(dims) and all(d['order']==i for i,d in enumerate(dims)))
    def coordinates(cube, values):
        info = structures.get(cube, {})
        dims = info.get('dimensions', [])
        matched = bool(info.get('complete_order') and len(dims)==len(values))
        return dict(status='recorded_order' if matched else 'UNKNOWN', evidence=dict(table='cube_has_dimension',cube=cube,basis='dim_order'),
            expected=len(dims) if info.get('complete_order') else None,
            actual=len(values), items=[dict(position=i+1, node=node, dimension=dims[i]['name'] if matched else None,
                dimension_exists=dims[i]['exists'] if matched else False) for i,node in enumerate(values)])
    for write in result['writes']:
        write['coordinate_mapping'] = coordinates(write['cube'], write['coordinates'])
        if write['coordinate_mapping']['status']=='UNKNOWN' and write['trace_status']!='UNKNOWN': write['trace_status']='PARTIAL'
    for node in result['nodes']:
        if node['kind']=='read': node['coordinate_mapping'] = coordinates(node['cube'], node['coordinates'])
    by_id = {node['id']:node for node in result['nodes']}
    for write in result['writes']:
        root = by_id[write['value_node']]
        definition = by_id.get(root.get('definition'))
        write['formula_expression'] = (definition['variable']+' = '+definition['expression']
            if definition and definition['kind']=='assignment' else write['value_expression'])
        if write['trace_status']!='UNKNOWN' and any(by_id[index]['coordinate_mapping']['status']=='UNKNOWN' for index in write['read_nodes']):
            write['trace_status']='PARTIAL'
    _coordinate_bindings(con,result,constants)
    result['cube_structures'] = structures
    attach(result, row_context)
    return result


def _coordinate_bindings(con,report,constants):
    """Expose only catalog-verified member strings used as coordinates, never arbitrary constants."""
    nodes={n['id']:n for n in report['nodes']}
    def binding(index,depth=0):
        if depth>40:return dict(kind='UNRESOLVED',expression='定义链超过预算',evidence=[])
        n=nodes[index];kind=n['kind'];evidence=[n['evidence']]
        if kind in {'variable','assignment'} and n['children']:
            b=binding(n['children'][0],depth+1);return dict(b,evidence=evidence+b['evidence'])
        if kind=='parameter':return dict(kind='PARAMETER',expression=n['name'],evidence=evidence)
        if kind=='data_row':return dict(kind='DATA_ROW_VARIABLE',expression=n['name'],evidence=[],
            metadata_evidence=n['binding']['evidence'])
        if kind=='number':return dict(kind='NUMBER',expression=n['value'],value=n['value'],evidence=evidence)
        if kind=='read' and n['resolution']=='resolved':return dict(kind='LOOKUP_COORDINATE',expression=n['operation']+'('+n['cube']+', …)',source_cube=n['cube'],evidence=evidence)
        if kind=='redacted_string':return dict(kind='LITERAL_CANDIDATE',_value=constants.get(index),evidence=evidence)
        return dict(kind='UNRESOLVED',expression=n.get('name') or n.get('expression') or '动态坐标',reason=n.get('reason'),evidence=evidence)
    mappings=[w['coordinate_mapping'] for w in report['writes']]+[n['coordinate_mapping'] for n in report['nodes'] if n['kind']=='read']
    candidates={};pending=[]
    for m in mappings:
        for item in m['items']:
            b=binding(item['node']);pending.append((item,b))
            if b['kind']=='LITERAL_CANDIDATE' and b['_value'] is not None and item['dimension']:
                candidates.setdefault(item['dimension'],set()).add(b['_value'])
    present={}
    for dim,values in sorted(candidates.items()):
        values=sorted(values);slots=','.join('?' for _ in values)
        sql=f"""SELECT DISTINCT coalesce(json_extract_string(e.value,'$.name'),json_extract_string(e.value,'$'))
            FROM json_each((SELECT CASE WHEN json_type(try_cast(elements AS JSON))='ARRAY' THEN elements ELSE '[]' END FROM dimensions WHERE name=?)) e
            WHERE coalesce(json_extract_string(e.value,'$.name'),json_extract_string(e.value,'$')) IN ({slots})"""
        present[dim]={r[0] for r in con.execute(sql,[dim]+values).fetchall()}
    for item,b in pending:
        if b['kind']=='LITERAL_CANDIDATE':
            value=b.pop('_value')
            if value is not None and value in present.get(item['dimension'],set()):
                b.update(kind='FIXED_MEMBER',value=value,expression=repr(value),member_evidence=dict(table='dimensions',dimension=item['dimension'],member=value))
            else:b.update(kind='UNRESOLVED',expression='固定字符串待成员目录确认',reason='不公开未经成员目录验证的字符串')
        item['binding']=b


def node_label(node):
    return (node.get('name') or node.get('value') or node.get('expression') or
            (node.get('operation','')+' · '+(node.get('cube') or 'UNKNOWN') if node['kind']=='read' else
             '字符串常量已隐藏' if node['kind']=='redacted_string' else node.get('operator') or node.get('reason') or node['kind']))


def markdown(report):
    from html import escape
    def esc(value): return escape(str(value)).replace('`','\\`').replace('\n',' ')
    nodes = {n['id']:n for n in report['nodes']}
    lines = ['# TI 计算检查', '', f"过程：{esc(report['process'])}", f"源码哈希：{report['source_hash']}",
             f"模型指纹：{report.get('model_fingerprint','未提供模型上下文')}",
             '', '范围：单个 TI，未展开子进程。静态定义依赖不证明运行时值或迁移等价。字符串常量已隐藏。', '']
    def coordinate_lines(mapping, label):
        values = [f"- {label}映射：{mapping['status']} · 实际 {mapping['actual']} / 结构要求 {mapping['expected'] if mapping['expected'] is not None else 'UNKNOWN'}"]
        for c in mapping['items']:
            n=nodes[c['node']];e=n['evidence']
            values.append(f"  - 位置 {c['position']} / {esc(c['dimension'] or 'UNKNOWN')}：{esc(node_label(n))} · {e['section']}:{e['line']}:{e['column']}")
        return values
    for write in report['writes']:
        loc=write['evidence']
        lines += [f"## 写入 {write['id']+1} · {esc(write['operation'])} → {esc(write['cube'] or 'UNKNOWN')}",
                  f"依据：{loc['section']}:{loc['line']}:{loc['column']} · {write['trace_status']}",
                  f"值表达式：`{esc(write['value_expression'])}`", f"源定义：`{esc(write['formula_expression'])}`", '']
        for context in write['control_context']:
            lines.append(f"- 控制边界：{context['kind']} · {context['section']}:{context['line']} · {esc(context['condition'])}；未验证可达性或迭代次数。")
        for index in write['definition_nodes']:
            n=nodes[index];e=n['evidence']
            lines.append(f"- 定义 `{esc(n['variable'])} = {esc(n['expression'])}` · {e['section']}:{e['line']}:{e['column']}")
        for index in write['read_nodes']:
            n=nodes[index];e=n['evidence']
            lines.append(f"- 静态读取依赖：{esc(n.get('cube') or 'UNKNOWN')} · {n['operation']} · {e['section']}:{e['line']}:{e['column']}")
            lines += coordinate_lines(n['coordinate_mapping'], '读取坐标')
        lines += coordinate_lines(write['coordinate_mapping'], '目标坐标')
        for index in write['unknown_nodes']:
            lines.append(f"- UNKNOWN：{esc(node_label(nodes[index]))} · {esc(nodes[index].get('reason','对象尚未解析'))}")
        lines.append('')
    lines += ['## 独立调用边界', '源码位置次序，不代表实际执行或完成次序；不从调用推导值流。']
    lines += [f"- {esc(c['operation'])} → {esc(c['target'] or 'UNKNOWN')} · {c['section']}:{c['line']}:{c['column']}" for c in report['calls']]
    lines += ['', '## 限制', *['- '+esc(value) for value in report.get('limits',[])],
              *['- '+esc(value.get('reason',value) if isinstance(value,dict) else value) for value in report['diagnostics']]]
    return '\n'.join(lines)+'\n'
