import duckdb
from tm1_insight.store.queries import trace_cell_value


def test_strict_mdx_measure_matching_keeps_dynamic_but_rejects_conflicts():
    con = duckdb.connect(':memory:')
    con.execute('CREATE TABLE cube_has_dimension (cube_name TEXT, dimension_name TEXT, dim_order INTEGER)')
    con.execute('CREATE TABLE ti_flow_dims (process_name TEXT, target_cube TEXT, write_point_id TEXT, operation TEXT, dim_index INTEGER, dim_value TEXT, conditions TEXT)')
    con.execute('CREATE TABLE ti_flows (process_name TEXT, target_cube TEXT, source_cubes TEXT, write_point_count INTEGER)')
    con.execute("INSERT INTO cube_has_dimension VALUES ('B', 'Measure', 0), ('B', 'Year', 1)")
    con.executemany('INSERT INTO ti_flow_dims VALUES (?, ?, ?, ?, ?, ?, ?)', [
        ('Fixed', 'B', '1', 'CellPutN', 0, 'Amount', '[]'),
        ('Dynamic', 'B', '2', 'CellPutN', 0, '<vMeasure>', '[]'),
        ('Conflict', 'B', '3', 'CellPutN', 0, 'Volume', '[]'),
        ('Missing', 'B', '4', 'CellPutN', 1, '2025', '[]'),
    ])
    result = trace_cell_value(con, 'B', {'Measure': ['Amount']}, strict=True, focus_dimension='Measure')
    assert [c['process'] for c in result['candidates']] == ['Fixed', 'Dynamic', 'Missing']
    assert result['candidates'][0]['matched_dims'] == ['Measure']
    assert result['candidates'][1]['variable_dims'] == ['Measure']
    assert result['candidates'][2]['match_mode'] == 'partial'
    assert not result['relaxed']
    con.execute("DELETE FROM ti_flow_dims WHERE process_name = 'Dynamic'")
    only_conflicts = trace_cell_value(con, 'B', {'Measure': ['Other'], 'Year': ['1999']}, strict=True)
    assert not only_conflicts['candidates']
    assert not only_conflicts['relaxed']
    con.close()
