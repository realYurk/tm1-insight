"""TI discovery is literal source evidence, not inferred invocation or value flow."""
import hashlib

import duckdb
import pytest
from fastapi.testclient import TestClient

import tm1_insight.config as config
import tm1_insight.datasource as ds
from tm1_insight.store import queries
from tm1_insight.store.schema import ALL_TABLES


TARGET = "Cub.Example.Attachment.Load.From.CSV"
CALLER = "Cub.Example.Task.Caller"
CALLER_CODE = f"# source lookup only\nExecuteProcess('{TARGET}');\nExecuteProcess(pDynamicChild);"


def insert_process(con, name, prolog="", data="", metadata="", epilog=""):
    con.execute("INSERT INTO processes VALUES (?, ?, ?, ?, ?, '[]', 'null', ?)",
                [name, prolog, metadata, data, epilog, len(prolog + data)])


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    for ddl in ALL_TABLES.values():
        connection.execute(ddl)
    insert_process(connection, TARGET, data="CellPutN(vValue, 'ExampleTarget', vPeriod);")
    insert_process(connection, CALLER, prolog=CALLER_CODE)
    yield connection
    connection.close()


def test_name_default_excludes_source_reference_and_ranks_exact_first(con):
    insert_process(con, "A." + TARGET)
    insert_process(con, TARGET + ".FollowUp")
    result = queries.search_process_page(con, "  " + TARGET.lower() + "  ")
    assert [item["name"] for item in result["items"]] == [TARGET, TARGET + ".FollowUp", "A." + TARGET]
    assert all(item["match"] == {"kind": "name"} for item in result["items"])


def test_explicit_fulltext_has_source_location_and_preserves_legacy_contract(con):
    result = queries.search_process_page(con, TARGET, scope="all")
    assert [item["name"] for item in result["items"]] == [TARGET, CALLER]
    evidence = result["items"][1]["match"]
    assert evidence == {"kind": "code", "section": "prolog", "line": 2,
                        "column": 17, "excerpt": f"ExecuteProcess('{TARGET}');"}
    assert queries.search_process_page(con, TARGET, scope="code")["total"] == 1
    assert set(queries.search_processes(con, TARGET)) == {TARGET, CALLER}
    assert con.execute("SELECT count(*) FROM process_calls_process").fetchone()[0] == 0


@pytest.mark.parametrize("keyword", ["%", "_", "O'Brien", "?&+#", "中文"])
def test_search_uses_literal_characters(con, keyword):
    insert_process(con, "literal " + keyword)
    assert [item["name"] for item in queries.search_process_page(con, keyword)["items"]] == ["literal " + keyword]


def test_pagination_has_true_total_beyond_legacy_500_and_clamps_last_page(con):
    con.executemany("INSERT INTO processes VALUES (?, '', '', '', '', '[]', 'null', 0)",
                    [(f"Bulk.{i:04d}",) for i in range(1128)])
    page = queries.search_process_page(con, "Bulk.", offset=1100, limit=100)
    assert page["total"] == 1128 and len(page["items"]) == 28
    assert page["items"][0]["name"] == "Bulk.1100"
    assert queries.search_process_page(con, "Bulk.", offset=99999)["offset"] == 1100
    assert queries.search_process_page(con, "absent", offset=500)["offset"] == 0


def test_code_hit_does_not_resolve_dynamic_call_or_create_edges(con):
    result = queries.search_process_page(con, "pDynamicChild", scope="code")
    assert result["items"][0]["match"]["line"] == 3
    assert "callee" not in result["items"][0]
    from tm1_insight.resolver import resolve_symbol
    unresolved = resolve_symbol("pDynamicChild", {})
    assert not unresolved.resolved and unresolved.kind == "unresolved"
    assert con.execute("SELECT count(*) FROM process_calls_process").fetchone()[0] == 0


@pytest.mark.parametrize("section", ["prolog", "metadata", "data", "epilog"])
def test_each_section_and_multiline_search_points_to_original_start(con, section):
    insert_process(con, "Section.Example", **{section: "# intro\nvExample = 1;\nvOther = 2;"})
    match = queries.search_process_page(con, "vExample = 1;\nvOther", scope="code")["items"][0]["match"]
    assert (match["section"], match["line"], match["column"]) == (section, 2, 1)


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
        insert_process(connection, TARGET, prolog="vCarMaterial = 'Example';\nCellPutN(vUnknown, 'ExampleTarget', vPeriod);")
        insert_process(connection, CALLER, prolog=CALLER_CODE)
        insert_process(connection, "<script>alert('synthetic')</script>", epilog="# <script>source</script>")
    with TestClient(app) as test_client:
        yield test_client
    config.get_settings.cache_clear()


