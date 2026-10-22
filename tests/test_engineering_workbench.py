"""Offline workbench contracts. Formal databases are never opened writable."""
import hashlib
import json
import pytest
from pydantic import ValidationError
from tm1_insight import workbench as wb
from tm1_insight.domain.model import Dependency, DependencyKind
from tm1_insight.lineage.engine import get_downstream
from test_architecture import con as architecture_con  # noqa: F401
from test_datasource_api import client  # noqa: F401


@pytest.fixture
def con(architecture_con):
    # The older architecture fixture intentionally exercises ti_flows and source
    # fallback without access indexes. This suite explicitly tests those indexes.
    architecture_con.execute("INSERT INTO process_reads_cube VALUES ('Load','Cube_A')")
    architecture_con.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_B')")
    return architecture_con


def graph(con, **kwargs):
    from tm1_insight.store.queries import cube_rule_semantics
    from tm1_insight.workbench_rules import project
    nodes,edges=wb.indexed_graph(con,'snap')
    for (cube,) in con.execute('SELECT name FROM cubes WHERE has_rules').fetchall():
        edges=edges+project(cube_rule_semantics(con,cube),'snap')
    return wb.query_graph((nodes,edges), wb.GraphQuery(**kwargs), 'snap')


def test_cube_candidate_not_value_flow_and_rule_distinct(con):
    result=graph(con, objects=[{'name':'Cube_A'}])
    e=next(e for e in result['edges'] if e['kind']=='TI_CANDIDATE')
    assert e['status']=='CANDIDATE' and not e['runtime_verified']
    assert {x['table'] for x in e['evidence']}=={'process_reads_cube','process_writes_cube'}
    assert e['process_name']=='Load'
    assert any(e['kind']=='RULE_REFERENCE' for e in result['edges'])
    assert not any('value_flow' in e for e in result['edges'])


def test_direct_read_write_orientation_and_multiple_semantics(con):
    result=graph(con,objects=[{'type':'process','name':'Load'}],view='objects')
    names={n['id']:n['name'] for n in result['nodes']}
    edges={(names[e['source']],names[e['target']],e['kind']) for e in result['edges']}
    assert ('Cube_A','Load','TI_READ') in edges
    assert ('Load','Cube_B','TI_WRITE') in edges
    assert all(e['evidence'] for e in result['edges'])


def test_prefix_path_and_no_invented_paths(con):
    yes=graph(con, source_prefix='Cube_A*',target_prefix='RuleOutput*',depth=4)
    assert yes['paths'] and {e['kind'] for e in yes['edges']}=={'TI_CANDIDATE','RULE_REFERENCE'}
    no=graph(con, source_prefix='RuleOutput',target_prefix='Cube_A',depth=4)
    assert not no['paths'] and not no['edges']
    assert not graph(con,source_prefix='Missing',target_prefix='Cube_A')['edges']


def test_depth_budget_cycle_and_self_loop(con):
    con.execute("INSERT INTO process_writes_cube VALUES ('Load','Cube_A')")
    r=graph(con,objects=[{'name':'Cube_A'}],depth=1,node_budget=2)
    assert len(r['nodes'])<=2 and any(e['source']==e['target'] for e in r['edges'])
    assert r['limits']['truncated']
    zero=graph(con,objects=[{'name':'Cube_A'}],depth=0)
    assert len(zero['nodes'])==1
    assert all(e['source']==e['target'] for e in zero['edges'])


def test_stable_order_identity_and_different_snapshot(con):
    q=wb.GraphQuery(objects=[wb.ObjectRef(name='Cube_A')])
    a=wb.query_graph(wb.indexed_graph(con,'snap'),q,'snap')
    assert a==wb.query_graph(wb.indexed_graph(con,'snap'),q,'snap')
    b=wb.query_graph(wb.indexed_graph(con,'other'),q,'other')
    assert not {n['id'] for n in a['nodes']} & {n['id'] for n in b['nodes']}


def test_dedupe_and_technical_filter(con):
    con.execute("INSERT INTO process_reads_cube VALUES ('Load','Cube_A')")
    con.execute("INSERT INTO cubes VALUES ('}System','[]','',false,0)")
    con.execute("INSERT INTO process_reads_cube VALUES ('Load','}System')")
    a=graph(con,objects=[{'type':'process','name':'Load'}],view='objects',depth=1)
    assert not any(n['name']=='}System' for n in a['nodes'])
    assert len({e['id'] for e in a['edges']})==len(a['edges'])
    b=graph(con,objects=[{'type':'process','name':'Load'}],view='objects',include_technical=True,depth=1)
    assert any(n['name']=='}System' for n in b['nodes'])


