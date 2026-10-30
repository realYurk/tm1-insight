import copy
import json
import time
from pathlib import Path

import pytest
from tm1_insight import module_spec as ms, workbench as wb
from tm1_insight.tasks import TaskCancelled
from test_architecture import con  # noqa: F401
from test_datasource_api import client  # noqa: F401
from module_spec_fixture import seed, definition


@pytest.fixture
def model(con):
    seed(con)
    return con


def build(con,tmp_path,d=None):
    d=d or definition()
    return ms.build(con,d,wb.indexed_graph(con,d.snapshot_id),tmp_path)


def test_inputs_writes_nativeview_and_independent_constant(model,tmp_path):
    s=build(model,tmp_path)
    assert s['schema_version']==ms.VERSION and not s['runtime_verified']
    view=next(i for i in s['inputs'] if i['kind']=='DATASOURCE' and i['process']=='ViewLoad')
    assert view['name']=='Cube_A' and view['view']=='Input' and len(view['variables'])==3
    calc=[c for c in s['calculations'] if c['process']=='ViewLoad']
    assert len(calc)==2 and sum(c['status']=='STATIC_VALUE_DEPENDENCY' for c in calc)==1
    assert all(c['status']=='NO_CONFIRMED_SOURCE_VALUE_DEPENDENCY' for c in s['calculations'] if c['process']=='ConstantLoad')
    writes=[w for w in s['outputs'] if w.get('process')=='ViewLoad']
    assert len({w['id'] for w in writes})==2
    assert all(w['operation']=='CellIncrementN' for w in writes)
    assert [m['dimension_order'] for m in s['data_models'] if m['name']=='Cube_B']==[['Year','Region','Measure']]
    evidence={e['id'] for e in s['evidence']}
    for rows in ('inputs','outputs','process_calls','rules','feeders','unknowns','validation_requirements'):
        assert all(set(r['evidence_refs'])<=evidence for r in s[rows])
    assert all(v['status']=='NOT_RUN' for v in s['validation_requirements'])


def test_rule_feeder_calls_chore_and_boundaries(model,tmp_path):
    s=build(model,tmp_path)
    assert s['rules'] and s['feeders']
    assert any(i['kind']=='RULE_REFERENCE' and i['name']=='Cube_B' for i in s['inputs'])
    assert any(i['kind']=='FEEDER_SUPPORT_NOT_VALUE_FLOW' for i in s['inputs'])
    assert any(c['caller']=='Caller' and c['callee']=='Load' for c in s['process_calls'])
    assert any(c['callee'] is None for c in s['process_calls'])
    assert any(p['path']==['Caller','Load','BusinessChild'] for p in s['call_paths'])
    assert any(x['chore']=='Nightly' and x['process']=='Caller' for x in s['schedules'])
    assert any(x['target']=='}bedrock.synthetic.clear' for x in s['scope']['outside_dependencies'])
    assert not any(x.get('name')=='}bedrock.synthetic.clear' for x in s['objects'])
    assert not s['coverage']['complete_reconstruction']


def test_missing_variables_does_not_invent_and_notes_are_separate(model,tmp_path):
    d=definition();s=build(model,tmp_path,d)
    rows=[c for c in s['calculations'] if c['process']=='MissingVariables']
    assert all(c['status']=='NO_CONFIRMED_SOURCE_VALUE_DEPENDENCY' for c in rows)
    assert any('variables' in u['reason'].lower() or '变量' in u['reason'] for u in s['unknowns'] if u['object']=='MissingVariables')
    changed=d.model_copy(update={'notes':ms.Notes(objective='假定这是已运行验证的全部值流')})
    other=build(model,tmp_path,changed)
    assert s['calculations']==other['calculations'] and s['rules']==other['rules']
    assert other['user_interpretation']['provenance']=='USER_DESCRIPTION'
    assert not other['runtime_verified']


