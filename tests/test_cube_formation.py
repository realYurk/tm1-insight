"""Cube-centric formation contracts, including false-lineage and scope counterexamples."""
import json
import time
import hashlib
import duckdb
import pytest
from tm1_insight import architecture
from tm1_insight.store.calculation import inspect
from tm1_insight.store.schema import ALL_TABLES
from test_architecture import fixture
from test_datasource_api import client  # noqa: F401


@pytest.fixture
def con():
    c=duckdb.connect(':memory:')
    for ddl in ALL_TABLES.values():c.execute(ddl)
    fixture(c)
    c.execute('INSERT INTO dimensions(name,element_count,elements) VALUES (?,?,?)',['Scenario',2,json.dumps([dict(name='ACT',type='N'),dict(name='PLAN',type='N')])])
    for cube,dims in [('Cube_A',['Scenario','Product']),('Cube_B',['Product','Scenario'])]:
        c.execute('DELETE FROM cube_has_dimension WHERE cube_name=?',[cube])
        c.execute('UPDATE cubes SET dimension_count=?,dimensions=? WHERE name=?',[2,json.dumps(dims),cube])
        for i,d in enumerate(dims):c.execute('INSERT INTO cube_has_dimension VALUES (?,?,?)',[cube,d,i])
    params=json.dumps([dict(Name=n) for n in ['pProduct','pFlag','pCube','pYear']])
    c.execute("UPDATE processes SET prolog=?,data=?,parameters=? WHERE name='Load'",["cScenario='ACT';", "n=CellGetN('Cube_A',cScenario,pProduct);CellPutN(n*2,'Cube_B',pProduct,cScenario);",params])
    c.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')")
    yield c;c.close()


def test_cube_entry_static_expression_actual_order_fixed_member_and_evidence(con,tmp_path):
    r=architecture.build(con,'Cube_B',entry_kind='cube')
    assert r['module']['kind']=='cube_scope' and r['formation_version']=='cube-formation-1'
    x=next(x for x in r['write_explanations'] if x['process']=='Load')
    assert x['calculation']=="Cube_B[Product=pProduct,Scenario='ACT'] = (Cube_A[Scenario='ACT',Product=pProduct] * 2)"
    assert x['target_coordinates'][1]['kind']=='FIXED_MEMBER' and x['target_coordinates'][1]['value']=='ACT'
    assert x['target_coordinates'][0]['kind']=='PARAMETER' and x['mode']=='OVERWRITE'
    correspondence=next(c for c in x['coordinate_correspondences'] if c['source_dimension']=='Product')
    assert correspondence['target_dimension']=='Product' and correspondence['expression']=='pProduct'
    types={d['relation_type'] for d in r['formation_relationships']}
    assert {'CUBE_READ','CUBE_WRITE','STATIC_VALUE_DEPENDENCY','STRUCTURAL_RELATION','EXECUTION_CALL','CHORE_SCHEDULE'}<=types
    ids={e['id'] for e in r['evidence']}
    assert all(set(e['evidence_refs'])<=ids for e in r['formation_relationships'])
    assert all(set(c['evidence_refs'])<=ids for c in x['target_coordinates'])
    sample=next(d for d in r['dimensions'] if d['name']=='Product')['consolidation_sample']
    assert sample['items'][0]['weight_known'] and sample['items'][0]['weight']=='0.5'
    assert not r['runtime_verified'] and r==architecture.build(con,'Cube_B',entry_kind='cube')
    a=architecture.artifact(r,tmp_path)
    try:
        import io,zipfile
        from tm1_insight.architecture_extraction import package
        first=b''.join(package(a.path))
        assert first==b''.join(package(a.path))
        with zipfile.ZipFile(io.BytesIO(first)) as z:assert all(i.date_time==(1980,1,1,0,0,0) for i in z.infolist())
        md=''.join(architecture.markdown(a.path))
        assert '入口 Cube' in md and "Scenario = 'ACT'" in md and 'UNKNOWN[UNKNOWN]' not in md
    finally:a.cleanup()


def test_read_and_constant_write_do_not_make_value_flow(con):
    con.execute("UPDATE processes SET data=? WHERE name='Load'",["n=CellGetN('Cube_A',cScenario,pProduct);CellPutN(5,'Cube_B',pProduct,cScenario);"])
    r=architecture.build(con,'Cube_B',entry_kind='cube')
    assert not any(d['relation_type']=='STATIC_VALUE_DEPENDENCY' for d in r['formation_relationships'])
    assert not r['write_explanations'][0]['source_reads']
    read=r['transformation_summaries'][0]['observed_reads'][0]
    assert read['usage']=='READ_OBSERVATION_ONLY'
    assert r['dimension_comparisons'][0]['basis']=='STRUCTURE_ONLY_NOT_VALUE_MAPPING'


