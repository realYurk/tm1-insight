"""导出的范围和页面必须是同一把尺子。

这条约束看着琐碎，但它决定用户能不能对上账：屏幕写「已隐藏 1 条」，
下载下来却是全量，核对材料的人会以为自己在看两份不同的东西，
然后开始怀疑是不是自己数错了。

所以这里钉住四件事：
1. 页面显示几条，导出就是几条；
2. ``system=1`` 能拿回全部，且导出正文自己说明「这次是全量」；
3. 隐藏时逐条留账（数量、立方体名、构成），并保留原始编号（允许跳号，不许重编）；
4. 用法位置被隐藏时要特别喊停——「这里少了一条」不能被读成「这个参数没被用到」。
"""
import json
import re
from collections import Counter

import pytest
from test_datasource_api import client  # noqa: F401
from test_calculation_api import seed
from tm1_insight.config import get_settings
from tm1_insight.store.db import Store


def _source(page):
    return re.search(r'source=([a-f0-9]{64})', page.text)[1]


def _shown(page):
    return int(re.search(r'选择写入点 <span class="tag">(\d+)</span>', page.text)[1])


def prepare_invocation(client):
    """父 TI 调一个子 TI，子 TI 把同一个参数写进业务立方体和 } 系统立方体。"""
    seed(client)
    con = Store(get_settings()).connect()
    con.execute('INSERT INTO processes (name,data,parameters) VALUES (?,?,?)', ['Child',
        "v=CellGetN('Input',pDept)*pAmount; CellPutN(v,'Result',pDept); CellPutN(pAmount,'}Audit',pDept);",
        json.dumps([dict(name='pAmount'), dict(name='pDept')])])
    con.execute('INSERT INTO processes (name,prolog,parameters) VALUES (?,?,?)', ['Entry',
        "ExecuteProcess('Child','pAmount',1,'pDept','D1');",
        json.dumps([dict(name='pDept')])])
    con.close()
    page = client.get('/calculation', params={'name': 'Entry'})
    assert page.status_code == 200
    return _source(page)


def test_calculation_export_is_the_list_on_screen(client):
    seed(client)
    page = client.get('/calculation', params={'name': 'Compute'})
    assert page.status_code == 200
    source = _source(page)
    data = client.get('/api/calculation/export', params=dict(name='Compute', source=source)).json()
    assert _shown(page) == len(data['writes']) == 1
    assert data['writes'][0]['cube'] == 'Result'
    assert data['scope_view'] == dict(scope='business', visible=1, hidden=1,
                                      cubes=['}Audit'], write_ids=[1], system_count=1)
    full = client.get('/api/calculation/export',
                      params=dict(name='Compute', source=source, system=1)).json()
    assert [w['cube'] for w in full['writes']] == ['Result', '}Audit']
    assert full['scope_view'] == dict(scope='all', visible=2, hidden=0, cubes=[], write_ids=[],
                                      system_count=1)


def test_export_explains_the_difference_in_its_own_text(client):
    seed(client)
    source = _source(client.get('/calculation', params={'name': 'Compute'}))
    md = client.get('/api/calculation/export',
                    params=dict(name='Compute', source=source, format='markdown')).text
    assert '## 收录范围' in md
    assert '另有 1 条记录未包含在本文件内' in md
    assert '`}Audit`' in md and 'system=1' in md
    assert '会出现跳号' in md
    full = client.get('/api/calculation/export',
                      params=dict(name='Compute', source=source, format='markdown', system=1)).text
    assert '范围：全量（含 } 前缀系统对象）' in full and '另有' not in full


def test_hidden_rows_keep_their_original_numbers(client):
    """系统写入点排在前面时，剩下的那条不能因为被显示而改叫「写入 1」。"""
    seed(client)
    con = Store(get_settings()).connect()
    con.execute('UPDATE processes SET data=? WHERE name=?',
                ["CellPutN(1,'}Audit',pDept);\nv=CellGetN('Input',pDept);\nCellPutN(v,'Result',pDept);", 'Compute'])
    con.close()
    source = _source(client.get('/calculation', params={'name': 'Compute'}))
    data = client.get('/api/calculation/export', params=dict(name='Compute', source=source)).json()
    assert [w['id'] for w in data['writes']] == [1]
    md = client.get('/api/calculation/export',
                    params=dict(name='Compute', source=source, format='markdown')).text
    assert '## 写入 2' in md and '## 写入 1' not in md


