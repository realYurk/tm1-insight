"""阶段 1：TI 源码查看的性能止损边界。

守住四条契约：
1. 首屏不构建调用树（源码不被多层展开阻塞）。
2. 调用树按需加载、有节点预算、截断必须显式说明。
3. 调用树的 SQL 次数只与层数有关，不随节点数线性增长。
4. 惰性代码段仍保留完整源码文本（搜索与 Ctrl+F 不依赖高亮）。

全部使用合成模型，不读取也不写入 data/ 下的任何真实库。
"""
import importlib
import json
import re
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

import tm1_insight.config as config
import tm1_insight.datasource as ds
from tm1_insight.store import queries
from tm1_insight.store.schema import ALL_TABLES


def insert_process(con, name, prolog="", data="", metadata="", epilog=""):
    con.execute("INSERT INTO processes VALUES (?, ?, ?, ?, ?, '[]', 'null', ?)",
                [name, prolog, metadata, data, epilog, len(prolog + data)])


def connect_calls(con):
    con.execute("INSERT INTO process_calls_process VALUES (?, ?)", ["Parent", "Child"])


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    for ddl in ALL_TABLES.values():
        connection.execute(ddl)
    yield connection
    connection.close()


class _Counter:
    """统计 execute 次数的连接代理（只读用途）。"""

    def __init__(self, con):
        self._con = con
        self.count = 0

    def execute(self, sql, params=None):
        self.count += 1
        return self._con.execute(sql, params) if params is not None else self._con.execute(sql)

    def __getattr__(self, item):
        return getattr(self._con, item)


# ---------------------------------------------------------------------------
# 调用树：查询预算
# ---------------------------------------------------------------------------

def _chain(con, length: int, prefix="Chain"):
    for i in range(length):
        insert_process(con, f"{prefix}.{i:04d}")
        if i:
            con.execute("INSERT INTO process_calls_process VALUES (?, ?)",
                        [f"{prefix}.{i - 1:04d}", f"{prefix}.{i:04d}"])
    con.execute("INSERT INTO process_calls_process VALUES (?, ?)", ["Chain.Root", f"{prefix}.0000"])


def test_sql_count_depends_on_depth_not_node_count(con):
    """同一深度、不同规模的模型，调用树 SQL 次数应相同。"""
    narrow = duckdb.connect(":memory:")
    wide = duckdb.connect(":memory:")
    for db in (narrow, wide):
        for ddl in ALL_TABLES.values():
            db.execute(ddl)

    for db, leaves in ((narrow, 5), (wide, 50)):
        insert_process(db, "Root")
        for c in range(10):
            insert_process(db, f"Root.C{c}")
            db.execute("INSERT INTO process_calls_process VALUES (?, ?)", ["Root", f"Root.C{c}"])
            for g in range(leaves):
                name = f"Root.C{c}.G{g}"
                insert_process(db, name)
                db.execute("INSERT INTO process_calls_process VALUES (?, ?)", [f"Root.C{c}", name])

    n_counter, w_counter = _Counter(narrow), _Counter(wide)
    narrow_tree = queries.process_call_tree(n_counter, "Root", max_depth=8, max_breadth=30)
    wide_tree = queries.process_call_tree(w_counter, "Root", max_depth=8, max_breadth=30)
    try:
        assert narrow_tree["node_count"] < wide_tree["node_count"]
        # 关键契约：SQL 次数只与层数有关，不随节点数增长。
        assert n_counter.count == w_counter.count
        assert n_counter.count <= 2 * 2 + 2
    finally:
        narrow.close()
        wide.close()


def test_budget_stops_expansion_and_is_reported(con):
    insert_process(con, "Root")
    for c in range(30):
        insert_process(con, f"Root.C{c}")
        con.execute("INSERT INTO process_calls_process VALUES (?, ?)", ["Root", f"Root.C{c}"])
        for g in range(30):
            name = f"Root.C{c}.G{g}"
            insert_process(con, name)
            con.execute("INSERT INTO process_calls_process VALUES (?, ?)", [f"Root.C{c}", name])

    tree = queries.process_call_tree(con, "Root", max_depth=8, max_breadth=30, max_nodes=40)
    assert tree["truncated"] is True
    assert tree["node_count"] == 40
    assert tree["limits"]["max_nodes"] == 40
    # 预算内的节点必须真实展开，不能因为截断而丢失已取到的关系。
    assert len(tree["callees"]) == 30


