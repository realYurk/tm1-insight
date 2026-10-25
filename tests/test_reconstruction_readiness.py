"""Synthetic reconstruction boundaries; no server execution or cell access."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_data_row_lineage import con, setup  # noqa: F401
from test_datasource_api import client  # noqa: F401
from tm1_insight import workflow, workflow_review
from tm1_insight.store.calculation import inspect


def review(con,tmp_path):
    data=workflow.build(con,'Load',max_depth=0)
    data['source_fingerprint']='synthetic'
    a=workflow.artifact(data,tmp_path)
    try:return workflow_review.build(a.path,declaration=workflow_review.source_declaration(con,'Load'))
    finally:a.cleanup()


def test_native_view_without_cellget_has_separate_declaration_and_value_proof(con,tmp_path):
    setup(con,"n=vValue*2;CellIncrementN(n,'Cube_B',vProduct,vScenario);CellIncrementN(42,'Cube_B',vProduct,vScenario);")
    r=review(con,tmp_path)
    assert not r['summary']['reads'] and r['summary']['view_sources']==['Cube_A']
    assert r['sources']['view_binding']['row_layout_status']=='NATIVE_CELL_ROW'
    assert len(r['sources']['variables'])==3 and r['sources']['declaration']['type']=='TM1CubeView'
    first,constant=r['writes']['writes']
    assert first['data_row_value_dependencies'][0]['source_cube']=='Cube_A'
    assert first['data_row_binding_status']=='STATIC_CELL_VALUE_DEPENDENCY'
    assert not constant['data_row_value_dependencies']
    assert any('累加数值' in b for b in r['summary']['behaviors'])
    md=workflow_review.markdown(r)
    assert 'VIEW 声明来源：Cube_A' in md and '数据行值参数依赖：vValue' in md
    assert '源列位置（非维度位置）' in md and r['evidence_context']['source_hash'] in md
    assert not r['runtime_verified']


@pytest.mark.parametrize('kind',['MDXView','UNKNOWN'])
def test_view_declaration_does_not_upgrade_unknown_layout(con,tmp_path,kind):
    setup(con,view_type=kind)
    r=review(con,tmp_path)
    assert r['summary']['view_sources']==['Cube_A']
    assert r['sources']['view_binding']['row_layout_status']=='UNKNOWN'
    write=r['writes']['writes'][0]
    assert write['data_row_binding_status']=='VARIABLE_DEPENDENCY_ONLY'
    assert write['data_row_value_dependencies'][0]['source_cube'] is None


def test_variables_missing_retains_declaration_not_value_dependency(con,tmp_path):
    setup(con,variables=[])
    r=review(con,tmp_path)
    assert r['summary']['view_sources']==['Cube_A'] and not r['sources']['variables']
    assert not r['writes']['writes'][0]['data_row_value_dependencies']
    assert r['sources']['reasons']
    # Legacy code-only declaration uses the existing Architecture resolver.
    con.execute('DROP TABLE process_source_metadata')
    con.execute("UPDATE processes SET prolog=? WHERE name='Load'",["DataSourceType='VIEW';DataSourceNameForServer='Cube_A';DataSourceCubeView='Input';"])
    old=review(con,tmp_path)
    assert old['summary']['view_sources']==['Cube_A']
    assert old['sources']['declaration']['evidence'][0]['section']=='prolog'
    assert not old['writes']['writes'][0]['data_row_value_dependencies']


def test_stale_or_dynamic_metadata_never_becomes_active_view(con,tmp_path):
    setup(con)
    con.execute("UPDATE processes SET prolog=? WHERE name='Load'",["DataSourceNameForServer=pDynamic;"])
    r=review(con,tmp_path)
    assert not r['summary']['view_sources']
    assert r['sources']['declaration']['status']=='UNKNOWN'
    assert r['sources']['view_binding'] is None


def test_cube_row_projection_uses_value_chain_not_declaration_alone(con):
    from test_cube_lineage_ui import js
    setup(con,"CellIncrementN(vValue,'Cube_B',vProduct,vScenario);CellIncrementN(42,'Cube_B',vProduct,vScenario);")
    data=inspect(con,'Load');data['reads']=[n for n in data['nodes'] if n['kind']=='read']
    rows=js(data,"window.TM1CubeLineage.writeRows(data,'Cube_A','Cube_B')")
    assert rows[0]['source_data_rows'][0]['variable']=='vValue'
    assert rows[0]['source_row_slices'][0]['dimension']=='Scenario'
    assert rows[0]['target_slices'][0]['dimension']=='Product'
    assert not rows[1]['source_data_rows'] and not rows[1]['source_reads']


def test_bounded_cube_report_controller():
    node=shutil.which('node')
    if not node:pytest.skip('Node needed for the actual browser controller')
    r=subprocess.run([node,'tests/ui/cube_review_controller.js','src/tm1_insight/api/static/cube-lineage.js'],capture_output=True,text=True,encoding='utf-8')
    assert r.returncode==0,r.stderr
    assert json.loads(r.stdout)['cancelled']


def test_routes_keep_model_identity_and_reject_stale_source(client):
    assert 'data-model="old-model"' in client.get('/graph?cube=Cube_B&model=old-model').text
    assert 'data-model="old-model"' in client.get('/graph?ti=Load&model=old-model').text
    assert client.get('/explorer/process/Load?model=old-model').status_code==409
    assert client.get('/explorer/cube/Cube_B?model=old-model').status_code==409
    assert client.post('/api/workbench/graph',json={'snapshot_id':'old-model','objects':[{'name':'Cube_B'}]}).status_code==409


def test_writes_budget_is_scoped_and_legacy_fields_preserved(client,con,monkeypatch):
    import tm1_insight.api.workbench as api
    setup(con)
    class Lease:
        def execute(self,*a,**k):return con.execute(*a,**k)
        def close(self):pass
    class ReadOnlyStore:
        def connect(self,read_only=False):
            assert read_only
            return Lease()
    monkeypatch.setattr(api,'guard',lambda snapshot:(ReadOnlyStore(),'synthetic'))
    data=client.get('/api/workbench/writes',params={'snapshot_id':'synthetic','process':'Load'}).json()
    assert data['data_row_lineage']['source_view_binding']['cube']=='Cube_A'
    assert data['writes'][0]['data_row_value_dependencies'][0]['variable']=='vValue'
    con.execute("UPDATE processes SET data=? WHERE name='Load'",['#'+'x'*250000])
    response=client.get('/api/workbench/writes',params={'snapshot_id':'synthetic','process':'Load'})
    assert response.status_code==413
