"""调用点位置：把「A 调用 B」补成「A 在第 12 行调用 B」。

## 为什么不放进采集

三张调用事实表（``process_calls_process`` / ``ti_business_calls`` /
``ti_framework_calls``）都只有 caller/callee。加列意味着迁移已采集的库，
而位置只对**字面调用**有意义：变量解析出来的目标本来就带推断成分，
它的「行号」是解析器的行号，不是源码里那个调用点。

所以这里现算：只解析一个 TI 的源码（毫秒级），结果不落库。

## 三条口径

1. 用 ``mask_log_regions`` 而不是 ``strip_log_regions``。后者按行删除，
   删完后面所有行号都往前挪——位置错了比没有位置更坏。
2. 位置属于**调用点所在的那个 TI**。下游节点的位置在 root 的源码里，
   上游节点的位置在上游 TI 的源码里。两者绝不能混：2B 曾把被调用方的
   类型贴到调用方头上，一次错 121 个节点。
3. 同一个 TI 调同一个子进程多次时，只报第一处，另给次数。列五行位置
   没有意义，但「这里只有一处」和「这里共三处」是两回事。

## 覆盖范围

只覆盖 ``ExecuteProcess`` / ``RunProcess`` 的字面或已赋值参数。
bedrock 调用（``}bedrock.cube.data.copy`` 等）同样是字面调用，也能定位；
``ti_framework_calls`` 里的用途描述不参与定位。
"""
from __future__ import annotations

from tm1_insight.ingest.hard_extract import (
    extract_assignments, extract_calls, mask_log_regions,
)

SECTIONS = ("prolog", "metadata", "data", "epilog")


def position(code: str, offset: int) -> tuple[int, int]:
    """字符下标 → (行, 列)，均从 1 开始，与计算检查页的 evidence 同口径。"""
    line = code.count("\n", 0, offset) + 1
    column = offset - code.rfind("\n", 0, offset)
    return line, column


def attach(con, tree: dict) -> dict:
    """给调用树的**直接**上下游节点补上调用点位置（``node['site']``）。

    只做直接一层，理由有两条：

    - 成本：上游位置要逐个解析上游 TI 的源码（约 4 ms/个），深层展开会变成
      几十上百次解析，而首屏只需要知道「谁、在哪一行、调了它」；
    - 语义：``site`` 是「调用点所在 TI」的位置。更下层节点的调用点在那个
      中间 TI 的源码里，画在 root 的图上容易被读成 root 干的。

    ``site['process']`` 指明该行号属于谁——下游属于 root，上游属于上游自己。
    """
    root = tree.get("name")
    if not root:
        return tree
    marked = 0
    unlocated = 0

    def _counts(node) -> bool:
        """这个节点本该有位置吗？目录里没有、按范围未收录的，没有源码可定位。"""
        return node.get("catalog", "included") == "included"

    try:
        downstream = sites_for(con, root)
    except Exception:  # noqa: BLE001
        downstream = {}
    for node in tree.get("callees") or []:
        site = downstream.get(node.get("name"))
        if site:
            node["site"] = dict(site, process=root)
            marked += 1
        elif _counts(node):
            unlocated += 1
    for node in tree.get("callers") or []:
        caller = node.get("name")
        if not caller:
            continue
        try:
            upstream = sites_for(con, caller)
        except Exception:  # noqa: BLE001
            continue
        site = upstream.get(root)
        if site:
            node["site"] = dict(site, process=caller)
            marked += 1
        elif _counts(node):
            unlocated += 1
    tree["site_count"] = marked
    # 未定位的也要报数：有边却没有位置，说明调用目标在源码里是变量拼出来的，
    # 或者这条边来自历史采集、与当前源码不一致。安静地不标，会被读成「都一样」。
    tree["site_unlocated"] = unlocated
    return tree

def sites_for(con, name: str) -> dict[str, dict]:
    """某个 TI 源码里每个被调用目标的第一个调用点。

    返回 ``{被调用 TI 名: {section, line, column, operation, count}}``。
    解析失败的对象不进结果——没有位置就是没有位置，不猜。
    """
    row = con.execute(
        "SELECT prolog, metadata, data, epilog FROM processes WHERE name = ?", [name]
    ).fetchone()
    if row is None:
        return {}
    sites: dict[str, dict] = {}
    for section, code in zip(SECTIONS, row):
        if not code:
            continue
        # 廉价的预筛：绝大多数代码段里没有调用语句，别为它们跑完整的赋值/调用解析。
        lowered = code.lower()
        if 'executeprocess' not in lowered and 'runprocess' not in lowered:
            continue
        masked = mask_log_regions(code)
        try:
            assignments = extract_assignments(masked)
            calls = extract_calls(masked, assignments)
        except Exception:  # noqa: BLE001 —— 单个 TI 解析失败不应拖垮整张图
            continue
        for call in calls:
            callee = call.get("callee")
            if not callee or callee.startswith("<"):
                continue
            line, column = position(masked, call.get("offset") or 0)
            item = sites.get(callee)
            if item is None:
                sites[callee] = dict(section=section, line=line, column=column,
                                     operation=call["operation"], count=1)
            else:
                item["count"] += 1
    return sites
