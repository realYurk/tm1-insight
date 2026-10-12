"""Deterministic, evidence-backed knowledge extraction from the local TM1 catalog."""
from __future__ import annotations

import json
import re


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def _safe_code(code: str) -> str:
    """Keep source evidence while removing common embedded secrets and local paths."""
    code = re.sub(r"(?im)(\b(?:password|passwd|token|clientsecret|sso)\b\s*[:=]\s*)(['\"])[^'\"]*\2", r"\1'REDACTED'", code)
    code = re.sub(r"(?i)[A-Z]:\\Users\\[^\\\s'\"]+", "<LOCAL_USER>", code)
    return code


def extract(con, prefix: str, scope: dict | None = None) -> dict:
    scope = scope or {"cubes": True, "processes": True, "dimensions": True, "rules": True}
    term = (prefix or "").strip().rstrip("*").lower()
    matched = {}
    for kind, table in (("cubes", "cubes"), ("processes", "processes"), ("dimensions", "dimensions")):
        if scope.get(kind, True):
            matched[kind] = [r[0] for r in con.execute(f"SELECT name FROM {table} WHERE lower(name) LIKE ? ORDER BY name", [term + "%"]).fetchall()]
        else:
            matched[kind] = []
    # Expand the selected scope through explicit catalog relationships. A business
    # prefix often names its cubes but not the TI processes that operate on them.
    tables = _tables(con)
    cube_names = set(matched["cubes"])
    if "processes" in tables and cube_names:
        related = set()
        for table in ("process_reads_cube", "process_writes_cube"):
            if table in tables:
                related.update(r[0] for r in con.execute(f"SELECT process_name FROM {table} WHERE cube_name IN (SELECT unnest(?))", [list(cube_names)]).fetchall())
        matched["processes"] = sorted(set(matched["processes"]) | related)
    if "cube_has_dimension" in tables and cube_names:
        related_dims = {r[0] for r in con.execute("SELECT DISTINCT dimension_name FROM cube_has_dimension WHERE cube_name IN (SELECT unnest(?))", [list(cube_names)]).fetchall()}
        matched["dimensions"] = sorted(set(matched["dimensions"]) | related_dims)
    matched["rules"] = ([r[0] for r in con.execute("SELECT name FROM cubes WHERE lower(name) LIKE ? AND has_rules ORDER BY name", [term + "%"]).fetchall()]
                        if scope.get("rules", True) else [])
    cubes, procs, dims = map(set, (matched["cubes"], matched["processes"], matched["dimensions"]))
    facts, behaviors = [], []
    for table, op in (("process_reads_cube", "READ"), ("process_writes_cube", "WRITE"), ("process_calls_process", "CALL")):
        if table not in tables: continue
        for row in con.execute(f"SELECT * FROM {table}").fetchall():
            if row[0] in procs:
                facts.append({"process": row[0], "operation": op, "target": row[1]})
    for name in sorted(procs):
        row = con.execute("SELECT prolog, metadata, data, epilog FROM processes WHERE name=?", [name]).fetchone()
        code = "\n".join(str(x or "") for x in row)
        seq = []
        for match in re.finditer(r"CellGet[NS]|CellPut[NS]|CellIncrement[NS]|ExecuteProcess|Dimension(?:Element|Delete|Create)|View(?:Create|ZeroOut)|Subset(?:Create|Delete)", code, re.I):
            token = match.group(0).lower()
            op = "READ" if token.startswith("cellget") else "WRITE" if token.startswith(("cellput", "cellincrement")) else "CALL" if token == "executeprocess" else "DIMENSION_MAINTENANCE" if token.lower().startswith("dimension") else "VIEW_OPERATION" if token.lower().startswith("view") else "SUBSET_OPERATION"
            seq.append({"behavior": op, "evidence": match.group(0)})
        if any(f["process"] == name and f["operation"] == "READ" for f in facts) and "READ" not in [x["behavior"] for x in seq]: seq.insert(0,{"behavior":"READ","evidence":"process_reads_cube relationship"})
        if any(f["process"] == name and f["operation"] == "WRITE" for f in facts) and "WRITE" not in [x["behavior"] for x in seq]: seq.append({"behavior":"WRITE","evidence":"process_writes_cube relationship"})
        seq = sorted(seq, key=lambda x: code.find(x["evidence"]) if x["evidence"] in code else -1)
        kinds = [x["behavior"] for x in seq]
        role = "ORCHESTRATION" if "CALL" in kinds and "WRITE" not in kinds else "CALCULATION" if "READ" in kinds and "WRITE" in kinds else "LOAD" if "WRITE" in kinds else "UNKNOWN"
        behaviors.append({"process":name,"behavior_sequence":seq,"observed_role":role,"source_code":_safe_code(code)})
    signatures = {}
    for item in behaviors:
        sig = " → ".join(x["behavior"] for x in item["behavior_sequence"])
        if sig and sig not in ("UNKNOWN",): signatures.setdefault(sig, []).append(item["process"])
    patterns = [{"id":f"PC-{i:03}","candidate_type":"OBSERVED_BEHAVIOR","behavior_signature":sig.split(" → "),"processes":names,"status":"candidate","human_label":None,"description":None,"notes":None,"confidence":"OBSERVED","evidence":[f for f in facts if f["process"] in names]} for i,(sig,names) in enumerate(signatures.items(),1) if len(names)>1 or any(t in sig for t in ("READ → WRITE","READ → CALCULATE → WRITE"))]
    flows = []
    for name in sorted(procs):
        reads = [f["target"] for f in facts if f["process"] == name and f["operation"] == "READ"]
        writes = [f["target"] for f in facts if f["process"] == name and f["operation"] == "WRITE"]
        if reads or writes:
            flows.append({"process":name,"sources":reads,"targets":writes,"evidence":"process_reads_cube / process_writes_cube"})
    lineage = []
    if "ti_flows" in tables and procs:
        for row in con.execute("SELECT process_name, target_cube, source_cubes, write_point_count FROM ti_flows").fetchall():
            if row[0] in procs:
                lineage.append({"process":row[0],"target_cube":row[1],"source_cubes":row[2],"write_point_count":row[3]})
    return {"prefix":prefix,"matched":{k:len(v) for k,v in matched.items()},"objects":matched,"facts":facts,"data_flows":flows,"lineage":lineage,"processes":behaviors,"pattern_candidates":patterns,"stages":["Object Discovery","Relationship Analysis","Process Behavior Analysis","Data Flow Analysis","Pattern Candidate Detection","Knowledge Package Generation"],"progress":{"status":"completed","stage":"Knowledge Package Generation","current":6,"total":6,"message":"知识包已生成"}}


def markdown(package: dict) -> str:
    lines=[f"# TM1 Knowledge: {package['prefix'] or 'All'}", "", "## Scope", ""]
    lines += [f"- {k}: {v}" for k,v in package["matched"].items()]
    lines += ["", "## Process behavior", ""]
    lines += [f"- **{p['process']}** ({p['observed_role']}): " + " → ".join(x["behavior"] for x in p["behavior_sequence"]) for p in package["processes"]]
    lines += ["", "## Pattern candidates", ""]
    lines += [f"- {p['id']}: " + " → ".join(p["behavior_signature"]) + f" ({', '.join(p['processes'])})" for p in package["pattern_candidates"]]
    lines += ["", "## Evidence", "", "```json", json.dumps(package["facts"],ensure_ascii=False,indent=2), "```", ""]
    return "\n".join(lines)
