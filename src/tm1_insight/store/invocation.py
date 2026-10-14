"""One observed invocation and one child, without substitution or recursion."""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from tm1_insight.learning.calculation import SENSITIVE
from tm1_insight.store.calculation import inspect


def inspect_call(con, name, call_id):
    caller = inspect(con, name)
    if caller is None:
        return None
    call = next((c for c in caller['calls'] if c['id'] == call_id), None)
    if call is None:
        return None
    result = dict(schema='ti-invocation-inspection-1', process=name, source_hash=caller['source_hash'],
        runtime_verified=False, status='PARTIAL', scope='one_call_one_child_no_substitution',
        call=call, nodes=caller['nodes'], child=None, bindings=[], omitted_parameters=[], diagnostics=[])
    if call['operation'].casefold() != 'executeprocess' or call['status'] != 'resolved' or not call['target']:
        result['diagnostics'].append('UNKNOWN · 仅展开具有目录内字面目标的 ExecuteProcess；动态目标和 RunProcess 保持独立调用观察。')
        return result
    child = inspect(con, call['target'])
    if child is None:
        result['diagnostics'].append('UNKNOWN · 被调用 TI 不存在。')
        return result
    result['child'] = child
    for label, report in [('调用方',caller),('子 TI',child)]:
        for diagnostic in report['diagnostics']:
            result['diagnostics'].append(label+' · '+str(diagnostic.get('reason',diagnostic) if isinstance(diagnostic,dict) else diagnostic))
    row = con.execute('SELECT parameters FROM processes WHERE name=?', [child['process']]).fetchone()
    try:
        parameters = json.loads(row[0] or '[]')
    except (ValueError, TypeError):
        parameters = []
    declared = [p['name'] for p in parameters if isinstance(p, dict) and isinstance(p.get('name'), str)] if isinstance(parameters,list) else []
    counts = Counter(n.casefold() for n in declared)
    canonical = {hashlib.sha256(n.casefold().encode()).hexdigest(): n for n in declared}
    provided = Counter(b['parameter_hash'] for b in call['arguments'])
    by_id = {n['id']: n for n in child['nodes']}

    def parameter_uses(root, stop_reads=False):
        pending, seen, found = [root], set(), []
        while pending:
            index = pending.pop()
            if index in seen:
                continue
            seen.add(index)
            node = by_id[index]
            if node['kind'] == 'parameter':
                found.append(node)
            if node['kind'] != 'unknown' and not (stop_reads and node['kind']=='read'):
                pending.extend(node['children'])
        return found

    usages = {}
    usage_count = 0
    for write in child['writes']:
        if usage_count >= 2000:
            result['diagnostics'].append('PARTIAL · 参数使用位置达到 2000 条预算；后续位置未展开。')
            break
        roots = [('write_value', write['value_node'], True), ('write_target',write['target_node'],False)]
        roots += [('write_coordinate', n, False) for n in write['coordinates']]
        for index in write['read_nodes']:
            read = by_id[index]
            roots += [('read_coordinate', n, False) for n in read['coordinates']]
            if read['children']:
                roots.append(('read_target',read['children'][0],False))
        for role, root, stop in roots:
            if usage_count >= 2000:
                break
            for node in parameter_uses(root, stop):
                if usage_count >= 2000:
                    break
                usage = dict(role=role, parameter_evidence=node['evidence'], write_id=write['id'],
                    write_evidence=write['evidence'], cube=write['cube'], operation=write['operation'],
                    write_expression=write['formula_expression'], control_context=write['control_context'])
                records = usages.setdefault(node['name'].casefold(), [])
                if usage not in records:
                    records.append(usage)
                    usage_count += 1
    if usage_count >= 2000 and not any('2000' in d for d in result['diagnostics']):
        result['diagnostics'].append('PARTIAL · 参数使用位置达到 2000 条预算，可能还有位置未展开。')
    for binding in call['arguments']:
        parameter = canonical.get(binding['parameter_hash'])
        reason = None
        if not call['argument_pairs_complete']:
            reason = '参数名/值没有完整配对'
        elif parameter is None:
            reason = '参数名不是可确认的子 TI 声明；原字符串已隐藏'
        elif SENSITIVE.search(parameter):
            reason = '敏感参数未展开'
        elif counts[parameter.casefold()] != 1 or provided[binding['parameter_hash']] != 1:
            reason = '重复参数，不能确定有效绑定'
        result['bindings'].append(dict(**binding, parameter=parameter if parameter and not SENSITIVE.search(parameter) else None,
            status='UNKNOWN' if reason else 'EXPLICIT_BINDING', reason=reason,
            uses=[] if reason else usages.get(parameter.casefold(), [])))
    result['omitted_parameters'] = [n for h,n in canonical.items() if h not in provided and not SENSITIVE.search(n)]
    result['diagnostics'] += ['仅连接源码参数绑定和子 TI 中仍可追踪的参数使用，不替换公式、不证明调用成功或实际数值。',
        '参数类型未验证，缺省参数值未使用或导出；没有使用记录不代表参数未使用。分支、循环、参数覆盖和不支持的语法可能阻断追踪。',
        '子 TI 的其他调用不展开，结果不是完整功能模块或迁移等价证明。']
    return result


