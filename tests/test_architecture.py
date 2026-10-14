import hashlib
import json
import time
import threading
import duckdb
import pytest
from tm1_insight import architecture,workflow
from tm1_insight.store.schema import ALL_TABLES
from tm1_insight.tasks import TaskCancelled
from test_datasource_api import client  # noqa: F401


def fixture(con):
    dims=['Year','Product','Region','Measure']
    for dim in dims:
        elements=[dict(name='Member'+str(i),type='N') for i in range(120)]
        con.execute('INSERT OR REPLACE INTO dimensions(name,element_count,elements,attributes,edges,subsets) VALUES (?,?,?,?,?,?)',
            [dim,120,json.dumps(elements),json.dumps([dict(name='Map',type='S')]),json.dumps([dict(parent='Total',component='Member1',weight=.5)]),'[]'])
    for name,order in [('Cube_A',['Year','Product']),('Cube_B',['Year','Region','Measure']),('Journal',['Year']),('RuleOutput',['Year'])]:
        rules="['Member1']=N:DB('Cube_B',!Year,'Member1','Member1');\nFEEDERS;['Member1']=>DB('Cube_B',!Year,'Member1','Member1');" if name=='RuleOutput' else ''
        con.execute('INSERT INTO cubes VALUES (?,?,?,?,?)',[name,json.dumps(order),rules,bool(rules),len(order)])
        for i,d in enumerate(order):con.execute('INSERT INTO cube_has_dimension VALUES (?,?,?)',[name,d,i])
    prolog="""DataSourceType='VIEW';DataSourceNameForServer='Cube_A';
ViewCreate('Cube_A','SourceView');SubsetCreate('Product','Picked');
SubsetElementInsert('Product','Picked','Member1',1);ViewSubsetAssign('Cube_A','SourceView','Product','Picked');
ExecuteProcess('}bedrock.synthetic.clear','pCube','Cube_B','pView','TargetView');
ExecuteProcess('BusinessChild');ExecuteProcess(pDynamic);
#Region - Initialize Logging
CellPutN(1,'Journal',vYear);dummy=CellGetN('Journal',vYear);
#EndRegion - Initialize Logging
"""
    data="n=CellGetN('Cube_A',vYear,vProduct);result=n*2;CellPutN(result,'Cube_B',vYear,pRegion,pMeasure);mapped=AttrS('Product',vProduct,'Map');CellPutN(result,'Cube_B',vYear,mapped,pMeasure);"
    params=json.dumps([dict(Name=n) for n in ['vYear','vProduct','pRegion','pMeasure','pDynamic']])
    for name,p,d,ps in [('Load',prolog,data,params),('Caller',"ExecuteProcess('Load');",'',params),
                        ('BusinessChild',"ExecuteProcess('Load');",'',params),
                        ('}bedrock.synthetic.clear',"ViewZeroOut(pCube,pView);",'',json.dumps([dict(Name='pCube'),dict(Name='pView')]))]:
        con.execute('INSERT INTO processes(name,prolog,metadata,data,epilog,parameters) VALUES (?,?,?,?,?,?)',[name,p,'',d,'',ps])
    con.execute("INSERT INTO process_calls_process VALUES ('Caller','Load')")
    con.execute("INSERT INTO chore_runs_process VALUES ('Nightly','Caller',0)")
    con.execute('INSERT INTO chores VALUES (?,?,?)',['Nightly',json.dumps(['Caller']),1])
    con.execute("INSERT INTO rule_references_cube VALUES ('RuleOutput','Cube_B')")


@pytest.fixture
def con():
    c=duckdb.connect(':memory:')
    for sql in ALL_TABLES.values():c.execute(sql)
    fixture(c);yield c;c.close()


