import hashlib
import json
import threading
import time

import duckdb
import pytest

from tm1_insight import workflow
from tm1_insight.store.schema import ALL_TABLES
from tm1_insight.tasks import TaskCancelled
from test_datasource_api import client  # noqa: F401


FORMULA="nA=CellGetN('Cube_A',vYear,vProduct);\nunused=CellGetN('Cube_D',vYear,vProduct);\nnB=CellGetN('Cube_B',vYear,vProduct);\nnC=nA*nB;\nCellPutN(nC,'Cube_C',vYear,vProduct);\nExecuteProcess('Step1');"


def fixture(con):
    for dim in ['Year','Product']:con.execute('INSERT OR IGNORE INTO dimensions (name) VALUES (?)',[dim])
    for cube in ['Cube_A','Cube_B','Cube_C','Cube_D']:
        con.execute('INSERT INTO cubes (name,dimension_count,dimensions) VALUES (?,2,?)',[cube,json.dumps(['Year','Product'])])
        con.executemany('INSERT INTO cube_has_dimension VALUES (?,?,?)',[(cube,'Year',0),(cube,'Product',1)])
    rows=[('Entry',"ExecuteProcess('Step1','pYear',pYear);If(pRun=1);ExecuteProcess('}bedrock.synthetic.wrapper');EndIf;ExecuteProcess(pDynamic);",''),
          ('Step1',"ExecuteProcess('Step2');",''),('Step2',"ExecuteProcess('Step3');",''),
          ('Step3',"ExecuteProcess('Compute');",''),('Compute','',FORMULA),
          ('}bedrock.synthetic.wrapper',"ExecuteProcess('Compute');",''),('IndexOnly',"ExecuteProcess('Entry');",'')]
    for name,prolog,data in rows:
        con.execute('INSERT INTO processes (name,prolog,metadata,data,epilog,parameters) VALUES (?,?,?,? ,?,?)',
            [name,prolog,'# Metadata source',data,'# Epilog source',json.dumps([dict(Name=n) for n in ['vYear','vProduct','pYear','pRun','pDynamic']])])
    con.execute("INSERT INTO process_calls_process VALUES ('Entry','IndexOnly')")
    con.execute("INSERT INTO process_calls_process VALUES ('IndexOnly','Entry')")


@pytest.fixture
def con():
    connection=duckdb.connect(':memory:')
    for sql in ALL_TABLES.values():connection.execute(sql)
    fixture(connection)
    yield connection
    connection.close()


def test_deep_execution_cycles_framework_and_no_index_invented_execution(con):
    report=workflow.build(con,'Entry')
    assert {p['process'] for p in report['processes']}=={'Entry','Step1','Step2','Step3','Compute','}bedrock.synthetic.wrapper'}
    assert report['cycles'] and not report['runtime_verified']
    assert any(e['target']=='}bedrock.synthetic.wrapper' and e['control_context'][0]['condition']=='( pRun = 1 )' for e in report['execution'])
    assert any(e['target'] is None and e['status']=='parameter' for e in report['execution'])
    assert not any(e['target']=='IndexOnly' for e in report['execution'])
    assert any(e['target']=='IndexOnly' and e['status']=='STRUCTURAL_UNVERIFIED' for e in report['structure'])
    assert report['callers'][0]['process']=='IndexOnly' and report['callers'][0]['status']=='STRUCTURAL_UNVERIFIED'
    binding=report['execution'][0]['bindings'][0]
    assert binding['parameter']=='pYear' and binding['binding_status']=='EXPLICIT_NAME_BINDING'
    assert [s['section'] for s in report['processes'][0]['sections']]==['prolog','metadata','data','epilog']


def test_value_dependencies_follow_assignments_not_shared_object_reads(con):
    report=workflow.build(con,'Compute')
    calc=next(c for c in report['calculation'] if c['process']=='Compute')
    assert calc['reconstructed']=='Cube_C[Year,Product] = (Cube_A[Year,Product] * Cube_B[Year,Product])'
    assert calc['shared_coordinate_binding'] and calc['status']=='STATIC_EXPRESSION'
    assert {d['source_cube'] for d in calc['value_dependencies']}=={'Cube_A','Cube_B'}
    assert any(d['target']=='Cube_D' and d['relation_kind']=='source_reference' for d in report['data'])
    assert all(d['source_cube']!='Cube_D' for c in report['calculation'] for d in c['value_dependencies'])
    for d in calc['value_dependencies']:
        assert d['read_evidence']['section']=='data' and d['read_evidence']['line'] in {1,3}
        assert d['write_evidence']['line']==5 and not d['runtime_verified']


def test_changed_coordinates_do_not_collapse_to_same_slice_formula(con):
    con.execute('UPDATE processes SET data=? WHERE name=?',[FORMULA.replace("'Cube_B',vYear,vProduct","'Cube_B',pYear,vProduct"),'Compute'])
    calc=workflow.build(con,'Compute')['calculation'][0]
    assert not calc['shared_coordinate_binding']
    assert 'Year=pYear' in calc['reconstructed'] and 'Year=vYear' in calc['reconstructed']


