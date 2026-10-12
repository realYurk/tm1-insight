"""Deterministic study reports from a read-only catalog. No model mutation or AI."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json

from tm1_insight.knowledge import discover_scope
from tm1_insight.learning.catalog import CATALOG, SOP, SOURCES
from tm1_insight.learning.syntax import signals, statements

VERSION = "study-1"


def build_report(con, query="*", progress=None):
    def update(stage, index, current=0, total=None):
        if progress:
            progress(stage=stage, stage_index=index, stages_total=6, current=current, total=total)

    query = (query or "").strip()
    if not query:
        raise ValueError("请输入功能关键词，或用 * 选择整模型。")
    update("发现对象与关系", 1)
    selection = discover_scope(con, query, match_mode="keyword")
    selected = set(selection["objects"]["processes"])
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    relations = {}
    for table in ("process_reads_cube", "process_writes_cube", "process_calls_process"):
        relations[table] = con.execute(f"SELECT DISTINCT * FROM {table} ORDER BY 1,2").fetchall() if table in tables else []
    all_processes = {r[0] for r in con.execute("SELECT name FROM processes").fetchall()}
    # Include at most two caller/callee layers; disclose this finite scope.
    for _ in range(2):
        linked = {target for source, target in relations["process_calls_process"] if source in selected}
        selected.update(linked & all_processes)
    links = {kind:defaultdict(list) for kind in ("reads", "writes", "calls", "called_by")}
    for kind, table in (("reads", "process_reads_cube"), ("writes", "process_writes_cube"), ("calls", "process_calls_process")):
        for source, target in relations[table]:
            links[kind][source].append(target)
            if kind == "calls": links["called_by"][target].append(source)
    update("读取选定功能代码", 2, 0, len(selected))
    processes, findings, duplicates = [], [], defaultdict(list)
    if selected:
        cursor = con.execute("SELECT name,prolog,metadata,data,epilog FROM processes WHERE name IN (SELECT unnest(?)) ORDER BY name", [sorted(selected)])
        while rows := cursor.fetchmany(32):
            for name, *parts in rows:
                observed = signals(parts)
                operations = observed["operations"]
                def has(*names): return any(op in operations for op in names)
                def proof(*names):
                    return [event for op in names for event in operations.get(op, [])][:6]
                patterns = {}
                if len(links["calls"][name]) >= 2 and has("executeprocess"):
                    patterns["pipeline"] = proof("executeprocess")
                if observed["proportional_writes"]:
                    patterns["proportion"] = observed["proportional_writes"][:6]
                if any(e["section"] == "data" for e in operations.get("cellgets", [])):
                    patterns["configuration"] = proof("cellgets")
                if has("attrs", "attrn"):
                    patterns["mapping"] = proof("attrs", "attrn")
                if has("viewzeroout") and links["writes"][name]:
                    patterns["rebuild"] = proof("viewzeroout")
                if any(e["section"] == "data" for e in operations.get("cellincrementn", [])):
                    patterns["accumulate"] = proof("cellincrementn")
                if has("dimix", "dimensionelementexists", "elementexists") and has("itemskip", "itemreject"):
                    patterns["validation"] = proof("dimix", "dimensionelementexists", "elementexists", "itemskip", "itemreject")
                if has("viewcreate", "subsetcreate", "subsetcreatebymdx"):
                    patterns["temporary"] = proof("viewcreate", "subsetcreate", "subsetcreatebymdx")
                if has("dimensionelementinsert", "dimensionelementcomponentadd", "hierarchyelementinsert"):
                    patterns["dimension"] = proof("dimensionelementinsert", "dimensionelementcomponentadd", "hierarchyelementinsert")
                if has("runprocess"):
                    patterns["parallel"] = proof("runprocess")
                if has("asciioutput", "textoutput"):
                    patterns["output"] = proof("asciioutput", "textoutput")
                digest = hashlib.sha256("\n".join(p or "" for p in parts).encode()).hexdigest()
                for evidence in patterns.values():
                    for event in evidence: event["source_hash"] = digest
                processes.append({"process":name, "source_hash":digest,
                                  **{kind:links[kind][name] for kind in links},
                                  "patterns":patterns, "formulas":observed["formulas"],
                                  "explanation":("组织多个工作步骤；实际顺序需结合条件和循环。" if "pipeline" in patterns else
                                                 "写入值含乘除链，优先核对驱动、分母和对账。" if "proportion" in patterns else
                                                 "归集明细到目标；重点检查粒度和重复运行。" if "accumulate" in patterns else
                                                 "按下方读写关系和操作证据逐步复查。")})
                def finding(kind, title, detail, evidence):
                    findings.append({"process":name, "kind":kind, "title":title,
                                     "status":"review_required", "detail":detail, "evidence":evidence})
                if "accumulate" in patterns:
                    finding("rerun", "核对累加任务的重跑策略", "本 TI 的 Data 段出现累加。清理可能由上层执行；请先核对批次与清理范围，再判断是否重复累计。", patterns["accumulate"])
                if any("\\" in f["expression"] for f in observed["formulas"]):
                    finding("zero_weight", "核对安全除法的零分母处理", "安全除法可能将零分母结果变成零；需要记录未分配金额。接近零的判断还受服务器配置影响。", observed["formulas"])
                if has("itemskip"):
                    finding("rejection", "核对跳过记录是否可对账", "观察到 ItemSkip；它可能用于合理过滤，也可能跳过坏数据。检查拒绝原因、数量与金额。", proof("itemskip"))
                if len(links["calls"][name]) >= 10:
                    finding("coupling", "调用扇出较高，检查职责边界", f"目录中有 {len(links['calls'][name])} 个直接调用目标。10 是复查阈值，不是设计好坏评分。", proof("executeprocess"))
                business = [t for statement in statements(("", "", parts[2] or "", "")) for t in statement]
                if len(business) >= 50:
                    shape = " ".join("<literal>" if t["kind"] in {"string", "number"} else t["value"].casefold() for t in business)
                    duplicates[hashlib.sha256(shape.encode()).hexdigest()].append(name)
            update("逐个提取代码证据", 3, len(processes), len(selected))

    update("整理教材与改进清单", 4)
    chapters = []
    for card in CATALOG:
        matches = [p for p in processes if card["id"] in p["patterns"]]
        chapters.append({**card, "match_count":len(matches), "examples":[
            {"process":p["process"], "evidence":p["patterns"][card["id"]]} for p in matches[:8]],
            "classification":"code_signal_candidate"})
    duplicate_groups = [{"signature":key, "processes":names, "reason":"Data 段去除常量后词法结构一致；不同常量可能改变业务语义，需复查后再抽公共模板。"}
                        for key,names in sorted(duplicates.items()) if len(names) >= 3]
    cubes = set(selection["objects"]["cubes"])
    for p in processes: cubes.update(p["reads"] + p["writes"])
    readers, writers = defaultdict(list), defaultdict(list)
    for p in processes:
        for name in p["reads"]: readers[name].append(p["process"])
        for name in p["writes"]: writers[name].append(p["process"])
    cube_info = []
    cursor = con.execute("SELECT name,dimensions,has_rules FROM cubes ORDER BY name")
    for name, dims, has_rules in cursor.fetchall():
        if name not in cubes: continue
        try: dimensions = json.loads(dims or "[]")
        except (ValueError, TypeError): dimensions = []
        cube_info.append({"cube":name, "dimensions":dimensions, "has_rules":bool(has_rules),
                          "readers":readers[name], "writers":writers[name],
                          "position":"读写中转" if readers[name] and writers[name] else "读取来源" if readers[name] else "写入结果" if writers[name] else "待核对"})
    dimension_usage = Counter(dim for c in cube_info for dim in c["dimensions"] if isinstance(dim, str))
    update("生成可携带学习包", 5)
    return {"version":VERSION, "query":query, "privacy":{"classification":"private_local_only", "contains_source":False, "publishing_authorized":False},
            "summary":{"processes":len(processes), "cubes":len(cube_info), "dimensions":len(dimension_usage),
                       "chapters_with_evidence":sum(c["match_count"] > 0 for c in chapters), "review_items":len(findings)},
            "sop":SOP, "chapters":chapters, "processes":processes, "cubes":cube_info,
            "shared_dimensions":[{"dimension":name, "cube_count":count} for name,count in dimension_usage.most_common(30)],
            "findings":findings, "duplicate_groups":duplicate_groups, "sources":SOURCES,
            "limitations":["关键词仅用于选择范围，不证明业务分类；关联扩展包含直接 Cube 关系和最多两层下级调用。",
                           "已过滤已知日志区域与调试文件输出；自定义日志和框架仍可能影响候选统计。",
                           "代码信号是复查候选，不能自动确认设计质量、完整算法或运行时执行顺序。",
                           "公式仅沿单一定义变量的有限词法链观察，不解释条件、循环、多次赋值、Rule/Feeder 或动态调用。",
                           "只读取元数据与代码，未读取实际金额，也未证明分摊守恒或运行性能。",
                           "没有检测到某个操作不代表不存在；函数、框架调用、上层清理和动态引用可能尚未识别。"]}


def markdown(report):
    lines = ["# TM1 项目学习手册", "", f"范围：{report['query']}", "",
             "仅供本地私有学习。代码信号与待确认项不等于已经验证的业务结论。", "", "## 先用六步读懂一个功能", ""]
    lines += [f"{i}. {step}" for i,step in enumerate(report["sop"], 1)]
    lines += ["", "## 当前范围", "", " · ".join(f"{k}: {v}" for k,v in report["summary"].items())]
    for chapter in report["chapters"]:
        lines += ["", f"## {chapter['title']}", "", chapter["meaning"], "", f"适用条件：{chapter['when']}",
                  f"代价与边界：{chapter['tradeoff']}", f"迁移思路：{chapter['java']}", "", "复查练习："]
        lines += [f"- {check}" for check in chapter["checks"]]
        lines += [f"\n本范围观察到 {chapter['match_count']} 个候选 TI。"]
        for example in chapter["examples"]:
            positions = ", ".join(f"{e['section']}:{e['line']} {e['operation']}" for e in example["evidence"])
            lines += [f"- {example['process']} — {positions}"]
    lines += ["", "## 按输入到输出查业务地图", ""]
    for cube in report["cubes"]:
        lines += [f"### {cube['cube']}", f"观察位置：{cube['position']}；维度：{', '.join(cube['dimensions'])}",
                  f"读取它：{', '.join(cube['readers']) or '未在本范围观察到'}", f"写入它：{', '.join(cube['writers']) or '未在本范围观察到'}", ""]
    lines += ["## 关键 TI 与公式", ""]
    for process in report["processes"]:
        if not process["formulas"] and "proportion" not in process["patterns"]: continue
        lines += [f"### {process['process']}", process["explanation"]]
        lines += [f"- {f['section']}:{f['line']} `{f['variable']} = {f['expression']}`" for f in process["formulas"]]
    lines += ["", "## 可以做得更好的地方：逐项验证", ""]
    lines += [f"- {f['process']}：{f['title']}。{f['detail']}" for f in report["findings"]]
    lines += ["", "## 候选公共模板族", ""]
    lines += [f"- {' / '.join(group['processes'])}：{group['reason']}" for group in report["duplicate_groups"]]
    lines += ["", "## 分析边界", ""] + [f"- {item}" for item in report["limitations"]]
    lines += ["", "## 语义参考", ""] + [f"- [{s['title']}]({s['url']})" for s in report["sources"]]
    return "\n".join(lines) + "\n"
