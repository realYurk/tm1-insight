import json
import duckdb
import pytest
from tm1_insight.learning.calculation import worksheet
from tm1_insight.store import calculation
from tm1_insight.store.schema import ALL_TABLES

CATALOG={'cube':{'A','Rate','Target'},'process':{'Child'},'dimension':{'Dept'}}

def run(data='',prolog='',metadata='',epilog='',parameters=('pDept',)):
    return worksheet('Example',(prolog,metadata,data,epilog),CATALOG,parameters)

def test_two_read_arithmetic_dag_and_source_positions():
    report=run("base=CellGetN('A',pDept);\nrate=CellGetN('Rate',pDept);\nresult=base*rate/100;\nCellPutN(result,'Target',pDept);")
    write=report['writes'][0];nodes={n['id']:n for n in report['nodes']}
    assert write['trace_status']=='STATIC'
    assert {nodes[n]['cube'] for n in write['read_nodes']}=={'A','Rate'}
    assert [nodes[n]['variable'] for n in write['definition_nodes']]==['result','base','rate']
    assert write['evidence']==dict(section='data',line=4,column=1)
    assert all(child in nodes for n in report['nodes'] for child in n['children'])
    assert not report['runtime_verified']

def test_same_line_calls_have_distinct_locations_and_reassignment_is_ordered():
    report=run("v=CellGetN('A',pDept);CellPutN(v,'Target',pDept);v=CellGetN('Rate',pDept);CellPutN(v,'Target',pDept);")
    nodes={n['id']:n for n in report['nodes']}
    assert [[nodes[i]['cube'] for i in w['read_nodes']] for w in report['writes']]==[['A'],['Rate']]
    assert report['writes'][0]['evidence']['column']!=report['writes'][1]['evidence']['column']

def test_branch_merge_loop_and_cross_metadata_values_remain_unknown():
    for data in ["If(pDept@='X');v=1;Else;v=2;EndIf;CellPutN(v,'Target',pDept);",
                 "While(i<10);v=v+1;End;CellPutN(v,'Target',pDept);"]:
        report=run(data,prolog='v=5;')
        assert report['writes'][-1]['trace_status']=='PARTIAL'
        assert not report['writes'][-1]['read_nodes']
    report=run("CellPutN(v,'Target',pDept);",prolog='v=5;',metadata='v=CellGetN(\'A\',pDept);')
    assert report['writes'][0]['trace_status']=='PARTIAL'

def test_branch_local_definition_is_visible_but_not_runtime_verified():
    report=run("If(pDept@='X');v=CellGetN('A',pDept);CellPutN(v,'Target',pDept);Else;CellPutN(0,'Target',pDept);EndIf;")
    assert report['writes'][0]['read_nodes']
    assert report['writes'][0]['control_context'][0]['branch']==0
    assert report['writes'][1]['control_context'][0]['branch']==1

def test_unknown_function_does_not_invent_value_flow_from_nested_read():
    report=run("v=Unmodeled(CellGetN('A',pDept));CellPutN(v,'Target',pDept);")
    assert report['writes'][0]['trace_status']=='PARTIAL'
    assert not report['writes'][0]['read_nodes']
    assert any(r['target']=='A' for r in report['observations'])

def test_dynamic_target_coordinate_unknown_and_invocation_separate():
    report=run("ExecuteProcess('Child','pDept',pDept);v=CellGetN('A',unknownCoord);CellPutN(v,pCube,pDept);")
    assert report['calls'][0]['target']=='Child'
    assert report['writes'][0]['cube'] is None and report['writes'][0]['trace_status']=='PARTIAL'
    assert report['writes'][0]['unknown_nodes']
    assert all(node['kind']!='call_result' for node in report['nodes'])

def test_precedence_unary_safe_division_and_no_evaluation():
    report=run("v=-(2+3)*4\\0;CellPutN(v,'Target',pDept);")
    binary=[n['operator'] for n in report['nodes'] if n['kind']=='binary']
    assert binary==['+','*','\\']
    assert report['writes'][0]['read_nodes']==[]
    assert 'evaluated_value' not in json.dumps(report)

