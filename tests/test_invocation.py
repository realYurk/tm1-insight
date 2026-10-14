import hashlib
import json
import re

import pytest
from test_datasource_api import client  # noqa: F401
from test_calculation_api import seed
from tm1_insight.config import get_settings
from tm1_insight.store.db import Store


def prepare(client, calls=None, child_code=None, declarations=None):
    seed(client)
    con = Store(get_settings()).connect()
    child = child_code or "value=pAmount*pRate; CellPutN(value,'Result',pDept); CellPutN(1,pTarget,pDept);"
    params = declarations or ['pAmount','pRate','pDept','pTarget','pDefault','password']
    con.execute('INSERT INTO processes (name,data,parameters) VALUES (?,?,?)', ['Child',child,
        json.dumps([dict(name=n,value='PRIVATE_DEFAULT_CANARY') for n in params])])
    code = calls or "amount=CellGetN('Input',pDept); ExecuteProcess('Child','pAmount',amount,'pRate',2,'pDept',pDept,'pTarget',pTarget); ExecuteProcess(pDynamic);"
    con.execute('INSERT INTO processes (name,prolog,parameters) VALUES (?,?,?)', ['Entry',code,
        json.dumps([dict(name='pDept'),dict(name='pTarget'),dict(name='pDynamic')])])
    con.close()
    response = client.get('/calculation',params={'name':'Entry'})
    assert response.status_code == 200
    return re.search(r'source=([a-f0-9]{64})',response.text)[1]


def exported(client, source, call=0):
    response=client.get('/api/invocation/export',params=dict(name='Entry',call=call,source=source))
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    return response.json()


def test_explicit_binding_has_separate_source_and_child_usage_evidence(client):
    source=prepare(client)
    path=get_settings().db_path
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    r=exported(client,source)
    assert not r['runtime_verified'] and r['scope']=='one_call_one_child_no_substitution'
    assert r['child']['process']=='Child' and r['source_hash']!=r['child']['source_hash']
    amount,rate,dept,target=r['bindings']
    assert amount['parameter']=='pAmount' and amount['status']=='EXPLICIT_BINDING'
    nodes={n['id']:n for n in r['nodes']}
    assert [nodes[i]['cube'] for i in amount['read_nodes']]==['Input']
    assert amount['uses'][0]['role']=='write_value'
    assert amount['uses'][0]['write_expression']=='value = pAmount * pRate'
    assert {u['role'] for u in dept['uses']}=={'write_coordinate'}
    assert target['uses'][0]['role']=='write_target' and target['uses'][0]['cube'] is None
    assert rate['expression']=='2' and r['omitted_parameters']==['pDefault']
    assert 'PRIVATE_DEFAULT_CANARY' not in json.dumps(r)
    html=client.get('/invocation',params=dict(name='Entry',call=0,source=source))
    assert html.status_code==200 and 'Input' in html.text and '写入值定义' in html.text
    assert '核对参数' in client.get('/calculation',params=dict(name='Entry')).text
    md=client.get('/api/invocation/export',params=dict(name='Entry',call=0,source=source,format='markdown'))
    assert 'write_value' in md.text and '子 TI 源码哈希' in md.text
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    dynamic=exported(client,source,1)
    assert dynamic['child'] is None and 'UNKNOWN' in dynamic['diagnostics'][0]


@pytest.mark.parametrize('call,reason',[
    ("ExecuteProcess('Child','pAmount',1,'pAmount',2);",'重复参数'),
    ("ExecuteProcess('Child','notDeclared',1);",'声明'),
    ("ExecuteProcess('Child',pDynamic,1);",'声明'),
    ("ExecuteProcess('Child','pAmount',1,'pRate');",'配对'),
    ("ExecuteProcess('Child','password','SECRET_LITERAL_CANARY');",'敏感参数'),
])
def test_invalid_or_sensitive_binding_never_claims_usage(client,call,reason):
    source=prepare(client,call)
    r=exported(client,source)
    assert all(b['status']=='UNKNOWN' and not b['uses'] for b in r['bindings'])
    assert reason in r['bindings'][0]['reason']
    assert 'SECRET_LITERAL_CANARY' not in json.dumps(r)


