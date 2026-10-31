"""读取依赖也要按范围收，但绝不能收成「这个值没有来源」。

写入点被隐藏，读者看得见：列表短了一条，页面上还写着「另有 N 条」。
读取依赖被隐藏，读者看不见：定义链上只剩一个常量，他会当成这个值凭空算出来。
所以这一组测试钉住的不是「藏了几条」，是**藏了之后还说不说得清**：

1. 藏掉的读取依赖要报数、报名字、报构成；
2. 全部读取都被藏掉时，不能说「没有可确认的直接读取依赖」；
3. ``system=1`` 要能拿回来，且此时不再提示「未显示」；
4. 导出的 JSON 保留完整 ``read_nodes``（DAG 是推理依据，砍了就推不出结论），
   页面用 ``reads_shown``，两者差在哪要写在正文里。
"""
import json
import re

from test_datasource_api import client  # noqa: F401
from test_calculation_api import seed
from tm1_insight.config import get_settings
from tm1_insight.store.db import Store


def _seed_reads(client):
    """两个 TI：一个读业务 + 系统，一个只读系统。"""
    seed(client)
    con = Store(get_settings()).connect()
    con.execute("INSERT INTO cubes (name,dimension_count) VALUES ('}APQ Settings',1)")
    con.execute("INSERT INTO cube_has_dimension VALUES ('}APQ Settings','Dept',0)")
    con.execute('INSERT INTO processes (name,data,parameters) VALUES (?,?,?)', ['Mixed',
        "base=CellGetN('Input',pDept);\nsetting=CellGetN('}APQ Settings',pDept);\n"
        "v=base*setting;\nCellPutN(v,'Result',pDept);",
        json.dumps([dict(name='pDept')])])
    con.execute('INSERT INTO processes (name,data,parameters) VALUES (?,?,?)', ['OnlySystem',
        "s=CellGetN('}APQ Settings',pDept);\nCellPutN(s,'Result',pDept);",
        json.dumps([dict(name='pDept')])])
    con.close()


def _source(page_text):
    return re.search(r'source=([a-f0-9]{64})', page_text)[1]


def _section(page_text):
    """只取 ②「此定义链中的读取依赖」这一节，避免被页面别处的同名文字误导。"""
    start = page_text.index('<h3>②')
    return page_text[start:page_text.index('</section>', start)]


def test_system_reads_are_folded_but_named(client):
    _seed_reads(client)
    page = client.get('/calculation', params={'name': 'Mixed'})
    assert page.status_code == 200
    section = _section(page.text)
    assert '另有 1 条读取依赖未显示（1 条指向系统立方体）：}APQ Settings' in section
    assert '隐藏不等于这个值没有来源' in section
    assert 'CellGetN · <a' in section and '>Input</a>' in section

    data = client.get('/api/calculation/export',
                      params=dict(name='Mixed', source=_source(page.text))).json()
    write = data['writes'][0]
    nodes = {node['id']: node for node in data['nodes']}
    # DAG 不裁剪：read_nodes 仍是两条；页面显示的那条单独记在 reads_shown
    assert len(write['read_nodes']) == 2
    assert [nodes[i]['cube'] for i in write['reads_shown']] == ['Input']
    assert [nodes[i]['cube'] for i in write['reads_hidden']] == ['}APQ Settings']
    assert write['reads_hidden_cubes'] == ['}APQ Settings'] and write['reads_hidden_system'] == 1
    assert data['scope_view']['reads_hidden'] == 1 and data['scope_view']['reads_total'] == 2


def test_all_reads_folded_never_claims_there_is_no_source(client):
    _seed_reads(client)
    page = client.get('/calculation', params={'name': 'OnlySystem'})
    section = _section(page.text)
    assert '全部落在日志或系统立方体上' in section
    assert '没有可确认的直接读取依赖' not in section
    assert '已收起的系统读取' in page.text


def test_switching_to_full_shows_the_reads_without_the_warning(client):
    _seed_reads(client)
    page = client.get('/calculation', params={'name': 'Mixed', 'system': 1})
    section = _section(page.text)
    assert '}APQ Settings' in section and 'Input' in section
    assert '未显示' not in section


def test_export_says_where_the_two_views_differ(client):
    _seed_reads(client)
    page = client.get('/calculation', params={'name': 'Mixed'})
    md = client.get('/api/calculation/export',
                    params=dict(name='Mixed', source=_source(page.text),
                                format='markdown')).text
    assert '另有 1 条读取依赖未显示' in md
    assert 'writes[].read_nodes 仍是完整定义链' in md
    assert 'reads_shown 才是页面上那几条' in md


def test_full_export_has_no_reads_hidden(client):
    _seed_reads(client)
    page = client.get('/calculation', params={'name': 'Mixed', 'system': 1})
    data = client.get('/api/calculation/export',
                      params=dict(name='Mixed', source=_source(page.text), system=1)).json()
    assert data['scope_view']['reads_hidden'] == 0
    assert len(data['writes'][0]['reads_shown']) == 2
    assert data['writes'][0]['reads_hidden'] == []