def test_relation_filter_and_missing(con):
    a=graph(con,objects=[{'name':'Cube_B'}],relation_types=['RULE_REFERENCE'])
    assert all(e['kind']=='RULE_REFERENCE' for e in a['edges'])
    missing=graph(con,objects=[{'name':'missing'}])
    assert missing['limits']['missing']==[{'type':'cube','name':'missing'}]
    assert not missing['nodes']


def test_unclassified_rule_index_never_exposed_as_computation(con):
    result=wb.query_graph(wb.indexed_graph(con,'snap'),wb.GraphQuery(objects=[wb.ObjectRef(name='RuleOutput')]),'snap')
    assert not any(e['kind'].startswith('RULE') for e in result['edges'])


def test_feeder_direction_separate_and_not_value_flow(con):
    r=graph(con,objects=[{'name':'RuleOutput'}],include_technical=True)
    names={n['id']:n['name'] for n in r['nodes']}
    feeder=next(e for e in r['edges'] if e['kind']=='FEEDER_REFERENCE')
    rule=next(e for e in r['edges'] if e['kind']=='RULE_REFERENCE')
    assert names[feeder['source']]=='RuleOutput' and names[feeder['target']]=='Cube_B'
    assert names[rule['source']]=='Cube_B' and names[rule['target']]=='RuleOutput'
    assert feeder['id']!=rule['id'] and feeder['evidence'][0]['line']!=rule['evidence'][0]['line']
    assert not feeder['runtime_verified']


def test_multiple_tis_aggregate_only_same_semantics(con):
    con.execute("INSERT INTO processes(name) VALUES ('Other')")
    con.execute("INSERT INTO process_reads_cube VALUES ('Other','Cube_A')")
    con.execute("INSERT INTO process_writes_cube VALUES ('Other','Cube_B')")
    r=graph(con,objects=[{'name':'Cube_A'}])
    edge=next(e for e in r['edges'] if e['kind']=='TI_CANDIDATE')
    assert sorted(edge['process_names'])==['Load','Other'] and len(edge['evidence'])==4


def test_prefix_page_is_deterministic_and_snapshot_qualified(con):
    for i in range(25):con.execute('INSERT INTO cubes VALUES (?,?,?,?,?)',[f'SC{i:02}','[]','',False,0])
    a=graph(con,source_prefix='SC*',depth=0,node_budget=30)
    b=graph(con,source_prefix='SC*',seed_offset=20,depth=0,node_budget=30)
    assert len(a['nodes'])==20 and len(b['nodes'])==5
    assert a['limits']['next_seed_offset']==20 and b['limits']['next_seed_offset'] is None
    assert not {n['id'] for n in a['nodes']} & {n['id'] for n in b['nodes']}


def test_view_boundary_not_confused_with_budget_cut(con):
    """局部视图边界 ≠ 预算截断。边界外仍有对象是探索常态，不能恒报「已截断」。"""
    full=graph(con,objects=[{'name':'Cube_A'}],depth=2,node_budget=60)
    assert full['limits']['truncated'] is False
    cut=graph(con,objects=[{'name':'Cube_A'}],depth=2,node_budget=2)
    assert cut['limits']['truncated'] is True


def test_bounded_existing_lineage_retains_legacy(con):
    deps=[Dependency(DependencyKind.OTHER,str(i),str(i+1)) for i in range(30)]
    assert len(get_downstream(deps,'0'))==30
    assert len(get_downstream(deps,'0',max_depth=3,max_nodes=2))==2


def workspace():
    obj=wb.ObjectRef(name='Cube_A');key=wb.stable_id('snap','cube','Cube_A')
    return wb.Workspace(snapshot_id='snap',name='研究',objects=[obj],selected=[key],
        notes='人工说明，不是模型事实',mdx='SELECT ...',groups=[wb.Group(id='g1',name='甲',members=[key]),wb.Group(id='g2',name='乙',members=[key])],
        drafts=[wb.DraftCube(id='draft-cost',name='Cost',dimensions=['Year','Product'])],layout={'zoom':1.2,'x':4,'y':8})


def test_save_restore_notes_groups_drafts_and_idempotent(tmp_path):
    w=workspace();key='a'*32;rev=wb.save_workspace(tmp_path,key,w,'')
    restored,r=wb.load_workspace(tmp_path,key)
    assert restored==w and r==rev
    assert wb.save_workspace(tmp_path,key,w,rev)==rev
    assert (tmp_path/(key+'.json.bak')).read_bytes()==(tmp_path/(key+'.json')).read_bytes()
    assert restored.groups[0].provenance=='USER_INTERPRETATION'
    assert restored.drafts[0].provenance=='DESIGN_DRAFT'


def test_concurrent_revision_does_not_overwrite(tmp_path):
    key='a'*32;w=workspace();rev=wb.save_workspace(tmp_path,key,w,'');old=(tmp_path/(key+'.json')).read_bytes()
    with pytest.raises(FileExistsError):wb.save_workspace(tmp_path,key,w.model_copy(update={'notes':'bad'}),'wrong')
    assert (tmp_path/(key+'.json')).read_bytes()==old


