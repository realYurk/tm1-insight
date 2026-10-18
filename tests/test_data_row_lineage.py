"""Positive/negative Data Row Binding acceptance cases; no server execution."""
import json
from types import SimpleNamespace
import duckdb
import pytest
from tm1_insight import architecture, workflow
from tm1_insight.store.calculation import inspect
from tm1_insight.store.data_row import save_metadata
from tm1_insight.store.schema import ALL_TABLES
from tm1_insight.ingest.process_metadata import collect, import_bundle
from test_datasource_api import client  # noqa: F401


@pytest.fixture
def con():
    c=duckdb.connect(':memory:')
    for ddl in ALL_TABLES.values():c.execute(ddl)
    for name in ('Scenario','Product'):
        c.execute('INSERT INTO dimensions(name,element_count,elements) VALUES (?,?,?)',[name,1,json.dumps(['ACT'])])
    for cube,dims in [('Cube_A',['Scenario','Product']),('Cube_B',['Product','Scenario'])]:
        c.execute('INSERT INTO cubes VALUES (?,?,?,?,?)',[cube,json.dumps(dims),'',False,2])
        for i,d in enumerate(dims):c.execute('INSERT INTO cube_has_dimension VALUES (?,?,?)',[cube,d,i])
    c.execute("INSERT INTO processes VALUES ('Load','','','','','[]',NULL,0)")
    c.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')")
    yield c
    c.close()


def setup(c,data="CellPutN(vValue,'Cube_B',vProduct,vScenario);",*,variables=None,view_type='NativeView',prolog='',metadata=''):
    c.execute("UPDATE processes SET prolog=?,metadata=?,data=? WHERE name='Load'",[prolog,metadata,data])
    p=dict(name='Load',prolog=prolog,metadata=metadata,data=data,epilog='',
           datasource=dict(type='TM1CubeView',cube='Cube_A',view='Input'),
           variables=variables if variables is not None else [dict(Name=n,Type=t,Position=i,StartByte=0,EndByte=0)
               for i,(n,t) in enumerate([('vScenario','String'),('vProduct','String'),('vValue','Numeric')],1)],
           source_view=dict(cube='Cube_A',name='Input',type=view_type,dimension_order=['Scenario','Product']))
    save_metadata(c,p)
    return p


def explanation(c):
    r=architecture.build(c,'Cube_B',entry_kind='cube')
    return r,r['write_explanations'][0]


@pytest.mark.parametrize('operation',['CellPutN','CellIncrementN'])
def test_A_direct_native_value_and_D_reversed_target_order(con,operation):
    setup(con,f"{operation}(vValue,'Cube_B',vProduct,vScenario);")
    r,x=explanation(con)
    assert x['data_row_binding']=='STATIC_CELL_VALUE_DEPENDENCY'
    assert x['calculation']==('Cube_B[Product=vProduct,Scenario=vScenario]'+(' += ' if operation=='CellIncrementN' else ' = ')+'Cube_A[Scenario=vScenario,Product=vProduct]')
    assert [(c['dimension'],c['variable']) for c in x['source_coordinate_mapping']]==[('Scenario','vScenario'),('Product','vProduct')]
    assert x['data_row_value_dependencies'][0]['variable']=='vValue'
    assert x['data_row_value_dependencies'][0]['use_location']['line']==1
    assert not x['runtime_verified']
    edges=[e for e in r['formation_relationships'] if e['relation_type']=='STATIC_VALUE_DEPENDENCY']
    assert len(edges)==1 and edges[0]['source']=='Cube_A'
    ids={e['id'] for e in r['evidence']}
    assert all(set(e['evidence_refs'])<=ids for e in r['formation_relationships'])


def test_B_arithmetic_alias_branch_export_and_source_evidence(con,tmp_path):
    setup(con,"alias=vValue;nResult=alias*2;If(vScenario @= 'ACT');CellPutN(nResult,'Cube_B',vProduct,vScenario);EndIf;")
    r,x=explanation(con)
    assert x['calculation'].endswith('(Cube_A[Scenario=vScenario,Product=vProduct] * 2)')
    assert x['conditions'] and len(x['value_definition_chain'])==2
    assert {d['variable'] for d in x['value_definition_chain']}=={'alias','nResult'}
    a=architecture.artifact(r,tmp_path)
    try:
        md=''.join(architecture.markdown(a.path))
        assert 'Data 行值依赖' in md and 'nResult' in md and 'Cube_A[Scenario=vScenario' in md
        _,_,items=architecture.page(a.path,'write_explanations',0,10)
        assert items[0]['data_row_schema']=='data-row-1'
    finally:a.cleanup()


