"""Python 跨版本兼容性治理 1.0 测试。

覆盖：
1. 核心模块可导入。
2. architecture.py 的 Pydantic 模型可定义与校验（原始 str | None 崩溃点）。
3. python_compat.check / version_info / banner 行为。
4. 不支持的版本会给出明确提示（通过 monkeypatch sys.version_info 模拟）。
5. FastAPI 路由可注册、Web 应用可加载。
"""
from __future__ import annotations

import pytest

from tm1_insight import python_compat


def test_core_modules_import():
    """所有核心模块能够导入（无 PEP 604 运行时求值崩溃）。"""
    import tm1_insight.api.app
    import tm1_insight.api.architecture
    import tm1_insight.collector
    import tm1_insight.config
    import tm1_insight.resolver
    import tm1_insight.dependency.engine
    import tm1_insight.lineage.engine
    import tm1_insight.snapshot.schema
    import tm1_insight.snapshot.store
    import tm1_insight.store.queries
    import tm1_insight.compare.engine
    import tm1_insight.change_intelligence.engine
    assert True


def test_architecture_start_model_builds():
    """原始崩溃点：architecture.Start 的 str | None 字段可正常定义与校验。"""
    from tm1_insight.api.architecture import Start

    # process 入口
    m = Start(process="SomeProcess")
    assert m.process == "SomeProcess"
    assert m.entry_kind == "process"

    # cube 入口
    c = Start(cube="SomeCube", entry_kind="cube")
    assert c.cube == "SomeCube"

    # 字段集完整（含子类新增字段与父类字段）
    assert {"process", "cube", "entry_kind", "max_nodes",
            "allowed_relationship_types"}.issubset(set(Start.model_fields))

    # 校验失败路径：process 入口缺 process
    with pytest.raises(ValueError):
        Start()


def test_architecture_start_optional_fields_default_none():
    from tm1_insight.api.architecture import Start

    m = Start(cube="C", entry_kind="cube")
    # process 未提供时应为 None（原 str | None 语义）
    assert m.process is None


def test_python_compat_version_info():
    info = python_compat.version_info()
    assert info["python_version"]
    assert info["python_executable"]
    assert info["project_version"]
    # git_sha 可能为 None（无 .git 或无法读取），但键必须存在
    assert "git_sha" in info


def test_python_compat_check_ok_on_supported():
    """当前解释器（>=3.9）下 check 通过并返回信息。"""
    import sys
    if sys.version_info[:2] < python_compat.MIN_PYTHON:
        pytest.skip("当前解释器低于最低支持版本，无法测通过路径")
    info = python_compat.check()
    assert info["python_version"]


def test_python_compat_check_rejects_old_version(monkeypatch):
    """模拟 Python 3.8：check 应抛 SystemExit 并输出中文错误。"""
    import sys

    class FakeVersionInfo:
        major = 3
        minor = 8
        micro = 0
        releaselevel = "final"
        serial = 0

        def __getitem__(self, idx):
            return (self.major, self.minor, self.micro, self.releaselevel, self.serial)[idx]

        def __iter__(self):
            return iter((self.major, self.minor, self.micro, self.releaselevel, self.serial))

        def __lt__(self, other):
            return (self.major, self.minor) < tuple(other[:2])

    monkeypatch.setattr(sys, "version_info", FakeVersionInfo())
    with pytest.raises(SystemExit) as exc:
        python_compat.check()
    assert exc.value.code == 1


def test_python_compat_banner_mentions_python_and_version():
    b = python_compat.banner()
    assert "Python" in b
    assert "解释器路径" in b or "Python:" in b


def test_fastapi_routes_registered():
    """FastAPI 路由能正常注册，Web 应用可加载。"""
    from tm1_insight.api.app import app
    from tm1_insight.api.architecture import router as architecture_router
    from tm1_insight.api.workflow import router as workflow_router

    # 应用级路由 + 各 router 自身路由都应收录 /architecture、/workflow
    arch_paths = {getattr(r, "path", None) for r in architecture_router.routes}
    arch_paths.discard(None)
    wf_paths = {getattr(r, "path", None) for r in workflow_router.routes}
    wf_paths.discard(None)

    assert "/architecture" in arch_paths
    assert "/api/architecture/tasks" in arch_paths
    assert "/workflow" in wf_paths
    assert "/api/workflow/tasks" in wf_paths
    # 应用本身可加载（有路由即可，含 _IncludedRouter 包装）
    assert len(app.routes) > 0


def test_python_compat_no_pep604_in_module_source():
    """python_compat.py 自身必须能在 3.9 解析：不含 PEP 604 联合类型。"""
    import inspect
    import re
    src = inspect.getsource(python_compat)
    # 排除 set | set / re 标志等合法位或运算的干扰：直接检查注解中的 | None
    assert not re.search(r":\s*[A-Za-z_][A-Za-z0-9_\[\]]*\s*\|\s*None\b", src)
    assert " | None" not in src
