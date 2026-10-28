"""公共查询：CLI 与 Web API 共用，避免逻辑重复。"""
from __future__ import annotations

import json
import re

import duckdb


def _source_from_value(value: str | None) -> str | None:
    """从 dim_value 里解析嵌套 CellGet 的源头 Cube（格式 ←cube[dim...]→measure）。"""
    if not value:
        return None
    m = re.match(r"←([^\[]+)\[", value)
    if not m:
        return None
    cube = m.group(1).strip()
    if cube and not cube.startswith("<"):
        return cube
    return None


def _var_source_map(con: duckdb.DuckDBPyConnection, process_name: str) -> dict[str, list[str]]:
    """解析某个 TI 的「变量名 → 源头 cube」映射。

    遍历 prolog/metadata/data/epilog，对每个赋值语句用 hard_extract 的 resolve_value
    追溯其最终值；若结果是 ←cube[...]→measure 形式（即变量取自某个 cube 的 CellGetN/DBR），
    则记录该变量名对应的源头 cube。

    返回 { 变量名: [cube1, cube2, ...] }（同一变量多处赋值/多分支时可能有多个源头）。
    """
    from tm1_insight.ingest.hard_extract import extract_assignments, resolve_value

    row = con.execute(
        "SELECT prolog, metadata, data, epilog FROM processes WHERE name = ?", [process_name]
    ).fetchone()
    if not row:
        return {}

    full = "\n".join([row[0] or "", row[1] or "", row[2] or "", row[3] or ""])
    var_map = extract_assignments(full)

    result: dict[str, list[str]] = {}
    for var, exprs in var_map.items():
        cubes: list[str] = []
        for expr in exprs:
            val = resolve_value(expr, var_map)
            src = _source_from_value(val)
            if src and src not in cubes:
                cubes.append(src)
        if cubes:
            result[var] = cubes
    return result


# ---- 代码拆解翻译（TM1 内部语法 → 人类可读） ----
_OP_HUMAN = {
    "CellPutN": "写入数值",
    "CellPutS": "写入字符串",
    "CellPutProportionalSpread": "按比例分摊写入",
    "CellIncrementN": "数值累加",
    "CellGetN": "读取数值",
    "CellGetS": "读取字符串",
    "DBRW": "读写单元格",
    "DBR": "读取单元格",
    "ASCIIOutput": "导出文本文件",
    "ViewCreate": "创建视图",
    "ViewZeroOut": "视图清零",
    "DimensionElementInsert": "插入维度元素",
    "DimensionElementDelete": "删除维度元素",
    "ExecuteProcess": "调用子进程",
    "ItemReject": "拒绝记录",
    "TextOutput": "输出文本",
    "LogOutput": "输出日志",
    "SecurityRefresh": "刷新权限",
    "CubeClearData": "清空 Cube 数据",
}


def _op_human(operation: str | None) -> str:
    """把 TM1 操作名翻译成中文可读描述。"""
    if not operation:
        return ""
    return _OP_HUMAN.get(operation, operation)


def _translate_condition(cond: str) -> str:
    """把 IF 条件里的 TM1 函数翻译成人类可读描述。

    例：CellIsUpdateable(cCubTgt, pScenario, ...)=1
        → 判断目标单元格（cCubTgt）在「Scenario, Version, Year, ...」这些维度上是否允许写入
    """
    if not cond:
        return ""
    s = cond.strip()
    m = re.match(r"^CellIsUpdateable\(([^)]*)\)\s*=\s*1$", s, re.IGNORECASE)
    if m:
        args = [a.strip() for a in m.group(1).split(",")]
        cube = args[0] if args else ""
        dims = args[1:] if len(args) > 1 else []
        cube_desc = f"目标单元格（{cube}）" if cube else "目标单元格"
        dim_desc = "、".join(d for d in dims if d) if dims else "全部维度"
        return f"判断{cube_desc}在维度 [{dim_desc}] 上是否允许写入"
    return s


def _split_write_point_id(write_point_id: str) -> dict:
    """拆分 write_point_id 的「TI名::目标cube::序号」结构。"""
    parts = write_point_id.split("::") if write_point_id else []
    return {
        "raw": write_point_id or "",
        "process": parts[0] if len(parts) > 0 else "",
        "cube": parts[1] if len(parts) > 1 else "",
        "seq": parts[2] if len(parts) > 2 else "",
    }


def _dimension_elements(con: duckdb.DuckDBPyConnection, dim_name: str, limit: int = 5) -> list[str]:
    """取某个维度的前 N 个元素名（用于横向表格展示）。"""
    row = con.execute(
        "SELECT elements FROM dimensions WHERE name = ?", [dim_name]
    ).fetchone()
    if not row or not row[0]:
        return []
    try:
        data = json.loads(row[0])
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, list):
        return []
    names = []
    for item in data[:limit]:
        if isinstance(item, dict):
            n = item.get("name")
        elif isinstance(item, str):
            n = item
        else:
            n = None
        if n:
            names.append(n)
    return names


def _dimension_element_count(con: duckdb.DuckDBPyConnection, dim_name: str) -> int:
    """取某个维度的元素总数。"""
    row = con.execute(
        "SELECT element_count FROM dimensions WHERE name = ?", [dim_name]
    ).fetchone()
    return row[0] if row and row[0] else 0


def _extract_data_source(prolog: str) -> str | None:
    """从 prolog 的 Cubewise 框架 Header 注释里提取「DATA SOURCE」声明的源头 cube 名。

    注释格式并不统一，常见如：
        # DATA SOURCE:
        #    BP Management Report PnL
        #    Cube: Info MC Theory Standard Amount <- csv file
        #    1.Cube: EXP Account Balance Adjustment Input
        #    Cube [ General Ledger ]

    因此这里先取注释行，再剥离 `Cube:` / `Cube [` / `]` / `<- ...` / 序号等噪音，
    得到干净的 cube 名（用于跳转 /explorer/cube/<name>）。
    """
    if not prolog:
        return None
    lines = prolog.split("\n")
    for i, line in enumerate(lines):
        if "DATA SOURCE" not in line.upper():
            continue
        # 取其后 1-5 行，找第一个非空、非框架字段的注释内容
        for j in range(i + 1, min(i + 6, len(lines))):
            content = lines[j].strip()
            # 去掉行首 # 注释符
            content = re.sub(r"^#+\s*", "", content).strip()
            if not content:
                continue
            if content.upper().startswith(("REMARK", "PURPOSE", "CHANGE", "SOURCE TYPE", "PARAMETER")):
                break
            return _clean_source_cube(content)
        break
    return None


def _clean_source_cube(raw: str) -> str | None:
    """把 DATA SOURCE 注释里的噪音文字清理成干净的 cube 名。"""
    if not raw:
        return None
    s = raw.strip()
    # 去掉 "1." / "1.Cube:" 之类的前导序号 + Cube 前缀
    s = re.sub(r"^\d+\s*[.)]\s*", "", s)
    s = re.sub(r"^Cube\s*[:：-]\s*", "", s, flags=re.IGNORECASE)
    # 去掉 "Cube [ ... ]" 包裹
    s = re.sub(r"^Cube\s*\[", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\]\s*$", "", s)
    # 去掉 " <- csv file" 之类来源说明后缀
    s = re.sub(r"\s*<-\s*.*$", "", s)
    s = s.strip().strip("[]()").strip()
    return s or None


def _resolve_source_cube(con: duckdb.DuckDBPyConnection, prolog: str) -> str | None:
    """提取 DATA SOURCE 注释里的 cube 名，并校验其确实存在于 cubes 表。

    注释里写的名称可能带噪音（Cube:/[]/<- 等）或顺序颠倒、缩写，未必等于真实 cube 名。
    这里：
    1. 清洗出干净名称，若精确命中 cubes 表则直接返回；
    2. 否则做大小写不敏感的模糊匹配（cube 名是「描述词序列」，注释往往打乱顺序/漏词）；
    3. 都匹配不到则返回 None，前端不生成跳转链接（避免点进去 404）。
    """
    raw = _extract_data_source(prolog)
    if not raw:
        return None

    cube_names = [r[0] for r in con.execute("SELECT name FROM cubes").fetchall()]
    name_set = {n for n in cube_names}
    if raw in name_set:
        return raw

    # 大小写不敏感精确匹配
    lowered = {n.lower(): n for n in cube_names}
    if raw.lower() in lowered:
        return lowered[raw.lower()]

    # 模糊匹配：注释词集合必须是真实 cube 名词集合的子集（注释可能漏词，但不能多出词）
    raw_words = set(re.findall(r"[A-Za-z0-9]+", raw.lower()))
    if not raw_words:
        return None
    best, best_ratio = None, 0.0
    for n in cube_names:
        n_words = set(re.findall(r"[A-Za-z0-9]+", n.lower()))
        if not n_words:
            continue
        overlap = len(raw_words & n_words) / len(raw_words)
        if overlap > best_ratio:
            best, best_ratio = n, overlap
    # 阈值：注释里 80% 的词都能在真实 cube 名里找到，才认为匹配（避免误判）
    if best is not None and best_ratio >= 0.8:
        return best
    return None


