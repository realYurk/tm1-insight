import duckdb

from tm1_insight.knowledge import development_context, discover_scope, extract, markdown
from tm1_insight.knowledge_behavior import analyze_process


def _catalog():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE cubes(name TEXT, dimensions TEXT, rules TEXT, has_rules BOOLEAN, dimension_count INTEGER)")
    con.execute("CREATE TABLE processes(name TEXT, prolog TEXT, metadata TEXT, data TEXT, epilog TEXT, parameters TEXT, datasource TEXT, code_length INTEGER)")
    con.execute("CREATE TABLE dimensions(name TEXT, is_system BOOLEAN, element_count INTEGER, elements TEXT, attributes TEXT, edges TEXT, subsets TEXT)")
    con.execute("CREATE TABLE process_reads_cube(process_name TEXT, cube_name TEXT)")
    con.execute("CREATE TABLE process_writes_cube(process_name TEXT, cube_name TEXT)")
    con.execute("CREATE TABLE process_calls_process(caller TEXT, callee TEXT)")
    con.execute("CREATE TABLE cube_has_dimension(cube_name TEXT, dimension_name TEXT, dim_order INTEGER)")
    con.execute("INSERT INTO cubes VALUES ('BP Input', '[]', '', false, 0)")
    con.execute("INSERT INTO dimensions VALUES ('BP Version', false, 1, '[]', '{}', '[]', '[]')")
    con.execute("INSERT INTO processes VALUES (?, '', '', ?, '', '[]', null, 0)", ["Load Data", "v = CellGetN('BP Input'); CellPutN(v, 'BP Output');"])
    con.execute("INSERT INTO process_reads_cube VALUES ('Load Data', 'BP Input')")
    con.execute("INSERT INTO process_writes_cube VALUES ('Load Data', 'BP Output')")
    con.execute("INSERT INTO cube_has_dimension VALUES ('BP Input', 'BP Version', 0)")
    return con


def test_prefix_scope_expands_to_related_process_and_dimension():
    con = _catalog()
    try:
        result = extract(con, "BP*")
        assert result["matched"] == {"cubes": 1, "processes": 1, "dimensions": 1, "rules": 0}
        assert result["processes"][0]["observed_role"] == "DATA_TRANSFORM"
        assert [x["behavior"] for x in result["processes"][0]["behavior_sequence"]] == ["READ", "WRITE"]
        assert result["facts"]
        assert "# TM1 Knowledge" in markdown(result)
    finally:
        con.close()


def test_comments_and_string_literals_are_not_operations():
    item = analyze_process("P", ("# CellPutN(1, 'A', 'x');\ns = 'CellGetN(''A'', ''x'')';", "", "", ""))
    assert item["behavior_sequence"] == []
    assert item["references"] == []
    assert item["observed_role"] == "UNKNOWN"


def test_repeated_operations_keep_source_order_and_location():
    item = analyze_process("P", ("", "", "a=CellGetN('A','x');\nCellPutN(a,'B','x');\nb=CellGetN('C','x');", ""))
    assert [x["behavior"] for x in item["behavior_sequence"]] == ["READ", "WRITE", "READ"]
    assert [x["evidence"]["line"] for x in item["behavior_sequence"]] == [1, 2, 3]
    assert all(x["evidence"]["section"] == "data" for x in item["behavior_sequence"])
    assert len(item["source_hash"]) == 64


def test_disabled_scope_does_not_reintroduce_related_processes():
    con = _catalog()
    try:
        scope = discover_scope(con, "BP", {"processes":False, "dimensions":False})
        assert scope["matched"]["processes"] == 0
        assert scope["matched"]["dimensions"] == 0
        assert discover_scope(con, "")["matched"]["cubes"] == 0
        assert discover_scope(con, "Missing")["matched"]["processes"] == 0
        assert discover_scope(con, "BP PnL")["matched"]["cubes"] == 0
    finally:
        con.close()


def test_percent_and_underscore_are_literal_and_keyword_mode_is_explicit():
    con = _catalog()
    try:
        assert discover_scope(con, "B_")["matched"]["cubes"] == 0
        assert discover_scope(con, "%")["matched"]["cubes"] == 0
        assert discover_scope(con, "Input")["matched"]["cubes"] == 0
        assert discover_scope(con, "Input", match_mode="keyword")["matched"]["cubes"] == 1
    finally:
        con.close()


def test_patterns_are_stable_and_source_is_excluded_by_default():
    con = _catalog()
    try:
        first = extract(con, "BP")
        second = extract(con, "BP*")
        assert first["pattern_candidates"][0]["id"] == second["pattern_candidates"][0]["id"]
        assert first["pattern_candidates"][0]["confidence"] == "SYNTAX_OBSERVED"
        assert first["pattern_candidates"][0]["evidence"][0]["line"] == 1
        assert "source_code" not in first["processes"][0]
        assert not first["privacy"]["publishing_authorized"]
        context = development_context(first, "process", "Load Data")
        assert [p["process"] for p in context["processes"]] == ["Load Data"]
        assert "scope" not in context
        assert all(set(p["processes"]) <= {"Load Data"} for p in context["pattern_candidates"])
        assert all(e["process"] == "Load Data" for p in context["pattern_candidates"] for e in p["evidence"])
        assert development_context(first, "cube", "BP Input")["data_flows"]
        assert development_context(first, "pattern", first["pattern_candidates"][0]["id"])["facts"]
    finally:
        con.close()


def test_progress_reports_real_process_counts_and_monotonic_stages():
    con = _catalog()
    events = []
    try:
        extract(con, "BP", progress=lambda **event:events.append(event))
        assert [event["stage_index"] for event in events] == sorted(event["stage_index"] for event in events)
        completed = [event for event in events if event["stage_index"] == 3][-1]
        assert completed["current"] == completed["total"] == 1
    finally:
        con.close()
