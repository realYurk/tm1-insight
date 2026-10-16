"""TM1 客户端：薄封装 TM1py，复用 tm1tree/main.py 的 API 面。

设计原则：
- 只负责「连接 + 读取 + 标准化为 dict」，不做落盘/调度（落盘在 ingest.exporter）。
- 每线程一个独立连接（TM1py 非线程安全）。
- 保留原实现的三级规则回退与 dict/对象兼容逻辑。
"""
from __future__ import annotations

import logging
from typing import Any

from TM1py import TM1Service

from tm1_insight.config import Settings

logger = logging.getLogger(__name__)


def safe_getattr(obj: Any, attr: str, default: Any = None) -> Any:
    """同时兼容 dict 与 TM1py 对象。"""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _subset_name(s: Any) -> str | None:
    """从子集条目提取名称，兼容三种来源形态。

    TM1py 的 ``Hierarchy.from_dict()`` 把 ``subsets`` 构造为 ``list[str]``
    （子集名称字符串），而 ``SubsetService.get()`` 返回 ``Subset`` 对象，
    Raw JSON 里则可能是 ``{"Name": ...}`` dict。对字符串取 ``.name`` 会得到
    None，导致子集名称系统性丢失——这里显式分派，绝不把「缺失名称」当空子集。

    返回 None 仅表示该条目确实无法解析出名称（而非空字符串）。
    """
    if s is None:
        return None
    if isinstance(s, str):
        return s
    if isinstance(s, dict):
        return s.get("Name") or s.get("name")
    return safe_getattr(s, "name")


def safe_filename(name: str) -> str:
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '_')
    return name