def test_nothing_hidden_is_stated_plainly(client):
    seed(client)
    con = Store(get_settings()).connect()
    con.execute('UPDATE processes SET data=? WHERE name=?',
                ["v=CellGetN('Input',pDept);\nCellPutN(v,'Result',pDept);", 'Compute'])
    con.close()
    page = client.get('/calculation', params={'name': 'Compute'})
    assert '这个 TI 没有 } 前缀写入点' in page.text and '已隐藏 0 条' not in page.text
    source = _source(page)
    md = client.get('/api/calculation/export',
                    params=dict(name='Compute', source=source, format='markdown')).text
    assert '本次没有需要隐藏的记录' in md
    assert client.get('/api/calculation/export',
                      params=dict(name='Compute', source=source, system=1)).json()['scope_view']['hidden'] == 0


def test_invocation_hides_system_usage_and_warns_about_it(client):
    source = prepare_invocation(client)
    page = client.get('/invocation', params=dict(name='Entry', call=0, source=source))
    assert page.status_code == 200
    assert page.text.count('范围 · 还有 1 条使用位置指向 } 前缀立方体') == 2
    narrow = client.get('/api/invocation/export',
                        params=dict(name='Entry', call=0, source=source)).json()
    # 被波及的不止目标参数：pDept 作为 }Audit 的坐标也少了一条，
    # 所以这里记 2 条使用位置 + 1 条子 TI 写入点。
    assert narrow['scope_view'] == dict(scope='business', hidden=3, cubes=['}Audit'], uses=2, writes=1,
                                        bindings_affected=2, system_count=3, visible_uses=3, visible_writes=1)
    by_name = {b['parameter']: b for b in narrow['bindings']}
    assert [u['cube'] for u in by_name['pAmount']['uses']] == ['Result']
    assert [b['uses_hidden'] for b in narrow['bindings'] if b.get('uses_hidden')] == [1, 1]
    assert [w['cube'] for w in narrow['child']['writes']] == ['Result']

    full = client.get('/api/invocation/export',
                      params=dict(name='Entry', call=0, source=source, system=1)).json()
    # 全量 5 条：Result 3 条（pAmount 写入值、pDept 写入坐标、pDept 读取坐标）+ }Audit 2 条
    assert Counter(u['cube'] for b in full['bindings'] for u in b['uses']) == {'Result': 3, '}Audit': 2}
    assert narrow['scope_view']['visible_uses'] == 3
    assert [w['cube'] for w in full['child']['writes']] == ['Result', '}Audit']

    md = client.get('/api/invocation/export',
                    params=dict(name='Entry', call=0, source=source, format='markdown')).text
    assert '另有 3 条记录未包含在本文件内' in md
    assert '空白不等于未使用' in md and '2 个参数的「子 TI 使用」一栏因此变短' in md


def test_invocation_page_can_switch_back_to_full(client):
    source = prepare_invocation(client)
    page = client.get('/invocation', params=dict(name='Entry', call=0, source=source))
    assert 'system=1' in page.text and '包含 } 前缀内容' in page.text
    wide = client.get('/invocation', params=dict(name='Entry', call=0, source=source, system=1))
    assert wide.status_code == 200 and '}Audit' in wide.text
    assert '只看业务对象' in wide.text


@pytest.mark.parametrize('url', [
    '/api/calculation/export?name=Compute&source=' + 'a' * 64 + '&system=maybe',
    '/api/invocation/export?name=Compute&call=0&source=' + 'a' * 64 + '&system=maybe',
])
def test_scope_flag_rejects_garbage(client, url):
    seed(client)
    assert client.get(url).status_code == 422
