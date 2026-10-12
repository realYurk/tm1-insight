from types import SimpleNamespace
from tm1_insight.tm1.client import TM1Client
from tm1_insight.config import Settings


def test_rules_normalize_actual_tm1py_and_string_payloads():
    from TM1py.Objects import Cube
    for cube in (Cube('Synthetic',[],rules="['A']=N:1;"),{'Rules':"['A']=N:1;"},{'rules':"['A']=N:1;"}):
        tm1=SimpleNamespace(cubes=SimpleNamespace(get=lambda name:cube))
        assert TM1Client.read_cube_rules(tm1,'Synthetic')==("['A']=N:1;",'available')


def test_empty_rule_and_unavailable_rule_are_different():
    tm1=SimpleNamespace(cubes=SimpleNamespace(get=lambda name:{'Rules':None}))
    assert TM1Client.read_cube_rules(tm1,'Synthetic')==('','available')
    def fail(*args,**kwargs):raise RuntimeError('synthetic permission error')
    tm1=SimpleNamespace(cubes=SimpleNamespace(get=fail),_rest=SimpleNamespace(GET=fail))
    assert TM1Client.read_cube_rules(tm1,'Synthetic')==('','unavailable')


def test_rule_rest_fallback_escapes_name_and_accepts_scalar_json():
    requested=[]
    def fail(name):raise RuntimeError()
    def read(url):requested.append(url);return SimpleNamespace(json=lambda:{'Rules':"['A']=N:1;"})
    tm1=SimpleNamespace(cubes=SimpleNamespace(get=fail,get_dimension_names=lambda name:[]),_rest=SimpleNamespace(GET=read))
    value=TM1Client(Settings()).fetch_cube(tm1,"A'B")
    assert value['rules_status']=='available' and value['has_rules']
    assert "A''B" in requested[0]