def test_dynamic_read_never_becomes_confirmed_architecture_source(con):
    con.execute("UPDATE processes SET data=? WHERE name='Load'", ["n=CellGetN(pCube,cScenario,pProduct);CellPutN(n,'Cube_B',pProduct,cScenario);"])
    r=architecture.build(con,'Cube_B',entry_kind='cube')
    write=next(x for x in r['write_explanations'] if x['process']=='Load')
    assert write['source_reads']==[]
    assert write['coordinate_correspondences']==[]
    assert not any(x['relation_type']=='STATIC_VALUE_DEPENDENCY' for x in r['formation_relationships'])
    assert write['location']['section']=='data' and not write['runtime_verified']


def test_view_binding_and_data_variable_are_distinct_from_value_dependency(con):
    con.execute("UPDATE processes SET prolog=?,data=? WHERE name='Load'",["cScenario='ACT';DataSourceType='VIEW';DataSourceNameForServer='Cube_A';DataSourceCubeView='SourceView';", "CellIncrementN(vValue,'Cube_B',pProduct,cScenario);"])
    r=architecture.build(con,'Cube_B',entry_kind='cube');x=r['write_explanations'][0]
    assert x['source_binding']['cube']=='Cube_A' and x['source_binding']['view']=='SourceView'
    assert x['data_row_binding']=='UNCONFIRMED' and x['calculation'] is None
    assert x['unknown_inputs'][0]['variable']=='vValue'
    assert x['mode']=='INCREMENT'
    assert not any(d['relation_type']=='STATIC_VALUE_DEPENDENCY' for d in r['formation_relationships'])
    assert any(d['relation_type']=='VIEW_DATASOURCE_BINDING' for d in r['formation_relationships'])


def test_conditional_formulas_and_dynamic_target_remain_separate(con):
    con.execute("UPDATE processes SET data=? WHERE name='Load'",["n=CellGetN('Cube_A',cScenario,pProduct);IF(pFlag=1);CellPutN(n*2,'Cube_B',pProduct,cScenario);ELSE;CellPutN(n*3,'Cube_B',pProduct,cScenario);ENDIF;CellPutN(n,pCube,pProduct,cScenario);"])
    r=architecture.build(con,'Cube_B',entry_kind='cube');writes=[w for w in r['write_explanations'] if w['process']=='Load']
    assert len(writes)==3 and '* 2' in writes[0]['calculation'] and '* 3' in writes[1]['calculation']
    assert writes[0]['conditions'][0]['branch']==0 and writes[1]['conditions'][0]['branch']==1
    assert writes[2]['cube'] is None and writes[2]['calculation'] is None
    assert any(d['relation_type']=='UNRESOLVED_RELATION' and d['target'] is None for d in r['formation_relationships'])
    value_edges=[d for d in r['formation_relationships'] if d['relation_type']=='STATIC_VALUE_DEPENDENCY' and d['target']=='Cube_B']
    assert all(d['conditions'] for d in value_edges)
    assert all(not w['runtime_verified'] for w in writes)


def test_unverified_member_and_sensitive_constant_never_leak(con):
    con.execute("UPDATE processes SET prolog=?,data=? WHERE name='Load'",["cScenario='synthetic-private';password='hidden-secret';", "CellPutN(1,'Cube_B',pProduct,cScenario);"])
    r=architecture.build(con,'Load');payload=json.dumps(r,ensure_ascii=False)
    assert 'synthetic-private' not in payload and 'hidden-secret' not in payload
    assert r['write_explanations'][0]['calculation'] is None
    assert r['write_explanations'][0]['target_coordinates'][1]['kind']=='UNRESOLVED'
    assert '_constant_values' not in payload


