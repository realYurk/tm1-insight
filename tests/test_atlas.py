"""资产地图（atlas-1）合成数据契约。

只使用合成对象，不读取 data/ 下的真实模型。验证：
- 系统对象默认排除，可显式包含；
- 排序由透明信号加权得出，不被名称影响；
- 前端映射大小写不一致仍能匹配；
- 无写入方的对象被标注，而不是被隐藏；
- 导出是可读 Markdown，含口径与缺口。
"""
import duckdb
import pytest

from tm1_insight import atlas
from tm1_insight.store.schema import ALL_TABLES


@pytest.fixture
def con():
    c = duckdb.connect(':memory:')
    for ddl in ALL_TABLES.values():
        c.execute(ddl)
    # 两个业务 Cube + 一个系统 Cube
    for name, rules, has_rules, count in [
        ('Sales', '', False, 3),
        ('PnL', 'x', True, 5),
        ('}Stats', '', False, 1),
        ('Orphan', '', False, 2),
    ]:
        c.execute('INSERT INTO cubes(name,dimensions,rules,has_rules,dimension_count) VALUES (?,?,?,?,?)',
                  [name, '[]', rules, has_rules, count])
    # 一个高扇入 Cube：被三个 TI 写、一个 TI 读；另一个只有 Rule
    for process in ('Load1', 'Load2', 'Load3'):
        c.execute('INSERT INTO process_writes_cube VALUES (?,?)', [process, 'Sales'])
        c.execute('INSERT INTO processes(name,prolog,metadata,data,epilog,parameters,code_length) VALUES (?,?,?,?,?,?,?)',
                  [process, '', '', '', '', '[]', 100])
    c.execute('INSERT INTO process_reads_cube VALUES (?,?)', ['Load1', 'PnL'])
    c.execute('INSERT INTO process_calls_process VALUES (?,?)', ['Load1', 'Load2'])
    c.execute('INSERT INTO rule_references_cube VALUES (?,?)', ['PnL', 'Sales'])
    c.execute('INSERT INTO chores(name,processes,process_count) VALUES (?,?,?)', ['Nightly', '["Load1"]', 1])
    # 前端映射写成全大写，模型里是混合大小写
    c.execute('INSERT INTO front_backend_mapping VALUES (?,?,?,?)', ['Menu/Sales', 'a.xlsx', 'SALES, PNL', 2])
    for dim in ('Year', 'Measure', 'Unused'):
        c.execute('INSERT INTO dimensions(name,is_system,element_count,elements,attributes,edges,subsets) '
                  'VALUES (?,?,?,?,?,?,?)', [dim, False, 10, '[]', '[]', '[]', '[]'])
    c.execute('INSERT INTO cube_has_dimension VALUES (?,?,?)', ['Sales', 'Year', 1])
    c.execute('INSERT INTO cube_has_dimension VALUES (?,?,?)', ['Sales', 'Measure', 2])
    yield c
    c.close()


def test_system_objects_excluded_by_default(con):
    names = [i['name'] for i in atlas.summary(con, 'cube')['items']]
    assert '}Stats' not in names
    assert 'Sales' in names
    shown = [i['name'] for i in atlas.summary(con, 'cube', include_system=True)['items']]
    assert '}Stats' in shown


def test_signals_and_ranking(con):
    data = atlas.summary(con, 'cube')
    top = data['items'][0]
    assert top['name'] == 'Sales'
    assert top['signals']['writers'] == 3
    assert top['signals']['scheduled'] == 1          # Load1 被 Nightly 调度
    assert top['signals']['frontend'] == 1           # 大写映射仍命中
    assert top['signals']['rule_refs'] == 1          # PnL 的 Rule 引用了 Sales
    # 分数等于信号加权和，可手工核对
    expected = 3 * 3 + 2 * 0 + 2 * 1 + 2 * 1 + 3 * 1 + 1 * 0
    assert top['score'] == expected


def test_no_writer_cube_is_flagged_not_hidden(con):
    orphan = next(i for i in atlas.summary(con, 'cube')['items'] if i['name'] == 'Orphan')
    assert orphan['signals']['writers'] == 0
    assert any('未记录写入方' in note for note in orphan['notes'])


def test_search_sort_and_paging(con):
    assert [i['name'] for i in atlas.summary(con, 'cube', query='pnl')['items']] == ['PnL']
    by_name = [i['name'] for i in atlas.summary(con, 'cube', sort='name')['items']]
    assert by_name == sorted(by_name, key=str.lower)
    page1 = atlas.summary(con, 'cube', limit=10, page=1)
    assert page1['total'] == 3 and page1['pages'] == 1


def test_dimension_and_process_views(con):
    dims = atlas.summary(con, 'dimension')
    by_name = {i['name']: i for i in dims['items']}
    assert by_name['Year']['signals']['cubes'] == 1
    assert any('没有任何 Cube 使用' in n for n in by_name['Unused']['notes'])
    processes = {i['name']: i for i in atlas.summary(con, 'process')['items']}
    assert processes['Load2']['signals']['callers'] == 1
    assert processes['Load1']['signals']['scheduled'] == 1


def test_gaps_and_export(con):
    gap = atlas.gaps(con)
    assert gap['cube_without_writer']['count'] == 2        # PnL(仅 Rule) + Orphan
    assert gap['frontend_linked'] == 2                     # SALES / PNL 归一化后命中
    text = atlas.export_markdown(con, 'cube', limit=10)
    assert text.startswith('# Cube 资产清单')
    assert '| 写入 TI | 3 |' in text
    assert '`Sales`' in text
    assert '覆盖缺口' in text
    assert '不代表运行时结果' in text
