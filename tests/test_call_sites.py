"""调用点位置：从「A 调用 B」到「A 在第 12 行调用 B」。

这一组测试盯的是**位置属于谁**。2B 那次把被调用方的类型贴到调用方头上，
一次错 121 个节点；位置比类型更容易错——行号本身是对的，挂错了文件就毫无意义。

所以这里不测「有没有位置」，测：

1. 行号算得对（1 基，与计算检查页 evidence 同口径）；
2. 日志区域被抹掉，但**行号不变**（strip 会删行，删完就全错位）；
3. 下游节点的位置属于 root，上游节点的位置属于上游自己；
4. 同一目标调两次，只报第一处并记次数；
5. 动态目标没有位置——它不是固定成员，也就没有"那一行"。
"""
import json
import re

from test_datasource_api import client  # noqa: F401
from tm1_insight.config import get_settings
from tm1_insight.store import call_sites, queries
from tm1_insight.store.db import Store

LOG_BLOCK = ("#Region - Initialize Logging\n"
             "ExecuteProcess('Ghost');\n"
             "#EndRegion - Initialize Logging")


def _seed(client):
    client.get('/')
    con = Store(get_settings()).connect()
    for name in ('Input', 'Result'):
        con.execute('INSERT INTO cubes (name,dimension_count) VALUES (?,1)', [name])
        con.execute("INSERT INTO cube_has_dimension VALUES (?,'Dept',0)", [name])
    con.execute("INSERT INTO dimensions (name) VALUES ('Dept')")
    con.execute('INSERT INTO processes (name,prolog,data,parameters) VALUES (?,?,?,?)', [
        'Child', '', "v=CellGetN('Input',pDept);\nCellPutN(v,'Result',pDept);",
        json.dumps([dict(name='pDept')])])
    con.execute('INSERT INTO processes (name,prolog,data,parameters) VALUES (?,?,?,?)', [
        'Entry',
        "cYear=2026;\n" + LOG_BLOCK + "\n"
        "ExecuteProcess('Child','pDept','D1');\n"
        "ExecuteProcess('Child','pDept','D2');\n"
        "ExecuteProcess(sProc);",
        '', json.dumps([dict(name='pDept'), dict(name='sProc')])])
    # 调用边本身来自采集阶段的三张表，这里手工补一条，模拟真实采集结果
    con.execute("INSERT INTO process_calls_process VALUES ('Entry','Child')")
    # 一条「有边但没有可定位源码」的边：目标由未赋值变量拼出
    con.execute('INSERT INTO processes (name,data,parameters) VALUES (?,?,?)',
                ['Mystery', 'ExecuteProcess(sTarget);', json.dumps([dict(name='sTarget')])])
    con.execute("INSERT INTO process_calls_process VALUES ('Mystery','Child')")
    con.close()


def _tree(con, name):
    tree = queries.process_call_tree(con, name, max_depth=8, max_breadth=30,
                                     root_breadth=30, max_nodes=400, include_system=False)
    tree['fingerprint'] = 'a' * 64
    return call_sites.attach(con, tree)


def test_position_is_one_based_like_the_calculation_page():
    code = "a;\nb;\nCellPutN(x);"
    assert call_sites.position(code, 0) == (1, 1)
    assert call_sites.position(code, 3) == (2, 1)
    assert call_sites.position(code, code.index('CellPutN')) == (3, 1)


def test_log_regions_are_masked_without_moving_any_line():
    from tm1_insight.ingest.hard_extract import extract_assignments, extract_calls, mask_log_regions
    code = "a=1;\n" + LOG_BLOCK + "\nb=2;"
    masked = mask_log_regions(code)
    assert len(masked.split('\n')) == len(code.split('\n')) == 5
    assert 'ExecuteProcess' not in masked
    assert masked.split('\n')[0] == 'a=1;' and masked.split('\n')[4] == 'b=2;'
    # 行号不变：b=2 仍在第 5 行
    assert call_sites.position(code, code.index('b=2')) == (5, 1)
    assert [c['callee'] for c in extract_calls(masked, extract_assignments(masked))] == []


def test_sites_from_source_ignore_masked_calls_but_keep_real_line_numbers(client):
    _seed(client)
    con = Store(get_settings()).connect()
    sites = call_sites.sites_for(con, 'Entry')
    con.close()
    assert 'Ghost' not in sites
    child = sites['Child']
    # 日志区占 3 行（第 2–4 行），真实调用在它后面，行号不能被前移
    assert child['section'] == 'prolog' and child['line'] == 5
    assert child['count'] == 2 and child['operation'] == 'ExecuteProcess'
    # 动态目标不是固定成员，没有位置
    assert not any(name.startswith('<') for name in sites)


def test_downstream_site_belongs_to_the_caller(client):
    _seed(client)
    con = Store(get_settings()).connect()
    tree = _tree(con, 'Entry')
    con.close()
    child = next(n for n in tree['callees'] if n['name'] == 'Child')
    assert child['site']['process'] == 'Entry'
    assert child['site']['section'] == 'prolog' and child['site']['line'] == 5


def test_upstream_site_belongs_to_the_upstream_not_to_root(client):
    """同一行号，两个方向指向两份不同的源码——这是最容易搞错的地方。"""
    _seed(client)
    con = Store(get_settings()).connect()
    tree = _tree(con, 'Child')
    con.close()
    entry = next(n for n in tree['callers'] if n['name'] == 'Entry')
    assert entry['site']['process'] == 'Entry'
    assert tree['site_count'] >= 1


def test_call_tree_fragment_links_to_the_right_source_file(client):
    _seed(client)
    page = client.get('/explorer/process/Child/call-tree', params={'scope': 'business'})
    assert page.status_code == 200
    match = re.search(r'<a class="tree-site" href="([^"]+)"', page.text)
    assert match, page.text[:500]
    href = match[1]
    assert 'Entry' in href and '#prolog-L5' in href
    assert 'data:12' in page.text  # 图例说明了这个数字是什么


def test_edges_without_a_source_line_are_counted_not_silently_skipped(client):
    """有边却没有位置，必须报出来——不然「没标」会被读成「都一样」。"""
    _seed(client)
    con = Store(get_settings()).connect()
    tree = _tree(con, 'Child')
    con.close()
    names = {n['name']: n for n in tree['callers']}
    assert 'site' in names['Entry']
    # Mystery 用未赋值变量调用，源码里没有可定位的字面目标
    assert 'site' not in names['Mystery']
    assert tree['site_count'] == 1 and tree['site_unlocated'] == 1

    page = client.get('/explorer/process/Child/call-tree', params={'scope': 'business'})
    assert '另有 1 个节点没标位置' in page.text