def markdown(report):
    from html import escape
    def clean(value):
        return escape(str(value)).replace('`','\\`').replace('\n',' ')
    lines = ['# 单次子 TI 参数检查', f"调用方：{clean(report['process'])}", f"源码哈希：{report['source_hash']}",
             f"模型指纹：{report.get('model_fingerprint','UNKNOWN')}", '范围：一个调用点与一个子 TI；未执行、未替换公式。']
    child = report['child']
    if child:
        lines += [f"子 TI：{clean(child['process'])}", f"子 TI 源码哈希：{child['source_hash']}"]
    nodes = {n['id']:n for n in report['nodes']}
    lines.append('Markdown 概览展示前 50 个参数，每类最多 20 条定义/读取/未知项/使用；坐标及完整预算内记录见 JSON。')
    for b in report['bindings'][:50]:
        e = b['evidence']
        lines += [f"- {clean(b['parameter'] or 'UNKNOWN')} ← {clean(b['expression'])} · {b['status']} · {e['section']}:{e['line']}:{e['column']}"]
        if b['reason']:
            lines.append('  - UNKNOWN：'+clean(b['reason']))
        for index in b['definition_nodes'][:20]:
            n=nodes[index];e=n['evidence']
            lines.append(f"  - 调用方定义：{clean(n['variable'])} = {clean(n['expression'])} · {e['section']}:{e['line']}:{e['column']}")
        for index in b['read_nodes'][:20]:
            n=nodes[index];e=n['evidence']
            lines.append(f"  - 调用方读取：{clean(n['cube'] or 'UNKNOWN')} · {e['section']}:{e['line']}:{e['column']}")
        for index in b['unknown_nodes'][:20]:
            lines.append('  - UNKNOWN：'+clean(nodes[index].get('reason','对象未解析')))
        for u in b['uses'][:20]:
            e = u['parameter_evidence']
            lines.append(f"  - {u['role']} · {e['section']}:{e['line']}:{e['column']} → {clean(u['cube'] or 'UNKNOWN')} · 写入点 {u['write_id']}")
            if u['role']=='write_value':
                lines.append('    - 子 TI 原定义：'+clean(u['write_expression']))
            if u['control_context']:
                lines.append('    - 条件/循环内，路径与次数未求值。')
    lines += ['- 未显式传入：'+clean(', '.join(report['omitted_parameters']) or '无可列出的声明'),
              *['- '+clean(d) for d in report['diagnostics']]]
    if len(lines)>2000:
        lines = lines[:2000]+['PARTIAL · Markdown 达到 2000 行预算；完整预算内记录见 JSON。']
    return '\n'.join(lines)+'\n'