@pytest.mark.parametrize('code',[
    "RunProcess('Child','pAmount',1);",
    "vChild='Child';ExecuteProcess(vChild,'pAmount',1);",
    "ExecuteProcess('Missing','pAmount',1);",
])
def test_only_supported_literal_invocations_expand(client,code):
    source=prepare(client,code)
    assert exported(client,source)['child'] is None


def test_branch_boundary_and_overwritten_child_parameter_stop_usage(client):
    source=prepare(client,"If(pDynamic@='x');ExecuteProcess('Child','pAmount',1);EndIf;",
        child_code="pAmount=7;CellPutN(pAmount,'Result',pDept);")
    r=exported(client,source)
    assert r['call']['control_context'][0]['kind']=='if'
    assert r['bindings'][0]['uses']==[]


def test_calls_on_one_line_remain_distinct_and_source_guarded(client):
    source=prepare(client,"ExecuteProcess('Child','pAmount',1);ExecuteProcess('Child','pAmount',2);")
    a,b=exported(client,source,0),exported(client,source,1)
    assert a['call']['column']!=b['call']['column']
    assert a['bindings'][0]['expression']=='1' and b['bindings'][0]['expression']=='2'
    assert client.get('/invocation',params=dict(name='Entry',call=99,source=source)).status_code==404
    assert client.get('/invocation',params=dict(name='Entry',call=-1,source=source)).status_code==422
    assert client.get('/invocation',params=dict(name='Entry',call=0)).status_code==422
    assert client.get('/api/invocation/export',params=dict(name='Entry',call=0,source='0'*64)).status_code==409


def test_coordinate_dependencies_are_separate_from_value_parameter_use(client):
    source=prepare(client,"ExecuteProcess('Child','pAmount',1,'pDept',pDept,'pTarget',pTarget);",
        child_code="v=CellGetN(pTarget,pDept);CellPutN(v*pAmount,'Result',pDept);")
    bindings={b['parameter']:b for b in exported(client,source)['bindings']}
    assert {u['role'] for u in bindings['pAmount']['uses']}=={'write_value'}
    assert {u['role'] for u in bindings['pDept']['uses']}=={'read_coordinate','write_coordinate'}
    assert {u['role'] for u in bindings['pTarget']['uses']}=={'read_target'}


def test_unsupported_function_and_caller_branch_stop_value_claims(client):
    source=prepare(client,"If(pDynamic@='x');v=1;Else;v=2;EndIf;ExecuteProcess('Child','pAmount',v);",
        child_code="CellPutN(UnknownFunction(pAmount),'Result',pDept);")
    binding=exported(client,source)['bindings'][0]
    assert binding['unknown_nodes'] and not binding['read_nodes']
    assert binding['uses']==[]


def test_literal_cube_argument_does_not_silently_substitute_child_target(client):
    source=prepare(client,"ExecuteProcess('Child','pTarget','Result');")
    r=exported(client,source)
    assert r['bindings'][0]['parameter']=='pTarget'
    assert r['bindings'][0]['uses'][0]['cube'] is None
    assert r['child']['writes'][1]['resolution']=='parameter'


def test_cyclic_child_call_does_not_expand_recursively(client):
    source=prepare(client,child_code="CellPutN(pAmount,'Result',pDept);ExecuteProcess('Entry');")
    r=exported(client,source)
    assert r['child']['calls'][0]['target']=='Entry'
    assert 'child' not in r['child']


def test_unknown_caller_read_coordinate_is_not_lost_at_read_boundary(client):
    source=prepare(client,"amount=CellGetN('Input',vMissing);ExecuteProcess('Child','pAmount',amount);")
    binding=exported(client,source)['bindings'][0]
    assert binding['read_nodes'] and binding['unknown_nodes']