def test_dynamic_cube_read_is_not_confirmed_value_source(model,tmp_path):
    data="n=CellGetN(pCube, vYear, vProduct);CellPutN(n,'Cube_B',vYear,'Member1','Member2');"
    model.execute("INSERT INTO processes(name,prolog,metadata,data,epilog,parameters) VALUES ('DynamicRead','','',?,'','[]')",[data])
    d=definition().model_copy(update={'members':definition().members+[ms.Ref(type='process',name='DynamicRead')]})
    result=build(model,tmp_path,d)
    calc=next(c for c in result['calculations'] if c['process']=='DynamicRead')
    assert calc['status']=='NO_CONFIRMED_SOURCE_VALUE_DEPENDENCY'
    assert not calc.get('confirmed_source_reads')
    assert not calc['runtime_verified']
    assert 'None' not in ms.markdown(result).split('## 计算与映射')[1].split('## TI 调用与调度')[0]
    from tm1_insight.store.calculation import inspect
    from tm1_insight.workflow import reconstruct
    worksheet=inspect(model,'DynamicRead')
    assert reconstruct(worksheet,worksheet['writes'][0])['value_dependencies']==[]
    # Old artifacts retain their original status but lack the new evidence
    # contract; Markdown must not promote that historical status to a fact.
    calc.pop('confirmed_source_reads');calc.pop('confirmed_data_row_dependencies')
    calc['status']='STATIC_VALUE_DEPENDENCY'
    row=next(line for line in ms.markdown(result).splitlines() if 'DynamicRead →' in line)
    assert '存在静态值依赖' not in row and '未确认源值依赖' in row


def test_confirmed_sources_require_resolved_reads_and_confirmed_view_value():
    from tm1_insight.workflow import confirmed_write_sources
    reads={1:dict(id=1,cube='Cube_A',resolution='resolved'),2:dict(id=2,cube=None,resolution='dynamic')}
    row=dict(source_cube='Cube_A',source_field=dict(kind='CELL_VALUE'))
    write=dict(trace_status='PARTIAL',read_nodes=[1,2],data_row_value_dependencies=[row],data_row_binding_status='UNKNOWN')
    confirmed,view=confirmed_write_sources(write,reads)
    assert confirmed==[reads[1]] and view==[]
    write['data_row_binding_status']='STATIC_CELL_VALUE_DEPENDENCY'
    assert confirmed_write_sources(write,reads)==([reads[1]],[row])
    write['trace_status']='UNKNOWN'
    assert confirmed_write_sources(write,reads)==([],[])
    write.pop('trace_status')
    assert confirmed_write_sources(write,reads)==([],[])


def test_deterministic_versioned_export_and_no_raw_source(model,tmp_path):
    d=definition();a=build(model,tmp_path,d)
    b=build(model,tmp_path,d.model_copy(update={'members':list(reversed(d.members))}))
    assert ms.canonical(a)==ms.canonical(b)
    md=ms.markdown(a)
    assert all(title in md for title in ['输入契约','输出契约','处理步骤','计算与映射','未确认事项','验证契约','证据附录'])
    assert a['snapshot_ref'] in md and '工程建议' in md
    assert not any('prolog' in r for r in a['process_summaries'])
    assert all('raw' not in r for r in a['rules']+a['feeders'])


def test_scope_preview_excludes_before_traversal_and_frozen_analysis(model,tmp_path):
    d=ms.Definition(name='small',snapshot_id='s',entries=[dict(type='process',name='Caller')],expand_calls=True,expand_access=False,depth=4,excluded=[dict(type='process',name='Load')])
    p=ms.propose(wb.indexed_graph(model,'s'),d)
    assert {n['name'] for n in p['nodes']}=={'Caller'}
    d=definition().model_copy(update={'members':[ms.Ref(type='process',name='Caller')],'process_budget':1})
    s=build(model,tmp_path,d)
    assert s['coverage']['processes_analyzed']==1
    assert not s['calculations'] and any(c['callee']=='Load' and not c['in_scope'] for c in s['process_calls'])


