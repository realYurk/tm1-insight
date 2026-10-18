"""Task 20.1: strict semantic certainty, never positional member guessing."""
import json
import duckdb
import pytest
from tm1_insight.learning.rule_semantics import parse_rule_semantics


def parse(rhs,lhs="['Measure':'Amount']",catalog=None):
    return parse_rule_semantics(f'{lhs}=N:{rhs};','Target',['Year','Measure'],
                                {'Cube_A'} if catalog is None else catalog)


@pytest.mark.parametrize('expression,kind',[
    ("DB('Cube_A',!Year,'Amount')",'DB_REFERENCE'),
    ("DB('Cube_A',!Year,')')",'DB_REFERENCE'),
    ("DB('Cube_A',!Year,'Amount')+ABS(1)",'EXPRESSION'),
    ("DB('Cube_A',!Year,'Amount')*2",'EXPRESSION'),
    ("DB('Cube_A',!Year,'Amount')*ABS(MAX(1,2))",'EXPRESSION'),
    ("ABS(MAX(DB('Cube_A',!Year,'Amount'),1))",'EXPRESSION'),
    ("DB('Cube_A',!Year,'Amount')+DB('Cube_A',!Year,'Amount')",'EXPRESSION'),
])
def test_db_must_consume_complete_rhs_with_balanced_tokens(expression,kind):
    r=parse(expression);rule=r['rules'][0]
    assert rule['rhs_kind']==kind and all(d['cube_resolved'] for d in rule['db_references'])
    assert rule['status']==('PARSED' if kind=='DB_REFERENCE' else 'PARTIAL')
    assert bool(r['unknowns'])==(kind!='DB_REFERENCE')


def test_dynamic_cube_keeps_reference_but_not_confirmed_dependency():
    r=parse("DB(pCube,!Year,'Amount')");rule=r['rules'][0];ref=rule['db_references'][0]
    assert rule['rhs_kind']=='DB_REFERENCE' and rule['status']=='PARTIAL'
    assert ref['cube']=='pCube' and not ref['cube_resolved'] and ref['cube_resolution']=='DYNAMIC'
    assert any('DB_CUBE_DYNAMIC' in reason for reason in rule['unresolved_reasons'])
    assert r['unknowns'] and all(u['kind']=='rule' and u['line']==1 for u in r['unknowns'])


def test_literal_missing_from_catalog_is_distinct_from_dynamic_cube():
    ref=parse("DB('Missing',!Year,'Amount')")['rules'][0]['db_references'][0]
    assert not ref['cube_resolved'] and ref['cube_resolution']=='MISSING_FROM_CATALOG'


@pytest.mark.parametrize('func,reason',[('Opaque','UNKNOWN_FUNCTION'),('ABS','FUNCTION_SEMANTICS_NOT_RECONSTRUCTED')])
def test_recognized_or_unknown_function_does_not_establish_complete_formula(func,reason):
    r=parse(f"{func}(DB('Cube_A',!Year,'Amount'))");rule=r['rules'][0]
    assert rule['db_references'][0]['cube_resolved'] and rule['status']=='PARTIAL'
    assert rule['rhs']['semantic_status']=='UNCONFIRMED' and func in rule['rhs']['expression']
    assert any(reason in u['reason'] for u in r['unknowns'])


@pytest.mark.parametrize('lhs',["['Amount'","['Measure':]","['Measure':'Amount']garbage"])
def test_incomplete_lhs_never_parsed(lhs):
    r=parse("DB('Cube_A',!Year,'Amount')",lhs=lhs);rule=r['rules'][0]
    assert rule['status']!='PARSED' and rule['lhs']['status']!='PARSED'
    assert rule['db_references'][0]['cube_resolved'] and r['unknowns']


@pytest.mark.parametrize('members',[{'Year':['2026'],'Measure':['Amount']},
                                  {'Year':['Amount'],'Measure':['Amount']},
                                  None])
def test_last_dimension_member_ambiguous_member_or_missing_member_index_never_gets_first_dimension(members):
    from tm1_insight.store.schema import ALL_TABLES
    from tm1_insight.store.queries import cube_rule_semantics
    c=duckdb.connect(':memory:')
    try:
        for ddl in ALL_TABLES.values():c.execute(ddl)
        c.execute('INSERT INTO cubes VALUES (?,?,?,?,?)',['Target',json.dumps(['Year','Measure']),"['Amount']=N:1;",True,2])
        for i,d in enumerate(['Year','Measure']):
            c.execute('INSERT INTO cube_has_dimension VALUES (?,?,?)',['Target',d,i])
            c.execute('INSERT INTO dimensions(name,elements) VALUES (?,?)',[d,json.dumps(members[d]) if members else None])
        r=cube_rule_semantics(c,'Target');rule=r['rules'][0];coord=rule['lhs']['coordinates'][0]
        # The v1 contract only receives Cube order, not a complete member index.
        # Even a real last-dimension member cannot be mapped from that order.
        assert coord['member']=='Amount' and coord['dimension'] is None
        assert rule['status']=='PARTIAL' and rule['lhs']['status']=='PARTIAL'
        assert any('OWNERSHIP_UNKNOWN' in x for x in rule['unresolved_reasons'])
    finally:c.close()


