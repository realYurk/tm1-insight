"""采集范围：哪些对象进快照，哪些只留名字。

``}`` 开头的对象（``}bedrock.*``、``}Cubes``、``}Dimensions`` …）默认不进快照。
这是**范围**决定，不是**事实**决定，两者必须分开记录：

- 对象正文不收录；调用边照旧保留（「谁调用了 ``}bedrock.cube.data.clear``」
  是一个可核对的事实，不因为没采它的源码就消失）。
- 被排除的名字必须落盘成清单，否则下游只能判成「目录中不存在」。

本模块是这条规则的唯一实现，``exporter``（落盘）与 ``collector``（返回 payload）
都只调用它，不各写一份。
"""
from __future__ import annotations

#: 排除原因，写进 excluded_objects.reason / payload["excluded_reason"]。
EXCLUDED_REASON = "采集范围排除：} 开头的系统对象未收录"


def is_system_object(name: str | None) -> bool:
    """只认 ``}`` 前缀。

    不按「名字看着像框架」猜测（``APQ.*``、``Bedrock.*`` 也可能像），
    也不把 ``}`` 出现在中间的名字算进来——那可能是业务命名习惯。
    """
    return bool(name) and name.startswith("}")


def split_by_scope(
    names: dict[str, list[str]], include_system: bool = False,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """把对象名清单拆成 ``(收录, 排除)``，保持原有分类键。

    :param names: ``{"processes": [...], "cubes": [...], ...}``
    :param include_system: 为 True 时原样返回，排除为空
    """
    if include_system:
        return names, {}
    kept: dict[str, list[str]] = {}
    excluded: dict[str, list[str]] = {}
    for kind, values in names.items():
        keep, drop = [], []
        for name in values or []:
            (drop if is_system_object(name) else keep).append(name)
        kept[kind] = keep
        if drop:
            excluded[kind] = drop
    return kept, excluded