def test_budgets_missing_object_and_snapshot_identity(model,tmp_path):
    d=definition().model_copy(update={'process_budget':1,'rule_budget':0,'edge_budget':1})
    s=build(model,tmp_path,d)
    assert s['coverage']['processes_unreviewed'] and s['coverage']['rule_owners_skipped']
    assert s['coverage']['relations_omitted']>0
    a=build(model,tmp_path,definition('snapshot-a'));b=build(model,tmp_path,definition('snapshot-b'))
    assert {o['id'] for o in a['objects']}.isdisjoint({o['id'] for o in b['objects']})
    missing=definition().model_copy(update={'members':[ms.Ref(name='Missing')]})
    s=build(model,tmp_path,missing)
    assert s['scope']['unresolved_objects']==1 and s['coverage']['processes_analyzed']==0


def test_study_storage_immutable_idempotent_and_checksum(tmp_path):
    d=definition();key=ms.save_definition(tmp_path,d);original=(tmp_path/(key+'.json')).read_bytes()
    assert ms.load_definition(tmp_path,key)==ms.Definition.model_validate(ms.normalized(d))
    assert ms.save_definition(tmp_path,d)==key and (tmp_path/(key+'.json')).read_bytes()==original
    with pytest.raises(ValueError):ms.load_definition(tmp_path,'../bad')
    (tmp_path/(key+'.json')).write_text('{}')
    with pytest.raises(ValueError):ms.load_definition(tmp_path,key)


def test_cancellation_and_scoped_source_reads(model,tmp_path):
    def cancel(**event):raise TaskCancelled()
    with pytest.raises(TaskCancelled):ms.build(model,definition(),wb.indexed_graph(model,'synthetic-module'),tmp_path,cancel)
    class Scoped:
        def execute(self,sql,args=None):
            if any(field in sql.lower() for field in ['select prolog,','select rules from']):assert 'where' in sql.lower()
            return model.execute(sql,args) if args is not None else model.execute(sql)
    assert build(Scoped(),tmp_path)['outputs']


def test_module_routes_and_api_full_cycle(client,model,tmp_path,monkeypatch):
    import tm1_insight.api.module_spec as api
    from tm1_insight.tasks import TaskManager
    class Store:
        def connect(self,read_only=False):
            assert read_only
            return model.cursor()
        settings=type('Settings',(),{'db_path':Path('synthetic'), 'model_copy':lambda self:self,'user_data_root':tmp_path})()
    store=Store();d=definition()
    def guard(snapshot):
        if snapshot and snapshot!=d.snapshot_id:
            from fastapi import HTTPException
            raise HTTPException(409,'model changed')
        return store,d.snapshot_id
    monkeypatch.setattr(api,'guard',guard);monkeypatch.setattr(api,'index',lambda *a:wb.indexed_graph(model,d.snapshot_id));monkeypatch.setattr(api,'root',lambda:tmp_path/'studies')
    tasks=TaskManager(tmp_path/'results');monkeypatch.setattr(api,'manager',lambda:tasks);monkeypatch.setattr(api,'Store',lambda settings:store);monkeypatch.setattr(api,'fingerprint',lambda *a:d.snapshot_id)
    assert client.get('/module-reconstruction?kind=cube&name=Cube_B').status_code==200
    body=d.model_dump(mode='json')
    p=client.post('/api/module-spec/preview',json=body);assert p.status_code==200
    saved=client.post('/api/module-spec/definitions',json=body).json()
    assert client.get('/api/module-spec/definitions/'+saved['id']).json()['members']
    task=client.post('/api/module-spec/tasks',json=body);assert task.status_code==202
    key=task.json()['task_id']
    try:
        for _ in range(100):
            state=client.get('/api/module-spec/tasks/'+key).json()
            if state['status'] in {'completed','failed'}:break
            time.sleep(.02)
        assert state['status']=='completed',state
        result=client.get('/api/module-spec/tasks/'+key+'/result');assert result.json()['outputs']
        assert 'module_reconstruction_' in client.get('/api/module-spec/tasks/'+key+'/result?format=markdown').headers['content-disposition']
        assert client.get('/api/module-spec/tasks/'+key+'/result?download=true').json()==result.json()
        assert client.post('/api/module-spec/tasks',json={**body,'snapshot_id':'other'}).status_code==409
    finally:tasks.close()