def test_cycle_is_visited_once_and_does_not_recurse(con):
    for name in ("A", "B", "C"):
        insert_process(con, name)
    con.execute("INSERT INTO process_calls_process VALUES ('A','B')")
    con.execute("INSERT INTO process_calls_process VALUES ('B','A')")
    con.execute("INSERT INTO process_calls_process VALUES ('B','C')")

    tree = queries.process_call_tree(con, "A", max_depth=8, max_breadth=30)
    assert tree["node_count"] == 4          # A + B(下游) + C + B(上游)
    down = json.dumps(tree["callees"], ensure_ascii=False)
    assert down.count('"B"') == 1           # 下游环上的 B 只展开一次
    assert down.count('"C"') == 1
    up = json.dumps(tree["callers"], ensure_ascii=False)
    assert up.count('"B"') == 1             # 上游方向独立去重，不与下游共享 visited


def test_depth_and_breadth_truncation_are_reported(con):
    """深层广度截断与深度截断都必须显式回报，不能只报节点预算。"""
    insert_process(con, "Root")
    for c in range(4):
        parent = f"D{c}"
        insert_process(con, parent)
        con.execute("INSERT INTO process_calls_process VALUES ('Root', ?)", [parent])
        for g in range(6):
            child = f"{parent}.G{g}"
            insert_process(con, child)
            con.execute("INSERT INTO process_calls_process VALUES (?, ?)", [parent, child])

    # 根层放宽到 10，让 4 个直接下游都展开；它们各自 6 个下游被每层上限 2 截断
    tree = queries.process_call_tree(con, "Root", max_depth=3, max_breadth=2, root_breadth=10)
    assert tree["truncated"] is True
    assert tree["truncation"]["breadth_parents"] == 4
    assert tree["truncation"]["nodes"] is False
    assert tree["truncation"]["root_capped_callees"] is False
    assert tree["direct"]["callees"] == {"shown": 4, "total": 4, "capped": False}

    # 根层被截断时必须给出真实总数，而不是只报展开条数
    capped = queries.process_call_tree(con, "Root", max_depth=3, max_breadth=2, root_breadth=2)
    assert capped["truncation"]["root_capped_callees"] is True
    assert capped["direct"]["callees"] == {"shown": 2, "total": 4, "capped": True}

    # 深度截断：链更长时，最后一层还有下游必须报告
    insert_process(con, "T0")
    for i in range(1, 6):
        insert_process(con, f"T{i}")
        con.execute("INSERT INTO process_calls_process VALUES (?, ?)", [f"T{i - 1}", f"T{i}"])
    deep = queries.process_call_tree(con, "T0", max_depth=2, max_breadth=30)
    assert deep["truncation"]["depth"] is True
    assert deep["truncated"] is True


def test_each_parent_keeps_its_own_breadth_limit(con):
    insert_process(con, "Root")
    for c in range(5):
        parent = f"P{c}"
        insert_process(con, parent)
        con.execute("INSERT INTO process_calls_process VALUES ('Root', ?)", [parent])
        for g in range(40):
            child = f"{parent}.G{g:02d}"
            insert_process(con, child)
            con.execute("INSERT INTO process_calls_process VALUES (?, ?)", [parent, child])

    tree = queries.process_call_tree(con, "Root", max_depth=8, max_breadth=7)
    # 广度限制按「每个父节点」生效，不是整层共享。
    assert all(len(node["children"]) == 7 for node in tree["callees"])


# ---------------------------------------------------------------------------
# 页面：首屏不构建调用树
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_USER_DATA_ROOT", tmp_path)
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path / "app")
    monkeypatch.setattr(config, "_DATA_DIR_OVERRIDE", None)
    monkeypatch.setattr(ds, "_source_cache", None)
    monkeypatch.setattr(ds, "_demo_data_dir", lambda: tmp_path / "demo")
    config.get_settings.cache_clear()
    ds.load_demo_data()
    from tm1_insight.api.app import app
    with duckdb.connect(str(config.get_settings().db_path)) as connection:
        insert_process(connection, "Wide.Hub", prolog="vSeed = CellGetN('Cube', vYear);",
                       data="\n".join(f"CellPutN({i}, 'Target', vYear);" for i in range(1, 61)))
        for i in range(120):
            caller = f"Wide.Caller.{i:03d}"
            insert_process(connection, caller, prolog="vX = 1;")
            connection.execute("INSERT INTO process_calls_process VALUES (?, 'Wide.Hub')", [caller])
    api_module = importlib.import_module("tm1_insight.api.app")
    api_module._call_tree_cache.clear()
    with TestClient(app) as test_client:
        yield test_client
    api_module._call_tree_cache.clear()
    config.get_settings.cache_clear()