def test_search_api_and_html_expose_text_evidence_and_escape_content(client):
    response = client.get("/api/processes/search", params={"q": TARGET})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["total"] == 1
    source = response.json()["source"]
    assert len(source) == 64 and ":" not in source
    page = client.get("/processes", params={"q": TARGET, "scope": "code"})
    assert page.status_code == 200
    assert "#prolog-L2" in page.text and "代码 · prolog : 2" in page.text
    assert "不证明调用或计算关系" in page.text
    escaped = client.get("/processes", params={"q": "<script>", "scope": "code"}).text
    assert "&lt;script&gt;source&lt;/script&gt;" in escaped
    assert "<script>source</script>" not in escaped
    detail = client.get("/explorer/process/" + TARGET)
    assert detail.status_code == 200
    assert 'id="open-process-switcher"' in detail.text and 'class="table semvar-table"' in detail.text
    assert "UNKNOWN · 未提取到赋值" in detail.text


@pytest.mark.parametrize("params", [{"limit": 101}, {"limit": -1}, {"offset": -1},
                                    {"scope": "invalid"}, {"q": "a" * 1001}])
def test_search_api_rejects_unbounded_or_invalid_parameters(client, params):
    assert client.get("/api/processes/search", params=params).status_code == 422


def test_source_switch_changes_search_context_and_preserves_every_database_byte(client, tmp_path):
    from test_datasource import _make_real_db
    local = _make_real_db(tmp_path / "local")
    before = hashlib.sha256(local.read_bytes()).hexdigest()
    demo = config.get_settings().db_path
    demo_before = hashlib.sha256(demo.read_bytes()).hexdigest()
    selected = client.post("/api/datasource/use", json={"source": "local", "path": str(local)})
    assert selected.json()["status"]["type"] == "real_local"
    local_key = client.get("/api/processes/search").json()["source"]
    home = client.get("/")
    assert 'data-type="real_local"' in home.text and "Local TM1 Data" in home.text
    assert "快照时间：未知" not in home.text
    assert client.get("/api/datasource/status").headers["cache-control"] == "no-store"
    for _ in range(2):
        assert client.post("/api/datasource/use", json={"source": "demo"}).status_code == 200
    assert local_key != client.get("/api/processes/search").json()["source"]
    assert hashlib.sha256(local.read_bytes()).hexdigest() == before
    assert hashlib.sha256(demo.read_bytes()).hexdigest() == demo_before
    assert client.post("/api/datasource/use", json={"source": "local", "path": str(local)}).status_code == 200
    assert client.get("/api/processes/search").json()["source"] == local_key


def test_data_source_change_during_search_is_rejected(client, monkeypatch):
    import importlib
    api = importlib.import_module("tm1_insight.api.app")
    calls = iter(["old", "new"])
    monkeypatch.setattr(api, "_process_search_source", lambda *args: next(calls))
    assert client.get("/api/processes/search").status_code == 409


def test_code_location_rejects_old_source_fingerprint(client):
    response = client.get("/api/processes/search", params={"q": TARGET, "scope": "code"}).json()
    url = "/explorer/process/" + CALLER
    assert client.get(url, params={"source": response["source"]}).status_code == 200
    with duckdb.connect(str(config.get_settings().db_path)) as connection:
        connection.execute("UPDATE processes SET prolog = '# changed source' WHERE name = ?", [CALLER])
    stale = client.get(url, params={"source": response["source"]})
    assert stale.status_code == 409 and "旧行号未用于定位" in stale.text
    assert client.get(url).status_code == 200  # Existing links remain compatible.


def test_unicode_source_prefix_does_not_shift_evidence_column(con):
    insert_process(con, "UnicodeExample", data="vİ = 0; CellPutN(vValue, 'Target', 'Period');")
    item = queries.search_process_page(con, "CellPutN", scope="code")["items"]
    unicode_match = next(row["match"] for row in item if row["name"] == "UnicodeExample")
    assert unicode_match["column"] == 9
