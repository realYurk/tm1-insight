import duckdb

from tm1_insight.knowledge import extract, markdown


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
        assert result["processes"][0]["observed_role"] == "CALCULATION"
        assert [x["behavior"] for x in result["processes"][0]["behavior_sequence"]] == ["READ", "WRITE"]
        assert result["facts"]
        assert "# TM1 Knowledge" in markdown(result)
    finally:
        con.close()
