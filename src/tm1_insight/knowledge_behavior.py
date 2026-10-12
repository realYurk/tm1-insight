"""Evidence adapters for Knowledge; reuse the existing parser for references."""
from __future__ import annotations

import hashlib
import re

from tm1_insight.parser import parse_process

SECTIONS = ("prolog", "metadata", "data", "epilog")
TOKENS = re.compile(
    r"(?P<comment>\#[^\r\n]*)|(?P<string>'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")"
    r"|(?P<call>\b[A-Za-z_][A-Za-z_0-9]*\s*(?=\())"
)


def behavior_for(operation: str) -> str | None:
    token = operation.casefold()
    if token in {"cellgetn", "cellgets"}: return "READ"
    if token in {"cellputn", "cellputs", "cellincrementn", "cellincrements"}: return "WRITE"
    if token in {"executeprocess", "runprocess"}: return "CALL"
    if token == "viewzeroout": return "ZEROOUT"
    if token.startswith("dimension") and token not in {"dimensionexists", "dimensionsortorder"}:
        return "DIMENSION_OPERATION"
    if token.startswith("view"): return "VIEW_OPERATION"
    if token.startswith("subset"): return "SUBSET_OPERATION"
    return None


def analyze_process(name: str, parts: tuple) -> dict:
    sequence, masked, offsets = [], {}, []
    line_offset = 0
    digest = hashlib.sha256("\n".join(raw or "" for raw in parts).encode()).hexdigest()
    for section, raw in zip(SECTIONS, parts):
        code = raw or ""
        offsets.append((line_offset + 1, section))
        line_offset += code.count("\n") + 1
        clean = list(code)
        for token in TOKENS.finditer(code):
            if token.lastgroup == "comment":
                clean[token.start():token.end()] = " " * (token.end() - token.start())
            elif token.lastgroup == "call":
                operation = token.group().strip()
                behavior = behavior_for(operation)
                if behavior:
                    sequence.append({"behavior": behavior, "operation": operation,
                                     "evidence": {"section": section,
                                                  "line": code.count("\n", 0, token.start()) + 1,
                                                  "column": token.start() - code.rfind("\n", 0, token.start()),
                                                  "source_hash": digest}})
        masked[section] = "".join(clean)
    parsed = parse_process({"name": name, "parameters": [], **masked})
    references = []
    actual_operations = {event["operation"].casefold() for event in sequence}
    for collection, kind, target_key in (("read_points", "READ", "source_cube"),
                                          ("write_points", "WRITE", "target_cube"),
                                          ("calls", "CALL", "callee")):
        for point in parsed.get(collection, []):
            if str(point.get("operation", "")).casefold() not in actual_operations:
                continue
            evidence = {"origin": "parser", "operation": point.get("operation"),
                        "section": None, "line": None, "source_hash": digest}
            if point.get("line", 0) > 0:
                for start, section in reversed(offsets):
                    if point["line"] >= start:
                        evidence.update(section=section, line=point["line"] - start + 1)
                        break
            target = point.get(target_key, "")
            references.append({"operation": kind, "target": target,
                               "resolution": "unresolved" if not target or "<" in target else "resolved",
                               "coordinates": point.get("dim_args", []),
                               "conditions": point.get("conditions", []), "evidence": evidence})
    operations = {item["behavior"] for item in sequence}
    role = ("DATA_TRANSFORM" if {"READ", "WRITE"} <= operations else
            "ORCHESTRATION" if "CALL" in operations and "WRITE" not in operations else
            "DIMENSION_MAINTENANCE" if "DIMENSION_OPERATION" in operations else "UNKNOWN")
    return {"process": name, "observed_role": role, "behavior_sequence": sequence,
            "sequence_semantics": "source_order_not_runtime_order", "references": references,
            "source_hash": digest}
