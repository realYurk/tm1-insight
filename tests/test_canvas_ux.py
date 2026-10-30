"""Synthetic front-end layout contracts. No browser or company model access."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

STATIC=Path(__file__).parents[1]/'src/tm1_insight/api/static'


def layout(nodes,edges,options=None):
    node=shutil.which('node')
    if not node:pytest.skip('Node is a development-only dependency for pure JS layout tests')
    code="const fs=require('fs'),vm=require('vm');global.window={};vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));const a=JSON.parse(process.argv[2]);console.log(JSON.stringify(window.TM1CanvasLayout.compute(a.nodes,a.edges,a.options)));"
    p=subprocess.run([node,'-e',code,str(STATIC/'canvas-layout.js'),json.dumps(dict(nodes=nodes,edges=edges,options=options or {}))],capture_output=True,text=True,check=True)
    return json.loads(p.stdout)


def objects(count):return [dict(id=f'n{i:03}',name='Synthetic object '+str(i),type='cube') for i in range(count)]


def test_high_degree_hub_defaults_to_directional_not_radial():
    nodes=objects(31);edges=[dict(source=nodes[0]['id'],target=n['id']) for n in nodes[1:]]
    r=layout(nodes,edges)
    assert r['strategy']=='layered'
    assert all(r['positions'][e['source']]['x']<r['positions'][e['target']]['x'] for e in edges)


def test_chain_merges_branches_and_top_bottom():
    nodes=objects(5);edges=[dict(source='n000',target='n002'),dict(source='n001',target='n002'),dict(source='n002',target='n003'),dict(source='n002',target='n004')]
    a=layout(nodes,edges);b=layout(nodes,edges,{'direction':'TB'})
    for e in edges:
        assert a['positions'][e['source']]['x']<a['positions'][e['target']]['x']
        assert b['positions'][e['source']]['y']<b['positions'][e['target']]['y']
    assert all(a['positions'][n['id']]['x']==b['positions'][n['id']]['y'] for n in nodes)


def test_cycles_and_self_loop_are_finite_and_separated():
    nodes=objects(9);edges=[dict(source=f'n{i:03}',target=f'n{(i+1)%7:03}') for i in range(7)]+[dict(source='n007',target='n007')]
    r=layout(nodes,edges);points=list(r['positions'].values())
    assert len(points)==9 and r['sccCount']==3
    for i,p in enumerate(points):
        assert abs(p['x'])<100000 and abs(p['y'])<100000
        for q in points[i+1:]:assert abs(p['x']-q['x'])>=80 or abs(p['y']-q['y'])>=90


def test_large_bounded_hub_and_empty_layout():
    nodes=objects(120);edges=[dict(source=nodes[0]['id'],target=n['id']) for n in nodes[1:]]
    r=layout(nodes,edges)
    assert len(r['positions'])==120
    assert layout([],[])['positions']=={}


def test_input_order_does_not_change_direction_or_positions():
    nodes=objects(5);edges=[dict(source='n000',target='n001'),dict(source='n000',target='n002'),dict(source='n002',target='n004')]
    assert layout(nodes,edges)==layout(nodes[::-1],edges[::-1])


def test_lineage_names_remain_complete_and_layout_reserves_height():
    node=shutil.which('node')
    if not node:pytest.skip('Node is required for presentation checks')
    name='Cub.General Ledger.Data.Load.From.CSV.Long.中文坐标.测试名称'
    code="const fs=require('fs'),vm=require('vm');global.window={};vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));console.log(JSON.stringify(window.TM1Canvas.lineageLabel(process.argv[2])));"
    p=subprocess.run([node,'-e',code,str(STATIC/'canvas-graph.js'),name],capture_output=True,text=True,encoding='utf-8',check=True)
    label=json.loads(p.stdout)
    assert label['text'].replace('\n','')==name and label['height']>54
    nodes=[dict(id='a',name=name,type='process',width=label['width']),dict(id='b',name='B',type='process',width=300)]
    positions=layout(nodes,[],{'rowHeight':label['height']+30})['positions']
    assert abs(positions['a']['y']-positions['b']['y'])>=label['height']+30


@pytest.mark.parametrize('name', [
    'Cub.General Ledger.Data.COST.Load.From.CSV',
    '含中文的维度名称和很长的程序名称及😀字符',
    'WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW',
])
def test_lineage_label_uses_available_width_without_losing_text(name):
    node=shutil.which('node')
    if not node:pytest.skip('Node is required for presentation checks')
    code="const fs=require('fs'),vm=require('vm');global.window={};vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));console.log(JSON.stringify(window.TM1Canvas.lineageLabel(process.argv[2])));"
    result=subprocess.run([node,'-e',code,str(STATIC/'canvas-graph.js'),name],capture_output=True,text=True,encoding='utf-8',check=True)
    label=json.loads(result.stdout)
    assert label['text'].replace('\n','')==name
    assert label['height'] >= len(label['text'].split('\n'))*21+12
    if name.startswith('Cub.General'):
        assert len(label['text'].split('\n')) <= 3


def test_lineage_sources_keep_left_column_and_wide_layers_do_not_wrap():
    nodes=[dict(id='file',name='input.csv',type='source',width=270,height=48),
           dict(id='source-less',name='independent TI',type='process',width=270,height=48),
           dict(id='root',name='General Ledger',type='cube',width=270,height=48)]
    nodes += [dict(id=f'ti{i}',name=f'Process {i}',type='process',width=270,height=60+i) for i in range(12)]
    edges=[dict(source='file',target='ti0'),dict(source='ti0',target='root')]
    edges += [dict(source='root',target=f'ti{i}') for i in range(1,12)]
    edges += [dict(source='source-less',target='root')]
    result=layout(nodes,edges,{'lineage':True});positions=result['positions']
    assert positions['file']['x'] < positions['source-less']['x'] < positions['root']['x']
    assert positions['file']['x'] < positions['ti0']['x'] < positions['root']['x']
    downstream=[positions[f'ti{i}'] for i in range(1,12)]
    assert len({p['x'] for p in downstream}) == 1
    for a,b in zip(sorted(downstream,key=lambda p:p['y']),sorted(downstream,key=lambda p:p['y'])[1:]):
        assert b['y']-a['y'] >= 90


def test_lineage_layout_cycles_are_finite_and_input_order_stable():
    nodes=[dict(id='file',name='input.csv',type='source',height=48),dict(id='a',name='A',type='cube',height=60),dict(id='b',name='B',type='process',height=80)]
    edges=[dict(source='file',target='b'),dict(source='b',target='a'),dict(source='a',target='b')]
    one=layout(nodes,edges,{'lineage':True})
    assert one['positions']==layout(nodes[::-1],edges[::-1],{'lineage':True})['positions']
    assert one['positions']['file']['x'] < one['positions']['a']['x']
    assert one['positions']['a']['y'] != one['positions']['b']['y']


def test_lineage_readback_retains_separate_file_ti_cube_layers():
    nodes=[dict(id='file',name='input.csv',type='source'),dict(id='load',name='Load',type='process'),
           dict(id='root',name='Root',type='cube',current=True),dict(id='next',name='Next',type='process'),
           dict(id='result',name='Result',type='cube')]
    edges=[dict(source='file',target='load'),dict(source='load',target='root'),
           dict(source='root',target='load'),dict(source='root',target='next'),dict(source='next',target='result')]
    result=layout(nodes,edges,{'lineage':True})
    positions=result['positions']
    assert all(positions[a]['x'] < positions[b]['x'] for a,b in [('file','load'),('load','root'),('root','next'),('next','result')])
    assert result['positions']==layout(nodes[::-1],edges[::-1],{'lineage':True})['positions']
