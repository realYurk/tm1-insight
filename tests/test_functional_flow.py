"""Functional Flow is a presentation of facts, never invented value transfer."""
import copy
import json
import time

import pytest

from tm1_insight import architecture
from tm1_insight.functional_flow import assemble, from_artifact, markdown, mermaid, slice_summary
from test_architecture import con, fixture  # noqa: F401
from test_datasource_api import client  # noqa: F401


def test_access_directions_proof_and_technical_folding(con):
    report = architecture.build(con, 'Load')
    flow = assemble(report, include_context=True)
    nodes = {n['id']: n for n in flow['nodes']}
    actions = {(nodes[e['source']]['name'], e['action'], nodes[e['target']]['name']) for e in flow['edges']}
    assert ('Cube_A','read','Load') in actions
    assert ('Load','write','Cube_B') in actions
    assert ('Caller','PROCESS_CALL','Load') in actions
    assert ('Nightly','CHORE_SCHEDULE','Caller') in actions
    assert not any(n['name'].startswith('}') or n['name']=='Journal' for n in flow['nodes'])
    assert not any(e['action'] in {'STATIC_VALUE_DEPENDENCY','CANDIDATE_FORMATION'} for e in flow['edges'])
    relations = {r['id']: r for r in report['unified_relations']}
    facts = {f['id'] for f in flow['evidence']}
    assert all(e['relation_ids'] and set(e['evidence_refs']) <= facts for e in flow['edges'])
    assert all(relations[r]['status']!='UNKNOWN' for e in flow['edges'] for r in e['relation_ids'])
    assert flow['statistics']['folded']['technical'] > 0
    assert not flow['runtime_verified']
    assert '值传输' in flow['note']


def test_core_helper_write_survives_without_showing_helper(con):
    con.execute("UPDATE processes SET data='',prolog=? WHERE name='Load'", ["ExecuteProcess('}bedrock.synthetic.clear');"])
    con.execute('UPDATE processes SET prolog=? WHERE name=?', ["n=CellGetN('Cube_A',vYear,vProduct);CellPutN(n,'Cube_B',vYear,pRegion,pMeasure);", '}bedrock.synthetic.clear'])
    flow = assemble(architecture.build(con,'Load'))
    nodes = {n['id']:n for n in flow['nodes']}
    assert any(nodes[e['source']]['name']=='Load' and nodes[e['target']]['name']=='Cube_B' and e['action']=='write' for e in flow['edges'])
    assert all(not n['name'].startswith('}') for n in flow['nodes'])


def test_candidate_read_write_never_becomes_transfer(con):
    con.execute("UPDATE processes SET data=? WHERE name='Load'", ["n=CellGetN('Cube_A',vYear,vProduct);CellPutN(7,'Cube_B',vYear,pRegion,pMeasure);"])
    flow = assemble(architecture.build(con, 'Load'))
    nodes = {n['id']:n for n in flow['nodes']}
    assert not any(nodes[e['source']]['kind']==nodes[e['target']]['kind']=='cube' for e in flow['edges'])


def test_slice_fixed_first_max_six_and_no_dimension_position_guess():
    coordinates = [dict(dimension='Year',kind='UNRESOLVED',expression='vYear'),
                   dict(dimension=None,kind='FIXED_MEMBER',expression="'NeverAssign'"),
                   dict(dimension='Measure',kind='FIXED_MEMBER',expression="'Amount'"),
                   dict(dimension='Map',kind='LOOKUP_COORDINATE',expression="CellGetS('Config',vYear)")]
    result = slice_summary(coordinates)
    assert result[0]['dimension']=='Measure'
    assert next(c for c in result if c['dimension']=='Year')['value']=='变量 · vYear'
    assert next(c for c in result if c['dimension']=='Map')['value']=='待确认'
    assert all(c['dimension'] is not None for c in result)
    assert len(slice_summary(coordinates*4))==6


def test_write_slices_keep_different_sites_and_conditions(con):
    con.execute("UPDATE processes SET data=? WHERE name='Load'", ["If(vYear @= 'ACT');CellPutN(1,'Cube_B',vYear,'Member1','Member2');EndIf;CellIncrementN(2,'Cube_B',vYear,'Member1','Member3');"])
    flow = assemble(architecture.build(con,'Load'))
    edge = next(e for e in flow['edges'] if e['action']=='write')
    assert sum(s['write_sites'] for s in edge['slices'])==2
    assert len(edge['slices'])==2
    assert any(s['conditional'] for s in edge['slices'])
    assert any(c['fixed'] for s in edge['slices'] for c in s['coordinates'])
    assert all(len(s['coordinates'])<=6 and s['context_refs'] for s in edge['slices'])


def test_rule_group_keeps_independent_proofs_dynamic_refs_not_confirmed(con):
    con.execute("UPDATE cubes SET rules=?,has_rules=true WHERE name='Cube_B'", ["[]=N:DB('Cube_A',!Year,dynamicMember)*2;\n['Member1']=N:DB(dynamicCube,!Year);\nFEEDERS;[]=>DB('Cube_A',!Year,'Member1'),DB('Journal',!Year);"])
    report = architecture.build(con,'Load')
    flow = assemble(report)
    rules = [n for n in flow['nodes'] if n['kind']=='rule']
    assert len(rules)==1 and len(rules[0]['object_ids'])==2
    assert any(e['action']=='RULE_TARGET' and len(e['relation_ids'])==2 for e in flow['edges'])
    assert any(e['action']=='RULE_DB_REFERENCE' for e in flow['edges'])
    assert all(n['kind'] not in {'feeder','unresolved'} for n in flow['nodes'])
    assert flow['statistics']['folded']['unconfirmed'] > 0
    assert any('DB_COORDINATE' in reason for e in flow['edges'] for reason in e['unresolved_reasons'])


