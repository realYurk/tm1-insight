"""Conservative block and reference analysis. Never executes TM1 code.

Constant names propagate through straight-line code. Branches merge only equal
values; loop writes are invalidated. Unknown names remain explicitly unknown.
This is a structural IR, not a complete TI grammar or runtime interpreter.
"""
from __future__ import annotations

from collections import Counter
from tm1_insight.learning.syntax import statements, calls, expression

OBJECT_ARGUMENTS = {
    "cellgetn":("cube",0), "cellgets":("cube",0),
    "cellputn":("cube",1), "cellputs":("cube",1), "cellincrementn":("cube",1),
    "executeprocess":("process",0), "runprocess":("process",0),
    "attrs":("dimension",0), "attrn":("dimension",0),
    "viewcreate":("cube",0), "viewzeroout":("cube",0), "viewdestroy":("cube",0),
    "subsetcreate":("dimension",0), "subsetcreatebymdx":("dimension",2),
    "dimensionelementinsert":("dimension",0), "dimensionelementcomponentadd":("dimension",0),
    "dimensionelementexists":("dimension",0), "dimix":("dimension",0),
}


def _assigned(nodes):
    result=set(); pending=list(nodes)
    while pending:
        node=pending.pop()
        tokens=node.get("tokens",[])
        if len(tokens)>2 and tokens[0]["kind"]=="id" and tokens[1]["value"]=="=":
            result.add(tokens[0]["value"].casefold())
        for branch in node.get("branches",[]):pending.extend(branch)
    return result


def structure(parts, *, include_logging=False):
    roots=[]; diagnostics=[]; controls=[]; statement_count=0
    for section_index in range(4):
        pieces=[""]*4;pieces[section_index]=parts[section_index] or ""
        root=[];current=root;stack=[]
        for tokens in statements(pieces, include_logging=include_logging):
            statement_count+=1
            first=tokens[0];word=first["value"].casefold()
            location={"section":first["section"],"line":first["line"]}
            if word in {"if","while"}:
                node={"kind":word,"tokens":tokens,"branches":[[]],"else":False,**location}
                current.append(node);stack.append((node,current));current=node["branches"][0]
                controls.append({"kind":word,"condition":expression(tokens[1:])[:300],**location})
            elif word in {"else","elseif"}:
                if not stack or stack[-1][0]["kind"]!="if" or stack[-1][0]["else"]:
                    diagnostics.append({"reason":"分支结构无法配对",**location});continue
                node=stack[-1][0];node["else"] = word=="else"
                node["branches"].append([]);current=node["branches"][-1]
                if word=="elseif":current.append({"kind":"condition","tokens":tokens,**location})
                controls.append({"kind":word,"condition":expression(tokens[1:])[:300],**location})
            elif word in {"endif","end"}:
                expected="if" if word=="endif" else "while"
                if not stack or stack[-1][0]["kind"]!=expected:
                    diagnostics.append({"reason":"结束语句无法配对",**location});continue
                _,current=stack.pop()
            else:current.append({"kind":"statement","tokens":tokens,**location})
        for node,_ in stack:
            diagnostics.append({"section":node["section"],"line":node["line"],"reason":"控制块没有可配对的结束语句"})
        roots.append(root)
    return roots,controls,diagnostics,statement_count