def _ti_datasource_cube(con: duckdb.DuckDBPyConnection, process_name: str) -> str | None:
    """解析某个 TI 的「数据源 cube」——TI 真正逐行读取数据的源头。

    优先解析 prolog 里的框架声明 `DatasourceNameForServer = <变量/字面量>`，
    再追溯该变量（如 cCubSrc = 'BP YC81N Detail'）到真实 cube 名；若没有该声明，
    则回退到 DATA SOURCE 注释（_resolve_source_cube）。

    这是变量维度（如 <vYear>/<vMonth> 等数据源视图字段）的最终兜底源头：
    这些循环变量不是 CellGetN(cube,...) 赋值的，静态追不到具体 cube，
    但它们必然来自这个 TI 的数据源 cube。
    """
    row = con.execute(
        "SELECT prolog, metadata, data, epilog FROM processes WHERE name = ?", [process_name]
    ).fetchone()
    if not row:
        return None
    full = "\n".join([row[0] or "", row[1] or "", row[2] or "", row[3] or ""])

    # 1) 解析 DatasourceNameForServer = <expr>（框架数据源声明）
    m = re.search(r"DatasourceNameForServer\s*=\s*([^;]+);", full, re.IGNORECASE)
    if m:
        expr = m.group(1).strip()
        # 去掉行尾注释
        expr = re.sub(r"\s+#.*$", "", expr)
        if expr:
            # 若 expr 是字符串字面量，直接用；否则作为变量名去 assignments 里追溯
            from tm1_insight.ingest.hard_extract import extract_assignments, resolve_value
            assignments = extract_assignments(full)
            val = resolve_value(expr, assignments)
            # resolve_value 可能返回 <var>（追不到）或真实 cube 名
            if val and not val.startswith("<"):
                # 校验是否真实 cube 名（或注释里写的是别名）
                cube_names = {r[0] for r in con.execute("SELECT name FROM cubes").fetchall()}
                if val in cube_names:
                    return val
                lowered = {n.lower(): n for n in cube_names}
                if val.lower() in lowered:
                    return lowered[val.lower()]

    # 2) 回退到 DATA SOURCE 注释
    return _resolve_source_cube(con, row[0] or "")


def _param_names(con: duckdb.DuckDBPyConnection, process_name: str) -> set[str]:
    """返回某个 TI 的参数入参名集合（来自 processes.parameters 表）。"""
    row = con.execute(
        "SELECT parameters FROM processes WHERE name = ?", [process_name]
    ).fetchone()
    if not row or not row[0]:
        return set()
    try:
        params = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return set()
    return {p.get("name") for p in params if isinstance(p, dict) and p.get("name")}


def _var_is_param(con: duckdb.DuckDBPyConnection, process_name: str, var_name: str,
                  assignments: dict) -> bool:
    """判断某个变量（维度值 <xxx>）是否最终源自该 TI 的参数入参。

    规则：
    1. 变量名本身就在参数表里（如 pYear / pScenario）→ 是入参；
    2. 通过赋值链追溯（cScenario = pScenario → 参数 pScenario）→ 是入参；
    3. 否则不是（可能是数据源视图字段或代码内计算的变量）。
    """
    param_names = _param_names(con, process_name)
    if not param_names:
        return False
    # 1) 变量名直接命中参数
    if var_name in param_names:
        return True
    # 2) 追溯赋值链：resolve_value 会返回 <pXxx>（落到参数）或其它形式
    from tm1_insight.ingest.hard_extract import resolve_value
    val = resolve_value(var_name, assignments)
    # resolve_value 对「参数派生变量」会返回 <pXxx>；参数名命中即入参
    if val.startswith("<") and val.endswith(">"):
        inner = val[1:-1]
        if inner in param_names:
            return True
    return False


def _extract_semantic_vars(prolog: str, data: str, metadata: str, epilog: str) -> list[dict]:
    """提取「业务语义变量」（v 开头，如 vMeasure / vScenario / vBrand），非框架/局部变量。

    这类变量表达 TI 里的维度、度量、业务口径，命名统一 vXxx（区别于 sXxx 字符串、pXxx 参数、
    cXxx 常量等）。返回 [{name, value}]，value 为该变量的赋值（若有，截断），否则为空字符串。
    """
    full = "\n".join([prolog, metadata, data, epilog])
    # 第一遍：收集所有 v 开头标识符的赋值（vXxx = ...，可能带缩进或行内）
    assigned: dict[str, str] = {}
    for line in full.split("\n"):
        m = re.match(r"^\s*(v[A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+?)\s*;?\s*$", line)
        if m:
            name = m.group(1)
            value = m.group(2).strip()
            value = re.sub(r"\s*;\s*$", "", value)  # 去行尾分号
            value = re.sub(r"\s+#.*$", "", value)   # 去行尾注释
            if len(value) > 60:
                value = value[:60] + "…"
            assigned[name] = value

    # 第二遍：收集所有出现的 v 开头标识符（含未赋值的，作为「业务变量」全集）
    used: set[str] = set()
    for line in full.split("\n"):
        for m in re.finditer(r"\b(v[A-Z][A-Za-z0-9_]*)\b", line):
            used.add(m.group(1))

    result = []
    for name in sorted(used):
        result.append({"name": name, "value": assigned.get(name, "")})
    return result


def process_call_tree(
    con: duckdb.DuckDBPyConnection, root: str, max_depth: int = 8, max_breadth: int = 30
) -> dict:
    """构建以 root 为根的「调用树」：谁调用我（上游）+ 我调用谁（下游），递归展开。

    返回嵌套 dict：
    {
      "name": root,
      "callers": [ {name, callers:[...]} ... ],   # 上游（谁调用我）
      "callees": [ {name, callees:[...]} ... ],   # 下游（我调用谁）
    }
    为避免爆炸，限制深度 max_depth、每层广度 max_breadth，并用 visited 去重防环。
    """
    def _children(parent: str, direction: str, depth: int, visited: set) -> list[dict]:
        if depth >= max_depth:
            return []
        col = "callee" if direction == "down" else "caller"
        other = "caller" if direction == "down" else "callee"
        rows = con.execute(
            f"SELECT DISTINCT {col} FROM process_calls_process WHERE {other} = ? ORDER BY 1 LIMIT ?",
            [parent, max_breadth],
        ).fetchall()
        out = []
        for (child,) in rows:
            if child in visited:
                continue
            visited.add(child)
            node = {"name": child}
            kids = _children(child, direction, depth + 1, visited)
            if kids:
                node["children"] = kids
            out.append(node)
        return out

    visited = {root}
    callers = _children(root, "up", 0, visited)
    visited = {root}
    callees = _children(root, "down", 0, visited)
    return {"name": root, "callers": callers, "callees": callees}


def process_relation_graph(
    con: duckdb.DuckDBPyConnection, name: str, max_up: int = 12, max_down: int = 12, max_cubes: int = 20
) -> dict:
    """构建以 name 为中心的「引用关系图」扁平结构，供前端 SVG 渲染。

    返回：
    {
      "root": name,
      "upstream": [ {name, kind: 'process'|'cube', link} ... ],   # 上游（谁调用我 + 我读的 cube）
      "downstream": [ {name, kind: 'process'|'cube', link} ... ], # 下游（我调用谁 + 我写的 cube）
    }
    其中 link 为对应详情页路径（process 或 cube）。

    过滤规则（用户明确要求）：
    - 调用关系只取 process_calls_process（业务进程调用），忽略 ti_framework_calls（全是 bedrock 框架调用）；
    - cube 读写只取 process_reads_cube / process_writes_cube（ingest 阶段已过滤掉 `}` 开头与 bedrock 系统 cube）。
    """
    upstream: list[dict] = []
    downstream: list[dict] = []

    # 上游：谁调用我（TI）
    for (caller,) in con.execute(
        "SELECT DISTINCT caller FROM process_calls_process WHERE callee = ? ORDER BY 1 LIMIT ?",
        [name, max_up],
    ).fetchall():
        upstream.append({"name": caller, "kind": "process",
                         "link": f"/explorer/process/{caller}"})

    # 上游：我读取的 cube（数据来源）
    for (cube,) in con.execute(
        "SELECT DISTINCT cube_name FROM process_reads_cube WHERE process_name = ? ORDER BY 1 LIMIT ?",
        [name, max_cubes],
    ).fetchall():
        upstream.append({"name": cube, "kind": "cube", "link": f"/explorer/cube/{cube}"})

    # 下游：我调用谁（TI）
    for (callee,) in con.execute(
        "SELECT DISTINCT callee FROM process_calls_process WHERE caller = ? ORDER BY 1 LIMIT ?",
        [name, max_down],
    ).fetchall():
        downstream.append({"name": callee, "kind": "process",
                           "link": f"/explorer/process/{callee}"})

    # 下游：我写入的 cube
    for (cube,) in con.execute(
        "SELECT DISTINCT cube_name FROM process_writes_cube WHERE process_name = ? ORDER BY 1 LIMIT ?",
        [name, max_cubes],
    ).fetchall():
        downstream.append({"name": cube, "kind": "cube", "link": f"/explorer/cube/{cube}"})

    return {"root": name, "upstream": upstream, "downstream": downstream}


