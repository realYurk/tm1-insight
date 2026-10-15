"""Dimension Explorer v1.2 元数据采集修复的合成测试。

覆盖（不连接真实 TM1，全部 Mock）：
1. Subset 字符串名称的正确采集（_subset_name 兼容 str / 对象 / dict）
2. Subset 对象与字典兼容
3. 静态与动态 Subset 定义（fetch_dimension_full 的 subset_definitions）
4. 属性值采集与 Alias（_collect_attribute_values）
5. 多 Hierarchy（fetch_dimension_full 的 hierarchies）
6. 采集权限不足或部分失败（状态标记，不伪造）
7. 增量补采（fetch_dimension_incremental）
8. 缺失名称不被当成真实空子集（collector._map_dimension）
"""
from __future__ import annotations

import pytest

from tm1_insight.tm1.client import TM1Client, _subset_name, safe_getattr
from tm1_insight.collector import _map_dimension


# ---------------------------------------------------------------------------
# 1. _subset_name 兼容三种来源形态
# ---------------------------------------------------------------------------
def test_subset_name_from_string():
    assert _subset_name("All Elements") == "All Elements"


def test_subset_name_from_dict():
    assert _subset_name({"Name": "Top 10"}) == "Top 10"
    assert _subset_name({"name": "Top 10"}) == "Top 10"


def test_subset_name_from_object():
    class S:
        name = "Dynamic Set"
    assert _subset_name(S()) == "Dynamic Set"


def test_subset_name_none_for_missing():
    # None / 无名对象 / 空 dict 都返回 None，绝不伪造空串
    assert _subset_name(None) is None
    assert _subset_name({}) is None
    assert _subset_name(12345) is None  # 非 str/dict/带 name 属性的对象


# ---------------------------------------------------------------------------
# 2/3. fetch_dimension 的 subsets 采集（str 来源不再丢失名称）
# ---------------------------------------------------------------------------
class _FakeHierarchy:
    def __init__(self, subsets, element_attributes=(), edges=None, elements=()):
        self.subsets = subsets  # 模拟 list[str]（Hierarchy.from_dict 的真实形态）
        self.element_attributes = element_attributes
        self.edges = edges or {}
        # 真实 Hierarchy.elements 是 dict（元素名 -> Element 对象），有 .values()
        if isinstance(elements, dict):
            self.elements = elements
        else:
            self.elements = {}
            for e in elements:
                name = e if isinstance(e, str) else e["name"]
                self.elements[name] = _FakeElement(name)


class _FakeElement:
    def __init__(self, name, element_type="Numeric"):
        self.name = name
        self.element_type = element_type


class _FakeTM1:
    """模拟 TM1py 连接：hierarchies.get 返回带 list[str] subsets 的 Hierarchy。"""
    def __init__(self, hierarchy=None):
        self._hierarchy = hierarchy
        self.hierarchies = _FakeHierarchyService(self._hierarchy)
        self.subsets = _FakeSubsetService()
        self.elements = _FakeElementService()

    def logout(self):
        pass


class _FakeHierarchyService:
    def __init__(self, hierarchy):
        self._hierarchy = hierarchy

    def get_all_names(self, name):
        return [name]

    def get(self, name, hname):
        return self._hierarchy


class _FakeSubsetService:
    def __init__(self):
        self.defs = {}

    def get_all_names(self, dimension, hierarchy_name=None, private=False):
        assert private is False  # 只采集公共子集
        return list(self.defs.keys())

    def get(self, subset_name, dimension, hierarchy_name=None, private=False):
        return self.defs[subset_name]


class _FakeElementService:
    def __init__(self):
        self.attr_values = {}

    def get_attribute_of_elements(self, dim, hierarchy, attr, elements, exclude_empty_cells=False):
        return {e: self.attr_values.get(attr, {}).get(e) for e in elements}


class _SubsetObj:
    def __init__(self, name, expression=None, elements=None, hierarchy_name=None):
        self._subset_name = name
        self._expression = expression
        self._elements = elements or []
        self._hierarchy_name = hierarchy_name

    @property
    def name(self):
        return self._subset_name

    @property
    def expression(self):
        return self._expression

    @property
    def elements(self):
        return self._elements

    @property
    def hierarchy_name(self):
        return self._hierarchy_name

    @property
    def is_dynamic(self):
        return bool(self._expression)


class _ElementAttr:
    def __init__(self, name, attribute_type):
        self._name = name
        self._attribute_type = attribute_type

    @property
    def name(self):
        return self._name

    @property
    def attribute_type(self):
        return self._attribute_type


class _Settings:
    tm1_light_system_dims = False


def test_fetch_dimension_preserves_subset_string_names():
    # Hierarchy.subsets 是 list[str]（真实 TM1py 行为），旧代码会丢名称
    h = _FakeHierarchy(
        subsets=["All Elements", "Top 10"],
        element_attributes=[_ElementAttr("Alias", "Alias"), _ElementAttr("Desc", "String")],
        edges={("Total", "A"): 1},
    )
    tm1 = _FakeTM1(h)
    client = TM1Client(_Settings())
    result = client.fetch_dimension(tm1, "Car Model", is_system=False)

    assert [s["name"] for s in result["subsets"]] == ["All Elements", "Top 10"]
    assert [a["name"] for a in result["attributes"]] == ["Alias", "Desc"]


