"""Typed projection over existing evidence, not a new parser or lineage closure."""
import copy
import io
import json
import time
import zipfile

import pytest
from tm1_insight import architecture
from tm1_insight.unified_relations import Projection, enrich, json_export
from test_architecture import con, fixture  # noqa: F401
from test_datasource_api import client  # noqa: F401


def edges(report, kind):
    return [r for r in report['unified_relations'] if r['relation_kind']==kind]


def test_relation_identity_separates_kind_mechanism_and_status_and_unions_proof():
    p = Projection()
    a, b = p.object('cube','A'), p.object('cube','B')
    e1 = p.evidence(dict(process='P', section='data', line=1, column=1))
    e2 = p.evidence(dict(process='P', section='data', line=2, column=1))
    assert p.evidence(dict(process='P', section='data', line=1, column=1)) == e1
    first = p.edge(a,b,'CANDIDATE_FORMATION','CO_OBSERVED_ACCESS',[e1],status='CANDIDATE')
    assert p.edge(a,b,'CANDIDATE_FORMATION','CO_OBSERVED_ACCESS',[e2,e1],status='CANDIDATE') == first
    assert p.relations[first]['evidence'] == sorted([e1,e2])
    assert p.edge(a,b,'STATIC_VALUE_DEPENDENCY','EXPRESSION',[e1]) != first
    assert p.edge(a,b,'CANDIDATE_FORMATION','OTHER',[e1],status='CANDIDATE') != first
    assert p.edge(a,b,'CANDIDATE_FORMATION','CO_OBSERVED_ACCESS',[e1],status='UNKNOWN') != first


def test_no_evidence_never_gets_confirmed_status():
    p=Projection();a=p.object('process','P');b=p.object('cube','A')
    rid=p.edge(a,b,'CUBE_WRITE','OBSERVATION',[])
    assert p.relations[rid]['status']=='UNKNOWN'
    assert 'EVIDENCE_MISSING' in p.relations[rid]['unresolved_reasons']


def test_read_write_direction_and_co_read_is_only_candidate(con):
    con.execute("UPDATE processes SET data=? WHERE name='Load'",["n=CellGetN('Cube_A',vYear,vProduct);CellPutN(10,'Cube_B',vYear,pRegion,pMeasure);"])
    report=architecture.build(con,'Load')
    assert any(r['source_name']=='Cube_A' and r['target_name']=='Load' for r in edges(report,'CUBE_READ'))
    assert any(r['source_name']=='Load' and r['target_name']=='Cube_B' for r in edges(report,'CUBE_WRITE'))
    assert not edges(report,'STATIC_VALUE_DEPENDENCY')
    candidate=next(r for r in edges(report,'CANDIDATE_FORMATION') if r['source_name']=='Cube_A')
    assert candidate['status']=='CANDIDATE' and candidate['semantic_status']=='UNCONFIRMED'


def test_supported_value_dependency_retains_worksheet_status(con):
    report=architecture.build(con,'Load')
    value=edges(report,'STATIC_VALUE_DEPENDENCY')
    assert value and any(r['status']=='STATIC_DEPENDENCY_CONFIRMED' for r in value)
    assert all(not r['runtime_verified'] for r in value)


def test_direct_indirect_and_cycle_reuse(con):
    con.execute("INSERT INTO processes(name,prolog) VALUES ('Deep','ExecuteProcess(''Load'');')")
    con.execute("UPDATE processes SET prolog='ExecuteProcess(''Deep'');' WHERE name='BusinessChild'")
    report=architecture.build(con,'Load')
    direct=edges(report,'PROCESS_CALL')
    indirect=edges(report,'EXECUTION_REACHABILITY')
    assert any(r['source_name']=='BusinessChild' and r['target_name']=='Deep' and r['directness']=='DIRECT' for r in direct)
    assert any(r['source_name']=='Load' and r['target_name']=='Deep' and r['directness']=='INDIRECT' for r in indirect)
    assert report['unified_model']['cycles']==report['cycles'] and report['cycles']
    assert len(indirect)<10
    assert any(r['source_name']=='Nightly' and r['target_name']=='Caller' for r in edges(report,'CHORE_SCHEDULE'))


