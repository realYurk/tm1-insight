"""Deterministic, evidence-backed knowledge extraction from the local TM1 catalog."""
from __future__ import annotations

import json
import re
import hashlib
from collections import defaultdict

from tm1_insight.knowledge_behavior import analyze_process

ENGINE_VERSION = "knowledge-2"
STAGES = ("Object Discovery", "Relationship Analysis", "Process Behavior Analysis",
          "Data Flow Analysis", "Pattern Candidate Detection", "Knowledge Package Generation")


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def _safe_code(code: str) -> str:
    """Keep source evidence while removing common embedded secrets and local paths."""
    code = re.sub(r"(?im)(\b\w*(?:password|passwd|token|secret|sso)\w*\s*[:=]\s*)(['\"])[^'\"]*\2", r"\1'REDACTED'", code)
    code = re.sub(r"(?i)[A-Z]:\\Users\\[^\\\s'\"]+", "<LOCAL_USER>", code)
    return code


def discover_scope(con, prefix: str, scope: dict | None = None, *,
                   include_dependencies: bool = True, match_mode: str = "prefix") -> dict:
    scope = {kind: bool((scope or {}).get(kind, True))
             for kind in ("cubes", "processes", "dimensions", "rules")}
    query = (prefix or "").strip()
    if match_mode not in {"prefix", "keyword"}:
        raise ValueError("match_mode must be prefix or keyword")
    term = query.rstrip("*").lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
    pattern = ("%" if match_mode == "keyword" else "") + term + "%"
    matched = {}
    for kind, table in (("cubes", "cubes"), ("processes", "processes"), ("dimensions", "dimensions")):
        if scope[kind] and query:
            matched[kind] = [r[0] for r in con.execute(f"SELECT name FROM {table} WHERE lower(name) LIKE ? ESCAPE '!' ORDER BY name", [pattern]).fetchall()]
        else:
            matched[kind] = []
    # Expand the selected scope through explicit catalog relationships. A business
    # prefix often names its cubes but not the TI processes that operate on them.
    tables = _tables(con)
    matched["rules"] = ([r[0] for r in con.execute("SELECT name FROM cubes WHERE lower(name) LIKE ? ESCAPE '!' AND (has_rules OR coalesce(rules,'') <> '') ORDER BY name", [pattern]).fetchall()]
                        if scope["rules"] and query else [])
    seed_counts = {kind:len(names) for kind,names in matched.items()}
    cube_names = set(matched["cubes"]) | set(matched["rules"])
    if include_dependencies and scope["processes"] and "processes" in tables and cube_names:
        related = set()
        for table in ("process_reads_cube", "process_writes_cube"):
            if table in tables:
                related.update(r[0] for r in con.execute(f"SELECT DISTINCT r.process_name FROM {table} r JOIN processes p ON p.name=r.process_name WHERE r.cube_name IN (SELECT unnest(?))", [list(cube_names)]).fetchall())
        matched["processes"] = sorted(set(matched["processes"]) | related)
    if include_dependencies and scope["cubes"] and matched["processes"]:
        related_cubes = set(matched["cubes"])
        for table in ("process_reads_cube", "process_writes_cube"):
            if table in tables:
                related_cubes.update(row[0] for row in con.execute(
                    f"SELECT DISTINCT r.cube_name FROM {table} r JOIN cubes c ON c.name=r.cube_name WHERE r.process_name IN (SELECT unnest(?))",
                    [matched["processes"]]).fetchall())
        matched["cubes"] = sorted(related_cubes)
        cube_names.update(related_cubes)
    if include_dependencies and scope["dimensions"] and "cube_has_dimension" in tables and cube_names:
        related_dims = {r[0] for r in con.execute("SELECT DISTINCT r.dimension_name FROM cube_has_dimension r JOIN dimensions d ON d.name=r.dimension_name WHERE r.cube_name IN (SELECT unnest(?))", [list(cube_names)]).fetchall()}
        matched["dimensions"] = sorted(set(matched["dimensions"]) | related_dims)
    return {"query": query, "match_mode": match_mode, "selected": scope,
            "include_dependencies": include_dependencies, "objects": matched,
            "seed_counts":seed_counts, "matched": {kind: len(names) for kind, names in matched.items()}}


