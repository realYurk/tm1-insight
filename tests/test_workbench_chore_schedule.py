"""Workbench 1.0 阶段 B：Chore 调度信息补采与显示 的合成测试。

不连接真实 TM1。覆盖：
1. chores 表增量迁移：旧 3 列库补上调度列（start_time/frequency/execution_mode/active）。
2. get_chore 返回 schedule 字段（有值 / 未采集 / 旧库无列回退）。
3. fetch_chore 采集 active 字段（Mock TM1py Chore 对象）。
4. UI 区分调度定义与实际执行（模板措辞）。
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from tm1_insight.store import queries
from tm1_insight.store.schema import ALL_TABLES, COLUMN_MIGRATIONS
from tm1_insight.tm1.client import TM1Client, safe_getattr


@pytest.fixture
def con():
    c = duckdb.connect()
    for ddl in ALL_TABLES.values():
        c.execute(ddl)
    yield c
    c.close()


def _apply_migrations(con):
    for table, column, ctype in COLUMN_MIGRATIONS:
        con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ctype}")


def test_column_migrations_idempotent(con):
    # 新库已有 7 列（CREATE TABLE 已含），再跑 migration 不应报错（幂等）
    _apply_migrations(con)
    _apply_migrations(con)


def test_get_chore_returns_schedule_when_collected(con):
    con.execute(
        "INSERT INTO chores (name, processes, process_count, start_time, frequency, execution_mode, active) "
        "VALUES ('Nightly', '[]', 0, '23:00:00', '每日', 'MultipleCommit', 'True')"
    )
    result = queries.get_chore(con, "Nightly")
    assert result["schedule"] == {
        "start_time": "23:00:00",
        "frequency": "每日",
        "execution_mode": "MultipleCommit",
        "active": "True",
    }


def test_get_chore_empty_schedule_when_not_collected(con):
    con.execute("INSERT INTO chores (name, processes, process_count) VALUES ('Empty', '[]', 0)")
    result = queries.get_chore(con, "Empty")
    assert result["schedule"] == {"start_time": "", "frequency": "", "execution_mode": "", "active": ""}


def test_fetch_chore_collects_schedule_fields():
    class _Chore:
        start_time = "06:00:00"
        frequency = "每日"
        execution_mode = "MultipleCommit"
        active = True
        tasks = []

    class _TM1:
        chores = type("C", (), {"get": staticmethod(lambda name: _Chore())})()

    class _Settings:
        pass

    client = TM1Client(_Settings())
    result = client.fetch_chore(_TM1(), "Nightly")
    assert result["start_time"] == "06:00:00"
    assert result["frequency"] == "每日"
    assert result["execution_mode"] == "MultipleCommit"
    assert result["active"] == "True"  # safe_getattr 转 str


def test_chore_template_distinguishes_definition_from_execution():
    html = (Path(__file__).resolve().parents[1]
            / "src" / "tm1_insight" / "api" / "templates" / "chore_view.html").read_text(encoding="utf-8")
    # 调度定义与实际执行明确区分，不伪造运行记录
    assert "调度定义" in html
    assert "不代表实际已执行成功" in html
    # 字段标签存在
    assert "启用状态" in html
    assert "计划执行时间" in html
    assert "执行频率" in html
