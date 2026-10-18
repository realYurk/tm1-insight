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
    con.execute('INSERT INTO chores (name, processes, process_count) VALUES (?,?,?)',['Nightly',json.dumps(['Caller']),1])
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
    assert not report['rules']
    assert report['downstream_consumers'][0]['cube']=='RuleOutput'
    rule=architecture.build(con,'Load',include_downstream=True)['rules'][0]
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
    assert client.get(base+'/export?format=evidence').json()['items']==report['evidence']
    assert client.get(base+'/export?format=diagnostics').json()['items']==report['diagnostics']
    import io,zipfile
    with zipfile.ZipFile(io.BytesIO(client.get(base+'/export?format=zip').content)) as z:
        assert json.loads(z.read('Architecture.json'))==report
    assert len({e['stable_id'] for e in report['evidence']})==len(report['evidence'])
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


def test_boundary_shared_helper_never_pulls_maintenance_or_consumers(con,tmp_path):
    con.execute("UPDATE processes SET prolog=prolog||? WHERE name='}bedrock.synthetic.clear'",["ExecuteProcess('UtilityInternal');"])
    con.execute("INSERT INTO processes(name,prolog) VALUES ('UtilityInternal', 'LogOutput(''INFO'',''x'');')")
    con.execute("INSERT INTO chore_runs_process VALUES ('UnrelatedMaintenance','}bedrock.synthetic.clear',0)")
    con.execute("INSERT INTO chore_runs_process VALUES ('UtilityMaintenance','UtilityInternal',0)")
    report=architecture.build(con,'Load')
    assert not any(p['process']=='UtilityInternal' for p in report['processes'])
    assert any(e['target']=='UtilityInternal' for e in report['execution_relationships'])
    assert not any(c['name']=='UnrelatedMaintenance' for c in report['chores'])
    assert not report['rules']
    assert any(d['cube']=='RuleOutput' for d in report['downstream_consumers'])
    expanded=architecture.build(con,'Load',include_technical_details=True,include_downstream=True)
    assert any(p['process']=='UtilityInternal' and p['module_role']=='TECHNICAL_SUPPORT' for p in expanded['processes'])
    assert expanded['rules'][0]['module_role']=='EXTERNAL_DEPENDENCY'
    assert not any(c['name']=='UtilityMaintenance' for c in expanded['chores'])
    artifact=architecture.artifact(report,tmp_path)
    try:
        text=''.join(architecture.markdown(artifact.path))
        assert 'UnrelatedMaintenance' not in text and 'source_hash' not in text and 'rule_read' not in text
    finally:artifact.cleanup()


def test_view_alias_chain_with_unrelated_control_and_reassignment(con):
    code="c='Cube_A';IF(flag=1);LogOutput('INFO','x');ENDIF;DataSourceType='VIEW';DataSourceNameForServer=c;DataSourceCubeView='V';"
    con.execute("UPDATE processes SET prolog=? WHERE name='Load'",[code])
    r=architecture.build(con,'Load');s=r['transformation_summaries'][0]
    assert s['source_slice']['cube']=='Cube_A' and s['source_slice']['view']=='V'
    assert len(s['source_slice']['evidence'])==4
    for suffix in ["c='Cube_B';", "IF(flag=1);c='Cube_B';ENDIF;", "c=UnknownFunction();"]:
        con.execute("UPDATE processes SET prolog=? WHERE name='Load'",[code+suffix])
        assert architecture.build(con,'Load')['transformation_summaries'][0]['source_slice'] is None


def test_summary_keeps_write_contexts_and_does_not_join_observations(con,tmp_path):
    con.execute("UPDATE processes SET data=? WHERE name='Load'",["n=CellGetN('Cube_A',vYear,vProduct);CellPutN(10,'Cube_B',vYear,pRegion,pMeasure);IF(n>0);CellPutN(n*3,'Cube_B',vYear,pRegion,pMeasure);ENDIF;"])
    r=architecture.build(con,'Load');s=r['transformation_summaries'][0]
    assert len(s['calculation_summary'])==2
    assert not s['calculation_summary'][0]['source_cubes']
    assert s['calculation_summary'][1]['condition'] and s['calculation_summary'][1]['expression'] is None
    assert all('Journal' not in c['source_cubes'] for c in s['calculation_summary'])
    d=next(d for d in r['dimension_comparisons'] if d['source']=='Cube_A')
    assert d['shared']==['Year'] and d['source_only']==['Product'] and d['target_only']==['Region','Measure']
    assert d['mapping_status']=='UNCONFIRMED'
    a=architecture.artifact(r,tmp_path)
    try:
        import zipfile,io
        from tm1_insight.architecture_extraction import package
        with zipfile.ZipFile(io.BytesIO(b''.join(package(a.path)))) as z:
            assert set(z.namelist())=={'Architecture.md','Architecture.json','Evidence.json','Diagnostics.json','UnifiedRelations.json'}
            assert json.loads(z.read('Evidence.json'))['items']==r['evidence']
            assert json.loads(z.read('Architecture.json'))==r
            assert len(z.read('Architecture.md'))<len(z.read('Architecture.json'))
    finally:a.cleanup()


def test_rule_aggregation_retains_all_evidence(con,tmp_path):
    rule="['Member1']=N:DB('Cube_A',!Year,'Member1');\n"*600+"FEEDERS;['Member1']=>DB('Cube_A',!Year,'Member1');"
    con.execute("UPDATE cubes SET rules=?,has_rules=true WHERE name='Cube_B'",[rule])
    r=architecture.build(con,'Load');groups=r['rules'][0]['groups']
    assert [(g['kind'],g['count']) for g in groups]==[('rule_read',600),('feeder_reference',1)]
    assert len(groups[0]['evidence_refs'])==600
    a=architecture.artifact(r,tmp_path)
    try:
        md=''.join(architecture.markdown(a.path))
        assert '600 处' in md and len(md.splitlines())<120
        assert 'e1' not in md and 'source_hash' not in md
    finally:a.cleanup()


def test_expansion_controls_and_node_budget(con):
    r=architecture.build(con,'Load',max_nodes=1)
    assert len(r['processes'])==1 and not r['cubes'] and not r['dimensions']
    assert any('预算' in u['message'] for u in r['unresolved_dependencies'])
    r=architecture.build(con,'Load',allowed_relationship_types=[])
    assert len(r['processes'])==1 and not r['cubes'] and not r['rules'] and not r['chores']
    with pytest.raises(ValueError):architecture.build(con,'Load',allowed_relationship_types=['nonsense'])


def test_view_final_type_after_null_guard_is_conditional_static_binding(con):
    prolog="c='Cube_A';IF(flag=1);DataSourceType='NULL';ENDIF;DataSourceType='VIEW';DataSourceNameForServer=c;"
    con.execute("UPDATE processes SET prolog=? WHERE name='Load'",[prolog])
    binding=architecture.build(con,'Load')['transformation_summaries'][0]['source_slice']
    assert binding['cube']=='Cube_A' and '提前退出' in binding['note']
    con.execute("UPDATE processes SET prolog=? WHERE name='Load'",[prolog+"IF(flag=2);DataSourceType='NULL';ENDIF;"])
    assert architecture.build(con,'Load')['transformation_summaries'][0]['source_slice'] is None
