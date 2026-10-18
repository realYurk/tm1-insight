"""Rule & Feeder Semantic IR —— 把 TM1 Rule / FEEDERS 源码解析为可解释结构。

目标：让用户从 Cube 进入后，能读懂**可证明**的计算逻辑，而不是只看到
Cube 之间的引用线。本模块是纯解析层，不连接 TM1、不执行规则、不推断
运行时值；所有无法证明的部分显式标记为 ``UNKNOWN``。

设计原则（对齐 Task 20 约束）：

- **不粗暴用正则切割嵌套表达式**：复用 ``learning.syntax`` 的平衡括号
  词法层（``statements`` / ``calls``），再在 token 流上做结构解析。
- **Rule 与 Feeder 分离**：Rule 的数值计算语义与 Feeder 的稀疏性馈送关系
  是两个独立 IR，绝不混为一谈；Feeder 不解释为数值公式。
- **坐标选择 ``['Dim':'Member', ...]`` 结构化**：左侧目标区域、右侧
  ``[...]`` 区域引用、``DB()`` 跨 Cube 引用、``!Dim`` 区域引用分别记录。
- **不支持的函数 / 动态坐标保留原始表达式并标记 UNKNOWN**，绝不静默删除。
- **证据定位**：每个 IR 节点带 section/line/column 与源码片段，可回到原文。

产物结构（顶层）：

.. code-block:: text

    RuleSemantics.parse(code, cube, dimensions) -> {
        "cube": str,
        "source_hash": str,
        "directives": [ {kind: SKIPCHECK|FEEDSTRINGS|..., line, raw} ],
        "rules": [ RuleIR ... ],       # 每条计算规则
        "feeders": [ FeederIR ... ],   # 每条 FEEDERS 语句
        "unknowns": [ {reason, line, raw} ],
    }

RuleIR 字段：
    cube / source / line_start / line_end / raw
    lhs: { target_area, dimensions:[...], coordinates:[...], qualifier: N|S|C|None }
    rhs: { kind: EXPRESSION|DB_REF|STET|CONTINUE|..., expression, ... }
    db_references: [ {cube, args:[...], line} ]
    attribute_calls: [ {func: ATTRS|ATTRN, args, line} ]
    conditions: [ {func, args, line} ]
    special: STET|CONTINUE|None
    status: PARSED|PARTIAL|UNKNOWN
    unresolved_reasons: [...]

FeederIR 字段：
    cube / source / line_start / line_end / raw
    source_area: {...}      # => 左侧
    target_area: {...}      # => 右侧（通常是 DB() 引用）
    status / unresolved_reasons
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Optional

from tm1_insight.learning.syntax import TOKEN, calls, statements

VERSION = "rule-semantics-1"
REVISION = 3

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 规则行为指令（出现在规则文件顶部或独立语句）
DIRECTIVES = {
    "SKIPCHECK",
    "FEEDSTRINGS",
    "SKIPCHECKDIM",
    "UNDEFVALS",
}

# 特殊语义
SPECIAL_KEYWORDS = {"STET", "CONTINUE"}

# 属性查询函数
ATTRIBUTE_FUNCS = {"ATTRS", "ATTRN"}

# 条件/控制函数（参数不一定是数值，需保留结构化）
CONDITION_FUNCS = {"IF", "ELISANC", "ELISPAR", "ELLEV", "ELCOMP", "ELWEIGHT"}

# 名称识别表，不是已实现返回值/计算语义的白名单。
KNOWN_FUNCTIONS = {
    "DB", "ATTRS", "ATTRN", "IF", "ELISANC", "ELISPAR", "ELLEV", "ELCOMP",
    "ELWEIGHT", "DIMNM", "DIMIX", "DNLEV", "DIMSIZ", "SUBST", "STR",
    "NUMBR", "ROUND", "ROUNDP", "ABS", "INT", "MIN", "MAX", "EXP", "LN",
    "SQRT", "RAND", "TIMVL", "NOW", "DATE", "DAYNO", "DAY", "MONTH", "YEAR",
    "STET", "CONTINUE",
}

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _is_string_token(tok: dict) -> bool:
    return tok.get("kind") == "string"


def _unwrap_string(tok: dict) -> str:
    """还原字符串字面量的值（TM1 用双写引号转义）。"""
    raw = tok["value"]
    if raw and raw[0] in ("'", '"'):
        quote = raw[0]
        body = raw[1:-1]
        return body.replace(quote * 2, quote)
    return raw


def _tokens_src(toks: Iterable[dict]) -> str:
    """把 token 序列还原为可读源码片段（字符串保留原样，不隐藏）。"""
    parts = []
    for t in toks:
        if t["value"] == ";":
            continue
        parts.append(t["value"])
    return " ".join(parts)


def _line_of(toks: list[dict]) -> int:
    return toks[0]["line"] if toks else 0


def _group_end(tokens, start):
    """Exclusive end of one balanced group; strings cannot close a group."""
    pairs={'(':')','[':']','{':'}'}
    if start>=len(tokens) or tokens[start]['value'] not in pairs:return None
    stack=[]
    for i,t in enumerate(tokens[start:],start):
        if t['kind']!='symbol':continue
        v=t['value']
        if v in pairs:stack.append(pairs[v])
        elif v in pairs.values():
            if not stack or stack.pop()!=v:return None
            if not stack:return i+1
    return None


def _balanced(tokens):
    i=0
    while i<len(tokens):
        t=tokens[i]
        if t['kind']=='symbol' and t['value'] in {'(','[','{'}:
            i=_group_end(tokens,i)
            if i is None:return False
        elif t['kind']=='symbol' and t['value'] in {')',']','}'}:return False
        else:i+=1
    return True


def _whole_call(tokens,name):
    return bool(len(tokens)>2 and tokens[0]['kind']=='id' and tokens[0]['value'].upper()==name
                and tokens[1]['value']=='(' and _group_end(tokens,1)==len(tokens))


def _literal_members(tokens):
    if not tokens or tokens[0]['value']!='{' or _group_end(tokens,0)!=len(tokens):return None
    members=[];expect_member=True
    for t in tokens[1:-1]:
        if expect_member:
            if not _is_string_token(t):return None
            members.append(_unwrap_string(t))
        elif t['value']!=',':return None
        expect_member=not expect_member
    return None if expect_member and members else members


# ---------------------------------------------------------------------------
# 坐标区域解析（[...] 与 ['D1':'M1', 'D2':'M2', ...]）
# ---------------------------------------------------------------------------


def _parse_area_bracket(tokens: list[dict], start: int, dimensions: list[str],
                        context: str = "lhs"):
    """解析一个 ``[ ... ]`` 区域选择。

    支持两种形态：
    - ``['DimA':'M', 'DimB':{'x','y'}]`` 多维坐标（含成员集合 / 单成员）。
    - ``['Account']`` / ``['Amount']`` 区域引用（右侧公式里的区域简写）。

    ``context`` 决定裸单成员的语义：
    - ``lhs``：裸成员没有位置维度语义；缺少成员归属索引时保留维度未知。
    - ``rhs``：右侧公式里，``['Account']`` 是「当前单元格成员」的区域引用。

    返回 (parsed_dict, next_index)。next_index 指向 ``]`` 之后。
    """
    result: dict[str, Any] = {
        "kind": "area",
        "coordinates": [],
        "dims": [],
        "raw": None,
        "status": "PARSED",
        "unresolved_reasons": [],
    }
    # tokens[start] 应为 '['
    i = start + 1
    raw_tokens = [tokens[start]]
    depth = 1
    items: list[dict] = []
    while i < len(tokens) and depth > 0:
        t = tokens[i]
        raw_tokens.append(t)
        if t["value"] == "[":
            depth += 1
        elif t["value"] == "]":
            depth -= 1
        i += 1
    result["raw"] = _tokens_src(raw_tokens)
    if depth or not _balanced(raw_tokens):
        result.update(status='UNKNOWN',unresolved_reasons=['AREA_DELIMITERS_INCOMPLETE: 区域括号/集合不完整'])
        return result,i

    # 解析内部：扁平化成顶层逗号分隔的「项」
    inner = raw_tokens[1:-1]  # 去掉 [ ]
    if not inner:
        return result, i

    # 顶层切分：按 ','（注意 {} 里的逗号不是顶层）
    top_items: list[list[dict]] = []
    cur: list[dict] = []
    brace = 0
    for t in inner:
        if t["value"] == "{":
            brace += 1
        elif t["value"] == "}":
            brace -= 1
        if t["value"] == "," and brace == 0:
            top_items.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        top_items.append(cur)
    elif inner and inner[-1]['value']==',':top_items.append([])

    for item in top_items:
        if not item:
            result['unresolved_reasons'].append('AREA_EMPTY_ITEM: 区域中有空坐标')
            result['status']='UNKNOWN'
            continue
        # 形如 'Dim':'Member' 或 'Dim':{'a','b'} 或 纯 'Member'
        if len(item) >= 3 and _is_string_token(item[0]) and item[1]["value"] == ":":
            dim = _unwrap_string(item[0])
            rest = item[2:]
            coord: dict[str, Any] = {"dimension": dim}
            if rest and rest[0]["value"] == "{" and _group_end(rest,0)==len(rest):
                members=_literal_members(rest)
                if members is None:
                    coord.update(kind='unknown',raw=_tokens_src(rest),status='UNKNOWN')
                    result['status']='UNKNOWN'
                    result['unresolved_reasons'].append('AREA_MEMBER_SET_UNCONFIRMED: 成员集合不是完整字面量列表')
                else:coord.update(members=members,kind='set')
            elif len(rest) == 1 and _is_string_token(rest[0]):
                coord["member"] = _unwrap_string(rest[0])
                coord["kind"] = "single"
            else:
                coord["kind"] = "dynamic"
                coord["raw"] = _tokens_src(rest)
                coord["status"] = "UNKNOWN"
                result['unresolved_reasons'].append('AREA_DYNAMIC_COORDINATE: 坐标不是可确认的成员/成员集合')
            result["coordinates"].append(coord)
            result["dims"].append(dim)
        elif len(item) == 1 and _is_string_token(item[0]):
            # 裸成员不能凭其出现顺序绑定维度。
            if context == "lhs":
                result["coordinates"].append(
                    {"dimension": None, "member": _unwrap_string(item[0]), "kind": "single"}
                )
            else:
                result["coordinates"].append(
                    {"dimension": None, "member": _unwrap_string(item[0]), "kind": "member_ref"}
                )
        elif item and item[0]["value"] == "{" and _literal_members(item) is not None:
            result['coordinates'].append(dict(dimension=None,members=_literal_members(item),kind='set'))
        else:
            result["coordinates"].append(
                {"dimension": None, "raw": _tokens_src(item), "kind": "unknown", "status": "UNKNOWN"}
            )
            result['unresolved_reasons'].append('AREA_UNSUPPORTED_COORDINATE: 无法确认区域项结构')
            result['status']='UNKNOWN'
    if context == "lhs":
        _resolve_positional_coordinates(result, dimensions)
    return result, i


def _resolve_positional_coordinates(area: dict, dimensions: list[str]):
    """Legacy helper name retained. Cube order is NOT member ownership evidence."""
    reasons=area.setdefault('unresolved_reasons',[])
    for coord in area.get("coordinates", []):
        dim=coord.get('dimension')
        if dim is None:
            coord.update(dimension_resolution='UNKNOWN',status='UNKNOWN')
            reasons.append('AREA_MEMBER_OWNERSHIP_UNKNOWN: 裸成员/集合缺少成员归属索引；不能按 Cube 维度顺序推断')
        elif not dimensions or dim not in dimensions:
            coord.update(declared_dimension=dim,dimension=None,dimension_resolution='UNKNOWN',status='UNKNOWN')
            reasons.append('AREA_DIMENSION_CATALOG_UNCONFIRMED: 显式标签未在当前 Cube 维度目录确认')
        else:coord['dimension_resolution']='EXPLICIT_LABEL_IN_CUBE'
        if coord.get('status')=='UNKNOWN':
            reasons.append('AREA_COORDINATE_UNCONFIRMED: 区域坐标仍有未确认项')
    area['dims']=list(dict.fromkeys(c['dimension'] for c in area.get('coordinates',[]) if c.get('dimension')))
    area['unresolved_reasons']=list(dict.fromkeys(reasons))
    if reasons and area['status']!='UNKNOWN':area['status']='PARTIAL'


# ---------------------------------------------------------------------------
# DB() 跨 Cube 引用解析
# ---------------------------------------------------------------------------


def _parse_db_call(token: dict, args: list[list[dict]], cube_catalog: Optional[set[str]]) -> dict:
    """解析一次 DB(...) 调用为跨 Cube 引用。"""
    cube = None
    cube_resolved = False
    coordinates: list[dict] = []
    resolution='MISSING_ARGUMENT'
    if args:
        first = args[0]
        if len(first) == 1 and _is_string_token(first[0]):
            cube = _unwrap_string(first[0])
            cube_resolved = cube_catalog is not None and cube in cube_catalog
            resolution='CATALOG_CONFIRMED' if cube_resolved else 'CATALOG_UNAVAILABLE' if cube_catalog is None else 'MISSING_FROM_CATALOG'
        else:
            cube = _tokens_src(first)
            cube_resolved = False
            resolution='DYNAMIC'
    for arg in args[1:]:
        if not arg:
            continue
        # 'Dim' 字面量坐标 或 !Dim 区域引用 或 其它
        if len(arg) == 1 and _is_string_token(arg[0]):
            coordinates.append({"kind": "literal", "value": _unwrap_string(arg[0])})
        elif len(arg)>1 and arg[0]["value"] == "!" and all(t['kind'] in {'id','number'} for t in arg[1:]):
            # !Dim 区域引用（可能是多词维度名）
            name_toks = arg[1:]
            coordinates.append(
                {"kind": "region", "dimension": _tokens_src(name_toks)}
            )
        else:
            coordinates.append(
                {"kind": "dynamic", "raw": _tokens_src(arg), "status": "UNKNOWN"}
            )
    reasons=[]
    if not cube_resolved:reasons.append('DB_CUBE_'+resolution+': Cube 身份没有由字面量和目录共同确认')
    if len(args)<2 or any(not arg for arg in args):reasons.append('DB_ARGUMENTS_INCOMPLETE: DB 参数缺失')
    if any(c['kind']=='dynamic' for c in coordinates):reasons.append('DB_COORDINATE_DYNAMIC: DB 坐标表达式尚未还原')
    return {
        "cube": cube,
        "cube_resolved": cube_resolved,
        "cube_resolution": resolution,
        "status": 'PARTIAL' if reasons else 'PARSED',
        "unresolved_reasons": reasons,
        "coordinates": coordinates,
        "line": token["line"],
        "column": token["column"],
    }


# ---------------------------------------------------------------------------
# 主解析器
# ---------------------------------------------------------------------------


class RuleSemanticsParser:
    """把一段 Rule 源码解析为 Rule + Feeder 语义 IR。"""

    def __init__(self, cube: str, dimensions: Optional[list[str]] = None,
                 cube_catalog: Optional[set[str]] = None):
        self.cube = cube
        self.dimensions = list(dimensions or [])
        self.cube_catalog = set(cube_catalog or []) if cube_catalog is not None else None

    # -- 顶层入口 ---------------------------------------------------------
    def parse(self, code: str) -> dict:
        code = code or ""
        self._expression_source = code
        source_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        self._expression_source_hash = source_hash
        stmts = list(statements((code, "", "", ""), include_logging=True))

        directives: list[dict] = []
        rules: list[dict] = []
        feeders: list[dict] = []
        unknowns: list[dict] = []

        in_feeders = False

        for toks in stmts:
            if not toks:
                continue
            # 空语句（仅注释/分号）
            meaningful = [t for t in toks if t["kind"] not in ("comment",)]
            if not meaningful or all(t["value"] == ";" for t in meaningful):
                continue

            head = meaningful[0]
            head_upper = head["value"].upper() if head["kind"] == "id" else head["value"]

            # 行为指令
            if head["kind"] == "id" and head_upper in DIRECTIVES:
                directives.append({
                    "kind": head_upper,
                    "line": head["line"],
                    "column": head["column"],
                    "raw": _tokens_src(meaningful),
                })
                continue

            # FEEDERS 段标记
            if head["kind"] == "id" and head_upper == "FEEDERS":
                in_feeders = True
                continue

            if in_feeders:
                record=self._parse_feeder(toks);feeders.append(record)
            else:
                record=self._parse_rule(toks);rules.append(record)
            for reason in record['unresolved_reasons']:
                unknowns.append(dict(kind=record['kind'],cube=self.cube,reason=reason,
                    line=record['line_start'],column=toks[0]['column'],raw=record['raw']))

        return {
            "version": VERSION,
            "engine_revision": REVISION,
            "cube": self.cube,
            "source_hash": source_hash,
            "directives": directives,
            "rules": rules,
            "feeders": feeders,
            "unknowns": unknowns,
        }

    # -- Rule 语句 --------------------------------------------------------
    def _parse_rule(self, toks: list[dict]) -> dict:
        line_start = toks[0]["line"]
        line_end = toks[-1]["line"]
        raw = _tokens_src(toks)

        # 找顶层 '='（区域 = 限定符 : 表达式）
        eq_idx = None
        brace = 0
        for idx, t in enumerate(toks):
            if t["value"] in ("[", "{"):
                pass
            if t["value"] == "(":
                brace += 1
            elif t["value"] == ")":
                brace -= 1
            if t["value"] == "=" and brace == 0:
                eq_idx = idx
                break

        lhs_area: dict[str, Any] = {"kind": "area", "raw": None, "status": "UNKNOWN"}
        qualifier = None
        rhs_kind = "UNKNOWN"
        rhs: dict[str, Any] = {}
        db_refs: list[dict] = []
        attr_calls: list[dict] = []
        conditions: list[dict] = []
        special = None
        unresolved: list[str] = []

        if eq_idx is None:
            # 无法定位 '='，整句未知
            unresolved.append("未定位到区域定义符号 '='")
            return self._rule_result(
                toks, line_start, line_end, raw, lhs_area, qualifier,
                rhs_kind, rhs, db_refs, attr_calls, conditions, special,
                unresolved, "UNKNOWN",
            )

        lhs_tokens = toks[:eq_idx]
        rhs_tokens = toks[eq_idx + 1:]

        # 解析 LHS 区域
        if lhs_tokens and lhs_tokens[0]["value"] == "[":
            lhs_area, end = _parse_area_bracket(lhs_tokens, 0, self.dimensions)
            if end!=len(lhs_tokens):
                lhs_area.update(status='UNKNOWN')
                lhs_area['unresolved_reasons'].append('LHS_TRAILING_TOKENS: 区域后有无法解释的内容')
        else:
            lhs_area = {"kind": "area", "raw": _tokens_src(lhs_tokens), "status": "UNKNOWN"}
            unresolved.append("左侧目标区域非标准 [...] 坐标")
        unresolved.extend(lhs_area.get('unresolved_reasons',[]))

        # 解析限定符 N: / S: / C: / STET 等
        # RHS 开头可能是 'N' ':' ... 或 'N' ':' 'STET' 或直接表达式
        j = 0
        if (j < len(rhs_tokens) and rhs_tokens[j]["kind"] == "id"
                and rhs_tokens[j]["value"].upper() in ("N", "S", "C")):
            qualifier = rhs_tokens[j]["value"].upper()
            j += 1
            if j < len(rhs_tokens) and rhs_tokens[j]["value"] == ":":
                j += 1
            else:unresolved.append('RULE_QUALIFIER_COLON_MISSING: 限定符缺少冒号')

        rhs_body = rhs_tokens[j:]
        # 去掉末尾 ';'
        while rhs_body and rhs_body[-1]["value"] == ";":
            rhs_body = rhs_body[:-1]

        # 特判 STET / CONTINUE
        if len(rhs_body)==1 and rhs_body[0]["kind"] == "id" and rhs_body[0]["value"].upper() in SPECIAL_KEYWORDS:
            special = rhs_body[0]["value"].upper()
            rhs_kind = special
            rhs = {"kind": special, "expression": special, "line": rhs_body[0]["line"]}
        elif not rhs_body:
            rhs_kind = "EMPTY"
            rhs = {"kind": "EMPTY", "expression": ""}
            unresolved.append("右侧计算表达式为空")
        else:
            # 提取 DB / ATTRS / ATTRN / 条件函数调用
            self._extract_calls(
                rhs_body, db_refs, attr_calls, conditions,
                cube_catalog=self.cube_catalog,
            )
            # 判断 RHS 主体
            rhs_kind = self._classify_rhs(rhs_body, db_refs)
            rhs = {
                "kind": rhs_kind,
                "expression": _tokens_src(rhs_body),
                "line": rhs_body[0]["line"],
            }

        rhs_status,rhs_reasons=self._review_rhs(rhs_body,db_refs)
        from tm1_insight.learning.rule_expression import parse_expression
        rhs['expression_ir'] = parse_expression(rhs_body, self._expression_source, self.dimensions, db_refs)
        rhs['expression_ir'].update(cube=self.cube, source_hash=self._expression_source_hash)
        unresolved.extend(rhs_reasons)
        rhs.update(status=rhs_status,semantic_status='STRUCTURE_ONLY' if rhs_status=='PARSED' else 'UNCONFIRMED')
        status='UNKNOWN' if lhs_area['status']=='UNKNOWN' or rhs_status=='UNKNOWN' else 'PARTIAL' if unresolved else 'PARSED'

        return self._rule_result(
            toks, line_start, line_end, raw, lhs_area, qualifier,
            rhs_kind, rhs, db_refs, attr_calls, conditions, special,
            unresolved, status,
        )

    def _rule_result(self, toks, line_start, line_end, raw, lhs_area, qualifier,
                     rhs_kind, rhs, db_refs, attr_calls, conditions, special,
                     unresolved, status):
        return {
            "kind": "rule",
            "cube": self.cube,
            "line_start": line_start,
            "line_end": line_end,
            "raw": raw,
            "lhs": lhs_area,
            "qualifier": qualifier,
            "rhs_kind": rhs_kind,
            "rhs": rhs,
            "db_references": db_refs,
            "attribute_calls": attr_calls,
            "conditions": conditions,
            "special": special,
            "status": status,
            "unresolved_reasons": list(dict.fromkeys(unresolved)),
        }

    # -- Feeder 语句 ------------------------------------------------------
    def _parse_feeder(self, toks: list[dict]) -> dict:
        line_start = toks[0]["line"]
        line_end = toks[-1]["line"]
        raw = _tokens_src(toks)

        # 找顶层 '=>'
        arrow_idx = None
        for idx in range(len(toks) - 1):
            if toks[idx]["value"] == "=" and toks[idx + 1]["value"] == ">":
                arrow_idx = idx
                break

        unresolved: list[str] = []
        status = "PARSED"

        if arrow_idx is None:
            unresolved.append("未定位到 Feeder 方向符号 '=>'")
            status = "UNKNOWN"
            source_area = {"kind": "area", "raw": raw, "status": "UNKNOWN"}
            target_area = {"kind": "area", "raw": None, "status": "UNKNOWN"}
            db_refs: list[dict] = []
            attr_calls: list[dict] = []
            conditions: list[dict] = []
        else:
            lhs_tokens = toks[:arrow_idx]
            rhs_tokens = toks[arrow_idx + 2:]
            while rhs_tokens and rhs_tokens[-1]['value']==';':rhs_tokens=rhs_tokens[:-1]

            source_area, _ = _parse_area_bracket(lhs_tokens, 0, self.dimensions) \
                if lhs_tokens and lhs_tokens[0]["value"] == "[" \
                else ({"kind": "area", "raw": _tokens_src(lhs_tokens), "status": "UNKNOWN"}, 0)
            if lhs_tokens and lhs_tokens[0]['value']=='[' and _group_end(lhs_tokens,0)!=len(lhs_tokens):
                source_area['status']='UNKNOWN'
                unresolved.append('FEEDER_SOURCE_INCOMPLETE: 馈送源区域不完整')
            unresolved.extend(source_area.get('unresolved_reasons',[]))

            db_refs = []
            attr_calls = []
            conditions = []
            if rhs_tokens:
                self._extract_calls(rhs_tokens, db_refs, attr_calls, conditions,
                                    cube_catalog=self.cube_catalog)
                # 目标区域：可能是 DB(...) 或 [...] 区域
                if rhs_tokens[0]["value"] == "[" and _group_end(rhs_tokens,0)==len(rhs_tokens):
                    target_area, _ = _parse_area_bracket(rhs_tokens, 0, self.dimensions)
                    unresolved.extend(target_area.get('unresolved_reasons',[]))
                elif _whole_call(rhs_tokens,'DB') and db_refs:
                    target_area = {
                        "kind": "db_reference",
                        "raw": _tokens_src(rhs_tokens),
                        "db": db_refs[0],
                        "status": db_refs[0]['status'],
                    }
                    if not db_refs[0]["cube_resolved"]:
                        unresolved.append("Feeder 目标 Cube 未解析")
                        status = "PARTIAL"
                else:
                    target_area = {"kind": "area", "raw": _tokens_src(rhs_tokens), "status": "UNKNOWN"}
                    unresolved.append("Feeder 目标区域无法解析")
                    status = "PARTIAL"
            else:
                target_area = {"kind": "area", "raw": None, "status": "UNKNOWN"}
                unresolved.append("Feeder 目标为空")
                status = "PARTIAL"

            for ref in db_refs:unresolved.extend(ref['unresolved_reasons'])
            if source_area.get('status')=='UNKNOWN' or target_area.get('status')=='UNKNOWN':
                status='UNKNOWN'
                unresolved.append('FEEDER_AREA_UNKNOWN: 馈送源/目标关键结构未确认')
            elif unresolved or source_area.get('status')=='PARTIAL' or target_area.get('status')=='PARTIAL':status='PARTIAL'

        return {
            "kind": "feeder",
            "cube": self.cube,
            "line_start": line_start,
            "line_end": line_end,
            "raw": raw,
            "source_area": source_area,
            "target_area": target_area,
            "db_references": db_refs,
            "attribute_calls": attr_calls,
            "conditions": conditions,
            "status": status,
            "unresolved_reasons": list(dict.fromkeys(unresolved)),
        }

    # -- 调用提取 ---------------------------------------------------------
    def _extract_calls(self, tokens: list[dict], db_refs: list[dict],
                       attr_calls: list[dict], conditions: list[dict],
                       cube_catalog: Optional[set[str]] = None):
        """从 token 流提取 DB / ATTRS / ATTRN / 条件函数调用。"""
        for token, args in calls(tokens):
            name = token["value"].upper()
            if name == "DB":
                ref=_parse_db_call(token,args,cube_catalog)
                for coord in ref['coordinates']:
                    if coord['kind']=='region' and coord['dimension'] not in self.dimensions:
                        coord['status']='UNKNOWN'
                        ref['unresolved_reasons'].append('DB_REGION_DIMENSION_UNCONFIRMED: !维度未在当前 Cube 目录确认')
                ref['unresolved_reasons']=list(dict.fromkeys(ref['unresolved_reasons']))
                if ref['unresolved_reasons']:ref['status']='PARTIAL'
                db_refs.append(ref)
            elif name in ATTRIBUTE_FUNCS:
                attr_calls.append({
                    "func": name,
                    "args": [_tokens_src(a) for a in args],
                    "line": token["line"],
                    "column": token["column"],
                })
            elif name in CONDITION_FUNCS:
                conditions.append({
                    "func": name,
                    "args": [_tokens_src(a) for a in args],
                    "line": token["line"],
                    "column": token["column"],
                })

    def _classify_rhs(self, rhs_body: list[dict], db_refs: list[dict]) -> str:
        """判断 RHS 主体形态。"""
        if not rhs_body:
            return "EMPTY"
        # Only a balanced DB call consuming the entire RHS is direct.
        if _whole_call(rhs_body,'DB'):
            return "DB_REFERENCE"
        # 区域简写引用 ['Account'] \ ['Amount']
        if rhs_body[0]["value"] == "[" and _group_end(rhs_body,0)==len(rhs_body):
            return "AREA_REFERENCE"
        # 含 DB 引用 + 运算 → 表达式
        if db_refs:
            return "EXPRESSION"
        # 纯算术/区域表达式
        return "EXPRESSION"

    def _review_rhs(self,tokens,db_refs):
        reasons=[]
        if not tokens:return 'UNKNOWN',['RHS_EMPTY: 右侧表达式为空']
        if not _balanced(tokens):return 'UNKNOWN',['RHS_DELIMITERS_INCOMPLETE: 右侧括号不完整']
        if tokens[-1]['kind']=='symbol' and tokens[-1]['value'] in {'+','-','*','/','\\',',',':','|','!'}:
            return 'UNKNOWN',['RHS_EXPRESSION_INCOMPLETE: 右侧表达式不完整']
        for ref in db_refs:reasons.extend(ref['unresolved_reasons'])
        found=list(calls(tokens))
        for token,args in found:
            name=token['value'].upper()
            if name!='DB':
                reasons.append(('UNKNOWN_FUNCTION: ' if name not in KNOWN_FUNCTIONS else 'FUNCTION_SEMANTICS_NOT_RECONSTRUCTED: ')+name)
        if _whole_call(tokens,'DB'):
            return ('PARTIAL' if reasons else 'PARSED'),list(dict.fromkeys(reasons))
        if len(tokens)==1:
            if tokens[0]['kind'] in {'number','string'} or tokens[0]['value'].upper() in SPECIAL_KEYWORDS:
                return 'PARSED',[]
            return 'UNKNOWN',['RHS_UNSUPPORTED_VALUE: 未确认的单独标识符或值']
        # The v1 parser extracts references/calls but builds no expression AST.
        # A known function name therefore never proves a complete formula.
        reasons.append('EXPRESSION_SEMANTICS_NOT_RECONSTRUCTED: 仅保留表达式结构和引用，未还原完整计算语义')
        return 'PARTIAL',list(dict.fromkeys(reasons))


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------


def parse_rule_semantics(code: str, cube: str, dimensions: Optional[list[str]] = None,
                         cube_catalog: Optional[set[str]] = None) -> dict:
    """解析一段 Rule 源码为语义 IR（便捷函数）。"""
    return RuleSemanticsParser(cube, dimensions, cube_catalog).parse(code)
