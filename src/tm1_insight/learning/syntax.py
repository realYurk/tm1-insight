"""Small lexical layer for explainable learning signals, not a TI interpreter."""
from __future__ import annotations

import re
from tm1_insight.ingest.hard_extract import (LOG_REGION_START, LOG_REGION_END,
                                           LOG_REGION_FINAL_START, LOG_REGION_FINAL_END)

TOKEN = re.compile(r"(?P<comment>\#[^\n]*)|(?P<string>'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")|(?P<id>[A-Za-z_][A-Za-z_0-9]*)|(?P<number>\d+(?:\.\d+)?)|(?P<space>\s+)|(?P<symbol>.)", re.S)
SECTIONS = ("prolog", "metadata", "data", "epilog")


def statements(parts, *, include_logging=False):
    for section, code in zip(SECTIONS, parts):
        pending, line, logging, line_start = [], 1, False, 0
        for match in TOKEN.finditer(code or ""):
            value, kind = match.group(), match.lastgroup
            if kind == "comment":
                if LOG_REGION_START.search(value) or LOG_REGION_FINAL_START.search(value): logging = True
                elif LOG_REGION_END.search(value) or LOG_REGION_FINAL_END.search(value): logging = False
            if (include_logging or not logging) and kind not in {"space", "comment"}:
                pending.append({"value":value, "kind":kind, "line":line, "section":section,
                                "column": match.start() - line_start + 1,
                                "offset": match.start()})
                if value == ";":
                    yield pending
                    pending = []
            line += value.count("\n")
            last_newline = value.rfind("\n")
            if last_newline >= 0: line_start = match.start() + last_newline + 1
        if pending:
            yield pending


def calls(tokens):
    """Yield call tokens and balanced arguments, including nested calls."""
    for index, token in enumerate(tokens[:-1]):
        if token["kind"] != "id" or tokens[index + 1]["value"] != "(":
            continue
        depth, args, current = 1, [], []
        for child in tokens[index + 2:]:
            value = child["value"]
            if value == "(": depth += 1
            elif value == ")":
                depth -= 1
                if depth == 0:
                    args.append(current)
                    yield token, args
                    break
            if value == "," and depth == 1:
                args.append(current); current = []
            else: current.append(child)


def expression(tokens):
    # Never copy string literals, paths or credentials to teaching extracts.
    return " ".join("'<常量>'" if t["kind"] == "string" else t["value"] for t in tokens if t["value"] != ";")


def signals(parts):
    operations, assignments, writes, samples = {}, {}, [], []
    for tokens in statements(parts):
        first = tokens[0]
        for token, args in calls(tokens):
            operation = token["value"].casefold()
            if operation in {"asciioutput", "textoutput"} and args and any(
                    t["kind"] == "id" and re.search("debug|logfile", t["value"], re.I) for t in args[0]):
                continue
            evidence = {"section":token["section"], "line":token["line"], "operation":token["value"]}
            operations.setdefault(operation, []).append(evidence)
            if operation in {"cellputn", "cellincrementn"} and token["section"] == "data" and args:
                writes.append((args[0], evidence))
        if len(tokens) > 2 and first["kind"] == "id" and tokens[1]["value"] == "=":
            if re.search(r"password|passwd|secret|token|sso|credential", first["value"], re.I):
                continue
            assignments.setdefault(first["value"].casefold(), []).append(tokens[2:])

    def dependencies(tokens, visited=None):
        visited = set() if visited is None else visited
        result = list(tokens)
        for token in tokens:
            name = token["value"].casefold()
            choices = assignments.get(name, [])
            if token["kind"] == "id" and name not in visited and len(choices) == 1 and len(visited) < 12:
                visited.add(name)
                result += dependencies(choices[0], visited)
        return result

    proportional = []
    for value, evidence in writes:
        chain = dependencies(value)
        symbols = {t["value"] for t in chain if t["kind"] == "symbol"}
        if "*" in symbols and ({"/", "\\"} & symbols):
            proportional.append({**evidence, "value_expression":expression(value),
                                 "interpretation":"写入值的单一定义词法链包含乘法与除法；需确认业务含义和分母范围。"})
    for name, choices in assignments.items():
        if len(choices) == 1 and choices[0][0]["section"] == "data":
            values = choices[0]
            if any(t["value"] in {"*", "/", "\\"} and t["kind"] == "symbol" for t in values):
                samples.append({"variable":name, "expression":expression(values)[:500],
                                "section":"data", "line":values[0]["line"]})
    return {"operations":operations, "proportional_writes":proportional, "formulas":samples[:12]}