def extract(con, prefix: str, scope: dict | None = None, *, include_dependencies: bool = True,
            include_source: bool = False, include_lineage: bool = True,
            match_mode: str = "prefix", progress=None) -> dict:
    def report(stage, current=0, total=None):
        if progress:
            progress(stage=STAGES[stage], stage_index=stage + 1, stages_total=len(STAGES),
                     current=current, total=total)

    report(0)
    selection = discover_scope(con, prefix, scope, include_dependencies=include_dependencies,
                               match_mode=match_mode)
    matched = selection["objects"]
    cubes, procs, dims = map(set, (matched["cubes"], matched["processes"], matched["dimensions"]))
    tables = _tables(con)
    report(1)
    facts, behaviors = [], []
    for table, op in (("process_reads_cube", "READ"), ("process_writes_cube", "WRITE"), ("process_calls_process", "CALL")):
        if table not in tables or not procs: continue
        for row in con.execute(f"SELECT DISTINCT * FROM {table} ORDER BY 1,2").fetchall():
            if row[0] in procs or (op == "CALL" and row[1] in procs):
                facts.append({"process": row[0], "operation": op, "target": row[1],
                              "evidence": {"table": table, "line": None, "section": None}})
    report(2, 0, len(procs))
    if procs:
        cursor = con.execute("SELECT name, prolog, metadata, data, epilog FROM processes "
                             "WHERE name IN (SELECT unnest(?)) ORDER BY name", [sorted(procs)])
        index = 0
        while batch := cursor.fetchmany(50):
            for row in batch:
                item = analyze_process(row[0], row[1:])
                if include_source:
                    item["source_code"] = _safe_code("\n".join(str(x or "") for x in row[1:]))
                behaviors.append(item)
                index += 1
                if index % 10 == 0 or index == len(procs):
                    report(2, index, len(procs))
    report(3)
    flows = []
    relationships = defaultdict(lambda: defaultdict(list))
    for fact in facts:
        relationships[fact["process"]][fact["operation"]].append(fact["target"])
    for name in sorted(procs):
        reads = relationships[name]["READ"]
        writes = relationships[name]["WRITE"]
        if reads or writes:
            flows.append({"process":name,"sources":reads,"targets":writes,"evidence":"process_reads_cube / process_writes_cube"})
    lineage = []
    if include_lineage and "ti_flows" in tables and procs:
        for row in con.execute("SELECT process_name, target_cube, source_cubes, write_point_count FROM ti_flows").fetchall():
            if row[0] in procs:
                lineage.append({"process":row[0],"target_cube":row[1],"source_cubes":row[2],"write_point_count":row[3]})
    report(4)
    signatures = {}
    for item in behaviors:
        sig = " → ".join(x["behavior"] for x in item["behavior_sequence"])
        if sig:
            signatures.setdefault(sig, []).append(item["process"])
    by_name = {process["process"]:process for process in behaviors}
    patterns = [{"id":"PC-" + hashlib.sha256(sig.encode()).hexdigest()[:16],
                 "candidate_type":"OPERATION_SEQUENCE", "behavior_signature":sig.split(" → "),
                 "processes":names,"status":"candidate","human_label":None,"description":None,
                 "notes":None,"confidence":"SYNTAX_OBSERVED",
                 "evidence":[{"process":name, "operation":event["operation"], **event["evidence"]}
                             for name in names for event in by_name[name]["behavior_sequence"]]}
                for sig,names in sorted(signatures.items())]
    report(5)
    return {"schema_version":"1.0", "engine_version":ENGINE_VERSION, "scope":selection,
            "privacy":{"classification":"private_local_only", "contains_source":include_source,
                       "publishing_authorized":False},
            "limitations":["Source order does not prove runtime order.",
                            "Operation sequences are candidates, not best-practice recommendations."],
            "prefix":prefix,"matched":{k:len(v) for k,v in matched.items()},"objects":matched,
            "facts":facts,"data_flows":flows,"lineage":lineage,"processes":behaviors,
            "pattern_candidates":patterns,"stages":list(STAGES),
            "progress":{"status":"completed","stage":STAGES[-1],"current":6,"total":6}}


def markdown(package: dict) -> str:
    lines=[f"# TM1 Knowledge: {package['prefix'] or 'All'}", "", "## Scope", ""]
    lines.insert(2, "Private local use only. Source order is not runtime order; candidates are not recommendations.")
    lines += [f"- {k}: {v}" for k,v in package["matched"].items()]
    lines += ["", "## Process behavior", ""]
    lines += [f"- **{p['process']}** ({p['observed_role']}): " + " → ".join(x["behavior"] for x in p["behavior_sequence"]) for p in package["processes"]]
    lines += ["", "## Pattern candidates", ""]
    lines += [f"- {p['id']}: " + " → ".join(p["behavior_signature"]) + f" ({', '.join(p['processes'])})" for p in package["pattern_candidates"]]
    lines += ["", "## Evidence", "", "```json", json.dumps(package["facts"],ensure_ascii=False,indent=2), "```", ""]
    return "\n".join(lines)


def development_context(package: dict, kind: str, name: str) -> dict:
    if kind == "process":
        names = {name}
    elif kind == "cube":
        names = {f["process"] for f in package["facts"] if f["target"] == name and f["operation"] in {"READ", "WRITE"}}
    elif kind == "pattern":
        candidate = next((p for p in package["pattern_candidates"] if p["id"] == name), None)
        if not candidate:
            raise ValueError("Unknown pattern candidate")
        names = set(candidate["processes"])
    else:
        raise ValueError("Context type must be process, cube or pattern")
    processes = [p for p in package["processes"] if p["process"] in names]
    if not processes:
        raise ValueError("No matching process context in this scope")
    result = dict(package)
    result.update(selection={"type":kind, "name":name}, processes=processes,
                  facts=[f for f in package["facts"] if f["process"] in names or (f["operation"] == "CALL" and f["target"] in names)],
                  data_flows=[f for f in package["data_flows"] if f["process"] in names],
                  lineage=[f for f in package["lineage"] if f["process"] in names],
                  pattern_candidates=[p for p in package["pattern_candidates"] if set(p["processes"]) & names])
    # Do not carry the original entire-model object list into a scoped context.
    related_cubes = sorted({f["target"] for f in result["facts"] if f["operation"] in {"READ", "WRITE"}})
    result["objects"] = {"processes":sorted(names), "cubes":related_cubes, "dimensions":[], "rules":[]}
    result["matched"] = {kind:len(items) for kind, items in result["objects"].items()}
    result.pop("scope", None)
    result["pattern_candidates"] = [
        {**candidate,
         "processes": [member for member in candidate["processes"] if member in names],
         "evidence": [item for item in candidate.get("evidence", []) if item.get("process") in names]}
        for candidate in result["pattern_candidates"]
    ]
    return result