def process_graph_rich(
    con: duckdb.DuckDBPyConnection, name: str, max_depth: int = 2, max_breadth: int = 12, max_nodes: int = 60
) -> dict:
    """知识图谱主查询：以 TI 为中心，递归展开上下游「调用链 + cube 读写」。

    相比 process_relation_graph 的扁平结构，这里：
    - 递归展开 TI→TI 调用链（上游 callers 链、下游 callees 链），带 visited 去重防环；
    - 每个 TI 节点附带其读/写的 cube（各取前 max_cubes 个）；
    - 过滤规则同 process_relation_graph：只用 process_calls_process（业务调用），
      忽略 bedrock 框架调用；cube 读写在 ingest 阶段已过滤 `}` 与 bedrock。

    返回：
    {
      "root": name,
      "root_reads": [cube...],   # 中心 TI 读取的 cube
      "root_writes": [cube...],  # 中心 TI 写入的 cube
      "callers": [ {name, depth, reads:[...], writes:[...]} ... ],  # 上游调用链（递归）
      "callees": [ {name, depth, reads:[...], writes:[...]} ... ],  # 下游调用链（递归）
    }
    """
    max_nodes=max(1,min(120,max_nodes));max_depth=max(0,min(4,max_depth));max_breadth=max(1,min(20,max_breadth))
    budget={'nodes':1,'truncated':False}
    def _cubes(proc: str, tbl: str, col: str) -> list[str]:
        return [r[0] for r in con.execute(
            f"SELECT DISTINCT {col} FROM {tbl} WHERE process_name = ? ORDER BY 1 LIMIT ?",
            [proc, max_breadth],
        ).fetchall()]

    def _walk(parent: str, direction: str, depth: int, visited: set) -> list[dict]:
        if depth >= max_depth:
            if con.execute('SELECT 1 FROM process_calls_process WHERE '+('caller' if direction=='down' else 'callee')+'=? LIMIT 1',[parent]).fetchone():budget['truncated']=True
            return []
        col = "callee" if direction == "down" else "caller"
        other = "caller" if direction == "down" else "callee"
        rows = con.execute(
            f"SELECT DISTINCT {col} FROM process_calls_process WHERE {other} = ? ORDER BY 1 LIMIT ?",
            [parent, max_breadth+1],
        ).fetchall()
        out = []
        if len(rows)>max_breadth:budget['truncated']=True
        for (child,) in rows[:max_breadth]:
            if budget['nodes']>=max_nodes:budget['truncated']=True;break
            if child in visited:
                continue
            visited.add(child)
            budget['nodes']+=1
            node = {
                "name": child,
                "depth": depth + 1,
                "reads": _cubes(child, "process_reads_cube", "cube_name"),
                "writes": _cubes(child, "process_writes_cube", "cube_name"),
            }
            kids = _walk(child, direction, depth + 1, visited)
            if kids:
                node["children"] = kids
            out.append(node)
        return out

    root_reads = _cubes(name, "process_reads_cube", "cube_name")
    root_writes = _cubes(name, "process_writes_cube", "cube_name")

    visited = {name}
    callers = _walk(name, "up", 0, visited)
    visited = {name}
    callees = _walk(name, "down", 0, visited)

    return {
        "root": name, "budget":dict(**budget,max_nodes=max_nodes,max_depth=max_depth),
        "root_reads": root_reads,
        "root_writes": root_writes,
        "callers": callers,
        "callees": callees,
    }


def ti_write_slices(con: duckdb.DuckDBPyConnection, name: str) -> dict:
    """「TI 视角」写入切面：给定 TI 进程，返回它往每个目标 Cube 写入的切面明细。

    这是知识图谱页的核心查询——用户打开一个 TI，最关心的是「它往哪个 cube 的哪个
    切面（维度组合）写数据」，而非上下游调用了谁。

    切面组装逻辑与 cube_lineage 的 writers 完全一致（复用同样的字段与差异维度折叠），
    区别只是视角：cube_lineage 是「给定 cube 反查写它的 TI」，本函数是「给定 TI 查它写的 cube」。

    返回：
    {
      "process": name,
      "writes": [                     # 每个目标 cube 一组
        {
          "cube": cube名,
          "dims": [维度名...],        # 该 cube 的维度顺序
          "write_points": [           # 该 TI 写该 cube 的所有写入点
            { write_point_id, operation, operation_human, conditions, conditions_human,
              dims: [ {index, dim_name, expr, value, source_cubes, is_param, is_variable, source_inferred} ...],
              source_cubes, diff_dims, summary, via_bedrock }
          ]
        }
      ],
      "reads": [cube名...],           # 该 TI 读取的 cube（数据来源，供对比展示）
    }
    """
    # 该 TI 读的 cube（数据来源）
    reads = sorted({r[0] for r in con.execute(
        "SELECT DISTINCT cube_name FROM process_reads_cube WHERE process_name = ?", [name]
    ).fetchall()})

    # 该 TI 写过的所有 cube（含 bedrock 搬运，ti_flow_dims 可能无维度记录）
    target_cubes = sorted({r[0] for r in con.execute(
        "SELECT DISTINCT target_cube FROM ti_flows WHERE process_name = ?", [name]
    ).fetchall()} | {r[0] for r in con.execute(
        "SELECT DISTINCT cube_name FROM process_writes_cube WHERE process_name = ?", [name]
    ).fetchall()})

    # 变量名 → 源头 cube 映射缓存（整个 TI 只算一次）
    var_source_cache: dict[str, list[str]] = _var_source_map(con, name)
    datasource_cache: str | None = None
    assignments_cache: dict | None = None

    def _assignments() -> dict:
        nonlocal assignments_cache
        if assignments_cache is None:
            from tm1_insight.ingest.hard_extract import extract_assignments
            row_p = con.execute(
                "SELECT prolog, metadata, data, epilog FROM processes WHERE name = ?", [name]
            ).fetchone()
            full_p = "\n".join([row_p[i] or "" for i in range(4)]) if row_p else ""
            assignments_cache = extract_assignments(full_p)
        return assignments_cache

    def _datasource() -> str | None:
        nonlocal datasource_cache
        if datasource_cache is None:
            datasource_cache = _ti_datasource_cube(con, name)
        return datasource_cache

    writes: list[dict] = []
    for cube in target_cubes:
        dims = [r[0] for r in con.execute(
            "SELECT dimension_name FROM cube_has_dimension WHERE cube_name = ? ORDER BY dim_order", [cube]
        ).fetchall()]

        rows = con.execute(
            """
            SELECT write_point_id, operation, dim_index, dim_expr, dim_value, conditions
            FROM ti_flow_dims
            WHERE process_name = ? AND target_cube = ?
            ORDER BY write_point_id, dim_index
            """,
            [name, cube],
        ).fetchall()

        wps_map: dict[str, dict] = {}
        for wp_id, op, dim_index, dim_expr, dim_value, conditions in rows:
            wp = wps_map.setdefault(wp_id, {
                "write_point_id": wp_id,
                "write_point_info": _split_write_point_id(wp_id),
                "operation": op,
                "operation_human": _op_human(op),
                "conditions": json.loads(conditions) if conditions else [],
                "conditions_human": [_translate_condition(c) for c in (json.loads(conditions) if conditions else [])],
                "dims": [],
            })
            dim_name = dims[dim_index] if 0 <= dim_index < len(dims) else f"<dim{dim_index}>"
            # 来源解析：与 cube_lineage 完全一致
            direct_src = _source_from_value(dim_value)
            is_param = False
            if direct_src:
                src_cubes = [direct_src]
                src_inferred = False
            elif dim_value.startswith("<") and dim_value.endswith(">"):
                var_name = dim_expr.strip()
                src_cubes = var_source_cache.get(var_name, [])
                src_inferred = False
                if not src_cubes:
                    if _var_is_param(con, name, var_name, _assignments()):
                        is_param = True
                    else:
                        ds = _datasource()
                        if ds:
                            src_cubes = [ds]
                            src_inferred = True
            else:
                src_cubes = []
                src_inferred = False
            wp["dims"].append({
                "index": dim_index,
                "dim_name": dim_name,
                "expr": dim_expr,
                "value": dim_value,
                "source_cube": direct_src,
                "source_cubes": src_cubes,
                "is_variable": bool(dim_value.startswith("<") and dim_value.endswith(">")),
                "is_param": is_param,
                "source_inferred": src_inferred,
            })

        write_points = list(wps_map.values())
        for wp in write_points:
            wp["source_cubes"] = sorted({
                s for d in wp["dims"] for s in d.get("source_cubes", [])
            })

        # bedrock 兜底：该 TI 写了该 cube 但 ti_flow_dims 无维度记录（纯 copy/clear）
        if not write_points:
            write_points.append({
                "write_point_id": f"{name}::{cube}::bedrock",
                "write_point_info": {"process": name, "cube": cube, "index": 0},
                "operation": "Bedrock",
                "operation_human": "Bedrock 数据搬运（copy/clear）",
                "conditions": [],
                "conditions_human": [],
                "dims": [],
                "source_cubes": [],
                "diff_dims": [],
                "summary": "通过 bedrock 搬运数据（无逐维度写入）",
                "via_bedrock": True,
            })

        # 差异维度折叠：同一 cube 多写入点，只提炼「取值不同的维度」作摘要
        if len(write_points) > 1:
            nd = max((len(wp["dims"]) for wp in write_points), default=0)
            varying: set[int] = set()
            for di in range(nd):
                vals = set()
                for wp in write_points:
                    if di < len(wp["dims"]):
                        vals.add(wp["dims"][di]["value"])
                if len(vals) > 1:
                    varying.add(di)
            for wp in write_points:
                diff = [d for d in wp["dims"] if d["index"] in varying]
                wp["diff_dims"] = diff
                parts = []
                last_idx = max((d["index"] for d in wp["dims"]), default=-1)
                for d in diff:
                    v = d["value"]
                    disp = d["expr"] if (v.startswith("<") and v.endswith(">")) else v
                    if d["index"] == last_idx:
                        parts.append(disp)
                    else:
                        parts.append(f"{d['dim_name']} = {disp}")
                wp["summary"] = " · ".join(parts)
        else:
            for wp in write_points:
                wp["diff_dims"] = []
                wp["summary"] = ""

        writes.append({
            "cube": cube,
            "dims": dims,
            "dimension_count": len(dims),
            "write_points": write_points,
        })

    return {"process": name, "reads": reads, "writes": writes}


# ---- Graph 层查询 ----
def cube_summary(con: duckdb.DuckDBPyConnection, cube: str) -> dict:
    """输入 Cube → 写者/读者/维度/Rule 来源（graph 层）。"""
    writers = [r[0] for r in con.execute(
        "SELECT DISTINCT process_name FROM process_writes_cube WHERE cube_name = ? ORDER BY 1",
        [cube],
    ).fetchall()]
    readers = [r[0] for r in con.execute(
        "SELECT DISTINCT process_name FROM process_reads_cube WHERE cube_name = ? ORDER BY 1",
        [cube],
    ).fetchall()]
    dims = [r[0] for r in con.execute(
        "SELECT dimension_name FROM cube_has_dimension WHERE cube_name = ? ORDER BY dim_order",
        [cube],
    ).fetchall()]
    rule_sources = [r[0] for r in con.execute(
        "SELECT source_cube FROM rule_references_cube WHERE cube_name = ? ORDER BY 1",
        [cube],
    ).fetchall()]
    return {
        "cube": cube,
        "dimensions": dims,
        "writers": writers,
        "readers": readers,
        "rule_sources": rule_sources,
    }


