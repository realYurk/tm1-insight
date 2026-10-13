"""Recorded Chore sequence must not turn incomplete metadata into execution proof."""
import json

import duckdb
import pytest
from tm1_insight.store import queries
from tm1_insight.store.schema import ALL_TABLES
from test_datasource_api import client  # noqa: F401: shared isolated fixture


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    for ddl in ALL_TABLES.values():
        connection.execute(ddl)
    connection.executemany("INSERT INTO processes VALUES (?, '', '', '', '', '[]', 'null', 0)",
                           [("First",), ("Second",)])
    yield connection
    connection.close()


def put_chore(con, steps, count=None):
    con.execute("INSERT INTO chores VALUES ('Example', ?, ?)",
                [json.dumps(steps), len(steps) if count is None else count])


def test_explicit_orders_sort_and_keep_original_evidence_indices(con):
    put_chore(con, [{"name": "Second", "step_order": 8}, {"name": "First", "step_order": 2}])
    result = queries.get_chore(con, "Example")
    assert result["order_status"] == "recorded" and not result["warnings"]
    assert [step["name"] for step in result["steps"]] == ["First", "Second"]
    assert result["steps"][0]["evidence"] == "chores.processes[1]"


@pytest.mark.parametrize("orders", [[None, 2], [2, 2], ["1", 2], [True, 2], [-1, 2]])
def test_partial_orders_preserve_stored_position_and_original_value(con, orders):
    put_chore(con, [{"name": name, "step_order": order} for name, order in zip(["Second", "First"], orders)])
    result = queries.get_chore(con, "Example")
    assert result["order_status"] == "unknown" and result["warnings"]
    assert [step["name"] for step in result["steps"]] == ["Second", "First"]
    assert result["steps"][0]["recorded_order"] == orders[0]


def test_legacy_strings_missing_names_and_count_mismatch_are_visible(con):
    put_chore(con, ["Second", "Missing", None], count=7)
    result = queries.get_chore(con, "Example")
    assert result["order_status"] == "unknown"
    assert [step["exists"] for step in result["steps"]] == [True, False, False]
    assert result["steps"][2]["name"] == ""
    assert len(result["warnings"]) == 3
    assert con.execute("SELECT count(*) FROM process_calls_process").fetchone()[0] == 0


def test_relational_fallback_and_invalid_json_are_not_silent(con):
    con.execute("INSERT INTO chores VALUES ('Example', 'invalid json', 2)")
    con.executemany("INSERT INTO chore_runs_process VALUES ('Example', ?, ?)", [("Second", 4), ("First", 1)])
    result = queries.get_chore(con, "Example")
    assert result["warnings"] and result["order_status"] == "recorded"
    assert [step["name"] for step in result["steps"]] == ["First", "Second"]
    assert all(step["evidence"] == "chore_runs_process.step_order" for step in result["steps"])


def test_chore_search_is_literal_paginated_and_bounded(con):
    con.executemany("INSERT INTO chores VALUES (?, '[]', 0)", [(f"Schedule.{i:04d}",) for i in range(1128)])
    result = queries.search_chore_page(con, "Schedule.", offset=1100)
    assert result["total"] == 1128 and len(result["items"]) == 28
    assert queries.search_chore_page(con, "%")["total"] == 0
    assert queries.search_chore_page(con, "", offset=999999)["offset"] == 1100


def test_chore_workspace_and_old_link_have_same_supported_content(client):
    result = client.get("/chores")
    assert result.status_code == 200 and 'class="chore-workspace"' in result.text
    assert 'aria-label="Chore 列表"' in result.text and 'aria-label="Chore 详情"' in result.text
    assert "Daily_Load" in result.text and "不是执行历史" in result.text
    old = client.get("/explorer/chore/Weekly_Inventory")
    assert old.status_code == 200 and "Update_Inventory" in old.text
    assert client.get("/chores", params={"name": "absent"}).status_code == 404
    assert "没有匹配的 Chore" in client.get("/chores", params={"q": "absent"}).text
    assert client.get("/chores?page=0").status_code == 422
    assert "Chore 调度" in client.get("/processes?q=Load").text


def test_large_chore_detail_bounds_rows_and_keeps_original_positions(client):
    from tm1_insight.config import get_settings
    client.get("/")
    with duckdb.connect(str(get_settings().db_path)) as connection:
        steps = [{"name": "Load_Sales", "step_order": i} for i in range(1128)]
        connection.execute("INSERT INTO chores VALUES ('LargeExample', ?, 1128)", [json.dumps(steps)])
    response = client.get("/chores", params={"name": "LargeExample", "step_page": 12})
    assert response.status_code == 200 and "已保存 1128 条步骤明细" in response.text
    table = response.text.split('id="chore-steps"')[1].split('</table>')[0]
    assert table.count('<tr>') == 29  # Header + last 28 steps, not all 1128 rows.
    assert "执行序号 1100" in table and "执行序号 1127" in table
    assert "下一页步骤" not in response.text


def test_chore_collector_preserves_zero_and_does_not_invent_missing_orders():
    from types import SimpleNamespace
    from tm1_insight.tm1.client import TM1Client
    from tm1_insight.config import Settings
    for tasks in ([{"Process": {"Name": "First"}, "Step": 0}, {"process_name": "Second"}],
                  [SimpleNamespace(process_name="First", step=0), SimpleNamespace(process_name="Second")]):
        service = SimpleNamespace(chores=SimpleNamespace(get=lambda name: SimpleNamespace(tasks=tasks)))
        result = TM1Client(Settings(_env_file=None)).fetch_chore(service, "Example")
        assert [step["step_order"] for step in result["processes"]] == [0, None]
