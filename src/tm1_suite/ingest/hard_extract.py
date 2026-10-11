"""TM1 TI 硬拆器（迁移自 tm1tree/hard_extract.py v6）。

逐语句扫描 IF、精确平衡括号匹配，产出写点/读点/调用/bedrock 过滤。
纯正则实现，无外部依赖。
"""
from __future__ import annotations

import re

LOG_CUBE_PATTERNS = [
    r"}APQ.*Log", r"}APQCubeLastUpdatedbyProcess", r"}APQ Process Response Message",
    r"}Sys.*Log", r"Sys.*Log", r".*ExecutionLog.*", r"Audit.*",
]
LOG_CUBE_RE = re.compile("|".join(f"({p})" for p in LOG_CUBE_PATTERNS), re.IGNORECASE)

LOG_REGION_START = re.compile(r"#Region\s*-\s*Initialize Logging", re.IGNORECASE)
LOG_REGION_END = re.compile(r"#EndRegion\s*-\s*Initialize Logging", re.IGNORECASE)
LOG_REGION_FINAL_START = re.compile(r"#Region\s*-\s*Finalize Logging", re.IGNORECASE)
LOG_REGION_FINAL_END = re.compile(r"#EndRegion\s*-\s*Finalize Logging", re.IGNORECASE)

DEBUG_KEYWORDS = [
    "cDebugLoc", "cDebug", "pDebug", "nDebug",
    "Location: Debugging", "sDebug",
    "cLogLoc", "sLogLoc",
]


def is_debug_condition(cond):
    for kw in DEBUG_KEYWORDS:
        if kw in cond:
            return True
    return False


def is_log_cube(cube_name):
    if not cube_name:
        return False
    return bool(LOG_CUBE_RE.search(cube_name))


def strip_log_regions(code):
    lines = code.split("\n")
    out = []
    skip = False
    for line in lines:
        if LOG_REGION_START.search(line) or LOG_REGION_FINAL_START.search(line):
            skip = True
            continue
        if LOG_REGION_END.search(line) or LOG_REGION_FINAL_END.search(line):
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out)


def split_statements(code):
    """按分号切分语句, 保护引号内的分号"""
    lines = code.split("\n")
    result = []
    for line_no, line in enumerate(lines):
        if not line.strip():
            continue
        buf = []
        quote = None
        for ch in line:
            buf.append(ch)
            if quote:
                if ch == quote:
                    quote = None
                continue
            if ch in "'\"":
                quote = ch
            elif ch == ";":
                s = "".join(buf).strip()
                if s:
                    result.append((line_no, s))
                buf = []
        if buf:
            s = "".join(buf).strip()
            if s:
                result.append((line_no, s))
    return result