class TM1Client:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ---- 连接 ----
    def connect(self) -> TM1Service:
        """创建一个 TM1py 连接（每线程调用一次）。

        连接参数全部来自 Settings（.env / 环境变量），
        使用 async_requests_mode 提升并发拉取性能。
        """
        s = self.settings
        return TM1Service(
            address=s.tm1_address,
            port=s.tm1_port,
            user=s.tm1_user,
            password=s.tm1_password,
            ssl=s.tm1_ssl,
            namespace=s.tm1_namespace,
            async_requests_mode=True,
        )

    def list_all_names(self) -> dict[str, list[str]]:
        """一次性获取全部对象名（连接复用）。"""
        with self.connect() as tm1:
            return {
                "cubes": tm1.cubes.get_all_names(),
                "processes": tm1.processes.get_all_names(),
                "dimensions": tm1.dimensions.get_all_names(),
                "chores": tm1.chores.get_all_names(),
            }

    def fetch_security(self) -> tuple[list[dict], list[dict]]:
        """拉取 Groups 与 Users（TM1 中 Client 即 User）。

        失败只降级为空列表并告警，不阻断主流程。
        """
        with self.connect() as tm1:
            try:
                # get_all_groups() 返回 List[str]（组名，非对象）
                groups = [{"name": g} for g in tm1.security.get_all_groups()]
            except Exception as e:  # noqa: BLE001
                logger.warning("拉取 Groups 失败: %s", e)
                groups = []
            try:
                # get_all_users() 返回 List[User]，TM1 中 User = Client
                users = [{"name": safe_getattr(u, "name")} for u in tm1.security.get_all_users()]
            except Exception as e:  # noqa: BLE001
                logger.warning("拉取 Users 失败: %s", e)
                users = []
            return groups, users

    def check(self) -> dict[str, Any]:
        """验证连接：返回服务器名、版本与各对象计数。用于 `tm1-insight check`。"""
        with self.connect() as tm1:
            info: dict[str, Any] = {}
            try:
                info["server_name"] = tm1.server.get_server_name()
            except Exception:  # noqa: BLE001
                info["server_name"] = "?"
            try:
                info["product_version"] = tm1.server.get_product_version()
            except Exception:  # noqa: BLE001
                info["product_version"] = "?"
            info["cubes"] = len(tm1.cubes.get_all_names())
            info["processes"] = len(tm1.processes.get_all_names())
            info["dimensions"] = len(tm1.dimensions.get_all_names())
            info["chores"] = len(tm1.chores.get_all_names())
            return info

    # ---- Read-only rule collection, preserving unavailable vs empty ----
    @staticmethod
    def _rule_text(value,depth=0):
        if depth>4:return None
        if isinstance(value,str):return value
        if value is None:return ""
        if isinstance(value,dict):
            for key in ("Rules","rules","Text","text","value"):
                if key in value:return TM1Client._rule_text(value[key],depth+1)
            return None
        text=getattr(value,"text",None)
        return text if isinstance(text,str) else None

    @staticmethod
    def read_cube_rules(tm1,cube_name):
        sentinel=object()
        try:
            cube=tm1.cubes.get(cube_name)
            value=safe_getattr(cube,"rules",sentinel)
            if value is sentinel:value=safe_getattr(cube,"Rules",sentinel)
            if value is not sentinel:
                text=TM1Client._rule_text(value)
                if text is not None:return text,"available"
        except Exception:pass
        for getter in (getattr(tm1.cubes,"get_rules",None),getattr(getattr(tm1.cubes,"rules",None),"get",None)):
            if callable(getter):
                try:
                    text=TM1Client._rule_text(getter(cube_name))
                    if text is not None:return text,"available"
                except Exception:pass
        try:
            escaped=cube_name.replace("'","''")
            data=tm1._rest.GET(f"/Cubes('{escaped}')?$select=Rules").json()
            text=TM1Client._rule_text(data)
            if text is not None:return text,"available"
        except Exception:pass
        return "","unavailable"

    @staticmethod
    def get_cube_rules(tm1,cube_name):
        # Backward-compatible text API. New collection also records status.
        return TM1Client.read_cube_rules(tm1,cube_name)[0]

    def fetch_cube(self,tm1,name):
        dims=tm1.cubes.get_dimension_names(name)
        text,status=self.read_cube_rules(tm1,name)
        return {"name":name,"dimensions":list(dims),"rules":text,
                "has_rules":bool(text.strip()),"rules_status":status}

    def fetch_process(self, tm1: TM1Service, name: str) -> dict:
        p = tm1.processes.get(name)

        params = []
        for param in safe_getattr(p, "parameters", []) or []:
            if isinstance(param, dict):
                params.append(
                    {
                        "name": param.get("Name") or param.get("name"),
                        "type": str(param.get("Type") or param.get("type", "")),
                        "default_value": param.get("Default") or param.get("default_value"),
                    }
                )
            else:
                params.append(
                    {
                        "name": safe_getattr(param, "name"),
                        "type": str(safe_getattr(param, "type", "")),
                        "default_value": safe_getattr(param, "default_value"),
                    }
                )

        ds = safe_getattr(p, "data_source", None) or safe_getattr(p, "datasource", None)
        ds_dict = None
        if ds:
            ds_dict = {
                "type": str(safe_getattr(ds, "type", "")),
                "cube": safe_getattr(ds, "cube_name") or safe_getattr(ds, "cube"),
                "view": safe_getattr(ds, "view_name") or safe_getattr(ds, "view"),
                "query": safe_getattr(ds, "query"),
            }

        return {
            "name": safe_getattr(p, "name"),
            "prolog": safe_getattr(p, "prolog_procedure", "") or "",
            "metadata": safe_getattr(p, "metadata_procedure", "") or "",
            "data": safe_getattr(p, "data_procedure", "") or "",
            "epilog": safe_getattr(p, "epilog_procedure", "") or "",
            "parameters": params,
            "datasource": ds_dict,
        }

    def _get_hierarchy(self, tm1: TM1Service, name: str):
        """获取维度的默认层级。

        多数维度默认层级名 == 维度名；但多层级维度的默认层级名可能不同，
        直接 get(name, name) 会 404，这里回退到「第一个层级名」。
        """
        try:
            return tm1.hierarchies.get(name, name)
        except Exception:  # noqa: BLE001
            hier_names = tm1.hierarchies.get_all_names(name)
            return tm1.hierarchies.get(name, hier_names[0])

    def fetch_dimension(self, tm1: TM1Service, name: str, is_system: bool) -> dict:
        hierarchy = self._get_hierarchy(tm1, name)

        elements = [
            {
                "name": safe_getattr(e, "name"),
                "type": str(safe_getattr(e, "element_type", "Numeric")),
            }
            for e in hierarchy.elements.values()
        ]

        if is_system and self.settings.tm1_light_system_dims:
            return {
                "name": name,
                "is_system": True,
                "elements": [e["name"] for e in elements],
                "element_count": len(elements),
            }

        edges = []
        if getattr(hierarchy, "edges", None):
            for edge, weight in hierarchy.edges.items():
                edges.append({"parent": edge[0], "component": edge[1], "weight": weight})

        attributes = []
        if getattr(hierarchy, "element_attributes", None):
            for a in hierarchy.element_attributes:
                # 属性名同样可能以 str / dict / 对象三种形态出现（ElementAttribute
                # 对象、Raw JSON 的 {"Name":...}、或纯字符串），统一用 _subset_name。
                attributes.append(
                    {"name": _subset_name(a), "type": str(safe_getattr(a, "attribute_type", ""))}
                )

        subsets = []
        if getattr(hierarchy, "subsets", None):
            for s in hierarchy.subsets:
                subsets.append({"name": _subset_name(s), "expression": safe_getattr(s, "expression")})

        return {
            "name": name,
            "is_system": False,
            "elements": elements,
            "element_count": len(elements),
            "edges": edges,
            "attributes": attributes,
            "subsets": subsets,
        }

    # ------------------------------------------------------------------
    # 完整层级 / 子集定义 / 属性值采集（版本化扩展，不破坏既有 fetch_dimension）
    # ------------------------------------------------------------------

    def _list_hierarchy_names(self, tm1: TM1Service, name: str) -> list[str]:
        """返回某维度的全部层级名（含默认层级）。失败降级为 [维度名]。"""
        try:
            names = list(tm1.hierarchies.get_all_names(name))
            return names if names else [name]
        except Exception as e:  # noqa: BLE001
            logger.warning("获取 %s 层级名失败: %s", name, e)
            return [name]

    def _collect_subset_definitions(self, tm1: TM1Service, dimension: str,
                                    hierarchy: str | None = None) -> dict:
        """采集某维度的公共子集名称与定义（区分静态/动态 MDX）。

        只采集公共子集（``private=False``），不采集其他用户私有子集。
        对每个子集用 ``SubsetService.get`` 取定义：
        - 动态子集：保留 MDX 表达式（``expression``），不在此求值。
        - 静态子集：保留成员列表及其顺序（``elements``）。

        返回 ``{"names": [...], "definitions": [...], "status": {...}}``，
        每个 definition 带 ``status`` 标记 collected/unavailable/failed，
        名称采集成功但定义失败的子集也会以 unavailable 形式列出，保证
        「名称与定义分离、不把失败当空子集」。
        """
        result: dict = {"names": [], "definitions": [], "status": {}}
        try:
            subset_names = list(tm1.subsets.get_all_names(
                dimension, hierarchy_name=hierarchy, private=False))
        except Exception as e:  # noqa: BLE001
            logger.warning("获取 %s 公共子集名称失败: %s", dimension, e)
            result["status"]["list"] = "failed"
            return result
        result["names"] = subset_names
        result["status"]["list"] = "collected"
        result["status"]["total"] = len(subset_names)

        for sname in subset_names:
            try:
                subset = tm1.subsets.get(sname, dimension, hierarchy_name=hierarchy, private=False)
                is_dynamic = bool(safe_getattr(subset, "expression"))
                definition = {
                    "name": _subset_name(subset) or sname,
                    "hierarchy": hierarchy or safe_getattr(subset, "hierarchy_name"),
                    "dimension": dimension,
                    "type": "dynamic" if is_dynamic else "static",
                    "expression": safe_getattr(subset, "expression"),
                    "elements": list(safe_getattr(subset, "elements") or []),
                    "status": "collected",
                }
            except Exception as e:  # noqa: BLE001
                # 名称可枚举但定义取不到（如权限受限 / 子集被删）
                logger.warning("获取子集 %s 定义失败: %s", sname, e)
                definition = {
                    "name": sname,
                    "hierarchy": hierarchy,
                    "dimension": dimension,
                    "type": "unknown",
                    "expression": None,
                    "elements": [],
                    "status": "unavailable",
                }
            result["definitions"].append(definition)
        return result

    def _collect_attribute_values(self, tm1: TM1Service, dimension: str,
                                  hierarchy: str, attributes: list[str],
                                  elements: list[str] | None = None,
                                  batch_size: int = 2000) -> dict:
        """按需采集属性值（含 Alias），只读、有限范围。

        ``attributes`` 为要采集的属性名（普通文本/数值属性与 Alias 都通过
        ``ElementService.get_attribute_of_elements`` 读取）；``elements`` 限定
        元素范围（None 表示不采集任何值，避免几十万元素全量拉取）。

        返回 ``{"attributes": {...}, "status": {...}}``，其中 attributes 是
        ``属性名 -> {"values": {元素名: 值}, "status": ...}``。采集失败保留
        具体状态，绝不伪造空白或未知值。
        """
        result: dict = {"attributes": {}, "status": {}}
        if not elements:
            result["status"]["skipped"] = "未指定元素范围，不采集属性值"
            return result
        for attr in attributes:
            entry: dict = {"values": {}, "status": "collected"}
            collected = 0
            try:
                for i in range(0, len(elements), batch_size):
                    batch = elements[i:i + batch_size]
                    values = tm1.elements.get_attribute_of_elements(
                        dimension, hierarchy, attr, batch, exclude_empty_cells=False)
                    if isinstance(values, dict):
                        for elem, val in values.items():
                            entry["values"][elem] = val
                            collected += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("采集属性 %s.%s 失败: %s", dimension, attr, e)
                entry["status"] = "failed" if collected == 0 else "partial"
            entry["count"] = collected
            result["attributes"][attr] = entry
        return result

    def fetch_dimension_full(self, tm1: TM1Service, name: str, is_system: bool,
                             *, include_hierarchies: bool = True,
                             include_subset_definitions: bool = True,
                             attributes: list[str] | None = None,
                             elements_for_values: list[str] | None = None) -> dict:
        """采集一个维度的完整元数据（层级 + 子集定义 + 可选属性值）。

        这是对 ``fetch_dimension`` 的增强版，产出「版本化扩展结构」：在既有
        raw dict 上追加 ``hierarchies``、``subset_definitions``、
        ``attribute_values`` 三个可选字段，不破坏 loader/exporter 对旧字段的
        消费。默认不采集属性值（``elements_for_values=None``），避免全量拉取。
        """
        base = self.fetch_dimension(tm1, name, is_system)
        if is_system and self.settings.tm1_light_system_dims:
            return base

        hierarchy_names = self._list_hierarchy_names(tm1, name)
        hierarchies = []
        for hname in hierarchy_names:
            try:
                h = tm1.hierarchies.get(name, hname)
            except Exception as e:  # noqa: BLE001
                logger.warning("获取层级 %s.%s 失败: %s", name, hname, e)
                hierarchies.append({"name": hname, "status": "failed"})
                continue
            edges = []
            for edge, weight in (safe_getattr(h, "edges") or {}).items():
                edges.append({"parent": edge[0], "component": edge[1], "weight": weight})
            hierarchies.append({
                "name": hname,
                "dimension": name,
                "element_count": len(safe_getattr(h, "elements") or []),
                "edges": edges,
                "default_member": safe_getattr(h, "default_member"),
                "attributes": [
                    {"name": _subset_name(a), "type": str(safe_getattr(a, "attribute_type", ""))}
                    for a in (safe_getattr(h, "element_attributes") or [])
                ],
                "subsets": [_subset_name(s) for s in (safe_getattr(h, "subsets") or [])],
                "status": "collected",
            })
        base["hierarchies"] = hierarchies
        base["hierarchy_names"] = hierarchy_names

        if include_subset_definitions:
            # 公共子集定义：对每个层级各取一次（多数维度只有一个默认层级）。
            definitions: list[dict] = []
            seen_names: set[str] = set()
            for hname in hierarchy_names:
                subset_meta = self._collect_subset_definitions(tm1, name, hname)
                for d in subset_meta["definitions"]:
                    if d["name"] not in seen_names:
                        seen_names.add(d["name"])
                        definitions.append(d)
            base["subset_definitions"] = definitions
            base["subset_definition_status"] = {
                "list": "collected",
                "total": len(definitions),
            }

        if attributes:
            # 只对默认层级采集属性值（属性在多层级间通常共享；避免重复）。
            default_h = hierarchy_names[0] if hierarchy_names else name
            base["attribute_values"] = self._collect_attribute_values(
                tm1, name, default_h, attributes, elements_for_values)
        return base

    def fetch_dimension_incremental(self, tm1: TM1Service, name: str,
                                    *, include_hierarchies: bool = True,
                                    include_subset_definitions: bool = True,
                                    attributes: list[str] | None = None,
                                    elements_for_values: list[str] | None = None) -> dict:
        """指定维度的增量补采（不重采整个模型）。

        与 ``fetch_dimension_full`` 等价，但语义上强调「单维度、按需」：
        用户可对 Car Model 这类单维度补采层级、公共子集、所选属性值，
        无需重新拉取 12,280 个维度。
        """
        return self.fetch_dimension_full(
            tm1, name, is_system=name.startswith("}"),
            include_hierarchies=include_hierarchies,
            include_subset_definitions=include_subset_definitions,
            attributes=attributes,
            elements_for_values=elements_for_values,
        )

    def fetch_chore(self, tm1: TM1Service, name: str) -> dict:
        chore = tm1.chores.get(name)
        processes = []
        # TM1py 的 Chore 对象里任务列表属性名是 `tasks`（不是 `processes`）。
        # 每个 ChoreTask 有 `process_name` 与 `step` 属性（1-based 顺序）。
        # 保留对 dict / 旧字段名的兼容，避免不同 TM1py 版本取不到。
        tasks = safe_getattr(chore, "tasks", None)
        if tasks is None:
            tasks = safe_getattr(chore, "processes", [])
        for task in tasks or []:
            if isinstance(task, dict):
                # dict 形态：REST 展开后 Task 的 Process 是 {"Name": ...}
                proc_ref = task.get("Process") or {}
                pname = task.get("process_name") or task.get("Name") or task.get("name")
                if isinstance(proc_ref, dict):
                    pname = pname or proc_ref.get("Name") or proc_ref.get("name")
                step = task.get("Step", task.get("step", task.get("step_order")))
                processes.append({"name": pname, "step_order": step})
            else:
                # ChoreTask 对象：process_name / step 属性
                pname = (safe_getattr(task, "process_name")
                         or safe_getattr(task, "name")
                         or safe_getattr(task, "Process"))
                # process_name 可能是 Process 对象，取其 name
                if hasattr(pname, "name"):
                    pname = pname.name
                processes.append(
                    {
                        "name": pname,
                        "step_order": safe_getattr(task, "step", None),
                    }
                )

        return {
            "name": name,
            "start_time": str(safe_getattr(chore, "start_time", "")),
            "execution_mode": str(safe_getattr(chore, "execution_mode", "")),
            "frequency": str(safe_getattr(chore, "frequency", "")),
            "active": str(safe_getattr(chore, "active", "")),
            "processes": processes,
        }
