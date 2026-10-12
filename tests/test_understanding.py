import json
from tm1_insight.learning.understanding import analyze,call_components,analyze_rule

CATALOG={"cube":{"A","B"},"process":{"Child"},"dimension":{"Dept"}}


def ir(prolog="",data="",params=()):return analyze((prolog,"",data,""),CATALOG,params)


def test_forward_alias_resolves_catalog_name_without_exporting_arbitrary_literals():
    value=ir("c='A';alias=c;password='synthetic-private-secret';","CellPutN(1,alias,'x');")
    assert value['references'][0]['target']=='A'
    assert value['references'][0]['status']=='resolved'
    assert 'synthetic-private-secret' not in json.dumps(value)


def test_branch_merge_retains_only_identical_bindings():
    value=ir(data="If(p=1);c='A';Else;c='B';EndIf;CellGetN(c,'x');")
    assert value['references'][0]['status']=='unresolved'
    same=ir(data="If(p=1);c='A';Else;c='A';EndIf;CellGetN(c,'x');")
    assert same['references'][0]['target']=='A'


def test_loop_and_repeated_data_records_do_not_reuse_stale_initial_bindings():
    value=ir("c='A';","While(i<10);CellGetN(c,'x');c='B';End;CellGetN(c,'x');")
    assert all(r['status']=='unresolved' for r in value['references'])
    value=ir("c='A';","CellGetN(c,'x');If(p=1);c='B';EndIf;")
    assert value['references'][0]['status']=='unresolved'


def test_elseif_condition_is_observed_and_unbalanced_blocks_invalidate_bindings():
    value=ir(data="If(x);ElseIf(CellGetN('A','x')>0);EndIf;")
    assert value['references'][0]['target']=='A'
    value=ir(data="If(x);CellGetN('A','x');")
    assert value['diagnostics']
    assert value['references'][0]['status']=='structure_unknown'


def test_parameter_unknown_missing_and_string_pseudo_calls_are_distinct():
    value=ir(data="CellGetN(pCube,'x');CellGetN('not-a-catalog-object','x');s='CellGetN(''A'')';",params=['pCube'])
    assert [r['status'] for r in value['references']]==['parameter','missing_object']
    assert 'not-a-catalog-object' not in json.dumps(value)


def test_call_bindings_are_structural_and_hide_argument_values():
    value=ir(data="ExecuteProcess('Child','pSecret','never-export-this');")
    assert value['call_bindings'][0]['target']=='Child'
    assert value['call_bindings'][0]['arguments'][0]['parameter']=='pSecret'
    assert 'never-export-this' not in json.dumps(value)


def test_subset_mdx_dimension_is_third_argument_not_mdx_text():
    value=ir(data="SubsetCreateByMDX('temp','{[Dept].[A]}','Dept',1);")
    assert value['references'][0]['target']=='Dept'


def test_iterative_components_handle_deep_graph_and_self_calls():
    names=[str(i) for i in range(5000)]
    edges=list(zip(names,names[1:]))+[('4999','4998'),('0','0')]
    assert call_components(names,edges)==[['0'],['4998','4999']]


def test_rule_inventory_preserves_sections_and_does_not_evaluate_or_leak_literals():
    code="SKIPCHECK;\n['Amount']=N:DB('A',!Dept);\nFEEDERS;\n['Input']=>DB('B',!Dept);\n# DB('fake')\n"
    value=analyze_rule(code,{'A','B'})
    assert value['counts']['scope_n']==1
    assert value['counts']['feeders']==1
    assert [(r['target'],r['section'],r['line']) for r in value['db_references']]==[('A','rule',2),('B','feeder',4)]
    assert not value['runtime_verified']
    assert 'Amount' not in json.dumps(value)