def test_rule_reference_identity_direction_dynamic_coordinates_and_feeder(con):
    code="['Member1']=N:IF(1=1,DB('Cube_A',!Year,dynamicMember),DB(dynamicCube,!Year));\nFEEDERS;['Member1']=>DB('Cube_A',!Year,'Member1'),DB('Journal',!Year);"
    con.execute("UPDATE cubes SET rules=?,has_rules=true WHERE name='Cube_B'",[code])
    report=architecture.build(con,'Load')
    objects={o['id']:o for o in report['relation_objects']}
    reads=edges(report,'RULE_DB_REFERENCE')
    good=next(r for r in reads if r['source_name']=='Cube_A')
    assert good['source_type']=='cube' and good['target_type']=='rule'
    assert good['status']=='SOURCE_CONFIRMED' and good['semantic_status']=='PARTIAL'
    assert any('DB_COORDINATE_DYNAMIC' in reason for reason in good['unresolved_reasons'])
    assert any(r['status']=='UNKNOWN' and r['source_type']=='unresolved' for r in reads)
    assert all(r['source_type']=='rule' and r['target_name']=='Cube_B' for r in edges(report,'RULE_TARGET'))
    targets=edges(report,'FEEDER_DB_REFERENCE')
    assert {r['target_name'] for r in targets}=={'Cube_A','Journal'}
    assert all(r['source_type']=='feeder' for r in targets)
    assert all(objects[r['source']]['rule_association']=='OWNER_CUBE_ONLY' for r in targets)
    assert edges(report,'FEEDER_OWNER')[0]['semantic_status']=='UNKNOWN'


def test_structure_order_write_coordinates_and_source_context_refs(con):
    report=architecture.build(con,'Load')
    dims=[r for r in edges(report,'CUBE_DIMENSION') if r['source_name']=='Cube_B']
    assert [(r['qualifier'],r['target_name']) for r in sorted(dims,key=lambda r:r['qualifier'])]==[(0,'Year'),(1,'Region'),(2,'Measure')]
    assert edges(report,'TI_WRITE_SLICE')
    for r in edges(report,'TI_WRITE_SLICE'):
        pointer=r['context_refs'][0].split('/')
        w=report[pointer[1]][int(pointer[2])]
        assert w['target_coordinates']
        assert r['semantic_status']=='PARTIAL'
        assert any(c['kind']!='FIXED_MEMBER' for c in w['target_coordinates'])


def test_deterministic_sort_no_tree_or_raw_code_on_relationships(con):
    report=architecture.build(con,'Load')
    again=architecture.build(con,'Load')
    for key in ('unified_relations','relation_objects','relation_evidence','unified_model'):
        assert report[key]==again[key]
    assert len({r['id'] for r in report['unified_relations']})==len(report['unified_relations'])
    facts={f['id'] for f in report['relation_evidence']}
    assert all(set(r['evidence'])<=facts and r['evidence'] for r in report['unified_relations'])
    assert all(not any(k in r for k in ('raw','expression_ir','source_code','password','token')) for r in report['unified_relations'])


def test_old_projection_without_optional_rule_ir_still_works():
    report={}
    enrich(report)
    assert report['unified_relations']==[] and report['relation_objects']==[]
    assert report['unified_model']['schema']=='calculation-relations-1'


def test_exports_keep_referenced_contexts_once_and_fold_helpers(con,tmp_path):
    report=architecture.build(con,'Load')
    artifact=architecture.artifact(report,tmp_path)
    try:
        projected=json.loads(''.join(json_export(artifact.path)))
        assert projected['relations']==report['unified_relations']
        assert projected['objects']==report['relation_objects']
        assert projected['context_document']=='Architecture.json'
        text=''.join(architecture.markdown(artifact.path))
        assert '}bedrock.synthetic.clear' not in text
        assert '统一计算关系与证据' in text and 'CANDIDATE_FORMATION' in text
        from tm1_insight.architecture_extraction import package
        with zipfile.ZipFile(io.BytesIO(b''.join(package(artifact.path)))) as z:
            assert json.loads(z.read('UnifiedRelations.json'))==projected
            assert json.loads(z.read('Architecture.json'))['unified_relations']==projected['relations']
    finally:artifact.cleanup()