def test_first_paint_renders_source_without_call_tree(client):
    response = client.get("/explorer/process/Wide.Hub")
    assert response.status_code == 200
    html = response.text
    assert "Wide.Hub" in html
    # 源码完整可读（搜索与 Ctrl+F 不需要高亮）；服务端只做 HTML 转义，不改写内容
    assert "CellPutN(60, &#39;Target&#39;, vYear);" in html
    # 源码段标记为惰性，服务端不预渲染行节点
    assert 'data-lazy-source="1"' in html
    assert '<div class="code-line">' not in html
    # 调用树不在首屏 HTML 里
    assert "tree-node" not in html
    assert 'id="call-tree-load"' in html
    assert "/explorer/process/Wide.Hub/call-tree" in html


def test_call_tree_fragment_is_bounded_and_explains_truncation(client):
    response = client.get("/explorer/process/Wide.Hub/call-tree")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "tree-node" in response.text
    # 120 个调用者 + 预算 400，应完整展开并说明未达上限
    assert "未达任何预算上限" in response.text or "以下内容未展开" in response.text
    # 上游数量必须是真实总数，不能只报展开条数
    assert "被调用（120）" in response.text


def test_root_fan_in_shows_true_total_instead_of_silent_breadth_cap(client, monkeypatch):
    """根层被广度上限截断时，必须同时给出「显示多少 / 共多少」。"""
    api_module = importlib.import_module("tm1_insight.api.app")
    monkeypatch.setitem(api_module.CALL_TREE_LIMITS, "root_breadth", 5)
    api_module._call_tree_cache.clear()
    response = client.get("/explorer/process/Wide.Hub/call-tree")
    assert response.status_code == 200
    assert "显示 5 / 共 120" in response.text
    assert "以下内容未展开" in response.text
    assert "不代表不存在" in response.text
    assert "直接调用者超过展示上限 5" in response.text


def test_call_tree_fragment_rejects_stale_source_and_missing_process(client):
    stale = client.get("/explorer/process/Wide.Hub/call-tree", params={"source": "0" * 64})
    assert stale.status_code == 409
    assert "数据源已变化" in stale.text
    missing = client.get("/explorer/process/Not.There/call-tree")
    assert missing.status_code == 404
    assert "未加载调用树" in missing.text


def test_call_tree_fragment_honours_configured_budget(client, monkeypatch):
    api_module = importlib.import_module("tm1_insight.api.app")
    monkeypatch.setitem(api_module.CALL_TREE_LIMITS, "max_nodes", 5)
    api_module._call_tree_cache.clear()
    response = client.get("/explorer/process/Wide.Hub/call-tree")
    assert response.status_code == 200
    assert "以下内容未展开" in response.text
    assert "不代表不存在" in response.text
    assert "已达节点预算 5" in response.text


def test_call_tree_cache_is_keyed_by_source_fingerprint(client, monkeypatch):
    api_module = importlib.import_module("tm1_insight.api.app")
    api_module._call_tree_cache.clear()
    first = client.get("/explorer/process/Wide.Hub/call-tree").text
    assert len(api_module._call_tree_cache) == 1
    second = client.get("/explorer/process/Wide.Hub/call-tree").text
    assert first == second
    assert len(api_module._call_tree_cache) == 1
    # 数据源指纹变化后，键不同、不会命中旧结果
    monkeypatch.setattr(api_module, "_process_search_source", lambda *a: "changed-fingerprint")
    client.get("/explorer/process/Wide.Hub/call-tree")
    assert len(api_module._call_tree_cache) == 2


def test_sections_are_lazy_but_keep_line_anchors(client):
    response = client.get("/explorer/process/Wide.Hub")
    html = response.text
    # 四个代码段都可能存在；没有内容的段不渲染空 pre
    assert html.count('data-lazy-source="1"') >= 1
    assert 'data-source-section="prolog"' in html
    assert 'data-source-section="data"' in html
    # 默认激活段在服务端就标记为 active，无脚本时仍能看到源码
    active = re.findall(r'class="tab-pane active" data-pane="(\w+)"', html)
    assert len(active) == 1
    assert f'class="tab-pane" data-pane="{active[0]}"' not in html


def test_source_viewer_renders_lazily_and_stays_searchable():
    """前端惰性渲染契约（Node + DOM 桩，无浏览器）：分批渲染但不丢全文与行锚点。"""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node 不可用；行为由浏览器验收覆盖。")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests" / "ui" / "source_viewer_lazy.js"),
         str(root / "src" / "tm1_insight" / "api" / "static" / "syntax.js")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