def test_failed_replace_preserves_old_file(tmp_path,monkeypatch):
    key='a'*32;w=workspace();rev=wb.save_workspace(tmp_path,key,w,'');old=(tmp_path/(key+'.json')).read_bytes()
    def fail(*a):raise OSError('simulated disk error')
    monkeypatch.setattr(wb.os,'replace',fail)
    with pytest.raises(OSError):wb.save_workspace(tmp_path,key,w.model_copy(update={'notes':'new'}),rev)
    assert (tmp_path/(key+'.json')).read_bytes()==old
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('change',[
    {'selected':['dangling']},{'schema_version':'future'},{'query':{'snapshot_id':'other'}},
    {'layout':{'x':float('nan')}},{'layout':{'script':2}},
    {'groups':[{'id':'g','name':'fake','provenance':'MODEL_FACT'}]},
    {'drafts':[{'id':'draft-x','name':'fake','provenance':'VERIFIED_ASSET'}]},
])
def test_reject_unsafe_contract(change):
    with pytest.raises(ValidationError):wb.Workspace.model_validate({**workspace().model_dump(),**change})


def test_invalid_path_and_corrupt_file(tmp_path):
    with pytest.raises(ValueError):wb.load_workspace(tmp_path,'../model')
    (tmp_path/('b'*32+'.json')).write_text('{broken')
    with pytest.raises(ValueError):wb.load_workspace(tmp_path,'b'*32)


def test_api_workspace_isolation_and_legacy_pages(client):
    obj=client.get('/api/workbench/objects',params={'q':'','type':'cube'}).json()
    snapshot=obj['snapshot_id'];n=obj['objects'][0]
    data=client.post('/api/workbench/graph',json={'objects':[{'name':n['name']}],'snapshot_id':snapshot}).json()
    assert data['snapshot_id']==snapshot
    assert client.post('/api/workbench/graph',json={'snapshot_id':'other'}).status_code==409
    w=wb.Workspace(snapshot_id=snapshot,name='API 研究',objects=[{'type':'cube','name':n['name']}],selected=[n['id']]).model_dump()
    saved=client.post('/api/workbench/workspaces',json={'workspace':w}).json()
    assert client.get('/api/workbench/workspaces/'+saved['id']).json()['workspace']==w
    assert client.put('/api/workbench/workspaces/'+saved['id'],json={'workspace':w,'revision':'stale'}).status_code==409
    assert client.get('/architecture?view=workbench').status_code==200
    for route in ['/architecture','/codegen','/graph','/cubes']:
        assert client.get(route).status_code==200


def test_read_only_model_hash_and_targeted_source(con,tmp_path):
    # SQL tracing: indexed discovery must never SELECT TI / Rule source text.
    class NoSource:
        def execute(self,sql,*args):
            assert not any(s in sql.lower() for s in ('prolog','rules','select *','insert','update','delete'))
            return con.execute(sql,*args)
    wb.indexed_graph(NoSource(),'snap')


def test_ai_payload_or_cell_execution_not_in_workspace_contract():
    with pytest.raises(ValidationError):wb.Workspace.model_validate({**workspace().model_dump(),'credentials':{'password':'secret'}})
    with pytest.raises(ValidationError):wb.GraphQuery(node_budget=121)
    with pytest.raises(ValidationError):wb.GraphQuery(depth=7)


def test_visible_objects_filters_brace_technical_but_keeps_legal_names():
    from tm1_insight.api.workbench import visible_objects
    nodes = {
        'a': dict(id='a', type='cube', name='General Ledger'),
        'b': dict(id='b', type='cube', name='}APQ Cube Dependency'),
        'c': dict(id='c', type='cube', name=' Sys Parameter'),       # 前导空格，合法对象，不得排除
        'd': dict(id='d', type='cube', name='#####.#########'),      # 特殊符号名，合法对象，不得排除
        'e': dict(id='e', type='cube', name="'}DimensionProperties'"),  # 引号包裹，不匹配 } 前缀规则，不扩大过滤
    }
    # 默认过滤：只去掉纯 } 前缀
    visible = visible_objects(nodes, type='cube', q='', include_technical=False)
    names = {n['name'] for n in visible}
    assert '}APQ Cube Dependency' not in names
    assert ' Sys Parameter' in names
    assert '#####.#########' in names
    assert "General Ledger" in names
    # include_technical=True 保留全部
    all_names = {n['name'] for n in visible_objects(nodes, type='cube', q='', include_technical=True)}
    assert '}APQ Cube Dependency' in all_names
    # q 过滤与 type 过滤仍生效
    assert [n['name'] for n in visible_objects(nodes, type='cube', q='ledger', include_technical=False)] == ['General Ledger']
    assert visible_objects(nodes, type='process', q='', include_technical=False) == []
