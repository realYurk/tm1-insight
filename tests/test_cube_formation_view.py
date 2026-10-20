"""cube_formation_view 数据形成专项视图的测试。

验证：
1. BP Management Report PnL 的 Rule 计算关系默认优先展示（而非仅 TI）。
2. CM09001（实为 BP09000）/PL01010 等目标区域及其公式。
3. 本 Cube 区域引用、跨 Cube DB 引用、IF 条件。
4. MDX 切面匹配（parse_mdx + trace_cell_value）。
5. 无法解析的 MDX 不伪造结果。

纯本地静态分析，不连接 TM1 Server，不执行规则。
"""
import duckdb
import pytest

from tm1_insight.store import queries


@pytest.fixture(scope="module")
def con():
    import os
    # 用真实 demo 数据（只读）
    candidates = [
        "data/demo/db/tm1_insight.duckdb",
        "data/tm1_insight.duckdb",
    ]
    path = None
    for c in candidates:
        if os.path.exists(c):
            path = c
            break
    if not path:
        pytest.skip("demo 数据库不存在，跳过数据形成专项测试")
    c = duckdb.connect(path, read_only=True)
    yield c
    c.close()


def test_formation_defaults_to_rules_not_ti(con):
    """默认应优先展示 Rule 计算关系，而非仅读取该 Cube 的 TI。"""
    f = queries.cube_formation_view(con, "BP Management Report PnL")
    assert f["cube"] == "BP Management Report PnL"
    # Rule 数量应显著大于 0（真实数据 60 条）
    assert f["rule_count"] > 0, "PnL 应有 Rule 计算关系"
    # 维度应包含 Scenario/Version/Year/Month 等
    dims = f["dimensions"]
    for d in ("Scenario", "Version", "Year", "Month"):
        assert d in dims, f"PnL 应含维度 {d}"
    # Rule 语义应包含表达式与目标区域
    assert any(r["expression"] for r in f["rules"]), "Rule 应有计算表达式"
    assert any(r["target"] for r in f["rules"]), "Rule 应有目标区域"


def test_formation_extracts_pl01010_and_bp09000(con):
    """真实数据中 PL01010（目标区域）与 BP09000（计算引用）可被解析。

    交接线索误报为「CM09001」；真实数据里对应的是 BP09000（作为计算表达式里的
    静态指标引用出现），PL01010 是真实的目标区域（行 70-71）。
    """
    f = queries.cube_formation_view(con, "BP Management Report PnL")
    targets = " ".join(r["target"] or "" for r in f["rules"])
    exprs = " ".join(r["expression"] or "" for r in f["rules"])
    assert "PL01010" in targets, "应解析出 PL01010 目标区域"
    assert "BP09000" in exprs, "应解析出 BP09000 指标引用（交接误报为 CM09001）"


def test_formation_has_cross_cube_refs_and_conditions(con):
    """跨 Cube DB 引用（Info Car Line / BP PnL Assumption）与 IF 条件应被记录。"""
    f = queries.cube_formation_view(con, "BP Management Report PnL")
    all_refs = {d["cube"] for r in f["rules"] for d in r["db_references"]}
    assert "Info Car Line" in all_refs, "应有 Info Car Line 跨 Cube 引用"
    assert "BP PnL Assumption" in all_refs, "应有 BP PnL Assumption 跨 Cube 引用"
    # 至少一条规则含条件分支
    assert any(r["conditions"] for r in f["rules"]), "应有 IF 条件分支"


def test_formation_distinguishes_status(con):
    """Rule 状态应显式区分 PARSED / PARTIAL / UNKNOWN。"""
    f = queries.cube_formation_view(con, "BP Management Report PnL")
    statuses = {r["status"] for r in f["rules"]}
    assert statuses, "应有状态标注"
    # 状态必须是合法枚举
    assert statuses <= {"PARSED", "PARTIAL", "UNKNOWN", "STET", "CONTINUE"}


def test_formation_mdx_slice(con):
    """MDX 切面应反解出成员并返回匹配的写入候选。"""
    mdx = "SELECT {[Account PnL].[PL01010]} ON 0 FROM [BP Management Report PnL] WHERE ([Scenario].[SP75],[Version].[WIP])"
    f = queries.cube_formation_view(con, "BP Management Report PnL", mdx)
    assert f["mdx_slice"] is not None, "应返回 MDX 切面"
    members = f["mdx_slice"]["members"]
    assert "Scenario" in members, "应反解出 Scenario 维度"
    assert "SP75" in members["Scenario"], "Scenario 应为 SP75"


def test_formation_mdx_unparseable_not_fabricated(con):
    """无法解析的 MDX 不应伪造结果（mdx_parse 返回空 members，mdx_slice 标注 relaxed/空候选）。"""
    mdx = "THIS IS NOT MDX AT ALL"
    f = queries.cube_formation_view(con, "BP Management Report PnL", mdx)
    # parse_mdx 对无法解析的输入返回空 members，不抛异常、不伪造
    assert f["mdx_parse"] is not None
    assert f["mdx_parse"]["cube"] is None
    assert f["mdx_parse"]["members"] == {}


def test_formation_limitations_present(con):
    """应显式声明分析边界（不伪装成逐单元格血缘）。"""
    f = queries.cube_formation_view(con, "BP Management Report PnL")
    assert f["limitations"], "应声明分析边界"
    assert any("未执行" in l or "静态" in l for l in f["limitations"])