def test_C_name_does_not_prove_numeric_value_field(con):
    vs=[dict(Name=n,Type=t,Position=i) for i,(n,t) in enumerate([('vValue','String'),('vProduct','String'),('amount','Numeric')],1)]
    setup(con,"dummy=CellGetN('Cube_A',vValue,vProduct);CellPutN(vValue,'Cube_B',vProduct,vValue);",variables=vs)
    r,x=explanation(con)
    assert x['calculation'] is None and x['data_row_binding']=='VARIABLE_DEPENDENCY_ONLY'
    assert x['data_row_value_dependencies'][0]['source_field']['kind']=='DIMENSION_MEMBER'
    assert not any(e['relation_type']=='STATIC_VALUE_DEPENDENCY' for e in r['formation_relationships'])


@pytest.mark.parametrize('kind',['MDXView','UNKNOWN'])
def test_F_dynamic_mdx_or_missing_view_keeps_variable_dependency_only(con,kind):
    setup(con,view_type=kind)
    r,x=explanation(con)
    assert x['source_view_binding']['cube']=='Cube_A'
    assert x['source_view_binding']['row_layout_status']=='UNKNOWN'
    assert x['data_row_binding']=='VARIABLE_DEPENDENCY_ONLY' and x['calculation'] is None
    assert not x['source_coordinate_mapping'] and x['unresolved_binding_reasons']
    assert not any(e['relation_type']=='STATIC_VALUE_DEPENDENCY' for e in r['formation_relationships'])


def test_E_multiple_numeric_fields_do_not_become_same_cell(con):
    vs=[dict(Name=n,Type=t,Position=i) for i,(n,t) in enumerate([('vScenario','String'),('vProduct','String'),('vValue','Numeric'),('other','Numeric')],1)]
    setup(con,"CellPutN(vValue+other,'Cube_B',vProduct,vScenario);",variables=vs)
    r,x=explanation(con)
    assert x['calculation'] is None and len(x['data_row_value_dependencies'])==2
    assert all(d['source_cube'] is None for d in x['data_row_value_dependencies'])
    assert not any(e['relation_type']=='STATIC_VALUE_DEPENDENCY' for e in r['formation_relationships'])


def test_G_legacy_snapshot_missing_variables_still_opens(con):
    con.execute("UPDATE processes SET prolog=?,data=? WHERE name='Load'",[
        "DataSourceType='VIEW';DataSourceNameForServer='Cube_A';DataSourceCubeView='Input';",
        "CellPutN(vValue,'Cube_B',vProduct,vScenario);"])
    con.execute('DROP TABLE process_source_metadata')
    r,x=explanation(con)
    assert x['calculation'] is None and not x['data_row_value_dependencies']
    assert 'MISSING_VARIABLE_METADATA' in x['unresolved_binding_reasons'][0]
    assert x['source_view_binding']['cube']=='Cube_A' and x['source_view_binding']['row_layout_status']=='UNKNOWN'


@pytest.mark.parametrize('data,expected',[
    ("vValue=5;CellPutN(vValue,'Cube_B',vProduct,vScenario);",False),
    ("If(vScenario @= 'ACT');vValue=5;EndIf;CellPutN(vValue,'Cube_B',vProduct,vScenario);",False),
    ("n=Opaque(vValue);CellPutN(n,'Cube_B',vProduct,vScenario);",False),
    ("If(vScenario @= 'ACT');n=vValue*2;CellPutN(n,'Cube_B',vProduct,vScenario);Else;n=0;CellPutN(n,'Cube_B',vProduct,vScenario);EndIf;",True),
])
def test_H_reassignment_unknown_function_branch_merge_and_I_false_positives(con,data,expected):
    setup(con,data)
    r,x=explanation(con)
    assert bool(x['data_row_value_dependencies'])==expected
    edges=[e for e in r['formation_relationships'] if e['relation_type']=='STATIC_VALUE_DEPENDENCY']
    assert bool(edges)==expected
    if not expected:assert 'Cube_A[' not in (x['calculation'] or '')


def test_no_dependency_from_row_coordinate_or_unrelated_read(con):
    setup(con,"unused=vValue;CellPutN(7,'Cube_B',vProduct,vScenario);")
    r,x=explanation(con)
    assert not x['data_row_value_dependencies']
    assert not any(e['relation_type']=='STATIC_VALUE_DEPENDENCY' for e in r['formation_relationships'])


