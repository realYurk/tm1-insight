"""范围视图：页面上看得见的，和导出拿到的，用同一把尺子。

计算检查页早就按 ``}`` 前缀隐藏写入点（``/calculation?system=``），
导出却一直是全量：屏幕上是 14 条，下载下来 15 条，没有一句话说明差在哪。
用户核对材料时对不上账，只能怀疑是自己看错。

差异本身可以有——导出是核对材料，宁多勿少——但**默认不能悄悄发生**。
所以这里做三件事：

1. 过滤只写一份，页面和导出都调它，不各写一套判断；
2. 隐藏掉的逐条留账（数量、立方体名、原始编号），并写进导出正文；
3. ``include_system=True`` 时原样放行，用同一个结构报告「这次是全量」。

只作用于**可独立成条的清单**（写入点、参数使用位置）。DAG 节点不过滤：
砍掉节点会打断 ``children`` 引用，而依赖图本来也不是「收录清单」，
它是「这张图的推理依据」，缺一个节点就说不出为什么这么推。

编号（``write.id``）一律保持原值，绝不重新编号——否则「写入 3」
在页面和导出里指向两条不同的记录，等于把对账做成了新的坑。
"""
from __future__ import annotations

from tm1_insight.ingest.scope import is_system_object

BUSINESS = 'business'
ALL = 'all'


def _dropped_summary(dropped: list[dict]) -> dict:
    return dict(
        hidden=len(dropped),
        cubes=sorted({w.get('cube') for w in dropped if w.get('cube')}),
        write_ids=[w['id'] for w in dropped if w.get('id') is not None],
    )


def narrow_report(report: dict | None, include_system: bool = False):
    """计算检查报告 → ``(可见视图, 范围账)``。

    返回的视图是浅拷贝，``writes`` 是新列表；入参 report 不被修改，
    因为同一个对象还要喂给节点渲染和 Markdown。
    """
    if not report:
        return report, dict(scope=ALL, visible=0, hidden=0, cubes=[], write_ids=[])
    writes = list(report.get('writes') or [])
    system_writes = [w for w in writes if is_system_object(w.get('cube'))]
    if include_system:
        view = dict(report)
        info = dict(scope=ALL, visible=len(writes), hidden=0, cubes=[], write_ids=[],
                    system_count=len(system_writes))
        view['scope_view'] = info
        return view, info
    kept = [w for w in writes if not is_system_object(w.get('cube'))]
    view = dict(report)
    view['writes'] = kept
    info = dict(scope=BUSINESS, visible=len(kept), **_dropped_summary(system_writes),
                system_count=len(system_writes))
    view['scope_view'] = info
    return view, info


def narrow_invocation(report: dict | None, include_system: bool = False):
    """单次调用报告 → ``(可见视图, 范围账)``。

    这里有两条清单要一起收：子 TI 的写入点，和每个参数在子 TI 里的使用位置。
    后者尤其不能默默砍——它一少，「这个参数没被用到」就成了假话。
    所以被隐藏的条数记在 ``uses`` 上，逐参数记在 ``uses_hidden`` 上，
    模板和导出都必须把它们说出来。
    """
    if not report:
        return report, dict(scope=ALL, hidden=0, cubes=[], uses=0, writes=0, system_count=0)
    child = report.get('child')
    child_writes = list(child.get('writes') or []) if child else []
    bindings = list(report.get('bindings') or [])
    system_writes = [w for w in child_writes if is_system_object(w.get('cube'))]
    system_uses = sum(1 for b in bindings for u in (b.get('uses') or []) if is_system_object(u.get('cube')))
    if include_system:
        view = dict(report)
        info = dict(scope=ALL, hidden=0, cubes=[], uses=0, writes=0,
                    system_count=len(system_writes) + system_uses,
                    visible_uses=sum(len(b.get('uses') or []) for b in bindings),
                    visible_writes=len(child_writes))
        view['scope_view'] = info
        return view, info

    kept_bindings, dropped_uses, hidden_per_binding = [], [], 0
    for binding in bindings:
        uses = list(binding.get('uses') or [])
        keep = [u for u in uses if not is_system_object(u.get('cube'))]
        drop = [u for u in uses if is_system_object(u.get('cube'))]
        item = dict(binding)
        item['uses'] = keep
        if drop:
            item['uses_hidden'] = len(drop)
            hidden_per_binding += 1
            dropped_uses.extend(drop)
        kept_bindings.append(item)

    view = dict(report)
    view['bindings'] = kept_bindings
    if child is not None:
        narrowed_child = dict(child)
        narrowed_child['writes'] = [w for w in child_writes if not is_system_object(w.get('cube'))]
        view['child'] = narrowed_child
    info = dict(scope=BUSINESS, hidden=len(system_writes) + len(dropped_uses),
                cubes=sorted({w.get('cube') for w in system_writes + dropped_uses if w.get('cube')}),
                uses=len(dropped_uses), writes=len(system_writes),
                bindings_affected=hidden_per_binding,
                system_count=len(system_writes) + system_uses,
                visible_uses=sum(len(b['uses']) for b in kept_bindings),
                visible_writes=len(child_writes) - len(system_writes))
    view['scope_view'] = info
    return view, info


def scope_lines(info: dict | None) -> list[str]:
    """把范围账写成导出正文里的几句话。

    没有隐藏时也要写一行「本次为全量」，否则读的人无法分辨
    「没有系统对象」和「被悄悄过滤掉了」。
    """
    if not info:
        return []
    if info.get('scope') == ALL:
        return ['- 范围：全量（含 } 前缀系统对象），未被页面范围过滤。']
    if not info.get('hidden'):
        return ['- 范围：业务对象（不含 } 前缀）；本次没有需要隐藏的记录。']
    parts = ['- 范围：业务对象（不含 } 前缀），另有 %d 条记录未包含在本文件内。' % info['hidden']]
    cubes = info.get('cubes') or []
    if cubes:
        shown = '、'.join('`' + name.replace('`', "'") + '`' for name in cubes[:8])
        rest = ' 等 %d 个} 前缀立方体' % len(cubes) if len(cubes) > 8 else ''
        parts.append(f'  - 被隐藏的记录指向：{shown}{rest}。')
    detail = []
    if info.get('writes'):
        detail.append(f'{info["writes"]} 条写入点')
    if info.get('uses'):
        detail.append(f'{info["uses"]} 条参数使用位置')
    if detail:
        parts.append('  - 构成：' + '、'.join(detail) + '。')
    if info.get('bindings_affected'):
        parts.append(f'  - 其中 {info["bindings_affected"]} 个参数的「子 TI 使用」一栏因此变短；'
                     '空白不等于未使用，需按全量重新导出一份再判读。')
    parts.append('  - 需要全量：同一地址加 `system=1`，本段会随之变成「全量」。')
    parts.append('  - 编号沿用页面的原始编号，所以下面会出现跳号——缺的那几个就是上面被隐藏的记录。')
    return parts
