"""Readable reports must preserve the existing Workflow evidence boundaries."""
import json

import pytest
from test_architecture import con  # noqa: F401
from test_datasource_api import client  # noqa: F401
from tm1_insight import workflow, workflow_review


def artifact(con,tmp_path,root='Caller',max_depth=3):
    report=workflow.build(con,root,max_processes=12,max_depth=max_depth)
    report['source_fingerprint']='synthetic-snapshot'
    return workflow.artifact(report,tmp_path)


def test_conditional_parameter_binding_and_actual_call_endpoints(con,tmp_path):
    con.execute("UPDATE processes SET prolog=? WHERE name='Caller'",["IF(vYear @= 'Member1');ExecuteProcess('Load','vYear',vYear);ENDIF;ExecuteProcess(pDynamic);"])
    a=artifact(con,tmp_path)
    try:
        result=workflow_review.build(a.path,[dict(chore='Nightly',step_order=0)])
        assert result['schema']=='ti-reconstruction-review-1'
        call=next(c for c in result['calls'] if c['target']=='Load')
        assert call['process']=='Caller' and call['control_context']
        binding=call['bindings'][0]
        assert binding['parameter']=='vYear' and binding['expression']=='vYear'
        assert binding['binding_status']=='EXPLICIT_NAME_BINDING'
        assert any(c['target'] is None for c in result['calls'])
        assert all(c['process']!='Caller' for c in result['downstream_calls'])
        assert any(c['process']=='BusinessChild' and c['target']=='Load' for c in result['downstream_calls'])
        assert result['schedules'][0]['chore']=='Nightly' and not result['runtime_verified']
        assert result['cycles']
    finally:a.cleanup()


def test_unknown_source_does_not_get_reconstructed_from_co_read(con,tmp_path):
    from test_cube_lineage_ui import seed
    seed(con)
    a=artifact(con,tmp_path,'Unbound')
    try:
        r=workflow_review.build(a.path)
        assert r['summary']['reads']==['Cube_A'] and r['summary']['writes']==['Cube_B']
        w=r['writes']['writes'][0]
        assert w['value_expression']=='vValue' and not w['read_nodes']
        assert w['coordinate_mapping']['items'][1]['binding']['value']=='Member1'
        assert r['summary']['uncertain_writes']==1
        md=workflow_review.markdown(r)
        assert '源值切面：未确认' in md and 'Region=Member1（固定）' in md
        assert 'CellIncrementN' in md and '一页摘要' in md and '工程明细' in md and '证据与范围附录' in md
    finally:a.cleanup()


def test_dynamic_cube_read_not_exported_as_confirmed_source(con,tmp_path):
    data="n=CellGetN(pCube,vYear,vProduct);CellPutN(n,'Cube_B',vYear,'Member1','Member2');"
    con.execute("INSERT INTO processes(name,prolog,metadata,data,epilog,parameters) VALUES ('DynamicRead','','',?,'','[]')",[data])
    a=artifact(con,tmp_path,'DynamicRead')
    try:
        report=workflow_review.build(a.path)
        write=report['writes']['writes'][0]
        assert write['read_nodes'] and not write['confirmed_source_read_ids']
        md=workflow_review.markdown(report)
        assert '静态表达式读取：' not in md and '源值切面：未确认' in md
    finally:a.cleanup()


def test_caller_index_stays_unverified_and_budgets_are_visible(con,tmp_path):
    a=artifact(con,tmp_path,'Load',max_depth=0)
    try:
        r=workflow_review.build(a.path)
        assert any(c['process']=='Caller' and c['status']=='STRUCTURAL_UNVERIFIED' for c in r['callers'])
        assert r['limitations'] and r['budgets']['max_depth']==0
        assert all(not c['runtime_verified'] for c in r['calls'])
        assert not r['downstream_calls']
        assert {x['section'] for x in r['sections']}=={'prolog','metadata','data','epilog'}
    finally:a.cleanup()


def test_report_deterministic_and_sensitive_constants_not_exported(con,tmp_path):
    con.execute("UPDATE processes SET prolog=? WHERE name='Caller'",["vPassword='private-secret-fixture';ExecuteProcess('Load','vYear',vPassword);"])
    a=artifact(con,tmp_path)
    try:
        r=workflow_review.build(a.path)
        assert r==workflow_review.build(a.path)
        assert 'private-secret-fixture' not in json.dumps(r)
        assert 'private-secret-fixture' not in workflow_review.markdown(r)
        assert '未执行 TI' in workflow_review.markdown(r)
    finally:a.cleanup()


def test_no_calls_or_writes_does_not_invent_activity(con,tmp_path):
    con.execute("INSERT INTO processes(name,prolog,metadata,data,epilog,parameters) VALUES ('Empty','','','','','[]')")
    a=artifact(con,tmp_path,'Empty')
    try:
        r=workflow_review.build(a.path)
        assert not r['calls'] and not r['writes']['writes'] and not r['summary']['reads']
        assert not r['schedules'] and not r['callers']
    finally:a.cleanup()


def test_review_api_and_export_use_same_projection(client,monkeypatch,con,tmp_path):
    import tm1_insight.api.workflow as api
    a=artifact(con,tmp_path,'Caller')
    class Lease:
        def execute(self,*args):return con.execute(*args)
        def close(self):pass
    class ReadOnlyStore:
        def __init__(self,*args):pass
        def connect(self,read_only=False):
            assert read_only
            return Lease()
    monkeypatch.setattr(api,'path',lambda task:a.path)
    monkeypatch.setattr(api,'state',lambda task:{})
    monkeypatch.setattr(api,'Store',ReadOnlyStore)
    try:
        r=client.get('/api/workflow/tasks/synthetic/review')
        assert r.status_code==200
        assert r.json()['schedules'][0]['chore']=='Nightly'
        md=client.get('/api/workflow/tasks/synthetic/review?format=markdown')
        assert md.status_code==200 and md.text==workflow_review.markdown(r.json())
        downloaded=client.get('/api/workflow/tasks/synthetic/review?download=true')
        assert 'TI-Reconstruction.json' in downloaded.headers['content-disposition']
        assert downloaded.json()==r.json()
        assert client.get('/graph?ti=Caller').status_code==200
        assert 'tr-root' in client.get('/graph?ti=Caller').text
        assert 'cl-root' in client.get('/graph?cube=Cube_B').text
        # Legacy synthetic stores may omit Chore metadata or its entire index.
        con.execute('DROP TABLE chores')
        old=client.get('/api/workflow/tasks/synthetic/review').json()
        assert old['schedules'][0]['active'] is None
        con.execute('DROP TABLE chore_runs_process')
        older=client.get('/api/workflow/tasks/synthetic/review').json()
        assert not older['schedules'] and any('缺少 Chore' in s for s in older['limitations'])
    finally:a.cleanup()