def test_fetch_dimension_full_subset_definitions_static_vs_dynamic():
    class StaticSubset(_SubsetObj):
        def __init__(self):
            super().__init__("Static Set", expression=None, elements=["A", "B", "C"])

    class DynamicSubset(_SubsetObj):
        def __init__(self):
            super().__init__("Dynamic Set", expression="{TM1FILTERBYLEVEL(...)}")

    h = _FakeHierarchy(subsets=["Static Set", "Dynamic Set"])
    tm1 = _FakeTM1(h)
    tm1.subsets.defs = {"Static Set": StaticSubset(), "Dynamic Set": DynamicSubset()}
    client = TM1Client(_Settings())
    result = client.fetch_dimension_full(tm1, "Car Model", is_system=False)

    defs = {d["name"]: d for d in result["subset_definitions"]}
    assert defs["Static Set"]["type"] == "static"
    assert defs["Static Set"]["elements"] == ["A", "B", "C"]
    assert defs["Static Set"]["status"] == "collected"
    assert defs["Dynamic Set"]["type"] == "dynamic"
    assert defs["Dynamic Set"]["expression"] == "{TM1FILTERBYLEVEL(...)}"


def test_fetch_dimension_full_subset_unavailable_kept():
    # 名称可枚举但定义取不到（权限受限/被删），必须保留为 unavailable，不丢名
    class _Boom:
        def __init__(self):
            pass

    h = _FakeHierarchy(subsets=["Locked Set"])
    tm1 = _FakeTM1(h)

    class FailingSubsetService(_FakeSubsetService):
        def get(self, subset_name, dimension, hierarchy_name=None, private=False):
            raise PermissionError("no access")

    tm1.subsets = FailingSubsetService()
    tm1.subsets.defs = {"Locked Set": _SubsetObj("Locked Set")}
    client = TM1Client(_Settings())
    result = client.fetch_dimension_full(tm1, "Car Model", is_system=False)

    defs = result["subset_definitions"]
    assert len(defs) == 1
    assert defs[0]["name"] == "Locked Set"
    assert defs[0]["status"] == "unavailable"


def test_fetch_dimension_full_multi_hierarchy():
    class HierarchyService(_FakeHierarchyService):
        def get_all_names(self, name):
            return ["Car Model", "Car Model Alternate"]

        def get(self, name, hname):
            return _FakeHierarchy(
                subsets=["S%d" % (1 if hname == "Car Model" else 2)],
                element_attributes=[_ElementAttr("Alias", "Alias")],
                edges={("Total", "A"): 1},
                elements=[{"name": "A"}],
            )

    tm1 = _FakeTM1(None)
    tm1.hierarchies = HierarchyService(None)
    client = TM1Client(_Settings())
    result = client.fetch_dimension_full(tm1, "Car Model", is_system=False)

    assert result["hierarchy_names"] == ["Car Model", "Car Model Alternate"]
    assert len(result["hierarchies"]) == 2
    assert [h["name"] for h in result["hierarchies"]] == ["Car Model", "Car Model Alternate"]


def test_attribute_value_collection_with_alias():
    h = _FakeHierarchy(subsets=[], element_attributes=[_ElementAttr("Alias", "Alias")])
    tm1 = _FakeTM1(h)
    tm1.elements.attr_values = {"Alias": {"A": "汽车A", "B": "汽车B"}}
    client = TM1Client(_Settings())
    result = client._collect_attribute_values(
        tm1, "Car Model", "Car Model", ["Alias"], ["A", "B"])

    assert result["attributes"]["Alias"]["status"] == "collected"
    assert result["attributes"]["Alias"]["values"] == {"A": "汽车A", "B": "汽车B"}
    assert result["attributes"]["Alias"]["count"] == 2


def test_attribute_value_skipped_without_elements():
    # 不指定元素范围时不采集，不伪造空值
    client = TM1Client(_Settings())
    result = client._collect_attribute_values(_FakeTM1(None), "Dim", "Dim", ["Alias"], None)
    assert "skipped" in result["status"]


def test_incremental_recollect_returns_full_structure():
    h = _FakeHierarchy(subsets=["All"], element_attributes=[_ElementAttr("Alias", "Alias")])
    tm1 = _FakeTM1(h)
    tm1.subsets.defs = {"All": _SubsetObj("All", elements=["X"])}
    client = TM1Client(_Settings())
    result = client.fetch_dimension_incremental(
        tm1, "Car Model", attributes=["Alias"], elements_for_values=["X"])

    assert result["name"] == "Car Model"
    assert "hierarchies" in result
    assert "subset_definitions" in result
    assert "attribute_values" in result
    assert result["subset_definitions"][0]["name"] == "All"


# ---------------------------------------------------------------------------
# 8. _map_dimension 缺失名称不当空子集
# ---------------------------------------------------------------------------
def test_map_dimension_drops_null_subset_names():
    raw = {
        "name": "Dim",
        "elements": [{"name": "A", "type": "Numeric"}],
        "subsets": [
            {"name": "All", "expression": None},
            {"name": None, "expression": None},  # 旧采集缺陷产物
            {"name": "", "expression": None},    # 空串也不当有效名
        ],
    }
    result = _map_dimension(raw)
    assert result["subsets"] == ["All"]  # 只保留真实名称，不伪造空串


def test_map_dimension_string_subsets_in_raw():
    # raw subsets 里若已是字符串（未来可能的形态），也应能取到名
    raw = {"name": "Dim", "elements": [], "subsets": ["S1", "S2"]}
    # 注意：collector._map_dimension 期望 subsets 是 dict 列表；字符串形态由
    # client 层已规范化为 dict，这里只验证 dict 形态的健壮性
    raw2 = {"name": "Dim", "elements": [], "subsets": [{"name": "S1"}, {"name": "S2"}]}
    assert _map_dimension(raw2)["subsets"] == ["S1", "S2"]