def test_helpers_fold_clear_prepare_write_cleanup_without_name_inference(con):
    code="ExecuteProcess('}bedrock.synthetic.clear','pCube','Cube_B','pView','V');"
    con.execute("UPDATE processes SET prolog=?,data='' WHERE name='Load'",[code])
    con.execute("UPDATE processes SET prolog=? WHERE name='}bedrock.synthetic.clear'",["ViewZeroOut(pCube,pView);ViewCreate(pCube,pView);SubsetCreate('Product','S');CellPutN(1,pCube,'Member1','ACT');ViewDestroy(pCube,pView);SubsetDestroy('Product','S');"])
    r=architecture.build(con,'Load');s=next(s for s in r['transformation_steps'] if s['process']=='Load')
    assert {'CLEAR','VIEW_PREPARATION','SUBSET_PREPARATION','DATA_TRANSFORMATION','CLEANUP'}<={e['category'] for e in s['effects']}
    w=next(w for w in r['write_explanations'] if w.get('via'))
    assert w['cube']=='Cube_B' and w['process']=='Load' and w['calculation'] is None
    assert w['target_coordinates']==[] and w['expression_status']=='CALLEE_CONTEXT_ONLY'
    assert not any(d['relation_type']=='STATIC_VALUE_DEPENDENCY' for d in r['formation_relationships'])


def test_rule_only_cube_and_feeder_do_not_require_any_ti(con):
    con.execute("DELETE FROM process_writes_cube")
    con.execute("UPDATE cubes SET rules=?,has_rules=true WHERE name='Cube_B'",["['ACT']=N:DB('Cube_A','ACT','Member1');FEEDERS;['ACT']=>DB('Cube_A','ACT','Member1');"])
    r=architecture.build(con,'Cube_B',entry_kind='cube')
    assert not r['processes'] and r['cubes'][0]['name']=='Cube_B'
    kinds={d['relation_type'] for d in r['formation_relationships']}
    assert 'RULE_REFERENCE' in kinds and 'FEEDER_REFERENCE' in kinds
    assert not r['write_explanations'] and r['rules'][0]['module_role']=='CORE'


def test_index_candidates_consumers_and_shared_objects_do_not_expand_modules(con):
    con.execute("INSERT INTO processes(name,prolog) VALUES ('WrongIndex', 'ExecuteProcess(''Unrelated'');')")
    con.execute("INSERT INTO processes(name,data) VALUES ('Unrelated', 'CellPutN(1,''Cube_A'',''ACT'',''Member1'');')")
    con.execute("INSERT INTO process_writes_cube VALUES ('WrongIndex','Cube_B')")
    con.execute("INSERT INTO process_writes_cube VALUES ('MissingSource','Cube_B')")
    con.execute("INSERT INTO processes(name,data,prolog) VALUES ('Consumer','x=CellGetN(''Cube_B'',''Member1'',''ACT'');','ExecuteProcess(''Unrelated'');')")
    con.execute("INSERT INTO process_reads_cube VALUES ('Consumer','Cube_B')")
    con.execute("INSERT INTO chore_runs_process VALUES ('Maintenance','}bedrock.synthetic.clear',0)")
    r=architecture.build(con,'Cube_B',entry_kind='cube')
    assert not any(p['process'] in {'WrongIndex','Unrelated','Consumer'} for p in r['processes'])
    assert any(d.get('kind')=='ti_reader' and d['process']=='Consumer' and d['status']=='SOURCE_CONFIRMED' for d in r['downstream_consumers'])
    assert not any(c['name']=='Maintenance' for c in r['chores'])
    assert any(u['process']=='MissingSource' for u in r['unresolved_dependencies'])
    assert any(c['name']=='Nightly' and c['target']=='Caller' for c in r['chores'])
    assert r['producer_discovery'][1]['status']=='UNVERIFIED_CANDIDATE'


def test_external_type_without_connection_secrets(con):
    con.execute("UPDATE processes SET prolog=?,data=? WHERE name='Load'",["DataSourceType='ODBC';DataSourceNameForServer='hidden-secret-dsn';", "CellPutN(1,'Cube_B',pProduct,'ACT');"])
    r=architecture.build(con,'Cube_B',entry_kind='cube')
    assert r['external_sources'][0]['external_type']=='ODBC'
    assert 'hidden-secret-dsn' not in json.dumps(r)
    assert not any(d['relation_type']=='STATIC_VALUE_DEPENDENCY' for d in r['formation_relationships'])


def test_cube_scope_budget_and_no_unscoped_source_read(con):
    class Scoped:
        def execute(self,sql,args=None):
            if 'SELECT prolog,metadata,data,epilog' in sql or sql.startswith('SELECT rules FROM'):assert 'WHERE name=?' in sql
            return con.execute(sql,args) if args is not None else con.execute(sql)
    r=architecture.build(Scoped(),'Cube_B',entry_kind='cube',max_nodes=1)
    assert not r['processes'] and len(r['cubes'])==1 and not r['dimensions']
    assert any('预算' in d['message'] for d in r['unresolved_dependencies'])
    with pytest.raises(KeyError):architecture.build(con,'Missing',entry_kind='cube')
    from tm1_insight.tasks import TaskCancelled
    def cancel(**event):
        if event['stage']=='解释写入坐标与值来源':raise TaskCancelled()
    with pytest.raises(TaskCancelled):architecture.build(con,'Cube_B',entry_kind='cube',progress=cancel)
    con.execute("UPDATE processes SET prolog=? WHERE name='Load'",['x'*250001])
    limited=architecture.build(con,'Load')
    assert limited['processes'][0]['module_role']=='CORE' and limited['processes'][0]['source_hash'] is None
    assert not limited['write_explanations']


