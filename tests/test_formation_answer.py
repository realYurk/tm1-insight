"""Answers must explain constants/parameters and never promote co-access."""
import json
from test_architecture import con  # noqa: F401
from test_datasource_api import client  # noqa: F401
from module_spec_fixture import seed
from tm1_insight.store.calculation import inspect
from tm1_insight.formation_answer import ti, rule
from tm1_insight.store.queries import cube_rule_semantics


def answer(con,name,dimension='',member=''):
    return ti(inspect(con,name),'synthetic','Cube_B',dimension,member)


def test_constant_and_source_expression_are_distinct(con):
    seed(con)
    a=answer(con,'ConstantLoad')['groups'][0]
    assert a['value_kind']=='CONSTANT' and not a['sources']
    assert not a['blocker_refs'] and a['evidence_state']=='CONFIRMED_STATIC'
    assert not answer(con,'ConstantLoad')['truncated']
    b=answer(con,'Load')['groups'][0]
    assert b['value_kind']=='SOURCE_EXPRESSION'
    assert {s['cube'] for s in b['sources']}=={'Cube_A'}
    assert not b['runtime_verified']
    assert any(c['kind']=='DYNAMIC' and c['expression']=='vYear' for c in b['coordinates'])


def test_nativeview_missing_variables_and_shared_root(con):
    seed(con)
    good=answer(con,'ViewLoad')
    assert good['groups'][0]['sources'][0]['kind']=='VIEW_VALUE'
    assert good['groups'][1]['value_kind']=='CONSTANT'
    missing=answer(con,'MissingVariables')
    assert not missing['groups'][0]['sources']
    assert missing['blockers']
    assert not missing['groups'][1]['blocker_refs']


def test_conditions_modes_and_slice_matching(con):
    code="IF(pYear @= 'Member1');CellPutN(1,'Cube_B',pYear,'Member1','Member1');ELSE;CellIncrementN(2,'Cube_B',pYear,'Member1','Member2');ENDIF;"
    con.execute("INSERT INTO processes(name,prolog,metadata,data,epilog,parameters) VALUES ('Branches','','',?,'',?)",[code,json.dumps([dict(Name='pYear')])])
    a=answer(con,'Branches')
    assert {g['operation'] for g in a['groups']}=={'CellPutN','CellIncrementN'}
    assert all(g['conditions'] for g in a['groups'])
    assert len(answer(con,'Branches','Measure','Member1')['groups'])==1
    assert answer(con,'Branches','Year','Member1')['groups'][0]['match']=='POSSIBLE'
    assert not answer(con,'Branches','Measure','NotPresent')['groups']


def test_rule_retains_reference_without_claiming_feeder_as_formula(con):
    a=rule(cube_rule_semantics(con,'RuleOutput'),'synthetic','RuleOutput')
    assert len(a['groups'])==1 and a['feeder_count']==1
    assert a['groups'][0]['operation']=='RULE'
    assert a['groups'][0]['sources'][0]['cube']=='Cube_B'
    assert a['groups'][0]['evidence_state']=='PARTIAL'


def test_plan_and_item_use_readonly_actual_endpoints(client,monkeypatch,con):
    import tm1_insight.api.workbench as api
    seed(con)
    class Lease:
        def execute(self,*args,**kwargs):return con.execute(*args,**kwargs)
        def close(self):pass
    class Local:
        def connect(self,read_only=False):
            assert read_only
            return Lease()
    monkeypatch.setattr(api,'guard',lambda snapshot:(Local(),'synthetic'))
    p=client.get('/api/workbench/formation-plan',params={'cube':'Cube_B','budget':1}).json()
    assert p['truncated'] and p['writers_selected']==1
    p=client.get('/api/workbench/formation-plan',params={'cube':'Cube_B'}).json()
    assert any(j['name']=='ConstantLoad' for j in p['jobs'])
    a=client.get('/api/workbench/formation-item',params={'cube':'Cube_B','kind':'TI','name':'ConstantLoad','snapshot_id':'synthetic'})
    assert a.status_code==200 and a.json()['groups'][0]['value_kind']=='CONSTANT'
    assert client.get('/api/workbench/formation-plan',params={'cube':'missing'}).status_code==404
    assert client.get('/api/workbench/formation-item',params={'cube':'Cube_B','kind':'RULE','name':'RuleOutput','snapshot_id':'synthetic'}).status_code==422


def test_real_answer_controller_cancel_retry_partial_and_snapshot_invalidation():
    import shutil, subprocess
    from pathlib import Path
    import pytest
    node=shutil.which('node')
    if not node: pytest.skip('Node is required for browser controller state checks')
    source=Path('src/tm1_insight/api/static/formation-answer.js').read_text(encoding='utf-8')
    harness=r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
class Element {
 constructor(){this.value='';this.dataset={};this.children=[];this.events={};this.style={};this.textContent='';}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;}
 addEventListener(event,fn){this.events[event]=fn;}
 click(){}
}
const ids=new Map(),get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
get('fa-budget').value='12';
let mode='cancel',pending,active=0,maxActive=0,firstTries=0,blob;
const response=(value,status=200)=>({ok:status===200,status,json:async()=>value});
const result={snapshot_id:'snapshot',groups:[],blockers:[],truncated:false};
const fetch=async(url,options)=>{
 if(url.includes('formation-plan'))return response({snapshot_id:'snapshot',jobs:[{kind:'TI',name:'First'},{kind:'TI',name:'Second'}],scope:'synthetic'});
 active++;maxActive=Math.max(active,maxActive);
 try {
  if(mode==='cancel')return await new Promise((resolve,reject)=>{pending={resolve,reject};options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('cancel'),{name:'AbortError'})));});
  if(mode==='stale')return response({},409);
  if(url.includes('name=First')&&mode==='failure'&&firstTries++===0)return response({},500);
  return response(result);
 }finally{active--;}
};
const context={window:{addEventListener(){}},document:{getElementById:get,createElement:()=>new Element()},
 fetch,AbortController,URLSearchParams,Blob,URL:{createObjectURL:b=>{blob=b;return 'blob:x';},revokeObjectURL(){}},setTimeout,console};
vm.runInNewContext(SOURCE,context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const submit=()=>get('cl-search').events.submit({preventDefault(){}});
(async()=>{
 get('cl-name').value='Cube_B';submit();await tick();assert.match(get('fa-status').textContent,/分析中/);
 get('fa-cancel').events.click();await tick();assert.match(get('fa-status').textContent,/已取消/);
 mode='failure';get('fa-retry').onclick();await tick();await tick();
 assert.match(get('fa-status').textContent,/部分失败/);assert.match(get('fa-status').textContent,/1 \/ 2/);
 get('fa-retry').onclick();await tick();await tick();assert.match(get('fa-status').textContent,/已完成.*2 \/ 2/);
 get('fa-export').onclick();assert.equal(JSON.parse(await blob.text()).task_status,'COMPLETED');
 assert.equal(maxActive,1,'high fan-in stays sequential');
 mode='stale';submit();await tick();await tick();assert.match(get('fa-status').textContent,/失败/);
 assert.equal(get('fa-export').disabled,true,'old-snapshot results are not exportable');
 console.log('cancel/retry/partial/snapshot verified');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    p=subprocess.run([node],input=harness.replace('SOURCE',json.dumps(source)),text=True,capture_output=True,encoding='utf-8',check=True)
    assert 'verified' in p.stdout