def test_architecture_model_processing_schedule_and_evidence(con,tmp_path):
    report=architecture.build(con,'Load')
    assert report['version']=='architecture-1'
    step=next(s for s in report['transformation_steps'] if s['process']=='Load')
    assert step['inputs']==['Cube_A'] and step['outputs']==['Cube_B']
    clear=next(e for e in step['effects'] if e.get('via'))
    assert clear['category']=='CLEAR' and clear['target']=='Cube_B' and len(clear['evidence'])==2
    assert any(e['category']=='VIEW_PREPARATION' for e in step['effects'])
    assert any(e['category']=='SUBSET_PREPARATION' for e in step['effects'])
    assert step['calculations'] and all('UNKNOWN' not in c['expression'] for c in step['calculations'])
    assert all('Journal' not in c['expression'] for c in step['calculations'])
    assert step['calculation_note']
    cubes={c['name']:c for c in report['cubes']}
    assert [d['name'] for d in cubes['Cube_A']['dimensions']]==['Year','Product']
    assert [d['name'] for d in cubes['Cube_B']['dimensions']]==['Year','Region','Measure']
    assert cubes['Cube_B']['upstream']==['Cube_A']
    assert cubes['Journal']['technical'] and 'Journal' not in report['input_outputs']['inputs']
    assert any(p['process']=='BusinessChild' for p in report['processes'])
    assert any(c['name']=='Nightly' and c['target']=='Caller' for c in report['chores'])
    assert any(e['process']=='Caller' and e['target']=='Load' for e in report['execution_relationships'])
    rule=report['rules'][0]
    assert rule['cube']=='RuleOutput' and {r['kind'] for r in rule['references']}=={'rule_read','feeder_reference'}
    ids={e['id'] for e in report['evidence']}
    for relationship in report['data_relationships']+report['execution_relationships']:
        assert relationship['evidence'] and set(relationship['evidence'])<=ids
    assert report['cycles'] and report['unresolved_dependencies'] and not report['runtime_verified']
    assert report==architecture.build(con,'Load')
    first=architecture.artifact(report,tmp_path);second=architecture.artifact(architecture.build(con,'Load'),tmp_path)
    try:assert first.path.read_bytes()==second.path.read_bytes()
    finally:first.cleanup();second.cleanup()


def test_core_helper_read_write_effects_survive_folding(con):
    con.execute("UPDATE processes SET data='',prolog=? WHERE name='Load'",["ExecuteProcess('}bedrock.synthetic.clear');"])
    con.execute('UPDATE processes SET prolog=? WHERE name=?',[
        "n=CellGetN('Cube_A',vYear,vProduct);CellPutN(n,'Cube_B',vYear,pRegion,pMeasure);",'}bedrock.synthetic.clear'])
    report=architecture.build(con,'Load')
    step=next(s for s in report['transformation_steps'] if s['process']=='Load')
    assert step['inputs']==['Cube_A'] and step['outputs']==['Cube_B']
    assert any(e['category']=='DATA_TRANSFORMATION' for e in step['effects'])
    assert not any(e['category']=='CLEAR' for e in step['effects'])


def test_architecture_source_queries_are_scoped(con):
    class Scoped:
        def execute(self,sql,args=None):
            if sql.startswith('SELECT prolog,metadata,data,epilog') or sql.startswith('SELECT rules FROM'):
                assert 'WHERE name=?' in sql
            return con.execute(sql,args) if args is not None else con.execute(sql)
    assert architecture.build(Scoped(),'Load')['cubes']


def test_helper_name_does_not_invent_clear_or_transfer(con):
    con.execute("UPDATE processes SET prolog='# Nothing implemented' WHERE name='}bedrock.synthetic.clear'")
    con.execute("UPDATE processes SET data='' WHERE name='Load'")
    report=architecture.build(con,'Load')
    step=next(s for s in report['transformation_steps'] if s['process']=='Load')
    assert not any(e['category']=='CLEAR' for e in step['effects'])
    assert not any(d['kind']=='static_value_dependency' for d in report['data_relationships'])
    assert not step['outputs'] and step['technical_calls']