def test_reaching_constant_alias_expands_but_branch_loop_and_record_aliases_do_not(con):
    con.execute('UPDATE processes SET prolog=? WHERE name=?',["child='Step1';alias=child;ExecuteProcess(alias);",'Entry'])
    report=workflow.build(con,'Entry')
    assert report['execution'][0]['target']=='Step1'
    assert report['execution'][0]['target_resolution']=='reaching_constant_alias'
    for code in ["If(pRun=1);child='Step1';Else;child='Step2';EndIf;ExecuteProcess(child);",
                 "While(pRun=1);child='Step1';End;ExecuteProcess(child);"]:
        con.execute('UPDATE processes SET prolog=? WHERE name=?',[code,'Entry'])
        assert workflow.build(con,'Entry')['execution'][0]['target'] is None
    con.execute('UPDATE processes SET prolog=?,data=?,epilog=? WHERE name=?',
        ['',"child='Step1';","ExecuteProcess(child);",'Entry'])
    assert workflow.build(con,'Entry')['execution'][0]['target'] is None


def test_record_assignments_do_not_resolve_epilog_cube_or_unknown_call(con):
    con.execute('UPDATE processes SET prolog=?,data=?,epilog=? WHERE name=?',
        ['',"cube='Cube_A';child='Step1';","CellPutN(1,cube,vYear,vProduct);ExecuteProcess(child);",'Entry'])
    report=workflow.build(con,'Entry')
    assert report['execution'][0]['target'] is None
    assert any('调用目标未确认' in u['reason'] for u in report['unknowns'])
    data=next(d for d in report['data'] if d['process']=='Entry' and d['operation']=='CellPutN')
    assert data['target'] is None
    assert report['calculation'][0]['cube'] is None


@pytest.mark.parametrize('code',[
    "If(pRun=1);v=1;Else;v=2;EndIf;CellPutN(v,'Cube_C',vYear,vProduct);",
    "v=UnknownFunction(CellGetN('Cube_A',vYear,vProduct));CellPutN(v,'Cube_C',vYear,vProduct);",
    "While(pRun=1);v=v+1;End;CellPutN(v,'Cube_C',vYear,vProduct);",
])
def test_unknown_control_or_function_never_becomes_confirmed_formula(con,code):
    con.execute('UPDATE processes SET data=? WHERE name=?',[code,'Compute'])
    calc=workflow.build(con,'Compute')['calculation'][0]
    assert calc['status']=='PARTIAL' and 'UNKNOWN' in calc['reconstructed']
    assert not calc['value_dependencies']


def test_scope_limits_and_cancellation_are_explicit(con):
    limited=workflow.build(con,'Entry',max_depth=1)
    assert len(limited['processes'])==3
    assert any(e['expansion']=='BOUNDARY' for e in limited['execution'])
    assert limited['unknowns']
    limited=workflow.build(con,'Entry',max_processes=1)
    assert limited['summary']['parsed']==1
    def cancel(**event):
        if event['stage_index']==3:raise TaskCancelled()
    with pytest.raises(TaskCancelled):workflow.build(con,'Entry',progress=cancel)


def test_source_is_scoped_and_per_ti_cache_is_context_bound(con,tmp_path,monkeypatch):
    calls=[]
    class Scoped:
        def execute(self,sql,args=None):
            if 'SELECT prolog,metadata,data,epilog,parameters' in sql:
                assert 'WHERE name=?' in sql
                calls.append(args[0])
            return con.execute(sql,args) if args is not None else con.execute(sql)
    first=workflow.build(Scoped(),'Entry',cache_root=tmp_path,cache_source='snapshot-A')
    assert 'IndexOnly' not in calls and len(calls)==first['summary']['parsed']
    original=workflow.inspect
    monkeypatch.setattr(workflow,'inspect',lambda *a,**k:pytest.fail('Repeated TI parse for same snapshot'))
    second=workflow.build(con,'Step1',cache_root=tmp_path,cache_source='snapshot-A')
    assert second['summary']['cache_hits']==second['summary']['parsed']
    monkeypatch.setattr(workflow,'inspect',original)
    changed=workflow.build(con,'Step1',cache_root=tmp_path,cache_source='snapshot-B')
    assert changed['summary']['cache_hits']==0


def seed_client(client):
    from tm1_insight.api.app import _store
    client.get('/')
    con=_store().connect()
    try:fixture(con)
    finally:con.close()


def await_task(client,task):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=client.get('/api/workflow/tasks/'+task).json()
        if state['status'] not in {'queued','running'}:return state
        time.sleep(.01)
    pytest.fail('Workflow job did not finish')


