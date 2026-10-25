"""Synthetic-only contracts for the read-only Cube lineage presentation."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_architecture import con  # noqa: F401
from test_datasource_api import client  # noqa: F401
from test_engineering_workbench import graph
from tm1_insight.store.calculation import inspect


def seed(con):
    """Deliberately mixed sources: an unrelated read must not become value flow."""
    con.execute("INSERT INTO process_reads_cube VALUES ('Load','Cube_A')")
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')")
    params=json.dumps([{'Name':'pYear'}])
    cases=[
        ('Unbound', "discard=CellGetN('Cube_A',pYear,'Member1');CellIncrementN(vValue,'Cube_B',pYear,'Member1','Member2');", ['Cube_A'],['Cube_B']),
        ('Multiple', "a=CellGetN('Cube_A',pYear,'Member1');ignored=CellGetN('Journal',pYear);CellPutN(a*2,'Cube_B',pYear,'Member1','Member2');CellPutN(vUnknown,'Cube_B',pYear,'Member2','Member1');", ['Cube_A','Journal'],['Cube_B']),
        ('Self', "a=CellGetN('Cube_B',pYear,'Member1','Member2');CellPutN(a,'Cube_B',pYear,'Member1','Member2');", ['Cube_B'],['Cube_B']),
        ('Dynamic', "a=CellGetN(vCube,pYear);CellPutN(a,'Cube_B',pYear,'Member1','Member2');", [],['Cube_B']),
    ]
    for name,data,reads,writes in cases:
        con.execute('INSERT INTO processes(name,prolog,metadata,data,epilog,parameters) VALUES (?,?,?,?,?,?)',[name,'','',data,'',params])
        for cube in reads:con.execute('INSERT INTO process_reads_cube VALUES (?,?)',[name,cube])
        for cube in writes:con.execute('INSERT INTO process_writes_cube VALUES (?,?)',[name,cube])
    con.execute("INSERT INTO cubes VALUES ('Unrelated','[]','',false,0)")


def js(value, expression):
    node=shutil.which('node')
    if not node:pytest.skip('Node is required for presentation contract tests')
    source=Path('src/tm1_insight/api/static/cube-lineage.js').read_text(encoding='utf-8')
    script="global.window={};global.document={getElementById:()=>null};\n"+source+"\nconst data="+json.dumps(value)+";console.log(JSON.stringify("+expression+"));"
    result=subprocess.run([node],input=script,capture_output=True,text=True,encoding='utf-8',check=True)
    return json.loads(result.stdout)


def payload(con,process):
    result=inspect(con,process)
    return dict(writes=result['writes'],reads=[n for n in result['nodes'] if n['kind']=='read'])


def test_cube_projection_multiple_ti_rule_and_self_loop(con):
    seed(con)
    result=graph(con,objects=[{'name':'Cube_B'}],depth=1)
    rows=js(result,'window.TM1CubeLineage.relations(data)')
    candidate=next(r for r in rows if r['source_name']=='Cube_A' and r['target_name']=='Cube_B')
    assert set(candidate['process_names'])=={'Load','Unbound','Multiple'}
    assert candidate['status']=='CANDIDATE' and not candidate['runtime_verified']
    assert any(r['source_name']==r['target_name']=='Cube_B' for r in rows)
    assert any(r['kind']=='RULE_REFERENCE' and r['target_name']=='RuleOutput' for r in rows)
    assert not any(r['source_name']=='Unrelated' or r['target_name']=='Unrelated' for r in rows)
    assert all(n['type']=='cube' for n in result['nodes'])


@pytest.mark.parametrize('direction,absent',[('upstream','RuleOutput'),('downstream','Cube_A')])
def test_cube_direction(con,direction,absent):
    seed(con)
    result=graph(con,objects=[{'name':'Cube_B'}],depth=1,direction=direction)
    assert absent not in {n['name'] for n in result['nodes']}


def test_unknown_source_known_target_does_not_promote_observed_reads(con):
    seed(con)
    rows=js(payload(con,'Unbound'),"window.TM1CubeLineage.writeRows(data,'Cube_A','Cube_B')")
    assert len(rows)==1 and rows[0]['operation']=='CellIncrementN'
    assert not rows[0]['source_reads'] and not rows[0]['source_observations']
    assert [(s['dimension'],s['kind'],s['value']) for s in rows[0]['target_slices']]==[
        ('Year','动态','pYear'),('Region','固定','Member1'),('Measure','固定','Member2')]
    assert rows[0]['trace_status']!='STATIC'


def test_multiple_reads_and_writes_are_independent(con):
    seed(con)
    data=payload(con,'Multiple')
    actual=js(data,"window.TM1CubeLineage.writeRows(data,'Cube_A','Cube_B')")
    unrelated=js(data,"window.TM1CubeLineage.writeRows(data,'Journal','Cube_B')")
    assert len(actual)==2 and len(actual[0]['source_reads'])==1
    assert not actual[1]['source_reads']
    assert all(not row['source_reads'] for row in unrelated)
    assert actual[0]['target_slices'][1]['value']!=actual[1]['target_slices'][1]['value']
    assert actual[0]['evidence']['section']=='data'


def test_unknown_cube_not_filled_from_name_or_index(con):
    seed(con)
    rows=js(payload(con,'Dynamic'),"window.TM1CubeLineage.writeRows(data,'Cube_A','Cube_B')")
    assert rows and not rows[0]['source_reads'] and rows[0]['trace_status']!='STATIC'


def test_legacy_mapping_without_binding_is_unknown():
    result=js({'items':[{'position':1,'dimension':None}]},'window.TM1CubeLineage.slices(data)')
    assert result[0]['kind']=='待确认'


def test_cube_entry_and_legacy_ti_routes(client):
    assert 'cl-root' in client.get('/graph?cube=Cube_B').text
    assert 'cl-root' in client.get('/graph').text
    assert 'ti-search' in client.get('/graph?ti=').text
    assert 'data-read-only="true"' in client.get('/architecture?view=workbench').text
    assert client.get('/codegen').status_code==200


def test_writes_api_preserves_old_fields_and_adds_read_evidence(client,monkeypatch,con):
    import tm1_insight.api.workbench as api
    seed(con)
    # A read-only lease prevents the endpoint from closing the fixture connection.
    class Lease:
        def execute(self,*a,**k):return con.execute(*a,**k)
        def close(self):pass
    class ReadOnlyStore:
        def connect(self,read_only=False):
            assert read_only
            return Lease()
    monkeypatch.setattr(api,'guard',lambda snapshot:(ReadOnlyStore(),'synthetic'))
    data=client.get('/api/workbench/writes',params={'snapshot_id':'synthetic','process':'Multiple'}).json()
    assert data['total']==2 and data['read_total']==1 and not data['runtime_verified']
    assert {'coordinate_mapping','value_expression','evidence','read_nodes','control_context'}<=data['writes'][0].keys()
    assert {'coordinate_mapping','evidence','resolution'}<=data['reads'][0].keys()


def test_unrelated_read_observation_cannot_supply_a_write_slice():
    data={'writes':[{'cube':'B','read_nodes':[],'coordinate_mapping':{'items':[]}}],
          'reads':[{'id':7,'cube':'A','coordinate_mapping':{'items':[]}}]}
    rows=js(data,"window.TM1CubeLineage.writeRows(data,'A','B')")
    assert not rows[0]['source_reads'] and len(rows[0]['source_observations'])==1


def exported(value):
    return js(value,'window.TM1CubeLineage.markdownReport(data.result,data.entry,data.relations,data.inspected,data.snapshot_id)')


def test_human_export_keeps_independent_writes_and_technical_contract(con):
    seed(con)
    writes=js(payload(con,'Multiple'),"window.TM1CubeLineage.writeRows(data,'Cube_A','Cube_B')")
    writes[0]['control_context']=[{'condition':'pRun = 1','section':'data','line':1}]
    value=dict(entry='Cube_B',snapshot_id='synthetic',result={'limits':{},'rule_scope':{'complete':True}},
               relations=[dict(id='ab',source_name='Cube_A',target_name='Cube_B',label='TI 候选处理关联',process_names=['Multiple'])],
               inspected=[dict(relation='ab',process='Multiple',writes=writes,total=2,read_total=1)])
    md=exported(value)
    human=md.split('## 技术证据附录')[0]
    assert '## 已核对的切面与计算' in human and r'a \* 2' in human
    assert 'Region = Member1（固定）' in human and 'Year = pYear（动态）' in human
    assert 'data:1:72' in human and 'data:1:121' in human and 'data:1:3' in human
    write_lines=[line for line in human.splitlines() if line.startswith('| data:')]
    assert len(write_lines)==2 and '静态读取依赖' in write_lines[0]
    assert '本表未确认该源切面' in write_lines[1] and 'vUnknown' in write_lines[1]
    assert 'VIEW 值列依赖分别投影' in human
    assert '| data:1:121' in human.split('条件（未求值）')[0]  # Conditions cannot break a Markdown table.
    assert '<details>' in md and '```json' not in human
    appendix=json.loads(md.split('```json\n')[1].split('\n```')[0])
    assert appendix['schema']=='cube-lineage-review-1' and len(appendix['inspected'][0]['writes'])==2
    assert not appendix['inspected'][0]['writes'][1]['source_reads']


def test_human_export_rule_unknowns_escaping_scope_and_deterministic_evidence():
    row=dict(id='rule',source_name='Cube_A',target_name='Cube_B',label='Rule 声明式引用')
    rule=dict(status='PARTIAL',line_start=9,lhs={'raw':"['Member1']"},rhs={'expression':"IF(pDynamic, DB('Cube_A', !Year), UnknownFn(1))"},
              db_references=[{'cube':'Cube_A','cube_resolved':True},{'cube':'pDynamic','cube_resolved':False}],conditions=['pDynamic'])
    value=dict(entry='Cube_B',snapshot_id='synthetic',result={'limits':{'truncated':True}},relations=[row],
               inspected=[dict(relation='rule',rules=[rule])])
    md=exported(value);human=md.split('## 技术证据附录')[0]
    assert 'Rule 为声明式计算' in human and 'Rule:9:1' in human
    assert r'| Cube\_A | 已记录（未求值） |' in human and 'UnknownFn(1)' in human
    assert '裸成员的维度归属与动态坐标' in human and '截断：是' in human
    assert '部分解析；未确认项见附录' in human
    value['relations'][0]['source_name']='Cube|A\n# <script>'
    escaped=exported(value).split('## 技术证据附录')[0]
    assert 'Cube\\|A \\# \\<script\\>' in escaped
    value['inspected'].append(dict(relation='rule',process='Later',writes=[]))
    forward=exported(value)
    value['inspected'].reverse()
    assert exported(value)==forward
    value['inspected']=[]
    assert '尚未主动核对 TI 写入点或 Rule' in exported(value)


def test_query_races_cancel_and_export_keep_the_loaded_cube():
    """Run the actual browser controller with deferred, abort-ignoring fetches."""
    node=shutil.which('node')
    if not node:pytest.skip('Node needed for browser controller behavior checks')
    source=Path('src/tm1_insight/api/static/cube-lineage.js').read_text(encoding='utf-8')
    harness=r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
class Element {
  constructor(){this.children=[];this.dataset={};this.value='';this.textContent='';this.disabled=false;this.attrs={};this.classList={add(){},remove(){}};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(name,value){this.attrs[name]=value;}
  scrollIntoView(){this.scrolled=true;}
  focus(){this.focused=true;}
  click(){}
}
const ids=new Map(),get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
get('cl-direction').value='both';
let requests=[],blob,location='';
const context={window:{addEventListener(){}},document:{getElementById:get,createElement:()=>new Element()},
  fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject})),
  AbortController,URLSearchParams,Blob,URL:{createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}},
  history:{replaceState:(a,b,url)=>{location=url;}},setTimeout:()=>0,clearTimeout(){},console};
vm.runInNewContext(SOURCE,context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function start(name){get('cl-name').value=name;get('cl-search').onsubmit({preventDefault(){}});return requests.at(-1);}
function done(req,name){req.resolve({ok:true,json:async()=>({snapshot_id:'synthetic',nodes:[],edges:[],limits:{},query:{objects:[{name}]}})});}
(async()=>{
  const old=start('Cube_A'),current=start('Cube_B');
  assert.equal(old.options.signal.aborted,true);
  // Editing the search field is not a new query or a new evidence scope.
  get('cl-name').value='Not_Queried';done(current,'Cube_B');await tick();
  assert.match(get('cl-summary').children[0].textContent,/^Cube_B /);
  assert.equal(get('cl-summary').children[1].href,'/explorer/cube/Cube_B');
  get('cl-export').onclick();assert.match(await blob.text(),/入口：Cube\\_B/);
  assert.equal(location,'/graph?cube=Cube_B&model=synthetic');
  const completed=get('cl-status').textContent;
  old.reject(new Error('obsolete request failed'));await tick();
  assert.equal(get('cl-status').textContent,completed);
  const staleSuccess=start('Cube_A'),latest=start('Cube_B');
  done(latest,'Cube_B');await tick();done(staleSuccess,'Cube_A');await tick();
  assert.match(get('cl-summary').children[0].textContent,/^Cube_B /);
  const withRelations=start('Cube_B');
  withRelations.resolve({ok:true,json:async()=>({snapshot_id:'synthetic',limits:{},
    nodes:['Cube_A','Cube_B','Cube_C'].map(name=>({id:name,name,type:'cube'})),
    edges:[{id:'ab',source:'Cube_A',target:'Cube_B',kind:'TI_CANDIDATE',process_names:['Load']},
           {id:'cb',source:'Cube_C',target:'Cube_B',kind:'RULE_REFERENCE'}]})});await tick();
  const table=get('cl-table').children[0],panels=get('cl-details').children;
  assert.equal(table.children.length,3); // Header + relations only, no embedded evidence rows.
  const first=table.children[1].children[5].children[0],second=table.children[2].children[5].children[0];
  await first.onclick();assert.equal(panels[0].hidden,false);assert.equal(first.attrs['aria-expanded'],'true');
  assert.equal(panels[0].scrolled,true);
  const initial=panels[0].children.length;
  await first.onclick();assert.equal(panels[0].hidden,true);
  await first.onclick();assert.equal(panels[0].children.length,initial); // No duplicate panel content.
  await second.onclick();assert.equal(panels[0].hidden,true);assert.equal(panels[1].hidden,false);
  await panels[1].children[0].children[1].onclick();assert.equal(panels[1].hidden,true);
  assert.equal(second.focused,true);
  assert.equal(second.attrs['aria-expanded'],'false');
  const cancelled=start('Cube_A');get('cl-cancel').onclick();
  assert.equal(get('cl-details').children.length,0);
  const status=get('cl-status').textContent;assert.equal(cancelled.options.signal.aborted,true);
  cancelled.reject(new Error('late cancellation failure'));await tick();
  assert.equal(get('cl-status').textContent,status);assert.equal(get('cl-export').disabled,true);
  assert(requests.every(r=>r.url==='/api/workbench/graph'&&r.options.method==='POST'));
  console.log('race, cancellation, result identity and read-only requests verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    completed=subprocess.run([node],input=harness.replace('SOURCE',json.dumps(source)),capture_output=True,text=True,encoding='utf-8',check=True)
    assert 'verified' in completed.stdout
