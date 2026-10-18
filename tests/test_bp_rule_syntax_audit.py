"""Task 21.1: synthetic equivalents of audited BP syntax, never enterprise fixtures.

Core Rule expressions already have complete syntax trees. These checks protect
the boundary between recognized coordinate expressions and unresolved values.
"""
import pytest

from tm1_insight.learning.rule_semantics import parse_rule_semantics


def walk(node):
    yield node
    for child in node['children']:
        yield from walk(child)


@pytest.mark.parametrize('coordinate', [
    "ATTRS('Item',!Item,'Group')",
    "ATTRS('Scenario',!Scenario,'Month') | ' YTD'",
    "IF(1=1,ATTRS('Item',!Item,'Group'),DB('Config',!Scenario))",
])
def test_calculated_db_coordinate_structure_does_not_confirm_its_value(coordinate):
    # Mirrors the observed attribute/concatenation/call nesting shapes, not data.
    code = "[]=N:DB('Source'," + coordinate + ');'
    parsed = parse_rule_semantics(code, 'Target', ['Item','Scenario'], {'Source','Config'})
    rule = parsed['rules'][0]
    tree = rule['rhs']['expression_ir']
    assert tree['type'] == 'DBReference'
    assert tree['structure_status'] == 'PARSED'
    assert tree['status'] == 'PARTIAL'
    assert rule['db_references'][0]['cube_resolved']
    assert rule['db_references'][0]['coordinates'][0]['status'] == 'UNKNOWN'
    assert any(n.get('name') == 'ATTRS' for n in walk(tree))
    assert 'FUNCTION_METADATA_NOT_VALIDATED:ATTRS' in tree['unresolved_reasons']
    for node in walk(tree):
        span = node['source']
        assert code[span['offset']:span['end_offset']] == node['raw']


def test_nested_coordinate_identifier_must_not_become_a_literal_member():
    parsed = parse_rule_semantics("[]=DB('Source',memberVariable);", 'Target', [], {'Source'})
    tree = parsed['rules'][0]['rhs']['expression_ir']
    assert tree['children'][1]['type'] == 'Identifier'
    assert tree['children'][1]['status'] == 'PARTIAL'
    assert tree['reference']['coordinates'][0]['kind'] == 'dynamic'


def test_labelled_multi_target_feeder_is_not_a_numeric_rule():
    code = "[]=1;FEEDERS;[]=>DB('Source','Group':'A'),DB('Source','Group':'B');"
    parsed = parse_rule_semantics(code, 'Target', ['Group'], {'Source'})
    assert len(parsed['rules']) == len(parsed['feeders']) == 1
    feeder = parsed['feeders'][0]
    assert feeder['status'] == 'UNKNOWN'
    assert 'rhs' not in feeder
    assert len(feeder['db_references']) == 2
    for ref in feeder['db_references']:
        assert ref['cube_resolved']
        assert ref['coordinates'][0]['kind'] == 'dynamic'
        assert ref['coordinates'][0]['status'] == 'UNKNOWN'


def test_unsupported_numeric_syntax_remains_unknown_not_needed_by_audited_rules():
    for expression in ('2^3', '1e3', '.5'):
        parsed = parse_rule_semantics('[]=N:' + expression + ';', 'Target')
        assert parsed['rules'][0]['rhs']['expression_ir']['status'] == 'UNKNOWN'