def analyze(parts, catalogs, parameters=(), *, include_logging=False):
    roots,controls,diagnostics,statement_count=structure(parts, include_logging=include_logging)
    references=[];operation_counts=Counter();bindings=[];assignments=0
    canonical={kind:{name.casefold():name for name in names} for kind,names in catalogs.items()}
    parameters={name.casefold() for name in parameters}

    def constant(tokens,env):
        tokens=[t for t in tokens if t["value"]!=";"]
        if len(tokens)!=1:return None
        token=tokens[0]
        if token["kind"]=="string":
            raw=token["value"];return raw[1:-1].replace(raw[0]*2,raw[0])
        if token["kind"]=="id":return env.get(token["value"].casefold())
        return None

    def visit(nodes,env,context=(),depth=0):
        nonlocal assignments
        if depth>80:
            diagnostics.append({"section":"unknown","line":None,"reason":"控制块嵌套超过安全深度，内部语义未解释"});return {}
        for node in nodes:
            tokens=node["tokens"]
            if node["kind"]=="while":
                env={k:v for k,v in env.items() if k not in _assigned(node["branches"][0])}
            for token,args in calls(tokens):
                op=token["value"].casefold();operation_counts[op]+=1
                if op not in OBJECT_ARGUMENTS:continue
                kind,index=OBJECT_ARGUMENTS[op]
                target=constant(args[index],env) if len(args)>index else None
                matched=canonical[kind].get(target.casefold()) if target is not None else None
                arg=args[index] if len(args)>index else []
                status="resolved" if matched else "missing_object" if target is not None else "parameter" if len(arg)==1 and arg[0]["value"].casefold() in parameters else "unresolved"
                reference={"kind":kind,"target":matched,"status":status,"expression":expression(arg)[:200],
                           "operation":token["value"],"section":token["section"],"line":token["line"],
                           "column":token.get("column"),"control_context":list(context)[-6:]}
                references.append(reference)
                if op in {"executeprocess","runprocess"}:
                    bindings.append({**reference,"arguments":[{"parameter":constant(args[i],{}),"expression":expression(args[i+1])[:200]}
                                                               for i in range(1,len(args)-1,2)]})
            if node["kind"]=="if":
                marker={"kind":"if","section":node["section"],"line":node["line"]}
                outcomes=[visit(branch,dict(env),context+(marker,),depth+1) for branch in node["branches"]]
                if not node["else"]:outcomes.append(dict(env))
                env={key:value for key,value in outcomes[0].items() if all(outcome.get(key)==value for outcome in outcomes[1:])}
            elif node["kind"]=="while":
                written=_assigned(node["branches"][0]);base={k:v for k,v in env.items() if k not in written}
                marker={"kind":"while","section":node["section"],"line":node["line"]}
                visit(node["branches"][0],dict(base),context+(marker,),depth+1);env=base
            elif len(tokens)>2 and tokens[0]["kind"]=="id" and tokens[1]["value"]=="=":
                assignments+=1;name=tokens[0]["value"].casefold();value=constant(tokens[2:],env)
                if value is None:env.pop(name,None)
                else:env[name]=value
        return env

    environment={}
    for index,root in enumerate(roots):
        if index in {1,2}:
            environment={k:v for k,v in environment.items() if k not in _assigned(root)}
        environment=visit(root,environment)
    # Any structural failure invalidates conservative name resolution. Retain
    # observations and locations, but do not claim proven object binding.
    if diagnostics:
        for reference in references+bindings:
            if reference["status"]=="resolved":reference["status"]="structure_unknown"
    counts=Counter(item["status"] for item in references)
    return {"ir_version":"ti-structure-1","statements":statement_count,"assignments":assignments,
            "controls":controls,"diagnostics":diagnostics,"references":references,"call_bindings":bindings,
            "reference_counts":dict(counts),"operations":dict(operation_counts),
            "semantic_status":"partial","runtime_verified":False,
            "limits":["只解释显式常量和直线别名；分支仅合并一致值，循环改写的符号不向外传播。",
                      "条件路径保留结构位置，未求值；不证明分支可达、执行顺序、跨过程参数传播或运行结果。",
                      "Rule/Feeder、MDX、外部 SQL/文件与动态对象名不属于此结构解释器的完整语义。"]}


def call_components(processes, pairs):
    """Iterative Kosaraju; typed process nodes cannot collide with Cube names."""
    nodes={('process',name) for name in processes};forward={n:[] for n in nodes};reverse={n:[] for n in nodes}
    for caller,callee in pairs:
        left,right=('process',caller),('process',callee)
        if left in nodes and right in nodes:forward[left].append(right);reverse[right].append(left)
    seen=set();order=[]
    for start in sorted(nodes):
        if start in seen:continue
        seen.add(start);stack=[(start,iter(forward[start]))]
        while stack:
            node,children=stack[-1];child=next(children,None)
            if child is None:order.append(node);stack.pop()
            elif child not in seen:seen.add(child);stack.append((child,iter(forward[child])))
    seen.clear();groups=[]
    for start in reversed(order):
        if start in seen:continue
        stack=[start];seen.add(start);group=[]
        while stack:
            node=stack.pop();group.append(node[1])
            for child in reverse[node]:
                if child not in seen:seen.add(child);stack.append(child)
        if len(group)>1 or start in forward[start]:groups.append(sorted(group))
    return sorted(groups)


def analyze_rule(code,cubes):
    """Inventory Rule sections and literal DB references; no evaluation claims."""
    canonical={name.casefold():name for name in cubes}
    references=[];counts=Counter();directives=[];feeder_section=False
    for tokens in statements((code,"","","")):
        first=tokens[0];word=first["value"].casefold()
        if word in {"skipcheck","feedstrings","undefvals","feeders"}:
            directives.append({"directive":word,"line":first["line"]})
            if word=="feeders":feeder_section=True
            continue
        values=[token["value"].casefold() for token in tokens]
        feeder=any(values[i:i+2]==['=','>'] for i in range(len(values)-1))
        counts["feeders" if feeder_section or feeder else "rule_statements"]+=1
        for index,value in enumerate(values[:-2]):
            if value=='=' and values[index+1] in {'n','c'} and values[index+2]==':':counts["scope_"+values[index+1]]+=1
        for signal in {'stet','continue'}:
            if any(t["kind"]=="id" and t["value"].casefold()==signal for t in tokens):counts[signal]+=1
        for token,args in calls(tokens):
            if token["value"].casefold()!='db' or not args:continue
            arg=args[0];target=None
            if len(arg)==1 and arg[0]["kind"]=="string":
                raw=arg[0]["value"];target=canonical.get(raw[1:-1].replace(raw[0]*2,raw[0]).casefold())
            references.append({"target":target,"line":token["line"],"status":"resolved" if target else "unresolved",
                               "expression":expression(arg)[:200],"section":"feeder" if feeder_section or feeder else "rule"})
    return {"schema":"rule-structure-1","counts":dict(counts),"directives":directives,"db_references":references,
            "semantic_status":"partial","runtime_verified":False,
            "limits":["只盘点语句、N/C 标记、指令和显式 DB 对象引用；不执行公式或解释完整目标切片。",
                      "未验证规则优先级、层级汇总、条件 Feeder、STET/CONTINUE、稀疏计算或金额结果。"]}
