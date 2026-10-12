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
                attributes.append(
                    {"name": safe_getattr(a, "name"), "type": str(safe_getattr(a, "attribute_type", ""))}
                )

        subsets = []
        if getattr(hierarchy, "subsets", None):
            for s in hierarchy.subsets:
                subsets.append({"name": safe_getattr(s, "name"), "expression": safe_getattr(s, "expression")})

        return {
            "name": name,
            "is_system": False,
            "elements": elements,
            "element_count": len(elements),
            "edges": edges,
            "attributes": attributes,
            "subsets": subsets,
        }

    def fetch_chore(self, tm1: TM1Service, name: str) -> dict:
        chore = tm1.chores.get(name)
        processes = []
        # TM1py 的 Chore 对象里任务列表属性名是 `tasks`（不是 `processes`）。
        # 每个 ChoreTask 有 `process_name` 与 `step` 属性（1-based 顺序）。
        # 保留对 dict / 旧字段名的兼容，避免不同 TM1py 版本取不到。
        tasks = safe_getattr(chore, "tasks", None)
        if tasks is None:
            tasks = safe_getattr(chore, "processes", [])
        for idx, task in enumerate(tasks or []):
            if isinstance(task, dict):
                # dict 形态：REST 展开后 Task 的 Process 是 {"Name": ...}
                proc_ref = task.get("Process") or {}
                pname = task.get("process_name") or task.get("Name") or task.get("name")
                if isinstance(proc_ref, dict):
                    pname = pname or proc_ref.get("Name") or proc_ref.get("name")
                step = task.get("Step") or task.get("step") or idx
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
                        "step_order": safe_getattr(task, "step", idx),
                    }
                )

        return {
            "name": name,
            "start_time": str(safe_getattr(chore, "start_time", "")),
            "execution_mode": str(safe_getattr(chore, "execution_mode", "")),
            "frequency": str(safe_getattr(chore, "frequency", "")),
            "processes": processes,
        }