def cube_rule_semantics(con: duckdb.DuckDBPyConnection, cube: str) -> dict:
    """输入 Cube → 解析后的 Rule/Feeder 语义 IR（可解释计算逻辑）。

    纯本地解析：读取该 Cube 的 rules 源码 + 维度顺序，经 rule_semantics 解析器
    产出结构化 IR。不连接服务器、不执行规则；无法解析的表达式标记 UNKNOWN。
    """
    from tm1_insight.learning.rule_semantics import parse_rule_semantics

    row = con.execute(
        "SELECT rules FROM cubes WHERE name = ?", [cube]
    ).fetchone()
    if not row:
        # 语义区分：cube 不在当前快照范围内 vs 源模型本身不存在。
        # 当前快照只覆盖采样的模型范围，不能据此断言「源模型不存在」。
        return {"cube": cube, "available": False,
                "reason": "当前范围未发现该 Cube（可能不在本次快照采样范围内，不代表源模型不存在）"}
    code = row[0] or ""
    dims = [r[0] for r in con.execute(
        "SELECT dimension_name FROM cube_has_dimension WHERE cube_name = ? ORDER BY dim_order",
        [cube],
    ).fetchall()]
    cube_catalog = {r[0] for r in con.execute("SELECT name FROM cubes").fetchall()}
    try:
        parsed = parse_rule_semantics(code, cube, dims, cube_catalog)
    except Exception as exc:  # 解析器必须降级，不抛给调用方
        return {"cube": cube, "available": True, "error": str(exc),
                "rules": [], "feeders": [], "directives": [], "unknowns": [
                    {"cube":cube,"kind":"rule_source","reason":"Rule 解析器异常；源码结构未知","status":"UNKNOWN"}]}
    return {
        "cube": cube,
        "available": True,
        "dimensions": dims,
        "source_hash": parsed["source_hash"],
        "directives": parsed["directives"],
        "rules": parsed["rules"],
        "feeders": parsed["feeders"],
        "unknowns": parsed["unknowns"],
    }


def cube_lineage(con: duckdb.DuckDBPyConnection, cube: str) -> dict:
    """深血缘：输入 Cube → 上游源头 Cube + 写入者 TI → 每个写入点的维度值 + 源头 + IF 条件。

    额外返回：
    - dimension_details: 每个维度的名称 + 前 N 个元素名（横向表格展示）
    - writers 内每个 write_point 含 operation_human（中文翻译）、conditions_human（条件翻译）、
      write_point_info（拆分后的 TI名/目标cube/序号）
    - downstream: 下游（谁读取当前 cube）
    - upstream_of_sources: 每个源头 cube 的写入者（血缘再往上一层）
    """
    dims = [r[0] for r in con.execute(
        "SELECT dimension_name FROM cube_has_dimension WHERE cube_name = ? ORDER BY dim_order",
        [cube],
    ).fetchall()]

    # 每个维度的元素（横向表格展示，各取前 5 个）
    dimension_details = [
        {
            "name": d,
            "order": i,
            "elements": _dimension_elements(con, d, limit=5),
            "total": _dimension_element_count(con, d),
        }
        for i, d in enumerate(dims)
    ]

    # 上游源头：所有写入该 Cube 的 TI，其 flow 层解析出的 source_cubes 并集
    sources: set[str] = set()
    for (sc,) in con.execute(
        "SELECT DISTINCT source_cubes FROM ti_flows WHERE target_cube = ?", [cube]
    ).fetchall():
        if sc:
            sources.update(json.loads(sc))

    rows = con.execute(
        """
        SELECT process_name, write_point_id, operation, dim_index, dim_expr, dim_value, conditions
        FROM ti_flow_dims
        WHERE target_cube = ?
        ORDER BY process_name, write_point_id, dim_index
        """,
        [cube],
    ).fetchall()

    writers_map: dict[str, dict] = {}
    # 每个 TI 的「变量名 → 源头 cube」映射（变量维度标源头用）
    var_source_cache: dict[str, dict[str, list[str]]] = {}
    # 每个 TI 的「数据源 cube」（变量维度追不到具体取数时的兜底源头）
    datasource_cache: dict[str, str | None] = {}
    # 每个 TI 的「变量赋值表」（判断变量是否源自参数入参用）
    assignments_cache: dict[str, dict] = {}
    for process, wp_id, op, dim_index, dim_expr, dim_value, conditions in rows:
        wp = writers_map.setdefault(process, {}).setdefault(wp_id, {
            "write_point_id": wp_id,
            "write_point_info": _split_write_point_id(wp_id),
            "operation": op,
            "operation_human": _op_human(op),
            "conditions": json.loads(conditions) if conditions else [],
            "conditions_human": [_translate_condition(c) for c in (json.loads(conditions) if conditions else [])],
            "dims": [],
        })
        dim_name = dims[dim_index] if 0 <= dim_index < len(dims) else f"<dim{dim_index}>"
        # 来源：优先从 dim_value 的嵌套 CellGet 里解析；若 value 是变量（<...>），
        # 则按变量名去 prolog 里追溯其源头 cube（运行时变量取数）。
        direct_src = _source_from_value(dim_value)
        is_param = False
        if direct_src:
            src_cubes = [direct_src]
            src_inferred = False
        elif dim_value.startswith("<") and dim_value.endswith(">"):
            # 变量维度：查变量名 → 源头 cube 映射
            if process not in var_source_cache:
                var_source_cache[process] = _var_source_map(con, process)
            var_name = dim_expr.strip()
            src_cubes = var_source_cache[process].get(var_name, [])
            src_inferred = False
            if not src_cubes:
                # 判断是否源自参数入参（cScenario = pScenario 这类赋值链追溯）
                if process not in assignments_cache:
                    from tm1_insight.ingest.hard_extract import extract_assignments
                    row_p = con.execute(
                        "SELECT prolog, metadata, data, epilog FROM processes WHERE name = ?",
                        [process],
                    ).fetchone()
                    full_p = "\n".join([row_p[i] or "" for i in range(4)]) if row_p else ""
                    assignments_cache[process] = extract_assignments(full_p)
                if _var_is_param(con, process, var_name, assignments_cache[process]):
                    is_param = True
                else:
                    # 兜底：变量是数据源视图字段（如 <vYear>/<vMonth>），
                    # 其源头就是这个 TI 声明的数据源 cube（DatasourceNameForServer）。
                    if process not in datasource_cache:
                        datasource_cache[process] = _ti_datasource_cube(con, process)
                    ds = datasource_cache[process]
                    if ds:
                        src_cubes = [ds]
                        src_inferred = True
        else:
            src_cubes = []
            src_inferred = False
        wp["dims"].append({
            "index": dim_index,
            "dim_name": dim_name,
            "expr": dim_expr,
            "value": dim_value,
            "source_cube": direct_src,
            "source_cubes": src_cubes,
            "is_variable": bool(dim_value.startswith("<") and dim_value.endswith(">")),
            "is_param": is_param,
            "source_inferred": src_inferred,
        })

    for wps in writers_map.values():
        for wp in wps.values():
            wp["source_cubes"] = sorted({
                s for d in wp["dims"] for s in d.get("source_cubes", [])
            })

    writers = [
        {"process": p, "write_points": list(wps.values())}
        for p, wps in writers_map.items()
    ]

    # 兜底：bedrock copy / clear 等「无维度写入点」的 TI（数据通过 bedrock 传递，
    # 无 CellPutN，故 ti_flow_dims 里没有维度记录），从 process_writes_cube 补进 writers，
    # 保证「谁写了这个 cube」在 cube 页完整可见（如 Data.Version.Copy 用 }bedrock.cube.data.copy）。
    existing_writers = {w["process"] for w in writers}
    for (pname,) in con.execute(
        "SELECT DISTINCT process_name FROM process_writes_cube WHERE cube_name = ? ORDER BY 1",
        [cube],
    ).fetchall():
        if pname in existing_writers:
            continue
        # 确认该 TI 没有 ti_flow_dims 记录（即纯 bedrock 写入），补一个占位写入点
        writers.append({
            "process": pname,
            "write_points": [{
                "write_point_id": f"{pname}::{cube}::bedrock",
                "write_point_info": {"process": pname, "cube": cube, "index": 0},
                "operation": "Bedrock",
                "operation_human": "Bedrock 数据搬运（copy/clear）",
                "conditions": [],
                "conditions_human": [],
                "dims": [],
                "source_cubes": [],
                "diff_dims": [],
                "summary": "通过 bedrock 搬运数据（无逐维度写入）",
                "via_bedrock": True,
            }],
        })

    # 为每个 TI 的写入点计算「差异维度摘要」：
    # 同一 TI 写同一 cube 时，往往只有 1 个维度（通常是 measure/账户）在变，
    # 其余维度完全相同。把「不同写入点之间取值不同的维度」提取出来作为摘要，
    # 让 UI 默认折叠展示，运维一眼看到「这个写入点写的是哪个账户」，避免 40+ 个
    # 几乎相同的写入点堆在一起像重复。
    for w in writers:
        wps = w["write_points"]
        if len(wps) <= 1:
            for wp in wps:
                wp["diff_dims"] = []
                wp["summary"] = ""
            continue
        # 维度数对齐（各写入点维度数应一致，防御性取最大）
        nd = max((len(wp["dims"]) for wp in wps), default=0)
        # 对每个 dim_index，判断该维度在不同写入点间是否取值有差异
        varying: set[int] = set()
        for di in range(nd):
            vals = set()
            for wp in wps:
                if di < len(wp["dims"]):
                    vals.add(wp["dims"][di]["value"])
            if len(vals) > 1:
                varying.add(di)
        for wp in wps:
            diff = [d for d in wp["dims"] if d["index"] in varying]
            wp["diff_dims"] = diff
            # 摘要 = 差异维度的「维度名 = 值」。measure 维度（最后一个）只显示值，
            # 避免长维度名（如 "M BP Business Analysis KPI - SC"）重复 43 遍。
            parts = []
            last_idx = max((d["index"] for d in wp["dims"]), default=-1)
            for d in diff:
                v = d["value"]
                if v.startswith("<") and v.endswith(">"):
                    disp = d["expr"]  # 变量显示变量名
                else:
                    disp = v
                if d["index"] == last_idx:
                    parts.append(disp)          # measure 维度只显示值
                else:
                    parts.append(f"{d['dim_name']} = {disp}")
            wp["summary"] = " · ".join(parts)

    # 每个源头 cube 的维度（血缘图展示「源头 cube 有哪些维度」）
    source_details: dict[str, dict] = {}
    for src in sorted(sources):
        src_dims = [r[0] for r in con.execute(
            "SELECT dimension_name FROM cube_has_dimension WHERE cube_name = ? ORDER BY dim_order",
            [src],
        ).fetchall()]
        source_details[src] = {
            "name": src,
            "dimensions": src_dims,
            "dimension_count": len(src_dims),
        }

    # 下游：谁读取当前 cube（用于「血缘往下一层」）
    downstream = [r[0] for r in con.execute(
        "SELECT DISTINCT process_name FROM process_reads_cube WHERE cube_name = ? ORDER BY 1",
        [cube],
    ).fetchall()]

    # 每个源头 cube 的写入者（血缘再往上一层：源头 cube 的源头）
    upstream_of_sources: dict[str, list[str]] = {}
    for src in sorted(sources):
        src_writers = [r[0] for r in con.execute(
            "SELECT DISTINCT process_name FROM process_writes_cube WHERE cube_name = ? ORDER BY 1",
            [src],
        ).fetchall()]
        upstream_of_sources[src] = src_writers

    return {
        "cube": cube,
        "dimensions": dims,
        "dimension_details": dimension_details,
        "sources": sorted(sources),
        "source_details": [source_details[s] for s in sorted(sources)],
        "writers": writers,
        "downstream": downstream,
        "upstream_of_sources": upstream_of_sources,
        "frontend_pages": cube_frontend_pages(con, cube),
    }