def test_new_api_paging_filters_evidence_and_context_on_existing_workbench(client,monkeypatch):
    from tm1_insight.api.app import _store
    client.get('/')
    c=_store().connect();fixture(c)
    c.execute("UPDATE cubes SET rules='[]=DB(''Cube_A'',!Year,''Member1'');',has_rules=true WHERE name='Cube_B'");c.close()
    task=client.post('/api/architecture/tasks',json={'process':'Load'}).json()['task_id']
    base='/api/architecture/tasks/'+task
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        s=client.get(base).json()
        if s['status'] not in ('queued','running'):break
        time.sleep(.01)
    assert s['status']=='completed',s
    small=client.get(base+'/result?view=relation_objects&limit=1')
    assert small.status_code==200 and len(small.content)<20000
    assert len(small.json()['items'])==1 and 'header' in small.json()
    items=client.get(base+'/result',params={'view':'unified_relations','relation_group':'rule'}).json()['items']
    assert items and all(r['relation_kind'].startswith('RULE_') for r in items)
    assert client.get(base+'/relation-fact',params={'id':items[0]['evidence'][0]}).status_code==200
    ref=items[0]['context_refs'][0]
    context=client.get(base+'/relation-context',params={'ref':ref}).json()
    assert context['rhs']['expression_ir']
    assert client.get(base+'/relation-context',params={'ref':'/details/secret'}).status_code==422
    assert client.get(base+'/export?format=relations').json()['schema']=='calculation-relations-1'
    page=client.get('/architecture').text
    assert '关系与计算' in page and '当前运行版本与模型' in page and f'架构 r{architecture.REVISION}' in page
    summaries=client.get(base+'/result?view=rule_summaries').json()['items']
    assert summaries and all('rule_semantics' not in r for r in summaries)
    assert client.get(base+'/relation-context',params={'ref':'/rules/99999/rule_semantics/0'}).status_code==404
    default=client.get(base+'/result',params={'view':'unified_relations'}).json()
    assert all(not r['technical'] and r['status']!='UNKNOWN' for r in default['items'])
    search=client.get(base+'/result',params={'view':'unified_relations','q':'Cube_A'}).json()
    assert search['total']>0
    consumers=client.get(base+'/result?view=downstream_consumers&confirmed_only=true').json()
    assert all(c['status']=='SOURCE_CONFIRMED' for c in consumers['items'])


def test_business_backbone_is_evidence_based_and_compact(con):
    report=architecture.build(con,'Load')
    step=next(s for s in report['business_steps'] if s['process']=='Load')
    assert step['primary_inputs']==['Cube_A']
    assert step['write_sites']==2 and step['modes']=={'OVERWRITE':2}
    assert step['helper_calls']==1
    assert report['workflow_spec']['purpose_status']=='HUMAN_CONFIRMATION_REQUIRED'
    assert not any(s['process'].startswith('}') for s in report['business_steps'])
    assert all('writes' not in s and 'expression_ir' not in s for s in report['business_steps'])
    proof={e['id'] for e in report['relation_evidence']}
    assert set(step['evidence'])<=proof


def test_projection_budget_and_cooperative_cancel(con,monkeypatch):
    import tm1_insight.unified_relations as module
    report=architecture.build(con,'Load')
    monkeypatch.setattr(module,'MAX_RELATIONS',2)
    enrich(report)
    assert report['unified_model']['truncated'] and len(report['unified_relations'])==2
    from tm1_insight.tasks import TaskCancelled
    def cancel(**kwargs):raise TaskCancelled()
    with pytest.raises(TaskCancelled):enrich(report,cancel)


def test_old_artifact_without_projection_remains_readable(con,tmp_path):
    from tm1_insight import workflow
    report=architecture.build(con,'Load')
    from tm1_insight.unified_relations import SECTIONS
    for key in SECTIONS|{'unified_model','workflow_spec'}:report.pop(key,None)
    old=workflow.artifact(report,tmp_path,sections=architecture.SECTIONS-SECTIONS)
    try:
        assert ''.join(architecture.markdown(old.path))
        assert json.loads(''.join(json_export(old.path)))['relations']==[]
    finally:old.cleanup()


def test_real_allocation_driver_end_to_end_read_only(tmp_path):
    from pathlib import Path
    import duckdb
    db=Path(__file__).resolve().parents[1]/'collections/model-rytp0epv/db/tm1_insight.duckdb'
    if not db.exists():pytest.skip('Local collection unavailable')
    con=duckdb.connect(str(db),read_only=True)
    try:
        report=architecture.build(con,'Allocation Driver BP',entry_kind='cube',max_processes=30,max_depth=6)
    finally:con.close()
    assert len({r['source_name'] for r in edges(report,'TI_WRITE_SLICE') if r['target_name']=='Allocation Driver BP'})==7
    assert any(r['target_name']=='Allocation Driver BP' for r in edges(report,'RULE_TARGET'))
    assert any(r['target_type']=='rule' for r in edges(report,'RULE_DB_REFERENCE'))
    assert edges(report,'PROCESS_CALL')
    # No schedule must be invented when this real scoped result has none.
    assert len(edges(report,'CHORE_SCHEDULE'))==len(report['chores'])
    artifact=architecture.artifact(report,tmp_path)
    try:
        exported=json.loads(''.join(json_export(artifact.path)))
        assert exported['statistics']['objects']>0
        assert 'Allocation Driver BP' in ''.join(architecture.markdown(artifact.path))
    finally:artifact.cleanup()
