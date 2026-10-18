"""Offline expression IR positive and negative contracts; no TM1 evaluation."""
import json
import pytest
from tm1_insight.learning.rule_semantics import parse_rule_semantics


def rule(expression):
    return parse_rule_semantics("['Year':'2026']=N:" + expression + ';', 'B', ['Year'], {'A','B'})['rules'][0]


def ir(expression):
    return rule(expression)['rhs']['expression_ir']


def walk(node):
    yield node
    for c in node['children']:
        yield from walk(c)


@pytest.mark.parametrize('expression,kind', [
    ("DB('A',!Year)", 'DBReference'),
    ("DB('A',!Year)+1", 'BinaryOperation'),
    ("DB('A',!Year)*DB('B',!Year)", 'BinaryOperation'),
    ("ABS(-2)", 'FunctionCall'),
    ("IF(1<2,IF(2=2,3,4),5)", 'ConditionalExpression'),
    ("['Year':'2026']", 'AreaReference'),
    ('!Year', 'RegionReference'), ('STET', 'SpecialExpression'),
    ('CONTINUE', 'SpecialExpression'), ('dynamic', 'Identifier'),
])
def test_node_types(expression, kind):
    assert ir(expression)['type'] == kind


@pytest.mark.parametrize('op', ['@=', '@<>', '@>=', '@<=', '<>', '>=', '<=', '=', '<', '>', '&', '%', '|', '\\'])
def test_multi_token_operators(op):
    tree = ir('1' + op + '2')
    assert tree['type'] == 'BinaryOperation'
    assert tree['operator'] == op


def test_precedence_and_grouping():
    tree = ir('1+2*3')
    assert tree['operator'] == '+'
    mul = tree['children'][1]
    assert mul['operator'] == '*'
    assert ir('(1+2)*3')['children'][0]['operator'] == '+'
    assert ir('-2*2')['children'][0]['type'] == 'UnaryOperation'


def test_unknown_function_retains_confirmed_nested_db_and_propagates():
    tree = ir("1+Mystery(DB('A',!Year),ABS(2))")
    assert tree['structure_status'] == 'PARSED'
    assert tree['status'] == 'PARTIAL'
    refs = [n for n in walk(tree) if n['type'] == 'DBReference']
    assert len(refs) == 1 and refs[0]['reference']['cube_resolved']
    assert any('Mystery'.upper() in r for r in tree['unresolved_reasons'])


def test_dynamic_cube_not_confirmed():
    tree = ir('DB(dynamic,!Year)')
    assert not tree['reference']['cube_resolved']
    assert tree['status'] == 'PARTIAL'


@pytest.mark.parametrize('expression', ['1+', 'IF(1,2', '1 2', 'DB(', '[', '1 @ = 2', "'unterminated", '2^3'])
def test_invalid_expressions_remain_unknown(expression):
    assert ir(expression)['status'] == 'UNKNOWN'


def test_arity_and_area_membership_remain_unconfirmed():
    assert ir('IF(1,2)')['status'] == 'PARTIAL'
    assert ir("['Amount']")['status'] == 'PARTIAL'
    assert ir('ATTRN(1,2,3)')['status'] == 'PARTIAL'
    assert ir('!Other')['status'] == 'PARTIAL'


def test_source_spans_exact_and_legacy_fields_unchanged():
    code = "# comment\n['Year':'2026']=N: IF(1<2,\n DB('A',!Year) + 2, CONTINUE);"
    parsed = parse_rule_semantics(code, 'B', ['Year'], {'A','B'})
    r = parsed['rules'][0]
    assert r['rhs_kind'] == 'EXPRESSION'
    assert r['rhs']['expression'] and r['conditions'] and r['db_references']
    for n in walk(r['rhs']['expression_ir']):
        span = n['source']
        assert code[span['offset']:span['end_offset']] == n['raw']
        assert span['section'] == 'rule'
    db = next(n for n in walk(r['rhs']['expression_ir']) if n['type']=='DBReference')
    assert db['source']['line'] == 3 and db['source']['column'] == 2
    json.dumps(parsed)


def test_feeder_has_no_expression_tree_and_lhs_stays_conservative():
    parsed = parse_rule_semantics("['Amount']=1; FEEDERS; ['Amount']=>DB('A',!Year);",'B',['Year'],{'A','B'})
    assert parsed['rules'][0]['lhs']['coordinates'][0]['dimension'] is None
    assert 'rhs' not in parsed['feeders'][0]


def test_bounded_flat_and_deep_expressions():
    for expression in ('+'.join(['1']*2000), '('*100+'1'+')'*100):
        assert ir(expression)['status'] == 'UNKNOWN'


def test_changed_source_does_not_reuse_tree():
    assert ir('1+2')['raw'] != ir('1*2')['raw']


def test_old_minimal_store_returns_additive_ir_without_migration():
    import duckdb
    from tm1_insight.store.queries import cube_rule_semantics
    con = duckdb.connect(':memory:')
    try:
        con.execute('create table cubes(name varchar, rules varchar)')
        con.execute('create table cube_has_dimension(cube_name varchar, dimension_name varchar, dim_order integer)')
        con.execute("insert into cubes values ('B', '[]=N:1+2;')")
        result = cube_rule_semantics(con, 'B')
        assert result['available']
        assert result['rules'][0]['rhs']['expression_ir']['operator'] == '+'
        assert result['rules'][0]['rhs']['expression'] == '1 + 2'
    finally:
        con.close()


def test_named_db_coordinate_is_not_silently_flattened():
    tree = ir("DB('A','Year':'2026')")
    assert tree['status'] == 'UNKNOWN'