def test_cube_api_keeps_process_contract_and_exports(client):
    from tm1_insight.api.app import _store
    from tm1_insight.config import get_settings
    client.get('/');c=_store().connect();fixture(c)
    c.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')");c.close()
    before=hashlib.sha256(get_settings().db_path.read_bytes()).hexdigest()
    assert client.post('/api/architecture/tasks',json={'entry_kind':'cube'}).status_code==422
    assert client.post('/api/architecture/tasks',json={'entry_kind':'cube','cube':'Missing'}).status_code==404
    task=client.post('/api/architecture/tasks',json={'entry_kind':'cube','cube':'Cube_B'}).json()['task_id'];base='/api/architecture/tasks/'+task
    for i in range(200):
        state=client.get(base).json()
        if state['status'] not in {'queued','running'}:break
        time.sleep(.01)
    assert state['status']=='completed'
    report=client.get(base+'/export').json()
    assert report['formation_version']=='cube-formation-1'
    visible=client.get(base+'/result?view=write_explanations&target_cube=Cube_B').json()['items']
    assert visible and all(w['cube']=='Cube_B' and not w['technical'] for w in visible)
    assert client.get(base+'/result?view=formation_relationships').status_code==200
    assert client.get(base+'/export?format=zip').status_code==200
    assert '入口 Cube' in client.get(base+'/export?format=markdown').text
    html = client.get('/cubes?name=Cube_B').text
    assert '查看上下游血缘' in html and '/graph?cube=Cube_B' in html
    assert client.get('/architecture?kind=cube&name=Cube_B').status_code==200
    assert client.get('/codegen').status_code==200
    assert hashlib.sha256(get_settings().db_path.read_bytes()).hexdigest()==before


def test_unique_prolog_literals_survive_exit_merge_but_conflicts_do_not(con):
    code="cScenario='ACT';IF(pFlag=0);ProcessQuit;ENDIF;"
    con.execute("UPDATE processes SET prolog=? WHERE name='Load'",[code])
    r=architecture.build(con,'Load')
    assert r['write_explanations'][0]['target_coordinates'][1]['value']=='ACT'
    for suffix in ["IF(pFlag=2);cScenario='PLAN';ENDIF;", "cScenario=UnknownFunction();"]:
        con.execute("UPDATE processes SET prolog=? WHERE name='Load'",[code+suffix])
        r=architecture.build(con,'Load');assert r['write_explanations'][0]['target_coordinates'][1]['kind']!='FIXED_MEMBER'


def test_control_and_coordinate_reads_are_not_numeric_value_contributions(con):
    code="flag=CellGetN('Cube_A',cScenario,pProduct);IF(flag>0);product=CellGetS('Cube_A',cScenario,pProduct);CellPutN(5,'Cube_B',product,cScenario);ENDIF;"
    con.execute("UPDATE processes SET data=? WHERE name='Load'",[code])
    r=architecture.build(con,'Cube_B',entry_kind='cube')
    uses={role for read in r['transformation_summaries'][0]['observed_reads'] for role in read['usages']}
    assert 'CONTROL_EXPRESSION' in uses and 'TARGET_COORDINATE_LOOKUP' in uses
    assert 'VALUE_EXPRESSION' not in uses
    assert not any(d['relation_type']=='STATIC_VALUE_DEPENDENCY' for d in r['formation_relationships'])
    x=r['write_explanations'][0]
    assert x['target_coordinates'][0]['kind']=='LOOKUP_COORDINATE' and x['calculation'] is None

    con.execute("UPDATE processes SET data=? WHERE name='Load'",["flag=CellGetN('Cube_A',cScenario,pProduct);IF(Unmodeled(flag));CellPutN(1,'Cube_B',pProduct,cScenario);ENDIF;"])
    r=architecture.build(con,'Load')
    assert r['transformation_summaries'][0]['observed_reads'][0]['usages']==['READ_OBSERVATION_ONLY']