def test_dynamic_helper_target_is_not_bound_and_scope_is_bounded(con):
    con.execute("UPDATE processes SET prolog=replace(prolog,'''pCube'',''Cube_B''','''pCube'',pDynamic') WHERE name='Load'")
    report=architecture.build(con,'Load')
    step=next(s for s in report['transformation_steps'] if s['process']=='Load')
    assert next(e for e in step['effects'] if e.get('via'))['target'] is None
    small=architecture.build(con,'Load',max_processes=1,max_depth=0)
    assert len(small['processes'])==1 and small['unresolved_dependencies']
    def cancel(**event):
        if event['stage']=='组装数据加工步骤':raise TaskCancelled()
    with pytest.raises(TaskCancelled):architecture.build(con,'Load',progress=cancel)


def test_helper_parameter_overwrite_invalidates_external_target_binding(con):
    con.execute('UPDATE processes SET prolog=? WHERE name=?',[
        'pCube=UnknownFunction();ViewZeroOut(pCube,pView);','}bedrock.synthetic.clear'])
    step=next(s for s in architecture.build(con,'Load')['transformation_steps'] if s['process']=='Load')
    assert next(e for e in step['effects'] if e.get('via'))['target'] is None


def test_unclosed_logging_marker_does_not_hide_unclassified_data_writes(con):
    con.execute("UPDATE processes SET prolog=replace(prolog,'#EndRegion - Initialize Logging','') WHERE name='Load'")
    report=architecture.build(con,'Load')
    journal=next(c for c in report['cubes'] if c['name']=='Journal')
    assert not journal['technical']


def test_architecture_api_export_lazy_dimensions_and_source_invalidation(client,monkeypatch):
    from tm1_insight.api.app import _store
    from tm1_insight.api import architecture as api
    from tm1_insight.config import get_settings
    client.get('/');c=_store().connect()
    try:fixture(c)
    finally:c.close()
    before=hashlib.sha256(get_settings().db_path.read_bytes()).hexdigest()
    started=client.post('/api/architecture/tasks',json={'process':'Load'})
    assert started.status_code==202
    task=started.json()['task_id'];base='/api/architecture/tasks/'+task
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=client.get(base).json()
        if state['status'] not in ['queued','running']:break
        time.sleep(.01)
    assert state['status']=='completed'
    monkeypatch.setattr(api.manager(),'result',lambda *a,**k:pytest.fail('Full report decoded for page'))
    report=client.get(base+'/export').json()
    assert architecture.SECTIONS<report.keys()
    assert all(k in report for k in ['module','entry_points','input_outputs','migration_notes'])
    assert client.get(base+'/result?view=cubes&limit=2').json()['total']>=3
    assert client.get(base+'/result?view=unavailable').status_code==422
    assert client.get(base+'/dimension?name=Product&page=2').json()['start']==51
    assert client.get(base+'/dimension?name=NotInScope').status_code==404
    assert client.get(base+'/implementation?process=Load').status_code==200
    assert client.get(base+'/evidence?process=Load&section=data').status_code==200
    assert client.get(base+'/fact?id='+report['evidence'][0]['id']).status_code==200
    assert client.get(base+'/export?format=markdown').status_code==200
    assert client.get('/architecture').status_code==200
    assert client.get('/codegen').status_code==200
    assert hashlib.sha256(get_settings().db_path.read_bytes()).hexdigest()==before
    c=_store().connect();c.execute("UPDATE processes SET epilog='# Changed' WHERE name='Load'");c.close()
    assert client.get(base+'/export').status_code==409
    assert client.post('/api/architecture/tasks',json={'process':'Missing'}).status_code==404


def test_architecture_api_cancel_is_cooperative(client,monkeypatch):
    from tm1_insight.api.app import _store
    client.get('/');c=_store().connect();fixture(c);c.close()
    entered=threading.Event();release=threading.Event();original=architecture.build
    def wait(*a,**k):
        entered.set();release.wait(3);return original(*a,**k)
    monkeypatch.setattr(architecture,'build',wait)
    task=client.post('/api/architecture/tasks',json={'process':'Load'}).json()['task_id']
    assert entered.wait(3)
    base='/api/architecture/tasks/'+task
    assert client.post(base+'/cancel').status_code==200
    release.set()
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        state=client.get(base).json()
        if state['status']=='cancelled':break
        time.sleep(.01)
    assert state['status']=='cancelled'
    assert client.get(base+'/export').status_code==409
