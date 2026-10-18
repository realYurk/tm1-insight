"""Bounded, non-executing use/definition worksheet for one TI.

Arithmetic is a syntax DAG. Only explicit CellGet values and known definitions
become static value dependencies. Unknown functions/control merges stop tracing.
String values are redacted; object names come only from the model catalog.
"""
from __future__ import annotations

import hashlib
import json
import re

from tm1_insight.learning.syntax import calls, expression, statements, SECTIONS
from tm1_insight.learning.understanding import analyze, structure, _assigned

VERSION = "ti-calculation-worksheet-8"
MAX_CODE = 250_000
MAX_NODES = 5000
SENSITIVE = re.compile(r"password|passwd|secret|token|credential|sso|pin(?:code)?$", re.I)
WRITES = {"cellputn", "cellputs", "cellincrementn"}


def safe(tokens):
    if any(t["kind"] == "id" and SENSITIVE.search(t["value"]) for t in tokens):
        return "<敏感表达式已隐藏>"
    text = expression(tokens)
    return text if len(text)<=600 else text[:600]+' … [表达式显示已截断；完整语法见节点/源码]'


def location(token):
    return {key: token[key] for key in ("section", "line", "column")}


class Unsupported(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class Builder:
    def __init__(self, references, parameters):
        self.nodes = []
        self.parameters = {name.casefold() for name in parameters}
        self.invalid_parameters = set()
        self.immutable_definitions = {}
        # Private resolver values are never serialized into the worksheet.
        self.constant_values = {}
        self.references = {(r["section"], r["line"], r["column"], r["operation"].casefold()): r for r in references}

    def add(self, kind, token, **fields):
        if len(self.nodes) >= MAX_NODES:
            raise BudgetExceeded()
        item = dict(id=len(self.nodes), kind=kind, evidence=location(token), children=[], **fields)
        self.nodes.append(item)
        return item["id"]

    def parse(self, tokens, env):
        tokens = [t for t in tokens if t["value"] != ";"]
        if not tokens:
            return self.add("unknown", {"section": "unknown", "line": 0, "column": 0}, reason="表达式缺失")
        if any(t["kind"] == "id" and SENSITIVE.search(t["value"]) for t in tokens):
            return self.add("unknown", tokens[0], reason="敏感表达式已隐藏")
        cursor = 0
        precedence = {"+": 1, "-": 1, "*": 2, "/": 2, "\\": 2}

        def parse_expr(minimum=0, depth=0):
            nonlocal cursor
            if depth > 24 or cursor >= len(tokens):
                raise Unsupported()
            token = tokens[cursor]; cursor += 1
            value = token["value"]
            if value in {"+", "-"} and token["kind"] == "symbol":
                child = parse_expr(3, depth + 1)
                left = self.add("unary", token, operator=value, operands=[child])
                self.nodes[left]["children"] = [child]
            elif value == "(":
                left = parse_expr(0, depth + 1)
                if cursor >= len(tokens) or tokens[cursor]["value"] != ")": raise Unsupported()
                cursor += 1
            elif token["kind"] == "number" and len(value) <= 100:
                left = self.add("number", token, value=value)
            elif token["kind"] == "string":
                left = self.add("redacted_string", token, reason="字符串常量已隐藏；在源码位置核对原值")
                self.constant_values[left]=value[1:-1].replace(value[0]*2,value[0])
            elif token["kind"] == "id":
                name = value.casefold()
                if cursor < len(tokens) and tokens[cursor]["value"] == "(":
                    cursor += 1; args = []
                    if cursor < len(tokens) and tokens[cursor]["value"] != ")":
                        while True:
                            args.append(parse_expr(0, depth + 1))
                            if cursor < len(tokens) and tokens[cursor]["value"] == ",": cursor += 1
                            else: break
                    if cursor >= len(tokens) or tokens[cursor]["value"] != ")": raise Unsupported()
                    cursor += 1
                    if name in {"cellgetn", "cellgets"} and args:
                        ref = self.references.get((token["section"], token["line"], token["column"], name), {})
                        left = self.add("read", token, operation=value, cube=ref.get("target"),
                                        resolution=ref.get("status", "unresolved"), coordinates=args[1:])
                        self.nodes[left]["children"] = args
                    else:
                        left = self.add("unknown", token, reason=f"函数 {value} 的返回值语义未支持；不推导其值流")
                elif name in env or name in self.immutable_definitions:
                    definition=env.get(name,self.immutable_definitions.get(name))
                    left = self.add("variable", token, name=value, definition=definition)
                    self.nodes[left]["children"] = [definition]
                elif name in self.parameters and name not in self.invalid_parameters:
                    left = self.add("parameter", token, name=value)
                else:
                    left = self.add("unknown", token, name=value, reason="没有该位置可安全复用的定义；数据源字段、外部状态或分支/循环结果未还原")
            else:
                raise Unsupported()
            while cursor < len(tokens) and tokens[cursor]["value"] in precedence:
                operator = tokens[cursor]
                level = precedence[operator["value"]]
                if level < minimum: break
                cursor += 1
                right = parse_expr(level + 1, depth + 1)
                node = self.add("binary", operator, operator=operator["value"], operands=[left, right])
                self.nodes[node]["children"] = [left, right]; left = node
            return left
        try:
            root = parse_expr()
            if cursor != len(tokens): raise Unsupported()
            return root
        except Unsupported:
            return self.add("unknown", tokens[0], reason="表达式超出支持的算术子集或语法不完整", expression=safe(tokens))

    def trace(self, root):
        seen, reads, unknowns, definitions = set(), [], [], []
        pending = [root]
        while pending:
            index = pending.pop()
            if index in seen: continue
            seen.add(index); node = self.nodes[index]
            if node["kind"] == "unknown": unknowns.append(index); continue
            if node["kind"] == "read":
                reads.append(index)
                if node["resolution"] != "resolved": unknowns.append(index)
                # Coordinates explain the read location, not additional value contributions.
                continue
            if node["kind"] == "assignment": definitions.append(index)
            pending.extend(reversed(node["children"]))
        return dict(read_nodes=reads, unknown_nodes=unknowns, definition_nodes=definitions)


def worksheet(name, parts, catalogs, parameters=(), *, retain_constants=False, row_symbols=None):
    report = dict(schema=VERSION, process=name, source_hash=hashlib.sha256(json.dumps(dict(zip(SECTIONS, parts)), sort_keys=True).encode()).hexdigest(),
                  runtime_verified=False, status="PARTIAL", nodes=[], writes=[], calls=[], observations=[], diagnostics=[], control_reads=[],
                  scope="single_process_no_callee_expansion", strings_redacted=True)
    if sum(map(len, parts)) > MAX_CODE:
        report["diagnostics"].append("源码超过 250000 字符预算；请直接查看源码，本页未分析截断片段。")
        return report
    roots, _, diagnostics, _ = structure(parts, include_logging=True)
    pending = [node for root in roots for node in root]
    while pending:
        node = pending.pop()
        if len(node["tokens"]) > 1000:
            report["diagnostics"].append("单条语句超过 1000 token 预算，本页未继续解释。")
            return report
        balance = 0
        for token in node['tokens']:
            if token['kind'] != 'symbol': continue
            if token['value'] in {"'", '"'}:
                report['diagnostics'].append(dict(reason='存在无法解析的字符串引号，本页未继续解释。', **location(token)))
                return report
            if token['value'] == '(': balance += 1
            elif token['value'] == ')': balance -= 1
            if balance < 0: break
        if balance != 0:
            report['diagnostics'].append(dict(reason='语句括号无法配对，本页未继续解释。', **location(node['tokens'][0])))
            return report
        for branch in node.get("branches", []): pending.extend(branch)
    observed = analyze(parts, catalogs, parameters, include_logging=True)
    report["diagnostics"] = diagnostics
    items = [{k:r[k] for k in ("kind", "target", "status", "operation", "section", "line", "column", "control_context")}
             for r in observed["references"]]
    report["observation_total"] = len(items)
    report["observations"] = items[:2000]
    report["calls"] = []
    if len(items) > 2000: report["diagnostics"].append("引用观察表只保留前 2000 条，超出部分未导出。")
    builder = Builder(observed["references"], parameters)
    # Retain only unique, unconditional Prolog literal definitions across conservative
    # branch/exit merges. Conflicting writes in any section invalidate this fallback.
    from collections import Counter
    assignment_counts=Counter(t[0]['value'].casefold() for t in statements(parts,include_logging=True)
        if len(t)>2 and t[0]['kind']=='id' and t[1]['value']=='=')
    immutable_locations={(n['tokens'][0]['section'],n['tokens'][0]['line'],n['tokens'][0]['column'])
        for n in roots[0] if n['kind']=='statement' and len(n['tokens'])>2 and n['tokens'][0]['kind']=='id' and n['tokens'][1]['value']=='='
        and assignment_counts[n['tokens'][0]['value'].casefold()]==1
        and len([t for t in n['tokens'][2:] if t['value']!=';'])==1
        and n['tokens'][2]['kind'] in {'string','number'}}
    process_names = {name.casefold():name for name in catalogs['process']}

    def visit(nodes, env, context=(), depth=0):
        if depth > 40: raise BudgetExceeded()
        for node in nodes:
            tokens = node["tokens"]
            if node['kind'] in {'if','while','condition'} and all(t['value'].casefold() in {'if','while','elseif'} for t,_ in calls(tokens)):
                control_reads=set()
                for token in tokens[1:]:
                    if token['kind']!='id':continue
                    definition=env.get(token['value'].casefold(),builder.immutable_definitions.get(token['value'].casefold()))
                    if definition is not None:control_reads.update(builder.trace(definition)['read_nodes'])
                for read_id in sorted(control_reads):
                    report['control_reads'].append(dict(read_node=read_id,evidence=location(tokens[0]),condition=safe(tokens[1:]),control_context=list(context)))
            if node["kind"] == "while":
                env = {k:v for k,v in env.items() if k not in _assigned(node["branches"][0])}
            for token, args in calls(tokens):
                if token['value'].casefold() in {'executeprocess', 'runprocess'} and len(report['calls']) < 2000:
                    ref = builder.references.get((token['section'], token['line'], token['column'], token['value'].casefold()), {})
                    direct = len(args[0]) == 1 and args[0][0]['kind'] == 'string' if args else False
                    target_value = None
                    if direct:
                        raw=args[0][0]['value'];target_value=raw[1:-1].replace(raw[0]*2,raw[0])
                    elif args and len(args[0])==1 and args[0][0]['kind']=='id':
                        target_value=builder.constant_values.get(env.get(args[0][0]['value'].casefold()))
                    target = process_names.get(target_value.casefold()) if isinstance(target_value,str) and not diagnostics else None
                    target_node=builder.parse(args[0] if args else [],env)
                    bindings = []
                    for i in range(1, len(args)-1, 2):
                        key = args[i]
                        literal = key[0]['value'][1:-1].replace(key[0]['value'][0]*2, key[0]['value'][0]) if len(key)==1 and key[0]['kind']=='string' else None
                        value = builder.parse(args[i+1], env)
                        trace = builder.trace(value)
                        for read in trace['read_nodes']:
                            for coordinate in builder.nodes[read]['coordinates']:
                                trace['unknown_nodes'].extend(builder.trace(coordinate)['unknown_nodes'])
                        trace['unknown_nodes'] = list(dict.fromkeys(trace['unknown_nodes']))
                        bindings.append(dict(parameter_hash=hashlib.sha256(literal.casefold().encode()).hexdigest() if literal is not None else None,
                            value_node=value, expression=safe(args[i+1]), evidence=location(key[0] if key else token), **trace))
                    report['calls'].append(dict(id=len(report['calls']), kind='process', operation=token['value'],
                        target=target, target_node=target_node,
                        target_resolution='literal' if direct else 'reaching_constant_alias' if target else 'unknown',
                        status='resolved' if target else 'structure_unknown' if diagnostics else 'missing_object' if target_value is not None else ref.get('status','unresolved') if ref.get('status')!='resolved' else 'unresolved', **location(token),
                        control_context=list(context), arguments=bindings, argument_pairs_complete=bool(len(args)%2),
                        target_expression=safe(args[0]) if args else 'UNKNOWN'))
                if token["value"].casefold() not in WRITES: continue
                ref = builder.references.get((token["section"], token["line"], token["column"], token["value"].casefold()), {})
                value = builder.parse(args[0] if args else [], env)
                trace = builder.trace(value)
                coordinates = [builder.parse(arg, env) for arg in args[2:]]
                target_node = builder.parse(args[1], env) if len(args)>1 else builder.parse([],env)
                coordinate_reads=[]
                for coordinate in coordinates:
                    coordinate_trace=builder.trace(coordinate)
                    trace['unknown_nodes'].extend(coordinate_trace['unknown_nodes'])
                    coordinate_reads.extend(coordinate_trace['read_nodes'])
                for read in trace['read_nodes']:
                    for coordinate in builder.nodes[read]['coordinates']:
                        trace['unknown_nodes'].extend(builder.trace(coordinate)['unknown_nodes'])
                trace['unknown_nodes'] = list(dict.fromkeys(trace['unknown_nodes']))
                if diagnostics: trace = dict(read_nodes=[], unknown_nodes=[value], definition_nodes=[])
                report["writes"].append(dict(id=len(report["writes"]), operation=token["value"],
                    cube=ref.get("target"), resolution=ref.get("status", "unresolved"), value_node=value,
                    value_expression=safe(args[0]) if args else "UNKNOWN", evidence=location(token),
                    coordinates=coordinates, coordinate_read_nodes=list(dict.fromkeys(coordinate_reads)), target_node=target_node, control_context=list(context),
                    trace_status="UNKNOWN" if diagnostics else "PARTIAL" if trace["unknown_nodes"] or ref.get("status") != "resolved" else "STATIC",
                    **trace))
            if node["kind"] == "if":
                outcomes = [visit(branch, dict(env), context + (dict(kind="if", section=node["section"],
                    line=node["line"], branch=index, condition=(safe(tokens[1:]) if index==0 else
                        safe(branch[0]['tokens'][1:]) if branch and branch[0]['kind']=='condition' else 'ELSE'),
                    note='分支路径未求值'),), depth+1)
                    for index, branch in enumerate(node["branches"])]
                if not node["else"]: outcomes.append(dict(env))
                env = {k:v for k,v in outcomes[0].items() if all(out.get(k) == v for out in outcomes[1:])}
            elif node["kind"] == "while":
                base = dict(env)
                visit(node["branches"][0], dict(base), context + (dict(kind="while", section=node["section"],
                    line=node["line"], condition=safe(tokens[1:]), note="循环与迭代未求值"),), depth+1)
                env = base
            elif len(tokens)>2 and tokens[0]["kind"]=="id" and tokens[1]["value"]=="=":
                variable=tokens[0]["value"]
                if SENSITIVE.search(variable):
                    index = builder.add("unknown", tokens[0], reason="敏感定义未展开")
                else:
                    rhs = builder.parse(tokens[2:], env)
                    index = builder.add("assignment", tokens[0], variable=variable, expression=safe(tokens[2:]))
                    builder.nodes[index]["children"] = [rhs]
                env[variable.casefold()] = index
                if (tokens[0]['section'],tokens[0]['line'],tokens[0]['column']) in immutable_locations and not SENSITIVE.search(variable):
                    builder.immutable_definitions[variable.casefold()]=index
                rhs_tokens=[t for t in tokens[2:] if t['value']!=';']
                if not SENSITIVE.search(variable) and len(rhs_tokens)==1:
                    token=rhs_tokens[0]
                    if token['kind']=='string':
                        raw=token['value'];builder.constant_values[index]=raw[1:-1].replace(raw[0]*2,raw[0])
                    elif token['kind']=='id':
                        rhs_node=builder.nodes[index]['children'][0]
                        definition=builder.nodes[rhs_node].get('definition')
                        if definition in builder.constant_values:builder.constant_values[index]=builder.constant_values[definition]
            elif tokens[0]["value"].casefold() in {"itemskip", "itemreject", "processquit", "processbreak", "break"}:
                env = {}
        return env

    env = {}
    try:
        for index, root in enumerate(roots):
            written = _assigned(root)
            builder.invalid_parameters.update(written & builder.parameters)
            if index in {1, 2}: env = {k:v for k,v in env.items() if k not in written}
            if index in {1, 2}:
                # Fresh datasource variables for a row. Metadata reassignments are
                # deliberately not propagated through the existing section boundary.
                for key, symbol in (row_symbols or {}).items():
                    if index == 2 and key in _assigned(roots[1]):
                        env[key] = builder.add('unknown', dict(section=SECTIONS[index],line=0,column=0),
                            name=symbol['name'],reason='Metadata 对行变量重新赋值；跨 Section 行状态传播未支持')
                    else:
                        env[key] = builder.add('data_row', dict(section=SECTIONS[index],line=0,column=0), **symbol)
                        builder.nodes[env[key]]['evidence'] = symbol['binding']['evidence']
            incoming = dict(env)
            env = visit(root, env)
            if index in {1, 2}: env = {k:v for k,v in incoming.items() if k not in written}
    except BudgetExceeded:
        report["diagnostics"].append("达到 5000 节点或控制嵌套预算；后续语句未展开。")
    # Do not export unused definitions or orphan arguments of unsupported functions.
    reachable = set()
    pending = [idx for write in report["writes"] for idx in [write["value_node"], write['target_node'], *write["coordinates"]]]
    pending.extend(arg['value_node'] for call in report['calls'] for arg in call['arguments'])
    pending.extend(call['target_node'] for call in report['calls'])
    pending.extend(c['read_node'] for c in report['control_reads'])
    while pending:
        index = pending.pop()
        if index in reachable: continue
        reachable.add(index); pending.extend(builder.nodes[index]["children"])
    report["nodes"] = [node for node in builder.nodes if node["id"] in reachable]
    report["limits"] = ["所有链路是静态定义依赖，不是运行时贡献；分支可达性、循环次数与实际值未验证。",
        "支持普通加减乘除、反斜杠安全除法的语法与显式 CellGetN/S；不计算数值或承诺安全除法零分母行为。",
        "未知函数、动态对象、跨记录累加和未确定的分支定义停止值流追踪；子进程保持独立调用边界。",
        "字符串常量已隐藏，目标成员值需回到源码核对；未验证 Rule/Feeder、合并、清空范围或迁移等价。"]
    if retain_constants:report["_constant_values"]=builder.constant_values
    return report
