"""Synthetic evidence boundaries of the shared diagram presentation."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_architecture import con  # noqa: F401
from test_datasource_api import client  # noqa: F401
from test_workflow_review import artifact


def view(value, expr):
    node=shutil.which('node')
    if not node: pytest.skip('Node is required to exercise the browser view model')
    source=Path('src/tm1_insight/api/static/lineage-view.js').read_text(encoding='utf-8')
    script='global.window={};\n'+source+'\nconst data='+json.dumps(value)+';console.log(JSON.stringify('+expr+'));'
    result=subprocess.run([node],input=script,text=True,capture_output=True,encoding='utf-8',check=True)
    return json.loads(result.stdout)


def test_cube_candidates_partial_and_resolved_are_separate():
    row={'id':'AB','kind':'TI_CANDIDATE','source':'A','target':'B','process_names':['T1','T2']}
    write={'source_reads':[{'cube':'A'}],'source_data_rows':[]}
    records=[{'relation':'AB','process':'T1','writes':[write]}]
    assert view({'row':row,'records':[]},'window.TM1LineageView.edgeSummary(data.row,data.records)')['state']=='CANDIDATE'
    mixed=view({'row':row,'records':records},'window.TM1LineageView.edgeSummary(data.row,data.records)')
    assert mixed['state']=='PARTIAL_STATIC_VALUE_DEPENDENCY' and '含候选' in mixed['label']
    records.append({'relation':'AB','process':'T2','writes':[]})
    assert view({'row':row,'records':records},'window.TM1LineageView.edgeSummary(data.row,data.records)')['state']=='PARTIAL_STATIC_VALUE_DEPENDENCY'
    records[1]['writes']=[write]
    assert view({'row':row,'records':records},'window.TM1LineageView.edgeSummary(data.row,data.records)')['state']=='STATIC_VALUE_DEPENDENCY'
    records[1]['truncated']=True
    assert view({'row':row,'records':records},'window.TM1LineageView.edgeSummary(data.row,data.records)')['state']=='PARTIAL_STATIC_VALUE_DEPENDENCY'


def test_cube_roles_bounds_and_safe_long_labels():
    long_name='Ledger '+('very long ' * 10)+'"<script>alert(1)</script>'
    nodes=[{'id':str(i),'name':long_name if i==1 else str(i),'type':'cube'} for i in range(30)]
    edges=[{'id':f'e{i}','kind':'TI_CANDIDATE','source':str(i),'target':'0','process_names':['T']} for i in range(1,30)]
    data={'graph':{'snapshot_id':'s','nodes':nodes,'limits':{}},'edges':edges}
    result=view(data,"(()=>{const m=window.TM1LineageView.cubeModel(data.graph,data.edges,'0');return {model:m,chart:window.TM1LineageView.mermaid(m)};})()")
    assert len(result['model']['nodes'])==24 and result['model']['display_limits']['nodes_hidden']==6
    assert result['model']['nodes'][0]['current']
    assert '<script>' not in result['chart']['code'] and '"<script>' not in result['chart']['code']
    assert any(n['name']==long_name for n in result['chart']['idMap'].values())


def test_flow_budget_keeps_connected_paths_and_prioritizes_recorded_file():
    data={'result':{'snapshot_id':'s','nodes':[{'id':'a','name':'A','type':'cube'},
          {'id':'b','name':'B','type':'cube'},{'id':'orphan','name':'Unrelated','type':'cube'}], 'limits':{}},
          'rows':[{'id':'ab','source':'a','target':'b','kind':'TI_CANDIDATE','process_names':[f'Load{i}' for i in range(40)]}],
          'inputs':[{'type':'file','name':'input.csv','process':'Load0','target':'B'}]}
    result=view(data,"window.TM1LineageView.flowModel(data.result,data.rows,'B',data.inputs)")
    nodes={n['id'] for n in result['nodes']};edges=result['edges']
    assert len(nodes)<=24 and len(edges)<=30 and result['display_truncated']
    assert 'orphan' not in nodes and any(n['name']=='input.csv' for n in result['nodes'])
    reached={'b'}
    for _ in nodes:
        for e in edges:
            if e['source'] in reached: reached.add(e['target'])
            if e['target'] in reached: reached.add(e['source'])
    assert reached==nodes
    assert all(e['source'] in nodes and e['target'] in nodes for e in edges)
    assert any(e['label']=='数据源声明' and e['state']=='CANDIDATE' for e in edges)


def test_layered_layout_places_file_before_process_and_cube():
    node=shutil.which('node')
    if not node: pytest.skip('Node is required for layout checks')
    source=Path('src/tm1_insight/api/static/canvas-layout.js').read_text(encoding='utf-8')
    script="global.window={};\n"+source+"\n"+r'''
const nodes=[{id:'file',name:'input.csv',type:'source'},{id:'ti',name:'Load',type:'process'},{id:'cube',name:'B',type:'cube'}];
const edges=[{source:'file',target:'ti'},{source:'ti',target:'cube'}];
console.log(JSON.stringify(window.TM1CanvasLayout.compute(nodes,edges,{strategy:'layered',direction:'LR'}).positions));
'''
    positions=json.loads(subprocess.run([node],input=script,text=True,capture_output=True,encoding='utf-8',check=True).stdout)
    assert positions['file']['x'] < positions['ti']['x'] < positions['cube']['x']


def test_large_fanout_keeps_complete_process_paths():
    cubes=[{'id':'root','name':'Root','type':'cube'}]+[{'id':f'c{i}','name':f'Target{i}','type':'cube'} for i in range(40)]
    rows=[{'id':f'r{i}','source':'root','target':f'c{i}','kind':'TI_CANDIDATE','process_names':[f'Load{i}']} for i in range(40)]
    data={'result':{'snapshot_id':'s','nodes':cubes,'limits':{}},'rows':rows}
    model=view(data,"window.TM1LineageView.flowModel(data.result,data.rows,'Root')")
    assert model['display_truncated'] and len(model['nodes'])<=24 and len(model['edges'])<=30
    processes=[n for n in model['nodes'] if n['type']=='process']
    assert processes
    for process in processes:
        ins=[e for e in model['edges'] if e['target']==process['id']]
        outs=[e for e in model['edges'] if e['source']==process['id']]
        assert ins and outs and ins[0]['source']=='root'
        assert any(n['id']==outs[0]['target'] and n['type']=='cube' for n in model['nodes'])
        assert ins[0]['state']=='CANDIDATE'


def test_calls_keep_direction_conditions_cycles_dynamic_and_index():
    c=lambda a,b,**extra:dict(process=a,target=b,**extra)
    data={'process':'A','snapshot_id':'s','analyzed_process_names':['A','B'],
          'calls':[c('A','B',section='data',line=2,control_context=[{'condition':'p=1'}]),c('A',None)],
          'downstream_calls':[c('B','A',section='data',line=3)],
          'callers':[c('B','A'),c('Outside','A')], 'schedules':[{'chore':'Nightly'}]}
    result=view(data,"window.TM1LineageView.callModel(data)")
    assert [(e['source'],e['target']) for e in result['edges']]==[('A','B'),('B','A'),('Outside','A')]
    assert [e['state'] for e in result['edges']]==['CONDITIONAL_CALL','SOURCE_CALL','INDEX_CALL']
    assert len(result['dynamic_calls'])==1 and result['schedules'][0]['chore']=='Nightly'
    chart=view(data,"window.TM1LineageView.mermaid(window.TM1LineageView.callModel(data))")
    assert '条件调用' in chart['code'] and '索引调用入口' in chart['code']


def test_review_existing_scoped_child_and_reject_outside(client,monkeypatch,con,tmp_path):
    import tm1_insight.api.workflow as api
    a=artifact(con,tmp_path,'Caller')
    class Lease:
        def execute(self,*args):return con.execute(*args)
        def close(self):pass
    class Local:
        def __init__(self,*args):pass
        def connect(self,read_only=False):
            assert read_only
            return Lease()
    monkeypatch.setattr(api,'path',lambda task:a.path)
    monkeypatch.setattr(api,'state',lambda task:{})
    monkeypatch.setattr(api,'Store',Local)
    try:
        root=client.get('/api/workflow/tasks/synthetic/review').json()
        assert 'Load' in root['analyzed_process_names']
        child=client.get('/api/workflow/tasks/synthetic/review',params={'process':'Load'})
        assert child.status_code==200 and child.json()['process']=='Load'
        assert child.json()['snapshot_id']==root['snapshot_id']
        assert not child.json()['downstream_calls']
        assert any('原入口报告' in item for item in child.json()['limitations'])
        assert client.get('/api/workflow/tasks/synthetic/review',params={'process':'not-in-scope'}).status_code==404
    finally:a.cleanup()


def test_picker_keyboard_clear_and_model_history():
    node=shutil.which('node')
    if not node: pytest.skip('Node is required to exercise the browser picker')
    source=Path('src/tm1_insight/api/static/lineage-search.js').read_text(encoding='utf-8')
    harness=r'''
const vm=require('vm');
class E {constructor(){this.events={};this.children=[];this.value='';this.hidden=true;this.attrs={};this.dataset={};} addEventListener(k,f){this.events[k]=f;} removeEventListener(){} setAttribute(k,v){this.attrs[k]=v;} removeAttribute(k){delete this.attrs[k];} replaceChildren(){this.children=[];} append(x){this.children.push(x);} scrollIntoView(){} focus(){} }
const input=new E(), list=new E(), status=new E(), clear=new E(), form=new E();
form.dataset={model:'model-1',lineageSearch:'cube'};form.querySelector=()=>input;form.contains=()=>true;
let submits=0;form.requestSubmit=()=>{submits++;form.events.submit();};
const storage={};const sessionStorage={getItem:k=>storage[k]||null,setItem:(k,v)=>storage[k]=v};
const document={querySelector:()=>form,getElementById:id=>({'lineage-search-results':list,'lineage-search-status':status,'lineage-clear':clear}[id]),createElement:()=>new E(),addEventListener(){},removeEventListener(){}};
const window={addEventListener(){}};const fetch=async()=>({ok:true,json:async()=>({snapshot_id:'model-1',objects:[{name:'Alpha'},{name:'Beta'}],total:2})});
vm.runInNewContext(SOURCE,{window,document,fetch,sessionStorage,AbortController,URLSearchParams,setTimeout,clearTimeout});
(async()=>{input.value='A';input.events.focus();await new Promise(r=>setImmediate(r));
 if(list.children.length!==2||input.value!=='A')throw Error('unexpected default selection');
 let prevented=0;input.events.keydown({key:'ArrowDown',preventDefault(){prevented++}});input.events.keydown({key:'ArrowDown',preventDefault(){prevented++}});input.events.keydown({key:'Enter',preventDefault(){prevented++}});
 if(input.value!=='Beta'||submits!==1||prevented!==3)throw Error('keyboard selection failed');
 if(!storage['tm1-lineage-search:model-1:cube'].includes('Beta'))throw Error('history not scoped');
 clear.events.click();await new Promise(r=>setImmediate(r));if(input.value!==''||list.children.length!==1||list.children[0].textContent!=='Beta')throw Error('clear/history failed');
 console.log('ok');})().catch(e=>{console.error(e);process.exitCode=1;});
'''.replace('SOURCE',json.dumps(source))
    result=subprocess.run([node,'-e',harness],capture_output=True,text=True,encoding='utf-8',check=True)
    assert result.stdout.strip()=='ok'


def test_lineage_canvas_has_offline_distinct_icons():
    node=shutil.which('node')
    if not node: pytest.skip('Node is required for canvas icon checks')
    source=Path('src/tm1_insight/api/static/canvas-graph.js').read_text(encoding='utf-8')
    script='global.window={};\n'+source+'\nconsole.log(JSON.stringify(window.TM1Canvas.icons));'
    icons=json.loads(subprocess.run([node],input=script,text=True,capture_output=True,encoding='utf-8',check=True).stdout)
    from urllib.parse import unquote
    cube=unquote(icons['cube']);file=unquote(icons['lineageFile']);gear=unquote(icons['lineageGear'])
    assert cube.count('<polygon')==3
    assert '<path' in file and 'M15 21h18' in file
    assert '<circle' in gear and 'cx=\'24\'' in gear and "width='192'" in gear
    assert all(value.startswith('data:image/svg+xml;utf8,') for value in (icons['cube'],icons['lineageFile'],icons['lineageGear']))