def test_explicit_dimension_positive_and_invalid_label_counterexample():
    rule=parse('1')['rules'][0]
    assert rule['status']=='PARSED' and rule['lhs']['coordinates'][0]['dimension']=='Measure'
    r=parse('1',"['NotACubeDimension':'Amount']");coord=r['rules'][0]['lhs']['coordinates'][0]
    assert coord['dimension'] is None and coord['declared_dimension']=='NotACubeDimension'
    assert r['rules'][0]['status']=='PARTIAL' and r['unknowns']


def test_rule_and_feeder_statuses_are_independent_and_not_numeric_flow():
    code="['Measure':'Amount']=N:Opaque(DB('Cube_A',!Year,'Amount'));\nFEEDERS;\n['Measure':'Amount']=>DB('Cube_A',!Year,'Amount');"
    r=parse_rule_semantics(code,'Target',['Year','Measure'],{'Cube_A'})
    assert r['rules'][0]['status']=='PARTIAL' and r['feeders'][0]['status']=='PARSED'
    assert not any(u['kind']=='feeder' for u in r['unknowns'])
    assert 'rhs' not in r['feeders'][0]
    code="['Measure':'Amount']=N:1;FEEDERS;['Amount']=>DB(pCube,!Year,'Amount');"
    r=parse_rule_semantics(code,'Target',['Year','Measure'],{'Cube_A'})
    assert r['rules'][0]['status']=='PARSED' and r['feeders'][0]['status']=='PARTIAL'
    assert all(u['kind']=='feeder' for u in r['unknowns'])


def test_feeder_expression_cannot_be_promoted_to_direct_db_target():
    r=parse_rule_semantics("FEEDERS;['Measure':'Amount']=>DB('Cube_A',!Year,'Amount')+ABS(1);",'Target',['Year','Measure'],{'Cube_A'})
    f=r['feeders'][0]
    assert f['status']=='UNKNOWN' and f['target_area']['status']=='UNKNOWN'
    assert f['db_references'][0]['cube_resolved'] and r['unknowns']


@pytest.mark.parametrize('rhs',["DB('Cube_A',!Year*2,'Amount')","DB('Cube_A',!Year,Opaque('Amount'))"])
def test_resolved_cube_does_not_prove_dynamic_coordinate_or_function_semantics(rhs):
    r=parse(rhs);rule=r['rules'][0]
    assert rule['status']=='PARTIAL' and rule['db_references'][0]['cube_resolved']
    assert any(c['kind']=='dynamic' for c in rule['db_references'][0]['coordinates'])


def test_malformed_rhs_preserves_available_facts_and_unknown_location():
    r=parse("Opaque(DB('Cube_A',!Year,'Amount')")
    assert r['rules'][0]['status']=='UNKNOWN' and r['rules'][0]['db_references'][0]['cube_resolved']
    assert all(u['line']==r['rules'][0]['line_start'] and u['raw']==r['rules'][0]['raw'] for u in r['unknowns'])


@pytest.mark.parametrize('lhs',["['Measure':{'A',}]","['Measure':{'A' 'B'}]","['Measure':{'A',Opaque('B')}]","['Measure':'Amount',]"])
def test_incomplete_or_computed_lhs_member_set_not_silently_flattened(lhs):
    r=parse('1',lhs)
    assert r['rules'][0]['status']=='UNKNOWN' and r['rules'][0]['lhs']['status']=='UNKNOWN'
    assert r['unknowns']


def test_nested_db_coordinate_is_still_a_whole_db_rhs_but_not_complete_semantics():
    r=parse("DB('Cube_A',DB('Cube_A',!Year,'Amount'),'Amount')")
    rule=r['rules'][0]
    assert rule['rhs_kind']=='DB_REFERENCE' and len(rule['db_references'])==2
    assert rule['status']=='PARTIAL' and all(d['cube_resolved'] for d in rule['db_references'])


def test_bang_dimension_must_be_confirmed_against_current_cube():
    r=parse("DB('Cube_A',!NotInCurrentCube,'Amount')");rule=r['rules'][0]
    assert rule['db_references'][0]['cube_resolved'] and rule['status']=='PARTIAL'
    assert any('DB_REGION_DIMENSION_UNCONFIRMED' in reason for reason in rule['unresolved_reasons'])


def test_query_parser_failure_does_not_return_empty_unknowns(monkeypatch):
    import tm1_insight.learning.rule_semantics as module
    from tm1_insight.store.queries import cube_rule_semantics
    c=duckdb.connect(':memory:')
    c.execute('CREATE TABLE cubes(name TEXT,rules TEXT)');c.execute("INSERT INTO cubes VALUES ('X','broken')")
    c.execute('CREATE TABLE cube_has_dimension(cube_name TEXT,dimension_name TEXT,dim_order INT)')
    def fail(*a,**kw):raise ValueError('fixture parse failure')
    monkeypatch.setattr(module,'parse_rule_semantics',fail)
    try:
        r=cube_rule_semantics(c,'X')
        assert r['available'] and r['unknowns'][0]['status']=='UNKNOWN'
    finally:c.close()