def test_string_value_write(con):
    vs=[dict(Name=n,Type='String',Position=i) for i,n in enumerate(['vScenario','vProduct','text'],1)]
    setup(con,"CellPutS(text,'Cube_B',vProduct,vScenario);",variables=vs)
    _,x=explanation(con)
    assert x['data_row_binding']=='STATIC_CELL_VALUE_DEPENDENCY' and x['calculation']


def test_stale_metadata_duplicate_positions_and_prolog_override(con):
    p=setup(con)
    con.execute("UPDATE processes SET data=data||'x=1;' WHERE name='Load'")
    report=inspect(con,'Load')
    assert 'METADATA_SOURCE_MISMATCH' in report['data_row_lineage']['unresolved_binding_reasons'][0]
    p=setup(con);p['variables'][1]['Position']=1;save_metadata(con,p)
    assert not inspect(con,'Load')['writes'][0]['data_row_value_dependencies']
    setup(con,prolog="DataSourceNameForServer=DynamicName;")
    report=inspect(con,'Load')
    assert report['data_row_lineage']['source_view_binding'] is None
    assert report['writes'][0]['data_row_binding_status']=='VARIABLE_DEPENDENCY_ONLY'


def test_metadata_section_reassignment_blocks_cross_section_guess(con):
    setup(con,metadata='vValue=vValue*2;')
    report=inspect(con,'Load')
    assert not report['writes'][0]['data_row_value_dependencies']
    assert any('Metadata' in n.get('reason','') for n in report['nodes'])


def test_get_only_incremental_collection_safe_fields_identity_and_atomic_import(con):
    p=setup(con)
    requested=[]
    d=dict(Name='Load',DataSource=dict(Type='TM1CubeView',dataSourceNameForServer='Cube_A',view='Input',password='secret'),
           Variables=p['variables'],Parameters=[],PrologProcedure='',MetadataProcedure='',DataProcedure=p['data'],EpilogProcedure='')
    def get(url):
        requested.append(url)
        return SimpleNamespace(json=lambda:d if url.startswith('/Processes') else
            {'Name':'Input','@odata.type':'#ibm.tm1.api.v1.NativeView'} if '/Views(' in url else
            {'Name':'Cube_A','Dimensions':[{'Name':'Scenario'},{'Name':'Product'}]})
    class Client:
        def connect(self):return self
        def __enter__(self):return SimpleNamespace(_rest=SimpleNamespace(GET=get))
        def __exit__(self,*args):pass
    progress=[]
    b=collect(Client(),['Load'],progress=lambda i,n:progress.append((i,n)))
    assert len(requested)==3 and all('Execute' not in u and 'Cells' not in u for u in requested)
    assert 'secret' not in json.dumps(b) and progress==[(0,1),(1,1)]
    assert import_bundle(con,b)==1
    assert inspect(con,'Load')['writes'][0]['data_row_binding_status']=='STATIC_CELL_VALUE_DEPENDENCY'
    old=con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]
    b['processes'][0]['data']='different'
    with pytest.raises(ValueError):import_bundle(con,b)
    assert con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]==old
    with pytest.raises(ValueError):collect(Client(),['x']*21+['y'+str(i) for i in range(21)])
    def cancel(i,n):raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):collect(Client(),['Load'],progress=cancel)


def test_tm1py_flat_properties_and_canonical_snapshot_preserve_variables():
    from TM1py.Objects import Process
    from tm1_insight.tm1.client import TM1Client
    from tm1_insight.config import Settings
    from tm1_insight.collector import _map_process
    from tm1_insight.snapshot.schema import validate_snapshot_payload
    p=Process('Synthetic',datasource_type='TM1CubeView',datasource_data_source_name_for_server='Cube_A',datasource_view='Input')
    p.add_variable('anything','Numeric')
    raw=TM1Client(Settings()).fetch_process(SimpleNamespace(processes=SimpleNamespace(get=lambda _:p)),'Synthetic')
    assert raw['datasource']['cube']=='Cube_A' and raw['variables'][0]['Position']==1
    canonical=_map_process(raw);validate_snapshot_payload({'processes':[canonical]})
    assert canonical['variables']==raw['variables'] and canonical['datasource']==raw['datasource']