def search_processes(con: duckdb.DuckDBPyConnection, keyword: str, limit: int = 50) -> list[str]:
    """按关键字模糊匹配 TI 进程名/代码。"""
    like = f"%{keyword}%"
    return [r[0] for r in con.execute(
        """
        SELECT DISTINCT name FROM processes
        WHERE name ILIKE ? OR prolog ILIKE ? OR metadata ILIKE ? OR data ILIKE ? OR epilog ILIKE ?
        ORDER BY name LIMIT ?
        """,
        [like, like, like, like, like, limit],
    ).fetchall()]


def search_process_page(
    con: duckdb.DuckDBPyConnection, keyword: str = "", scope: str = "name",
    offset: int = 0, limit: int = 100,
) -> dict:
    """Literal, paginated TI search. Code hits are source text, never execution/data edges.

    Only fetch source text for the returned page and only in code/all mode. The legacy
    search_processes contract remains available to existing API/graph consumers.
    """
    if scope not in {"name", "code", "all"}:
        raise ValueError("Unsupported process search scope")
    keyword = keyword.strip()
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    fields = ["name"] if scope == "name" or not keyword else ["prolog", "metadata", "data", "epilog"]
    if scope == "all" and keyword:
        fields.insert(0, "name")
    # strpos treats %, _ and quotes as literal characters; no SQL wildcard surprises.
    where = " OR ".join(f"strpos(lower(coalesce({field}, '')), lower(?)) > 0" for field in fields)
    params = [keyword] * len(fields)
    total = con.execute(f"SELECT count(*) FROM processes WHERE {where}", params).fetchone()[0]
    offset = min(offset, ((max(total, 1) - 1) // limit) * limit)
    columns = "name" if scope == "name" or not keyword else "name, prolog, metadata, data, epilog"
    rows = con.execute(
        f"SELECT {columns} FROM processes WHERE {where} "
        "ORDER BY CASE WHEN lower(name) = lower(?) THEN 0 "
        "WHEN starts_with(lower(name), lower(?)) THEN 1 "
        "WHEN strpos(lower(name), lower(?)) > 0 THEN 2 ELSE 3 END, lower(name), name "
        "LIMIT ? OFFSET ?",
        params + [keyword, keyword, keyword, limit, offset],
    ).fetchall()
    items = []
    source_pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    for row in rows:
        match = {"kind": "name"}
        if keyword and (scope == "code" or keyword.lower() not in row[0].lower()):
            # One inspectable first occurrence per process, bounded to this page.
            for section, source in zip(("prolog", "metadata", "data", "epilog"), row[1:]):
                source = source or ""
                occurrence = source_pattern.search(source)
                if occurrence is None:
                    continue
                position = occurrence.start()
                line = source.count("\n", 0, position) + 1
                line_start = source.rfind("\n", 0, position) + 1
                column = position - line_start
                start = max(line_start, position - 60)
                match = {"kind": "code", "section": section, "line": line,
                         "column": column + 1,
                         "excerpt": ("…" if start > line_start else "") + source[start:start + 240].split("\n")[0]}
                break
        items.append({"name": row[0], "match": match})
    return {"items": items, "total": total, "offset": offset, "limit": limit,
            "q": keyword, "scope": scope}


def search_objects(con: duckdb.DuckDBPyConnection, keyword: str, limit: int = 20) -> dict:
    """统一搜索 Cube + TI 进程 + Chore，返回带类型的对象列表（用于工作台/全局搜索）。

    返回 { "cubes": [...], "processes": [...], "chores": [...] }，各含 name 与类型标记，
    按名称匹配优先（前缀/包含），cube 名大小写不敏感。
    """
    kw = keyword.strip()
    if not kw:
        return {"cubes": [], "processes": [], "chores": []}
    limit = max(1, min(limit, 50))
    result = {}
    for key in ("cubes", "processes", "chores"):
        result[key] = [row[0] for row in con.execute(
            f"SELECT name FROM {key} WHERE strpos(lower(name), lower(?)) > 0 "
            "ORDER BY CASE WHEN lower(name)=lower(?) THEN 0 "
            "WHEN starts_with(lower(name),lower(?)) THEN 1 ELSE 2 END, lower(name), name LIMIT ?",
            [kw, kw, kw, limit],
        ).fetchall()]
    return result


def cube_frontend_pages(con: duckdb.DuckDBPyConnection, cube: str) -> list[dict]:
    """查该 Cube 出现在哪些前端 Excel 页面（front_backend_mapping 反向匹配）。

    backend_cubes 是大写逗号分隔字符串，需大小写不敏感、按单词边界匹配，
    避免 'SYS PARAMETER' 误命中 'SYS PARAMETER ...' 之外的其他 cube。
    返回 [{menu, excel_file}]，按 menu 排序。
    """
    rows = con.execute(
        "SELECT menu, excel_file, backend_cubes FROM front_backend_mapping ORDER BY menu, excel_file"
    ).fetchall()
    cube_u = cube.upper()
    pages: list[dict] = []
    for menu, excel_file, backend_cubes in rows:
        if not backend_cubes:
            continue
        # 逗号分隔成集合，大小写不敏感精确匹配
        names = {n.strip().upper() for n in backend_cubes.split(",")}
        if cube_u in names:
            pages.append({"menu": menu or "", "excel_file": excel_file})
    return pages


# ---- 值溯源排查（MDX 反解 + 写入点匹配） ----
def parse_mdx(mdx: str) -> dict:
    """从一段 MDX 查询里反解出「Cube 名 + 各维度的元素」。

    支持的常见形态（大小写不敏感）：
      SELECT {...} ON 0, {...} ON 1 FROM [Cube]
      { [Dim].[Elem1], [Dim].[Elem2] }  —— 维度成员集合
      WHERE ([Dim].[Elem], ...)
      [Dim].[Elem]  —— 任意单个成员

    返回 { cube, members: {维度: [元素...]} }，members 键为维度名（去方括号、去空格）。
    """
    result: dict = {"cube": None, "members": {}}
    if not mdx:
        return result

    # 1. 提取 FROM 后的 cube 名（FROM [Cube] 或 FROM Cube，cube 名可能含空格）
    #    优先匹配方括号包裹的 [含空格的 cube 名]，否则匹配到下一个空白/换行
    m_from = re.search(r"\bFROM\s+\[([^\]]+)\]", mdx, flags=re.IGNORECASE)
    if m_from:
        result["cube"] = m_from.group(1).strip()
    else:
        m_from = re.search(r"\bFROM\s+([^\s\[\]]+)", mdx, flags=re.IGNORECASE)
        if m_from:
            result["cube"] = m_from.group(1).strip()

    # 2. 提取成员：优先匹配三级 [Dim].[Dim].[Elem]（TM1 常见，如 [Scenario].[Scenario].[BG]），
    #    再匹配二级 [Dim].[Elem]。同时剔除维度自引用（[Dim].[Dim]）与集合函数里的维度引用。
    #    TM1SubsetToSet([Month].[Month], "...") 里的 [Month].[Month] 是「维度.自身」而非元素。
    #
    #    做法：先扫出所有「连续的 [X].[Y](.[Z])?」片段，再按上下文判定。
    #    简单可靠策略——先抓三级，标记其维度；再抓二级，跳过已被三级覆盖的（维度自引用）位置。
    member_re = re.compile(r"\[([^\]\.]+)\]\s*\.\s*\[([^\]]+)\]")

    def _add(dim: str, elem: str) -> None:
        # 跳过 ALL 层级与维度自引用
        if elem.lower() in ("all", "all members", "root"):
            return
        if dim.strip().lower() == elem.strip().lower():
            return
        result["members"].setdefault(dim.strip(), [])
        if elem not in result["members"][dim.strip()]:
            result["members"][dim.strip()].append(elem)

    # 先把 PROPERTIES 子句里的属性声明从待解析文本中剔除：
    # 形如 PROPERTIES [Dim].[Dim].[AttrName], ... ON ROWS/COLUMNS —— 属性名（Caption zh-Hans、
    # 描述、代码和描述 等）不是维度成员，不应参与匹配。
    # 做法：找到 PROPERTIES 关键字后、到 ON ROWS/ON COLUMNS 之间的区间，整体屏蔽。
    body = mdx
    body = re.sub(
        r"\bPROPERTIES\b.{0,200}?\bON\s+(?:ROWS|COLUMNS|0|1)\b",
        lambda m: " " * len(m.group(0)),
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 2a. 三级成员 [Dim].[Dim].[Elem]：真正的维度=第一段，元素=第三段
    triple_re = re.compile(r"\[([^\]\.]+)\]\s*\.\s*\[([^\]\.]+)\]\s*\.\s*\[([^\]]+)\]")
    for m in triple_re.finditer(body):
        d0, d1, elem = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        # [Dim].[Dim].[Elem]：第一、二段相同（维度自引用），元素是第三段
        if d0.lower() == d1.lower():
            _add(d0, elem)

    # 2b. 二级成员 [Dim].[Elem]（但跳过三级成员的中间段 [Dim].[Dim] 这类自引用）
    for m in member_re.finditer(body):
        dim = m.group(1).strip()
        elem = m.group(2).strip()
        _add(dim, elem)

    return result


def trace_cell_value(con: duckdb.DuckDBPyConnection, cube: str, dim_members: dict | None = None, *, strict: bool = False, focus_dimension: str | None = None) -> dict:
    """「值从哪里来」排查：给定 Cube + 若干维度元素（交叉点），找出可能写入该交叉点的 TI。

    策略：
    1. 取该 Cube 的全部写入点（ti_flow_dims），逐个判断其写入维度是否「覆盖」了给定交叉点。
       - 若某写入点把某维度写成固定值（如 '0032'），且该值与交叉点该维度元素一致 → 命中。
       - 若写成变量（如 <pScenario>、<vMonth>）→ 视为「可能命中」（变量取值未知，需运行时核实）。
       - 若交叉点没指定某维度，则该维度不参与匹配（通配）。
    2. 对命中的写入点，回溯其 source_cubes（上游源头），并标记上游是否前端输入页面。
    3. **按 TI 去重合并**：同一 TI 的多个写入点（如 12 个月份各一个 CellIncrementN）
       合并为一个候选卡片，避免重复堆列——卡片上标注命中的写入点数量与差异维度摘要。

    返回：
      { cube, dimensions, members, candidates: [
          { process, operation_human, matched_dims, variable_dims, source_cubes,
            upstream_frontend, write_point_count, diff_summary, score }
        ]
      }
    """
    dims = [r[0] for r in con.execute(
        "SELECT dimension_name FROM cube_has_dimension WHERE cube_name = ? ORDER BY dim_order", [cube]
    ).fetchall()]

    # 规范化交叉点：维度名 → 元素集合（大小写不敏感）
    target: dict[str, set[str]] = {}
    if dim_members:
        for d, elems in dim_members.items():
            dl = d.lower()
            target[dl] = {e.lower() for e in elems}

    rows = con.execute(
        """
        SELECT process_name, write_point_id, operation, dim_index, dim_value, conditions
        FROM ti_flow_dims WHERE target_cube = ? ORDER BY process_name, write_point_id, dim_index
        """,
        [cube],
    ).fetchall()

    # 按 (process, write_point_id) 分组
    from collections import OrderedDict
    wps: "OrderedDict[tuple, dict]" = OrderedDict()
    for process, wp_id, op, dim_index, dim_value, conditions in rows:
        key = (process, wp_id)
        wp = wps.setdefault(key, {
            "process": process, "write_point_id": wp_id, "operation": op,
            "operation_human": _op_human(op),
            "conditions": json.loads(conditions) if conditions else [],
            "dims": [],
        })
        dim_name = dims[dim_index] if 0 <= dim_index < len(dims) else f"<dim{dim_index}>"
        wp["dims"].append({"dim_index": dim_index, "dim_name": dim_name, "value": dim_value})

    # 逐个写入点做交叉点匹配，得到「命中的写入点」集合
    matched_wps: list[dict] = []   # 每个元素 = 命中的 wp（含 matched_dims / variable_dims）
    relaxed = False
    for wp in wps.values():
        if not target:
            # 未指定交叉点：列出所有写入点（不做过滤）
            matched_wps.append({**wp, "matched_dims": [], "variable_dims": [], "match_mode": "all"})
            continue
        # 判断该写入点是否覆盖给定交叉点，并计算相似度
        matched: list[str] = []       # 精确命中（字面量一致）
        variable: list[str] = []      # 变量命中（运行时取值，可能命中）
        mismatched: list[str] = []    # 字面量不一致（明确不命中）
        for d in wp["dims"]:
            dl = d["dim_name"].lower()
            if dl not in target:
                continue  # 交叉点未指定此维度，通配（不参与打分）
            val = (d["value"] or "").strip()
            if not val:
                variable.append(d["dim_name"])
                continue
            # 变量（<...>）视为可能命中；字面量需精确匹配（大小写不敏感）
            if val.startswith("<") and val.endswith(">"):
                variable.append(d["dim_name"])
                continue
            # 值里带源头标记 ←cube[...]→ 的，属于运行时变量取数，视为可能命中
            if "←" in val:
                variable.append(d["dim_name"])
                continue
            if val.lower() in target[dl]:
                matched.append(d["dim_name"])
            else:
                mismatched.append(f"{d['dim_name']}={val}")

        # Missing coordinates are not evidence of an exact match.
        present = {d["dim_name"].lower() for d in wp["dims"]}
        variable.extend(d for d in target if d not in present)
        # 只要没有「明确不命中」的字面量，就作为候选（变量维度不阻断）
        if not mismatched:
            matched_wps.append({**wp, "matched_dims": matched, "variable_dims": variable,
                                "match_mode": "exact" if not variable else "partial"})

    # 无「无冲突」候选时，降级为宽松匹配：只看维度名命中，忽略字面量不一致
    if not matched_wps and target and not strict:
        relaxed = True
        for wp in wps.values():
            matched = [d["dim_name"] for d in wp["dims"]
                       if d["dim_name"].lower() in target]
            if matched:
                matched_wps.append({**wp, "matched_dims": matched, "variable_dims": [],
                                    "match_mode": "relaxed"})

    # ===== 按 TI（process）聚合，去重合并 =====
    # 同一 TI 可能命中多个写入点（如 12 个月份），合并为一个候选卡片。
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for wp in matched_wps:
        g = groups.setdefault(wp["process"], {
            "process": wp["process"],
            "operations": [],
            "conditions": [],
            "wps": [],
        })
        if wp["operation_human"] and wp["operation_human"] not in g["operations"]:
            g["operations"].append(wp["operation_human"])
        for c in wp["conditions"]:
            if c not in g["conditions"]:
                g["conditions"].append(c)
        g["wps"].append(wp)

    candidates: list[dict] = []
    for process, g in groups.items():
        wps_in_group = g["wps"]
        cand = {
            "process": process,
            "write_point_count": len(wps_in_group),
            "operation_human": " · ".join(g["operations"]),
            "conditions_human": [_translate_condition(c) for c in g["conditions"]],
            # 命中的维度并集（去重，保持维度顺序）
            "matched_dims": sorted({d for wp in wps_in_group for d in wp["matched_dims"]},
                                   key=lambda x: dims.index(x) if x in dims else 999),
            "variable_dims": sorted({d for wp in wps_in_group for d in wp["variable_dims"]},
                                    key=lambda x: dims.index(x) if x in dims else 999),
            "match_mode": wps_in_group[0]["match_mode"],
        }
        candidates.append(cand)

    # 每个候选的 source_cubes（上游源头）与前端输入标记
    for cand in candidates:
        srcs = set()
        for (sc,) in con.execute(
            "SELECT source_cubes FROM ti_flows WHERE process_name = ? AND target_cube = ?", [cand["process"], cube]
        ).fetchall():
            if sc:
                srcs.update(json.loads(sc))
        cand["source_cubes"] = sorted(srcs)
        cand["upstream_frontend"] = [
            s for s in cand["source_cubes"] if cube_frontend_pages(con, s)
        ]

    # 相似度打分与排序（仅当有交叉点维度时才有意义）
    if target:
        n_target = len(target)
        for cand in candidates:
            matched = len(cand.get("matched_dims", []))
            variable = len(cand.get("variable_dims", []))
            # 精确命中权重 1.0，变量命中权重 0.5
            score = (matched + variable * 0.5) / n_target * 100.0
            cand["score"] = round(score, 1)
        # 按分数降序：精确命中越多越靠前；同分时变量少的优先（更确定）
        candidates.sort(
            key=lambda c: (c.get("score", 0), -len(c.get("variable_dims", []))),
            reverse=True,
        )

    if focus_dimension:
        focus = focus_dimension.lower()
        candidates.sort(key=lambda c: (
            -int(any(d.lower() == focus for d in c["matched_dims"])),
            -int(any(d.lower() == focus for d in c["variable_dims"])),
            c["process"].lower(),
        ))

    return {
        "cube": cube,
        "dimensions": dims,
        "members": dim_members or {},
        "candidates": candidates,
        "matched_count": len(candidates),
        "relaxed": relaxed,
    }


def _trace_candidate(con: duckdb.DuckDBPyConnection, wp: dict) -> dict:
    """把一个写入点规整成排查候选（翻译条件 + 来源变量）。"""
    return {
        "process": wp["process"],
        "write_point_id": wp["write_point_id"],
        "operation": wp["operation"],
        "operation_human": wp["operation_human"],
        "conditions": wp["conditions"],
        "conditions_human": [_translate_condition(c) for c in wp["conditions"]],
        "dims": wp["dims"],
    }


# ---- Explorer 视图查询 ----
def list_cubes(con: duckdb.DuckDBPyConnection, with_rules_only: bool = False) -> list[dict]:
    where = "WHERE has_rules = true" if with_rules_only else ""
    return [
        {"name": r[0], "has_rules": r[1], "dimension_count": r[2]}
        for r in con.execute(
            f"SELECT name, has_rules, dimension_count FROM cubes {where} ORDER BY name"
        ).fetchall()
    ]


def search_cubes(con: duckdb.DuckDBPyConnection, keyword: str = "",
                 offset: int = 0, limit: int = 100) -> dict:
    """分页 + 服务端搜索 Cube 列表，返回 {items, total, offset, limit}。"""
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        total = con.execute(
            "SELECT count(*) FROM cubes WHERE name ILIKE ?", [like]
        ).fetchone()[0]
        items = [
            {"name": r[0], "has_rules": r[1], "dimension_count": r[2]}
            for r in con.execute(
                "SELECT name, has_rules, dimension_count FROM cubes "
                "WHERE name ILIKE ? ORDER BY name LIMIT ? OFFSET ?",
                [like, limit, offset],
            ).fetchall()
        ]
    else:
        total = con.execute("SELECT count(*) FROM cubes").fetchone()[0]
        items = [
            {"name": r[0], "has_rules": r[1], "dimension_count": r[2]}
            for r in con.execute(
                "SELECT name, has_rules, dimension_count FROM cubes "
                "ORDER BY name LIMIT ? OFFSET ?",
                [limit, offset],
            ).fetchall()
        ]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


def list_processes(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [r[0] for r in con.execute("SELECT name FROM processes ORDER BY name").fetchall()]


def list_chores(con: duckdb.DuckDBPyConnection) -> list[dict]:
    return [
        {"name": r[0], "process_count": r[1]}
        for r in con.execute("SELECT name, process_count FROM chores ORDER BY name").fetchall()
    ]


def search_chore_page(con, keyword: str = "", offset: int = 0, limit: int = 50) -> dict:
    keyword = keyword.strip()
    limit = max(1, min(limit, 100))
    total = con.execute("SELECT count(*) FROM chores WHERE strpos(lower(name), lower(?)) > 0",
                        [keyword]).fetchone()[0]
    offset = min(max(offset, 0), ((max(total, 1) - 1) // limit) * limit)
    items = [{"name": row[0], "process_count": row[1]} for row in con.execute(
        "SELECT name, process_count FROM chores WHERE strpos(lower(name), lower(?)) > 0 "
        "ORDER BY lower(name), name LIMIT ? OFFSET ?", [keyword, limit, offset]).fetchall()]
    return {"items": items, "total": total, "offset": offset, "limit": limit, "q": keyword}


def get_chore(con: duckdb.DuckDBPyConnection, name: str) -> dict | None:
    """Recorded schedule evidence only: do not invent order for incomplete metadata."""
    # 调度定义字段（start_time / frequency / execution_mode / active）是增量迁移新增的列，
    # 旧库若无这些列则回退到空值（历史快照兼容）。用 try 包裹查询列名，避免旧库报错。
    schedule_cols = ("start_time", "frequency", "execution_mode", "active")
    try:
        row = con.execute(
            "SELECT name, processes, process_count, start_time, frequency, execution_mode, active "
            "FROM chores WHERE name = ?", [name]
        ).fetchone()
    except Exception:  # noqa: BLE001 —— 旧库无调度列，回退到旧列
        row = con.execute(
            "SELECT name, processes, process_count FROM chores WHERE name = ?", [name]
        ).fetchone()
    if not row:
        return None
    schedule = {}
    if len(row) > 3:
        schedule = {
            "start_time": row[3] or "",
            "frequency": row[4] or "",
            "execution_mode": row[5] or "",
            "active": row[6] or "",
        }
    steps = []
    warnings = []
    source_field = "chores.processes"
    try:
        raw = json.loads(row[1] or "[]")
        if isinstance(raw, list):
            steps = raw
        else:
            warnings.append("步骤 JSON 不是受支持的列表格式，尝试使用关联表。")
    except (ValueError, TypeError):
        warnings.append("步骤 JSON 无法读取，尝试使用已保存的关联表。")
    # 若 processes JSON 为空，回退查 chore_runs_process 关联表
    if not steps:
        source_field = "chore_runs_process"
        steps = [
            {"name": r[0], "step_order": r[1]}
            for r in con.execute(
                "SELECT process_name, step_order FROM chore_runs_process "
                "WHERE chore_name = ? ORDER BY step_order NULLS LAST, process_name", [name]
            ).fetchall()
        ]
    normalized = []
    for index, step in enumerate(steps):
        item = step if isinstance(step, dict) else {"name": step if isinstance(step, str) else None}
        order = item.get("step_order")
        valid_order = isinstance(order, int) and not isinstance(order, bool) and order >= 0
        normalized.append({**item, "name": item.get("name") if isinstance(item.get("name"), str) else "",
                           "step_order": order if valid_order else None, "recorded_order": order,
                           "source_index": index,
                           "evidence": f"{source_field}[{index}]" if source_field == "chores.processes" else "chore_runs_process.step_order"})
    orders = [step["step_order"] for step in normalized]
    explicit_order = bool(normalized) and all(order is not None for order in orders) and len(set(orders)) == len(orders)
    if explicit_order:
        normalized.sort(key=lambda step: step["step_order"])
    elif normalized:
        warnings.append("执行序号缺失、无效或重复；仅按存储位置展示，不能确认执行次序。")
    names = [step["name"] for step in normalized if step["name"]]
    available = set()
    if names:
        available = {row[0] for row in con.execute(
            "SELECT name FROM processes WHERE name IN (" + ",".join("?" for _ in names) + ")", names).fetchall()}
    for position, step in enumerate(normalized, 1):
        step["position"] = position
        step["exists"] = step["name"] in available
    declared_count = row[2] or 0
    if declared_count != len(normalized):
        warnings.append("已保存的步骤数量与明细数量不一致，明细可能不完整。")
    if any(not step["exists"] for step in normalized):
        warnings.append("部分步骤的 TI 名称缺失或当前本地库未找到该 TI；这不证明服务器对象已删除。")
    return {
        "name": row[0],
        "process_count": declared_count,
        "steps": normalized,
        "order_status": "recorded" if explicit_order else "unknown",
        "schedule": schedule,
        "warnings": warnings,
    }


def get_process(con: duckdb.DuckDBPyConnection, name: str) -> dict | None:
    row = con.execute(
        "SELECT name, prolog, metadata, data, epilog, parameters, datasource FROM processes WHERE name = ?",
        [name],
    ).fetchone()
    if not row:
        return None

    prolog = row[1] or ""
    metadata = row[2] or ""
    data = row[3] or ""
    epilog = row[4] or ""

    # 引用 Cube：关系层（正则，抓字面量）+ 血缘层（解析变量后的完整读写）取并集
    reads: set[str] = {r[0] for r in con.execute(
        "SELECT DISTINCT cube_name FROM process_reads_cube WHERE process_name = ?", [name]
    ).fetchall()}
    writes: set[str] = {r[0] for r in con.execute(
        "SELECT DISTINCT cube_name FROM process_writes_cube WHERE process_name = ?", [name]
    ).fetchall()}
    for (sc,) in con.execute(
        "SELECT DISTINCT source_cubes FROM ti_flows WHERE process_name = ?", [name]
    ).fetchall():
        if sc:
            reads.update(json.loads(sc))
    writes.update(r[0] for r in con.execute(
        "SELECT DISTINCT target_cube FROM ti_flows WHERE process_name = ?", [name]
    ).fetchall())

    # 变量：复用语句级解析器的赋值提取 + 值追溯
    from tm1_insight.ingest.hard_extract import extract_assignments, resolve_value

    full = "\n".join([prolog, metadata, data, epilog])
    var_map = extract_assignments(full)
    variables = [
        {"name": k, "value": resolve_value(v[-1], var_map)}
        for k, v in sorted(var_map.items())
    ]

    # 调用关系：调用了谁（子进程）+ 被谁调用（上游 caller）
    calls_process = [r[0] for r in con.execute(
        "SELECT DISTINCT callee FROM process_calls_process WHERE caller = ? ORDER BY 1", [name]
    ).fetchall()]
    business_calls = [r[0] for r in con.execute(
        "SELECT DISTINCT callee FROM ti_business_calls WHERE caller = ? ORDER BY 1", [name]
    ).fetchall()]
    framework_calls = [
        {"callee": r[0], "purpose": r[1] or ""}
        for r in con.execute(
            "SELECT callee, purpose FROM ti_framework_calls WHERE process_name = ? ORDER BY 1", [name]
        ).fetchall()
    ]
    called_by = sorted({r[0] for r in con.execute(
        "SELECT caller FROM process_calls_process WHERE callee = ?", [name]
    ).fetchall()} | {r[0] for r in con.execute(
        "SELECT caller FROM ti_business_calls WHERE callee = ?", [name]
    ).fetchall()})

    # 维度操作：维护维度 + 更新属性
    maintains_dims = [r[0] for r in con.execute(
        "SELECT DISTINCT dimension_name FROM process_maintains_dimension WHERE process_name = ? ORDER BY 1", [name]
    ).fetchall()]
    updates_attrs = [r[0] for r in con.execute(
        "SELECT DISTINCT dimension_name FROM process_updates_attribute WHERE process_name = ? ORDER BY 1", [name]
    ).fetchall()]

    # 各代码段行数
    def _lines(s: str) -> int:
        return len(s.split("\n")) if s.strip() else 0

    return {
        "name": row[0],
        "prolog": prolog,
        "metadata": metadata,
        "data": data,
        "epilog": epilog,
        "parameters": json.loads(row[5]) if row[5] else [],
        "datasource": json.loads(row[6]) if row[6] else None,
        "reads_cubes": sorted(reads),
        "writes_cubes": sorted(writes),
        "variables": variables,
        # 新增分析字段
        "source": _resolve_source_cube(con, prolog),
        "semantic_vars": _extract_semantic_vars(prolog, data, metadata, epilog),
        "calls_process": calls_process,
        "business_calls": business_calls,
        "framework_calls": framework_calls,
        "called_by": called_by,
        "maintains_dims": maintains_dims,
        "updates_attrs": updates_attrs,
        "section_lines": {
            "prolog": _lines(prolog),
            "metadata": _lines(metadata),
            "data": _lines(data),
            "epilog": _lines(epilog),
        },
        "total_lines": _lines(prolog) + _lines(metadata) + _lines(data) + _lines(epilog),
    }


def get_cube(con: duckdb.DuckDBPyConnection, name: str) -> dict | None:
    row = con.execute(
        "SELECT name, rules, has_rules, dimensions FROM cubes WHERE name = ?", [name]
    ).fetchone()
    if not row:
        return None
    return {
        "name": row[0],
        "rules": row[1] or "",
        "has_rules": row[2],
        "dimensions": json.loads(row[3]) if row[3] else [],
    }


# ---- Audit 视图查询 ----
def audit_summary(con: duckdb.DuckDBPyConnection) -> dict:
    row = con.execute("""SELECT count(*), count(*) FILTER (WHERE has_tm1),
        count(*) FILTER (WHERE risk = '高'),
        count(*) FILTER (WHERE asset_type IN ('Broken Link', 'Invalid Blob'))
        FROM excel_assets""").fetchone()
    return dict(zip(("total_assets", "with_tm1", "risk_high", "broken_link"), row),
                total_mappings=con.execute("SELECT count(*) FROM front_backend_mapping").fetchone()[0])


def audit_page(con: duckdb.DuckDBPyConnection, *, kind: str, keyword: str = "",
               risk: str = "", only_tm1: bool = False, only_broken: bool = False,
               page: int = 1, limit: int = 50) -> dict:
    """Filter the entire audit table in SQL; materialize only a bounded page.

    Literal substring search (including %/_); legacy full-list queries stay available.
    All displayed columns break ordering ties; identical rows are interchangeable.
    """
    if kind not in {"assets", "mappings"}:
        raise ValueError("Unknown audit table")
    if risk not in {"", "高", "中", "低"}:
        raise ValueError("Unknown risk")
    limit = min(100, max(1, limit))
    if kind == "assets":
        table = "excel_assets"
        columns = "menu, blob_name, asset_type, risk, link_status, excel_path, has_tm1, formula_count"
        search = "concat_ws(' ', menu, blob_name, asset_type, link_status)"
    else:
        table = "front_backend_mapping"
        columns = "menu, excel_file, backend_cubes, cube_count"
        search = "concat_ws(' ', menu, excel_file, backend_cubes)"
    clauses, params = [], []
    if keyword.strip():
        clauses.append(f"strpos(lower({search}), lower(?)) > 0")
        params.append(keyword.strip())
    if kind == "assets":
        if risk:
            clauses.append("risk = ?"); params.append(risk)
        if only_tm1:
            clauses.append("has_tm1 = true")
        if only_broken:
            clauses.append("asset_type IN ('Broken Link', 'Invalid Blob')")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    total = con.execute(f"SELECT count(*) FROM {table}{where}", params).fetchone()[0]
    pages = max(1, (total + limit - 1) // limit)
    page = min(pages, max(1, page))
    rows = con.execute(f"SELECT {columns} FROM {table}{where} ORDER BY {columns} LIMIT ? OFFSET ?",
                       params + [limit, (page - 1) * limit]).fetchall()
    items = [dict(zip(columns.split(", "), row)) for row in rows]
    for item in items:
        item["menu"] = item["menu"] or ""
        if kind == "mappings":
            item["backend_cubes"] = [c for c in (item["backend_cubes"] or "").split(", ") if c]
    return {"items": items, "total": total, "page": page, "pages": pages,
            "start": (page - 1) * limit + 1 if total else 0,
            "end": min(page * limit, total), "limit": limit}


def list_audit_assets(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """前端 Excel 资产清单。"""
    return [
        {
            "menu": r[0] or "",
            "blob_name": r[1],
            "asset_type": r[2],
            "risk": r[3] or "",
            "link_status": r[4] or "",
            "excel_path": r[5] or "",
            "has_tm1": r[6],
            "formula_count": r[7],
        }
        for r in con.execute(
            "SELECT menu, blob_name, asset_type, risk, link_status, excel_path, has_tm1, formula_count "
            "FROM excel_assets ORDER BY menu, blob_name"
        ).fetchall()
    ]


def list_audit_mappings(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """前端 Excel 文件 → 后端 Cube 映射。"""
    return [
        {
            "menu": r[0] or "",
            "excel_file": r[1],
            "backend_cubes": [c for c in (r[2] or "").split(", ") if c],
            "cube_count": r[3],
        }
        for r in con.execute(
            "SELECT menu, excel_file, backend_cubes, cube_count "
            "FROM front_backend_mapping ORDER BY menu, excel_file"
        ).fetchall()
    ]


def cube_formation_view(con: duckdb.DuckDBPyConnection, cube: str, mdx: str | None = None) -> dict:
    """Cube 数据形成专项视图：整合 Rule 声明式计算 + TI 写入 + 切面匹配。

    与 cube_lineage（深血缘）不同，本视图面向「这个 Cube 的值是怎么形成的」这一业务问题，
    默认优先展示 Rule 计算关系（而非仅读取该 Cube 的 TI），并显式区分：
      - rule_declared：Rule 声明式计算（目标区域 → 表达式 → 引用指标 → 来源 Cube）
      - ti_writes：TI 显式写入（含固定成员 / 动态成员 / 条件）
      - consolidation：维度层级汇总（仅当 Rule/TI 均不覆盖时的候选，标注为「可能」）
      - mdx_slice：MDX 反解的切面匹配（哪些写入点命中该切面）

    不连接服务器、不执行规则；无法解析的表达式标记 UNKNOWN，不伪造运行结果。
    """
    dims = [r[0] for r in con.execute(
        "SELECT dimension_name FROM cube_has_dimension WHERE cube_name = ? ORDER BY dim_order",
        [cube],
    ).fetchall()]

    # 1. Rule 语义（默认优先）
    semantics = cube_rule_semantics(con, cube)
    rules = []
    for r in semantics.get("rules", []):
        # 目标区域坐标：固定成员 vs 动态成员
        fixed_members: list[str] = []
        dynamic_members: list[str] = []
        lhs = r.get("lhs", {}) or {}
        for c in lhs.get("coordinates", []) or []:
            if c.get("member"):
                fixed_members.append(f"{c.get('dimension','?')}={c.get('member')}")
            elif c.get("members"):
                fixed_members.append(f"{c.get('dimension','?')}={{{','.join(c['members'])}}}")
            elif c.get("raw"):
                dynamic_members.append(f"{c.get('dimension','?')}←{c.get('raw')}")
        refs = []
        for d in r.get("db_references", []) or []:
            refs.append({"cube": d.get("cube"), "status": d.get("status", "UNKNOWN"),
                         "raw": d.get("raw")})
        rules.append({
            "line_start": r.get("line_start"),
            "line_end": r.get("line_end"),
            "raw": r.get("raw", ""),
            "target": lhs.get("raw"),
            "target_kind": lhs.get("kind"),
            "fixed_members": fixed_members,
            "dynamic_members": dynamic_members,
            "expression": (r.get("rhs", {}) or {}).get("expression", ""),
            "qualifier": r.get("qualifier"),
            "conditions": r.get("conditions", []),
            "db_references": refs,
            "special": r.get("special"),
            "status": r.get("status", "UNKNOWN"),
            "unresolved": r.get("unresolved_reasons", []),
        })

    # 2. TI 写入（cube_lineage 的 writers 部分）
    lineage = cube_lineage(con, cube)
    ti_writes = []
    for w in lineage.get("writers", []) or []:
        writes = []
        for wp in w.get("write_points", []) or []:
            fixed = []
            dynamic = []
            for d in wp.get("dims", []) or []:
                val = (d.get("value") or "").strip()
                if val.startswith("<") and val.endswith(">"):
                    dynamic.append(f"{d.get('dim_name')}={val}")
                elif val:
                    fixed.append(f"{d.get('dim_name')}={val}")
            writes.append({
                "operation": wp.get("operation_human"),
                "conditions": wp.get("conditions_human", []),
                "fixed_members": fixed,
                "dynamic_members": dynamic,
                "source_cubes": wp.get("source_cubes", []),
            })
        ti_writes.append({"process": w.get("process"), "writes": writes})

    # 3. MDX 切面匹配（若有）
    mdx_slice = None
    if mdx:
        parsed = parse_mdx(mdx)
        members = parsed.get("members") or None
        trace = trace_cell_value(con, cube, members)
        mdx_slice = {
            "cube": parsed.get("cube"),
            "members": parsed.get("members", {}),
            "matched_count": trace.get("matched_count", 0),
            "relaxed": trace.get("relaxed", False),
            "candidates": trace.get("candidates", []),
        }

    return {
        "cube": cube,
        "dimensions": dims,
        "available": semantics.get("available", False),
        "unavailable_reason": semantics.get("reason"),
        "rule_count": len(rules),
        "feeder_count": len(semantics.get("feeders", [])),
        "unknown_count": len(semantics.get("unknowns", [])),
        # 来源版本证据：Rule 源码 SHA-256，用于追溯快照与历史分析包的一致性。
        "rule_source_hash": semantics.get("source_hash"),
        "rules": rules,
        "ti_writes": ti_writes,
        "source_cubes": lineage.get("sources", []),
        "mdx_slice": mdx_slice,
        "mdx_parse": parse_mdx(mdx) if mdx else None,
        "limitations": [
            "Rule/Feeder 仅做静态语义解析，未执行；运行路径、最终金额与新旧等价需隔离运行验证。",
            "动态坐标、Subset/MDX 成员、Data Row Variables 未求值，标注为 UNKNOWN/可能。",
            "TI 读写关系是代码证据，不等于值一定由此传输；共同读写/静态调用边不视为实际值传输证明。",
        ],
    }