def test_sensitive_values_unused_literals_and_function_arguments_not_exported():
    report=run("password=987654321;unused='synthetic-private';v=1;CellPutN(v,'Target',pDept);ExecuteProcess('Child','pSecret','hidden-secret');")
    payload=json.dumps(report)
    for secret in ['987654321','synthetic-private','hidden-secret']:assert secret not in payload
    assert not any(n.get('variable')=='password' for n in report['nodes'])
    used=run("password=987654321;CellPutN(password,'Target',pDept);")
    assert '987654321' not in json.dumps(used) and used['writes'][0]['unknown_nodes']

def test_comments_pseudo_calls_and_logging_regions():
    report=run("# CellPutN(9,'Target',pDept);\ns='CellPutN(3,''Target'',pDept)';CellPutN(1,'Target',pDept);")
    assert len(report['writes'])==1

def test_structural_failure_and_budgets_are_explicit():
    report=run("If(pDept@='X');v=CellGetN('A',pDept);CellPutN(v,'Target',pDept);")
    assert report['writes'][0]['trace_status']=='UNKNOWN' and report['writes'][0]['read_nodes']==[]
    assert report['diagnostics']
    assert run('x'*250001)['diagnostics']
    assert run('v='+'+'.join('1' for _ in range(1001))+';')['diagnostics']

def test_mutated_parameter_never_falls_back_to_original_input_after_merge():
    report=run("If(flag);pDept=1;EndIf;CellPutN(pDept,'Target','x');")
    assert report['writes'][0]['trace_status']=='PARTIAL'
    assert report['writes'][0]['unknown_nodes']
    report=run("CellPutN(pDept,'Target','x');pDept=pDept+1;")
    assert report['writes'][0]['trace_status']=='PARTIAL'

def test_malformed_quotes_and_parentheses_do_not_export_raw_fragments():
    for data in ["v='private_unterminated;CellPutN(v,'Target',pDept);", "CellPutN(1,'Target',pDept;"]:
        report=run(data)
        assert report['diagnostics'] and not report['writes']
        assert 'private_unterminated' not in json.dumps(report)

def test_long_display_expression_marks_truncation_but_preserves_dag():
    report=run('v='+'+'.join('1234' for _ in range(150))+";CellPutN(v,'Target',pDept);")
    assert any('表达式显示已截断' in n.get('expression','') for n in report['nodes'])
    assert len([n for n in report['nodes'] if n['kind']=='number'])==150

@pytest.fixture
def con():
    con=duckdb.connect()
    for ddl in ALL_TABLES.values():con.execute(ddl)
    for cube in ['A','Rate','Target']:
        con.execute('INSERT INTO cubes (name,dimension_count) VALUES (?,1)',[cube])
        con.execute('INSERT INTO cube_has_dimension VALUES (?,\'Dept\',0)',[cube])
    con.execute("INSERT INTO dimensions (name) VALUES ('Dept')")
    con.execute('INSERT INTO processes (name,data,parameters) VALUES (?,?,?)', ['Example',
        "v=CellGetN('A',pDept)*CellGetN('Rate',pDept);CellPutN(v,'Target',pDept);",json.dumps([dict(name='pDept')])])
    yield con
    con.close()

def test_coordinate_order_and_markdown_export(con):
    report=calculation.inspect(con,'Example')
    write=report['writes'][0]
    assert write['coordinate_mapping']['items'][0]['dimension']=='Dept'
    assert write['trace_status']=='STATIC'
    assert '静态读取依赖：A' in calculation.markdown(report)
    con.execute("UPDATE cube_has_dimension SET dim_order=3 WHERE cube_name='Target'")
    report=calculation.inspect(con,'Example')
    assert report['writes'][0]['coordinate_mapping']['status']=='UNKNOWN'
    assert report['writes'][0]['coordinate_mapping']['items'][0]['dimension'] is None

def test_coordinate_arity_mismatch_never_guesses_alignment(con):
    con.execute("UPDATE processes SET data=? WHERE name='Example'", ["CellPutN(1,'Target',pDept,'extra');"])
    report=calculation.inspect(con,'Example')
    assert report['writes'][0]['coordinate_mapping']['expected']==1
    assert all(c['dimension'] is None for c in report['writes'][0]['coordinate_mapping']['items'])
    assert calculation.inspect(con,'Missing') is None