def test_snapshot_and_loader_round_trip_preserve_optional_metadata(con,tmp_path):
    from tm1_insight.collector import _map_process
    from tm1_insight.snapshot import SnapshotStore
    from tm1_insight.ingest.loader import Loader
    from tm1_insight.config import Settings
    p=setup(con);p['parameters']=[dict(name='pFlag',type='Numeric',default_value=0)]
    canonical=_map_process(p)
    store=SnapshotStore(tmp_path/'snapshots');store.create_snapshot('new','test','synthetic',{'processes':[canonical]})
    _,payload=store.load_snapshot('new')
    assert payload['processes'][0]['variables']==p['variables']
    assert payload['processes'][0]['parameter_definitions'][0]['default_value']==0
    con.execute("DELETE FROM processes WHERE name='Load'")
    con.execute('DELETE FROM process_source_metadata')
    Loader(Settings())._insert_objects(con,[],payload['processes'],[])
    assert inspect(con,'Load')['writes'][0]['data_row_binding_status']=='STATIC_CELL_VALUE_DEPENDENCY'
    assert json.loads(con.execute('SELECT payload FROM process_source_metadata').fetchone()[0])['parameters'][0]['type']=='Numeric'


@pytest.mark.parametrize('damage',['dimension_order','view_identity','rebuild','type_mismatch','sensitive_column'])
def test_inconsistent_view_metadata_and_type_conversion_never_yield_complete_formula(con,damage):
    p=setup(con)
    if damage=='dimension_order':p['source_view']['dimension_order']=['Product','Scenario']
    elif damage=='view_identity':p['source_view']['name']='OtherView'
    elif damage=='rebuild':
        p['prolog']="ViewCreateByMDX('Cube_A','Input',DynamicMDX);"
        con.execute("UPDATE processes SET prolog=? WHERE name='Load'",[p['prolog']])
    elif damage=='sensitive_column':p['variables'][0]['Name']='vPassword'
    else:p['variables'][-1]['Type']='String'
    save_metadata(con,p)
    _,x=explanation(con)
    assert x['calculation'] is None
    if damage!='type_mismatch':assert x['data_row_binding']=='VARIABLE_DEPENDENCY_ONLY'


def test_row_api_paging_exports_metadata_evidence_and_cache_invalidation(con,client):
    import time
    from tm1_insight.api.app import _store
    setup(con,'alias=vValue;CellPutN(alias*2,\'Cube_B\',vProduct,vScenario);')
    client.get('/')
    c=_store().connect()
    for table in ('cubes','dimensions','cube_has_dimension','processes','process_writes_cube','process_source_metadata'):
        rows=con.execute('SELECT * FROM '+table).fetchall()
        if rows:c.executemany(('INSERT OR REPLACE INTO ' if table in {'cubes','dimensions','processes','process_source_metadata'} else 'INSERT INTO ')+table+' VALUES ('+','.join('?' for _ in rows[0])+')',rows)
    c.close()
    def analyze():
        response=client.post('/api/architecture/tasks',json=dict(entry_kind='cube',cube='Cube_B'))
        assert response.status_code==202
        task=response.json()['task_id'];base='/api/architecture/tasks/'+task
        deadline=time.monotonic()+10
        while True:
            state=client.get(base).json()
            if state['status'] not in {'queued','running'}:break
            assert time.monotonic()<deadline;time.sleep(.01)
        assert state['status']=='completed'
        return base
    base=analyze()
    result=client.get(base+'/result?view=write_explanations&limit=1').json()
    x=result['items'][0]
    assert 'Cube_A[' in x['calculation'] and x['data_row_value_dependencies'][0]['variable']=='vValue'
    refs=x['data_row_value_dependencies'][0]['evidence_refs']
    facts=[client.get(base+'/fact',params={'id':ref}).json() for ref in refs]
    assert any(f.get('table')=='process_source_metadata' for f in facts)
    assert 'Data 行值依赖' in client.get(base+'/export?format=markdown').text
    assert client.get(base+'/export?format=json').json()['details']['Load']['data_row_lineage']['schema']=='data-row-1'
    # A metadata-only refresh changes the model fingerprint/cache key.
    c=_store().connect();c.execute("DELETE FROM process_source_metadata WHERE process_name='Load'");c.close()
    assert client.get(base+'/result').status_code==409
    newer=analyze()
    x=client.get(newer+'/result?view=write_explanations&limit=1').json()['items'][0]
    assert x['calculation'] is None and not x['data_row_value_dependencies']
