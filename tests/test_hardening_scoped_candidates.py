"""Synthetic graph only: unrelated fan-out must not consume a local query budget."""
from tm1_insight.workbench import GraphQuery, ObjectRef, query_graph, stable_id


def test_unrelated_cartesian_fanout_cannot_hide_target_candidate():
    snapshot='synthetic'
    nodes={}
    cube_ids=[]
    for i in range(3000):
        name=f'Cube_{i:04}'
        key=stable_id(snapshot,'cube',name)
        nodes[key]=dict(id=key,name=name,type='cube')
        cube_ids.append(key)
    for i in range(3000):
        key=f'p{i:04}'
        nodes[key]=dict(id=key,name=f'Process_{i:04}',type='process')
    def edge(source,target,kind):
        return dict(id=f'{kind}:{source}:{target}',source=source,target=target,kind=kind,
                    evidence=[dict(table='synthetic',source=source,target=target)])
    # 230 × 230 unrelated candidate pairs sort before the target process.
    raw=[edge(cube_ids[i],'p0000','TI_READ') for i in range(230)]
    raw += [edge('p0000',cube_ids[230+i],'TI_WRITE') for i in range(230)]
    raw += [edge(cube_ids[2998],'p2999','TI_READ'),edge('p2999',cube_ids[2999],'TI_WRITE')]
    q=GraphQuery(objects=[ObjectRef(type='cube',name='Cube_2999')],view='cubes',depth=1,direction='upstream')
    result=query_graph((nodes,raw),q,snapshot)
    candidates=[e for e in result['edges'] if e['kind']=='TI_CANDIDATE']
    assert len(candidates)==1
    assert candidates[0]['source']==cube_ids[2998] and candidates[0]['target']==cube_ids[2999]
    assert candidates[0]['status']=='CANDIDATE' and candidates[0]['runtime_verified'] is False
    assert not result['limits']['truncated']


def test_rule_hop_then_process_hop_stays_candidate():
    s='s'
    nodes={}
    def add(kind,name):
        key=stable_id(s,kind,name);nodes[key]=dict(id=key,name=name,type=kind);return key
    a,b,c=[add('cube',name) for name in ('A','B','C')]
    p=add('process','Load')
    def e(source,target,kind):
        return dict(id=kind+source+target,source=source,target=target,kind=kind,evidence=[dict(table='fixture')])
    raw=[e(a,b,'RULE_REFERENCE'),e(b,p,'TI_READ'),e(p,c,'TI_WRITE')]
    result=query_graph((nodes,raw),GraphQuery(objects=[ObjectRef(name='A')],direction='downstream',depth=2),s)
    assert {(x['source'],x['target'],x['kind']) for x in result['edges']}=={(a,b,'RULE_REFERENCE'),(b,c,'TI_CANDIDATE')}
    assert next(x for x in result['edges'] if x['kind']=='TI_CANDIDATE')['status']=='CANDIDATE'


def test_module_preview_retains_more_than_24_explicit_objects():
    from tm1_insight import module_spec as ms
    s='fixture'; nodes={}
    for i in range(30):
        name=f'Cube_{i:02}';key=stable_id(s,'cube',name)
        nodes[key]=dict(id=key,name=name,type='cube')
    definition=ms.Definition(name='fixture',snapshot_id=s,entries=[dict(name='Cube_00')],
        members=[dict(name=f'Cube_{i:02}') for i in range(1,30)],node_budget=30,depth=0)
    result=ms.propose((nodes,[]),definition)
    assert {x['name'] for x in result['nodes']}=={f'Cube_{i:02}' for i in range(30)}


def test_local_candidate_budget_reports_incomplete_scope():
    s='fixture';nodes={}
    def add(kind,name):
        key=stable_id(s,kind,name);nodes[key]=dict(id=key,name=name,type=kind);return key
    reads=[add('cube',f'A{i:03}') for i in range(120)]
    writes=[add('cube',f'B{i:03}') for i in range(500)]
    process=add('process','Fanout')
    def edge(source,target,kind):
        return dict(id=kind+source+target,source=source,target=target,kind=kind,evidence=[dict(table='fixture')])
    raw=[edge(c,process,'TI_READ') for c in reads]+[edge(process,c,'TI_WRITE') for c in writes]
    q=GraphQuery(objects=[ObjectRef(name=f'A{i:03}') for i in range(120)],direction='downstream',depth=1,node_budget=120)
    result=query_graph((nodes,raw),q,s)
    assert result['limits']['candidate_budget_exhausted']
    assert result['limits']['candidate_retained']==50000
    assert result['limits']['truncated']


def test_boundary_includes_unexpanded_candidate_edges():
    s='fixture';nodes={}
    def add(kind,name):
        key=stable_id(s,kind,name);nodes[key]=dict(id=key,name=name,type=kind);return key
    a,b,c=[add('cube',name) for name in ('A','B','C')]
    p,q=[add('process',name) for name in ('One','Two')]
    def edge(source,target,kind):return dict(id=kind+source+target,source=source,target=target,kind=kind,evidence=[dict(table='fixture')])
    raw=[edge(a,p,'TI_READ'),edge(p,b,'TI_WRITE'),edge(b,q,'TI_READ'),edge(q,c,'TI_WRITE')]
    result=query_graph((nodes,raw),GraphQuery(objects=[ObjectRef(name='A')],direction='downstream',depth=1),s)
    assert {x['name'] for x in result['nodes']}=={'A','B'}
    assert result['limits']['boundary'] is True