def find_function_call(stmt, func_names):
    """在语句里找函数调用, 返回 (函数名, 参数串)"""
    pattern = r'\b(' + '|'.join(func_names) + r')\s*\('
    m = re.search(pattern, stmt, re.IGNORECASE)
    if not m:
        return None
    fname = m.group(1)
    start = m.end()
    depth = 1
    quote = None
    i = start
    while i < len(stmt):
        ch = stmt[i]
        if quote:
            if ch == quote:
                if i + 1 < len(stmt) and stmt[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        else:
            if ch in "'\"":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return (fname, stmt[start:i])
        i += 1
    return None


def extract_if_condition(stmt):
    """从 If (...) 语句里提取条件, 用平衡括号"""
    m = re.match(r'^(?:If|IF)\s*\(', stmt, re.IGNORECASE)
    if not m:
        return None
    start = m.end() - 1
    depth = 0
    quote = None
    i = start
    while i < len(stmt):
        ch = stmt[i]
        if quote:
            if ch == quote:
                if i + 1 < len(stmt) and stmt[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        else:
            if ch in "'\"":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    cond = stmt[start + 1:i].strip()
                    cond = re.sub(r"\s+", " ", cond)
                    return cond
        i += 1
    return None


def scan_statements_with_conditions(code):
    """逐语句扫描, 维护 IF 栈。返回 [(line_no, 语句, 条件栈), ...]"""
    stmts = split_statements(code)
    result = []
    if_stack = []

    for line_no, stmt in stmts:
        s = stmt.strip()
        if not s:
            continue

        if re.match(r'^EndIF\s*;?\s*$', s, re.IGNORECASE):
            if if_stack:
                if_stack.pop()
            continue

        if re.match(r'^Else\s*;?\s*$', s, re.IGNORECASE):
            continue

        if re.match(r'^(?:If|IF)\s*\(', s, re.IGNORECASE):
            cond = extract_if_condition(s)
            if cond and not is_debug_condition(cond):
                if_stack.append(cond)
            continue

        result.append((line_no, s, list(if_stack)))

    return result


ASSIGN_PAT = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*;?\s*$"
)


def extract_assignments(code):
    result = {}
    for line_no, stmt in split_statements(code):
        m = ASSIGN_PAT.match(stmt)
        if m:
            var = m.group(1)
            expr = m.group(2).strip().rstrip(";").strip()
            result.setdefault(var, []).append(expr)
    return result


def split_args(s):
    args = []
    depth = 0
    quote = None
    buf = []
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        args.append("".join(buf).strip())
    return args


def resolve_value(expr, assignments, depth=0):
    if depth > 8:
        return f"<{expr}>"
    expr = expr.strip()
    if not expr:
        return ""

    if (expr.startswith("'") and expr.endswith("'")) or \
       (expr.startswith('"') and expr.endswith('"')):
        return expr[1:-1]

    if "|" in expr:
        parts = [p.strip() for p in expr.split("|")]
        return "".join(resolve_value(p, assignments, depth + 1) for p in parts)

    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", expr):
        if expr in assignments:
            return resolve_value(assignments[expr][-1], assignments, depth + 1)
        return f"<{expr}>"

    fn = re.match(r"^(\w+)\s*\((.*)\)$", expr, re.DOTALL)
    if fn:
        fname = fn.group(1)
        inner = fn.group(2)
        if fname.lower() == "expand":
            inner_clean = re.sub(r"%([^%]+)%", r"\1", inner)
            return resolve_value(inner_clean, assignments, depth + 1)

        if fname.lower() in ("cellgets", "cellgetn"):
            args = split_args(inner)
            if len(args) >= 2:
                cube = resolve_value(args[0], assignments, depth + 1)
                cube_clean = cube.strip("<>")
                dim_vals = [resolve_value(a, assignments, depth + 1) for a in args[1:-1]]
                measure = resolve_value(args[-1], assignments, depth + 1)
                dims_str = ", ".join(dim_vals) if dim_vals else ""
                return f"←{cube_clean}[{dims_str}]→{measure}"
            return "<CellGet(...)>"

        return f"<{fname}(...)>"

    return expr


LOG_MEASURE_VALUES = {
    "nProcessStartTime", "nProcessFinishTime", "nProcessStartedFlag",
    "nProcessCompletedFlag", "nProcessExecutionIndex",
    "nProcessExecutionIntraDayIndex", "nMetaDataRecordCount",
    "nDataRecordCount", "nPrologMinorErrorCount", "nMetaDataMinorErrorCount",
    "nDataMinorErrorCount", "nProcessReturnCode", "sProcessErrorLogFile",
    "sRunBy", "sParams", "nLastTimeUpdate", "sProcess", "sProcessRunBy",
}


def extract_write_points(code, assignments):
    points = []
    scanned = scan_statements_with_conditions(code)

    for line_no, stmt, conds in scanned:
        result = find_function_call(stmt, ["CellPutN", "CellPutS",
                                            "CellIncrementN", "CellIncrementS"])
        if not result:
            continue
        fname, args_str = result
        args = split_args(args_str)
        if len(args) < 3:
            continue
        target_expr = args[1]
        target_cube = resolve_value(target_expr, assignments)

        if is_log_cube(target_cube) or is_log_cube(target_expr):
            continue
        if target_expr in ("sProcLogCube", "sCubLogCube", "cCubRespMsg"):
            continue

        dim_args = [
            {"expr": a, "value": resolve_value(a, assignments)}
            for a in args[2:]
        ]

        last = dim_args[-1] if dim_args else None
        if last and last["value"] in LOG_MEASURE_VALUES:
            continue

        points.append({
            "operation": fname,
            "target_cube_expr": target_expr,
            "target_cube": target_cube,
            "dim_args": dim_args,
            "line": line_no + 1,
            "conditions": conds,
        })
    return points


def extract_read_points(code, assignments):
    points = []
    scanned = scan_statements_with_conditions(code)

    for line_no, stmt, conds in scanned:
        result = find_function_call(stmt, ["CellGetN", "CellGetS"])
        if not result:
            continue
        fname, args_str = result
        args = split_args(args_str)
        if len(args) < 2:
            continue
        source_expr = args[0]
        source_cube = resolve_value(source_expr, assignments)
        if is_log_cube(source_cube) or is_log_cube(source_expr):
            continue
        dim_args = [
            {"expr": a, "value": resolve_value(a, assignments)}
            for a in args[1:]
        ]
        points.append({
            "operation": fname,
            "source_cube_expr": source_expr,
            "source_cube": source_cube,
            "dim_args": dim_args,
        })
    return points


def _find_multiline_call(code, func_names):
    """跨行扫描函数调用：解决 ExecuteProcess(\n '}bedrock.cube.data.copy',\n ...) 这类
    多行调用被 split_statements 按单行切碎、导致括号无法闭合的问题。

    返回 [(func_name, args_str), ...]，args_str 为去括号后的完整参数字符串。
    """
    pattern = r'\b(' + '|'.join(func_names) + r')\s*\('
    results = []
    for m in re.finditer(pattern, code, re.IGNORECASE):
        fname = m.group(1)
        start = m.end()
        depth = 1
        quote = None
        i = start
        while i < len(code):
            ch = code[i]
            if quote:
                if ch == quote:
                    if i + 1 < len(code) and code[i + 1] == quote:
                        i += 2
                        continue
                    quote = None
            else:
                if ch in "'\"":
                    quote = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        results.append((fname, code[start:i]))
                        break
            i += 1
    return results


def extract_calls(code, assignments):
    calls = []
    # 用跨行扫描统一提取 ExecuteProcess/RunProcess（兼容单行与多行两种写法），
    # 替代原先依赖 split_statements 的单行扫描，避免多行调用漏解析。
    for fname, args_str in _find_multiline_call(code, ["ExecuteProcess", "RunProcess"]):
        args = split_args(args_str)
        if not args:
            continue
        proc_expr = args[0]
        callee = resolve_value(proc_expr, assignments)
        params = {}
        i = 1
        while i < len(args) - 1:
            p = args[i]
            if p.startswith("'") and p.endswith("'"):
                pname = p[1:-1]
                pval_expr = args[i + 1]
                params[pname] = {
                    "expr": pval_expr,
                    "value": resolve_value(pval_expr, assignments),
                }
                i += 2
            else:
                i += 1
        calls.append({
            "operation": fname,
            "callee_expr": proc_expr,
            "callee": callee,
            "params": params,
        })
    return calls


BEDROCK_OPS = {
    "}bedrock.cube.data.clear": "clear",
    "}bedrock.cube.data.copy": "copy",
    "}bedrock.cube.data.zeroout": "zeroout",
    "}bedrock.cube.view.create": "view_create",
    "}bedrock.cube.viewandsubsets.delete": "view_delete",
}


def rebuild_filter(filter_var, code, assignments):
    filters = []
    first_pat = re.compile(
        rf"^\s*{re.escape(filter_var)}\s*=\s*'([^']+)'\s*\|\s*(\w+)\s*\|\s*([^;]+?)\s*;",
        re.MULTILINE
    )
    for m in first_pat.finditer(code):
        filters.append({
            "dim": m.group(1),
            "value_expr": m.group(3).strip(),
            "value": resolve_value(m.group(3).strip(), assignments),
        })
    append_pat = re.compile(
        rf"^\s*{re.escape(filter_var)}\s*=\s*{re.escape(filter_var)}\s*\|\s*(\w+)\s*\|\s*'([^']+)'\s*\|\s*(\w+)\s*\|\s*([^;]+?)\s*;",
        re.MULTILINE
    )
    for m in append_pat.finditer(code):
        filters.append({
            "dim": m.group(2),
            "value_expr": m.group(4).strip(),
            "value": resolve_value(m.group(4).strip(), assignments),
        })
    return filters


def extract_bedrock_filters(calls, code, assignments):
    results = []
    for call in calls:
        callee = call["callee"]
        if not callee or not callee.startswith("}bedrock."):
            continue
        op = None
        for key, v in BEDROCK_OPS.items():
            if key in callee:
                op = v
                break
        if not op:
            continue
        target_cube = call["params"].get("pCube", {}).get("value", "")
        if is_log_cube(target_cube):
            continue
        pfilter_expr = call["params"].get("pFilter", {}).get("expr", "")
        pfilter_value = call["params"].get("pFilter", {}).get("value", "")
        filters = []
        if pfilter_expr and re.match(r"^[A-Za-z_]\w*$", pfilter_expr):
            filters = rebuild_filter(pfilter_expr, code, assignments)
        if not filters and pfilter_value and "<" not in pfilter_value:
            filters = parse_filter_string(pfilter_value)
        results.append({
            "bedrock_op": op,
            "target_cube": target_cube,
            "filters": filters,
        })
    return results


def parse_filter_string(s):
    if not s or "<" in s:
        return []
    filters = []
    for part in re.split(r"[&;¦]", s):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"([^=:¦~]+)[=:](.+)", part)
        if m:
            filters.append({
                "dim": m.group(1).strip(),
                "value": m.group(2).strip(),
            })
    return filters