def test_display_budget_cycles_stability_and_non_mutation(con):
    report = architecture.build(con,'Load')
    before = copy.deepcopy(report)
    a = assemble(report,max_nodes=3,max_edges=3)
    b = assemble(report,max_nodes=3,max_edges=3)
    assert a==b and report==before
    assert len(a['nodes'])<=3 and len(a['edges'])<=3 and a['statistics']['truncated']
    assert any(n['selected_entry'] for n in a['nodes'])
    full = assemble(report)
    nodes = {n['id']:n for n in full['nodes']}
    assert {('Load','BusinessChild'),('BusinessChild','Load')} <= {(nodes[e['source']]['name'],nodes[e['target']]['name']) for e in full['edges']}


def test_default_backbone_folds_callers_but_context_toggle_retains_them(con):
    report = architecture.build(con, 'Load')
    main = assemble(report)
    expanded = assemble(report, include_context=True)
    assert not any(n['name']=='Caller' for n in main['nodes'])
    assert any(n['name']=='Caller' for n in expanded['nodes'])
    assert any(n['name']=='BusinessChild' for n in main['nodes'])
    assert not main['statistics']['truncated']
    assert main['statistics']['folded']['context'] > 0


def test_cube_entry_preserves_writers_and_only_entry_rule_group(con):
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')")
    con.execute("UPDATE cubes SET rules='[]=1;',has_rules=true WHERE name='Cube_B'")
    report = architecture.build(con,'Cube_B',entry_kind='cube')
    flow = assemble(report)
    assert any(n['name']=='Load' and n['kind']=='process' for n in flow['nodes'])
    assert {n['name'] for n in flow['nodes'] if n['kind']=='rule'}=={'Cube_B'}
    assert any(n['selected_entry'] and n['name']=='Cube_B' for n in flow['nodes'])


def test_compact_index_projection_and_exports_without_source_duplication(con,tmp_path):
    report = architecture.build(con,'Load')
    artifact = architecture.artifact(report,tmp_path)
    try:
        flow = from_artifact(artifact.path)
        assert flow==assemble(report)
        md = ''.join(markdown(flow))
        assert '```mermaid' in md and '<details>' in md and '关键切面' in md
        assert '}bedrock.' not in md and 'UNKNOWN' not in md.split('<details>')[0]
        data = json.dumps(flow)
        assert 'expression_ir' not in data and 'source_code' not in data
        assert flow['context_document']=='Architecture.json'
        assert mermaid(flow).startswith('flowchart LR')
    finally:
        artifact.cleanup()


def test_mermaid_and_markdown_escape_untrusted_names():
    flow = dict(entry={'name':'<script>|title'},note='static',statistics={'truncated':False},
                nodes=[dict(id='a',title='Bad" ] --> x["<script>\n```',role='源数据',summary='safe')],edges=[],evidence=[],limitations=[])
    diagram = mermaid(flow)
    assert '<script>' not in diagram and '-->' not in diagram and '```' not in diagram
    assert '<script>' not in ''.join(markdown(flow))


def test_old_empty_projection_compatible():
    flow = assemble({})
    assert flow['nodes']==flow['edges']==[]
    assert not flow['statistics']['truncated']


def test_flow_api_exports_and_existing_views(client):
    response = client.post('/api/architecture/tasks',json={'process':'Load_Sales'})
    assert response.status_code==202
    task = response.json()['task_id']
    deadline = time.monotonic()+12
    while True:
        status = client.get('/api/architecture/tasks/'+task).json()
        if status['status'] not in {'queued','running'}: break
        assert time.monotonic()<deadline
        time.sleep(.02)
    assert status['status']=='completed', status
    base = '/api/architecture/tasks/'+task
    flow = client.get(base+'/functional-flow').json()
    assert flow['schema']=='functional-flow-1' and flow['nodes']
    for fmt, marker in [('flow-json','functional-flow-1'),('flow-markdown','业务流程图'),('mermaid','flowchart LR')]:
        r=client.get(base+'/export',params={'format':fmt})
        assert r.status_code==200 and marker in r.text
    assert client.get(base+'/functional-flow?max_nodes=10000').status_code==422
    assert client.get(base+'/result?view=cubes').status_code==200
    assert client.get(base+'/export?format=json').json()['version']=='architecture-1'
    assert client.get('/api/architecture/tasks/not-a-task/functional-flow').status_code==404


def test_entry_links_prefix_discovery_and_local_assets(client):
    page = client.get('/architecture?kind=discover&name=BP&view=functional_flow')
    assert page.status_code==200
    assert 'data-view="functional_flow"' in page.text and '按名称 / 前缀找入口' in page.text
    for path in ['/explorer/process/Load_Sales','/explorer/cube/Sales']:
        response = client.get(path)
        assert response.status_code==200 and 'view=functional_flow' in response.text
    for path in ['/static/functional-flow.js','/static/functional-flow.css']:
        assert client.get(path).status_code==200
    js = client.get('/static/functional-flow.js').text
    assert 'innerHTML' not in js and 'https://' not in js