def test_workspace_api_evidence_exports_source_safety_and_paging(client,monkeypatch):
    from tm1_insight.api import workflow as api
    from tm1_insight.config import get_settings
    seed_client(client)
    before=hashlib.sha256(get_settings().db_path.read_bytes()).hexdigest()
    started=client.post('/api/workflow/tasks',json={'process':'Entry'})
    assert started.status_code==202
    task=started.json()['task_id'];assert await_task(client,task)['status']=='completed'
    monkeypatch.setattr(api.manager(),'result',lambda *a,**k:pytest.fail('Decoded whole report for workspace page'))
    response=client.get(f'/api/workflow/tasks/{task}/result',params=dict(view='processes',limit=2,offset=2))
    assert response.status_code==200 and len(response.json()['items'])==2 and response.json()['total']==6
    calculations=client.get(f'/api/workflow/tasks/{task}/result',params={'view':'calculation'}).json()['items']
    assert calculations[0]['reconstructed'].startswith('Cube_C[Year,Product]')
    evidence=client.get(f'/api/workflow/tasks/{task}/evidence',params=dict(process='Compute',section='data',start=3,limit=2))
    assert evidence.status_code==200 and evidence.json()['lines'][0]['line']==3
    assert evidence.json()['lines'][0]['code']=="nB=CellGetN('Cube_B',vYear,vProduct);"
    assert client.get(f'/api/workflow/tasks/{task}/evidence',params=dict(process='IndexOnly')).status_code==404
    package=client.get(f'/api/workflow/tasks/{task}/export')
    assert package.status_code==200 and package.headers['cache-control']=='no-store'
    assert package.json()['version']=='workflow-1'
    md=client.get(f'/api/workflow/tasks/{task}/export?format=markdown')
    assert md.status_code==200 and 'STATIC_EXPRESSION_DEPENDENCY' in md.text
    assert 'STRUCTURAL_UNVERIFIED' in md.text and 'Cube_D' in md.text
    again=client.post('/api/workflow/tasks',json={'process':'Entry'}).json()['task_id']
    assert await_task(client,again)['cached']
    assert hashlib.sha256(get_settings().db_path.read_bytes()).hexdigest()==before
    assert client.get('/workflow').status_code==200
    assert client.post('/api/workflow/tasks',json={'process':'Missing'}).status_code==404
    assert client.post('/api/workflow/tasks',json={'process':'Entry','max_depth':65}).status_code==422
    assert client.post('/api/workflow/tasks',json={'process':'Entry','max_processes':True}).status_code==422


def test_workflow_cancel_and_stale_source(client,monkeypatch):
    from tm1_insight.api.app import _store
    seed_client(client)
    entered=threading.Event();release=threading.Event();original=workflow.inspect
    def slow(*args,**kwargs):
        entered.set();release.wait(3);return original(*args,**kwargs)
    monkeypatch.setattr(workflow,'inspect',slow)
    task=client.post('/api/workflow/tasks',json={'process':'Entry'}).json()['task_id']
    assert entered.wait(3)
    assert client.post(f'/api/workflow/tasks/{task}/cancel').status_code==200
    release.set();assert await_task(client,task)['status']=='cancelled'
    assert client.get(f'/api/workflow/tasks/{task}/result').status_code==409
    monkeypatch.setattr(workflow,'inspect',original)
    task=client.post('/api/workflow/tasks',json={'process':'Entry'}).json()['task_id']
    assert await_task(client,task)['status']=='completed'
    con=_store().connect();con.execute("UPDATE processes SET epilog='# changed' WHERE name='Entry'");con.close()
    assert client.get(f'/api/workflow/tasks/{task}/result').status_code==409
    assert client.get(f'/api/workflow/tasks/{task}/export').status_code==409


@pytest.mark.parametrize("change", ["unsupported_coordinate", "missing_dimension"])
def test_incomplete_coordinate_proof_keeps_formula_partial(con,change):
    if change=="unsupported_coordinate":
        con.execute('UPDATE processes SET data=? WHERE name=?',[FORMULA.replace("'Cube_B',vYear,vProduct", "'Cube_B',vYear+1,vProduct"),'Compute'])
    else:
        con.execute("DELETE FROM dimensions WHERE name='Year'")
    calc=workflow.build(con,'Compute')['calculation'][0]
    assert calc['status']=='PARTIAL'
    assert calc['reasons']


def test_export_preserves_partial_dependency_and_hides_raw_strings(con,tmp_path):
    code="secretNote='PRIVATE_CANARY_NEVER_EXPORT';n=CellGetN('Cube_A',vYear,vProduct);CellPutN(n,pDynamic,vYear,vProduct);"
    con.execute('UPDATE processes SET data=? WHERE name=?',[code,'Compute'])
    report=workflow.build(con,'Compute');report['source_fingerprint']='synthetic'
    dependency=report['calculation'][0]['value_dependencies'][0]
    assert dependency['status']=='PARTIAL_EXPRESSION_DEPENDENCY'
    artifact=workflow.artifact(report,tmp_path)
    try:
        md=''.join(workflow.markdown(artifact.path))
        assert 'PARTIAL_EXPRESSION_DEPENDENCY' in md
        assert 'STATIC_EXPRESSION_DEPENDENCY' not in md
        assert 'PRIVATE_CANARY_NEVER_EXPORT' not in md
        assert 'PRIVATE_CANARY_NEVER_EXPORT' not in json.dumps(report)
    finally:artifact.cleanup()