def _bedrock_cube_points(bedrock_calls):
    """把 bedrock 调用的 cube 转成读写点，补进血缘。

    bedrock 语义（用户定义）：
    - copy：pCube 既是读也是写（版本间拷贝，同一 cube 内部搬数据）
    - clear / zeroout：pCube 是写（清空）
    - view.create：pCube 是读（建视图读取数据）
    - view.delete：清理临时视图，不涉及业务数据流，跳过
    """
    writes = []
    reads = []
    for b in bedrock_calls:
        cube = b.get("target_cube", "")
        if not cube or cube.startswith("<") or is_log_cube(cube):
            continue
        op = b.get("bedrock_op", "")
        if op in ("copy",):
            writes.append({
                "operation": "BedrockCopy",
                "target_cube_expr": cube,
                "target_cube": cube,
                "dim_args": [],
                "line": 0,
                "conditions": [],
            })
            reads.append({
                "operation": "BedrockCopy",
                "source_cube_expr": cube,
                "source_cube": cube,
                "dim_args": [],
            })
        elif op in ("clear", "zeroout"):
            writes.append({
                "operation": "BedrockClear",
                "target_cube_expr": cube,
                "target_cube": cube,
                "dim_args": [],
                "line": 0,
                "conditions": [],
            })
        elif op == "view_create":
            reads.append({
                "operation": "BedrockViewCreate",
                "source_cube_expr": cube,
                "source_cube": cube,
                "dim_args": [],
            })
    return writes, reads


def process_ti(ti_json):
    name = ti_json.get("name", "")
    full = "\n".join([
        ti_json.get("prolog", "") or "",
        ti_json.get("metadata", "") or "",
        ti_json.get("data", "") or "",
        ti_json.get("epilog", "") or "",
    ])

    biz = strip_log_regions(full)
    assignments = extract_assignments(biz)

    writes = extract_write_points(biz, assignments)
    reads = extract_read_points(biz, assignments)
    calls = extract_calls(biz, assignments)
    bedrock = extract_bedrock_filters(calls, biz, assignments)

    # bedrock 调用涉及的 cube 补进读写边（数据通过 bedrock 传递，无 CellPutN/CellGetN）
    b_writes, b_reads = _bedrock_cube_points(bedrock)
    writes.extend(b_writes)
    reads.extend(b_reads)

    return {
        "name": name,
        "code_length": len(full),
        "business_code_length": len(biz),
        "params": [p.get("name") for p in (ti_json.get("parameters") or [])],
        "write_points": writes,
        "read_points": reads,
        "calls": calls,
        "bedrock_calls": bedrock,
    }
