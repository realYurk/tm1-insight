"""范围视图：页面上看得见的，和导出拿到的，用同一把尺子。

## 为什么要有一个单独的模块

计算检查页早就按 ``}`` 前缀隐藏写入点，导出却一直是全量：屏幕上是 14 条，
下载下来 15 条，没有一句话说明差在哪。用户核对材料时对不上账，只能怀疑自己看错。

差异本身可以有——导出是核对材料，宁多勿少——但**默认不能悄悄发生**。
所以这里做三件事：

1. 过滤只写一份，页面和导出都调它，不各写一套判断；
2. 隐藏掉的逐条留账（数量、立方体名、原始编号），并写进导出正文；
3. ``include_system=True`` 时原样放行，用同一个结构报告「这次是全量」。

## 两套写入口径差在哪（2026-10-31 实测）

血缘表 ``process_writes_cube`` 与计算检查页的写入点是两条独立链路，
差的**精确等于一类东西：日志 cube**（``}APQ Process Response Message`` 等）。
实测 ``Cub. Ckd Consignment Report.Update.Put``：计算页 58 个写入点涉及 4 个 cube，
血缘表 3 个——三个业务 cube 一个不少，少的正是那条日志。

血缘图不追踪日志是**有意**的（每个 TI 都写日志，画进去会把图淹掉），
计算页把每一处 ``CellPutN`` 都列出来也没有错。两边都不算错，
错的是**没有任何一处告诉用户这个差从哪来**。所以：

- 隐藏判据 = ``}`` 前缀 ∪ 日志清单（与血缘图的写入过滤对齐，再叠加系统对象）；
- 隐藏的理由分开记——``log`` 与 ``system`` 各有各的话，因为「日志」和
  「系统对象」对使用者是两个完全不同的解释。

判据本身不在这里定义：``ingest.scope.is_system_object`` 与 ``ingest.lineage.is_log_cube``
各管一头，本模块只组合，不复制清单。

## 两条自我约束

只作用于**可独立成条的清单**（写入点、参数使用位置）。DAG 节点不过滤：
砍掉节点会打断 ``children`` 引用，而依赖图本来也不是「收录清单」，
它是「这张图的推理依据」，缺一个节点就说不出为什么这么推。

读取依赖同理，但更危险。写入点少一条，读者知道还有别的写入；
读取依赖少一条，读者会认定**这个值没有来源**。所以它连"删"都不做——
``read_nodes`` 原样保留、``nodes`` 一个不动，另外给 ``reads_shown`` /
``reads_hidden`` 两个索引清单，谁渲染都得把两边都说出来。

编号（``write.id``）一律保持原值，绝不重新编号——否则「写入 3」
在页面和导出里指向两条不同的记录，等于把对账做成了新的坑。
"""
from __future__ import annotations

from collections import Counter

from tm1_insight.ingest.lineage import is_log_cube
from tm1_insight.ingest.scope import is_system_object

BUSINESS = 'business'
ALL = 'all'

KIND_PLAIN = 'plain'
KIND_LOG = 'log'
KIND_SYSTEM = 'system'


def target_kind(cube: str | None) -> str:
    """写入目标属于哪一类。日志优先于系统：日志 cube 也带 ``}`` 前缀，
    但「这是日志写入」比「这是系统对象」对使用者有用得多。"""
    if is_log_cube(cube):
        return KIND_LOG
    if is_system_object(cube):
        return KIND_SYSTEM
    return KIND_PLAIN


def is_hidden_target(cube: str | None) -> bool:
    return target_kind(cube) != KIND_PLAIN


def _summary(dropped: list[dict]) -> dict:
    kinds = Counter(target_kind(item.get('cube')) for item in dropped)
    cubes = sorted({item.get('cube') for item in dropped if item.get('cube')})
    return dict(
        hidden=len(dropped),
        log=kinds.get(KIND_LOG, 0),
        system=kinds.get(KIND_SYSTEM, 0),
        cubes=cubes,
        log_cubes=[name for name in cubes if target_kind(name) == KIND_LOG],
        write_ids=[item['id'] for item in dropped if item.get('id') is not None],
    )


def _empty(scope: str = ALL) -> dict:
    return dict(scope=scope, visible=0, hidden=0, log=0, system=0, cubes=[], log_cubes=[],
                write_ids=[], reads_hidden=0, reads_total=0)


def split_reads(writes: list[dict], nodes: dict, include_system: bool):
    """给每个写入点分出「留着的读取依赖」与「被范围收走的读取依赖」。

    读取依赖不是独立清单，它是某个写入点的定义链证据。收它的风险和收写入点
    完全不同：写入点少一条，读者知道有别的写入；读取依赖少一条，读者会以为
    **这个值没有来源**。所以这里只分类、不删除——``read_nodes`` 原样保留，
    另给 ``reads_shown`` / ``reads_hidden`` 两个索引清单，谁渲染都得两边都说。

    返回 ``(新 writes 列表, 被收走的读取依赖总条数)``。
    """
    annotated, total_hidden = [], 0
    for write in writes:
        item = dict(write)
        indices = list(write.get('read_nodes') or [])
        shown, hidden = [], []
        for index in indices:
            cube = (nodes.get(index) or {}).get('cube')
            if not include_system and is_hidden_target(cube):
                hidden.append(index)
            else:
                shown.append(index)
        item['reads_shown'] = shown
        item['reads_hidden'] = hidden
        if hidden:
            cubes = []
            for index in hidden:
                cube = (nodes.get(index) or {}).get('cube')
                if cube and cube not in cubes:
                    cubes.append(cube)
            kinds = Counter(target_kind((nodes.get(index) or {}).get('cube')) for index in hidden)
            item['reads_hidden_cubes'] = sorted(cubes)
            item['reads_hidden_log'] = kinds.get(KIND_LOG, 0)
            item['reads_hidden_system'] = kinds.get(KIND_SYSTEM, 0)
        total_hidden += len(hidden)
        annotated.append(item)
    return annotated, total_hidden


def narrow_report(report: dict | None, include_system: bool = False):
    """计算检查报告 → ``(可见视图, 范围账)``。

    返回的视图是浅拷贝，``writes`` 是新列表；入参 report 不被修改，
    因为同一个对象还要喂给节点渲染和 Markdown。
    """
    if not report:
        return report, _empty()
    nodes = {node['id']: node for node in (report.get('nodes') or [])}
    writes = list(report.get('writes') or [])
    hidden_writes = [w for w in writes if is_hidden_target(w.get('cube'))]
    if include_system:
        view = dict(report)
        shown, _ = split_reads(writes, nodes, True)
        view['writes'] = shown
        info = dict(scope=ALL, visible=len(writes), **_summary([]), system_count=len(hidden_writes),
                    reads_hidden=0, reads_total=sum(len(w.get('read_nodes') or []) for w in writes))
        view['scope_view'] = info
        return view, info
    kept = [w for w in writes if not is_hidden_target(w.get('cube'))]
    shown, reads_hidden = split_reads(kept, nodes, False)
    view = dict(report)
    view['writes'] = shown
    info = dict(scope=BUSINESS, visible=len(kept), **_summary(hidden_writes),
                system_count=len(hidden_writes), reads_hidden=reads_hidden,
                reads_total=sum(len(w.get('read_nodes') or []) for w in kept))
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
        return report, dict(scope=ALL, hidden=0, log=0, system=0, cubes=[], log_cubes=[],
                            uses=0, writes=0, system_count=0)
    child = report.get('child')
    child_writes = list(child.get('writes') or []) if child else []
    bindings = list(report.get('bindings') or [])
    hidden_writes = [w for w in child_writes if is_hidden_target(w.get('cube'))]
    all_uses = [u for b in bindings for u in (b.get('uses') or [])]
    hidden_uses = [u for u in all_uses if is_hidden_target(u.get('cube'))]
    system_count = len(hidden_writes) + len(hidden_uses)
    if include_system:
        view = dict(report)
        info = dict(scope=ALL, hidden=0, log=0, system=0, cubes=[], log_cubes=[],
                    uses=0, writes=0, system_count=system_count,
                    visible_uses=len(all_uses), visible_writes=len(child_writes))
        view['scope_view'] = info
        return view, info

    kept_bindings, affected = [], 0
    for binding in bindings:
        uses = list(binding.get('uses') or [])
        keep = [u for u in uses if not is_hidden_target(u.get('cube'))]
        drop = [u for u in uses if is_hidden_target(u.get('cube'))]
        item = dict(binding)
        item['uses'] = keep
        if drop:
            item['uses_hidden'] = len(drop)
            affected += 1
        kept_bindings.append(item)

    view = dict(report)
    view['bindings'] = kept_bindings
    if child is not None:
        narrowed_child = dict(child)
        narrowed_child['writes'] = [w for w in child_writes if not is_hidden_target(w.get('cube'))]
        view['child'] = narrowed_child
    kinds = Counter(target_kind(item.get('cube')) for item in hidden_writes + hidden_uses)
    cubes = sorted({item.get('cube') for item in hidden_writes + hidden_uses if item.get('cube')})
    info = dict(scope=BUSINESS, hidden=len(hidden_writes) + len(hidden_uses),
                log=kinds.get(KIND_LOG, 0), system=kinds.get(KIND_SYSTEM, 0),
                cubes=cubes, log_cubes=[name for name in cubes if target_kind(name) == KIND_LOG],
                uses=len(hidden_uses), writes=len(hidden_writes),
                bindings_affected=affected, system_count=system_count,
                visible_uses=sum(len(b['uses']) for b in kept_bindings),
                visible_writes=len(child_writes) - len(hidden_writes))
    view['scope_view'] = info
    return view, info


def hidden_text(info: dict | None, noun: str = '写入点') -> str:
    """一句话说清「藏了什么、为什么」，给状态条和模板用。

    日志与系统分开说。合并成「3 条系统记录」是省字，但把两种完全不同的
    解释糊成一种——「每个 TI 都会写日志」和「这里碰到了一个系统立方体」
    对使用者的意义差得远。
    """
    if not info or not info.get('hidden'):
        return ''
    log, system = info.get('log', 0), info.get('system', 0)
    parts = []
    if log:
        parts.append('%d 条日志写入' % log)
    if system:
        parts.append('%d 条指向系统立方体' % system)
    text = '另有 %d 条%s未显示' % (info['hidden'], noun)
    if parts:
        text += '（' + '、'.join(parts) + '）'
    cubes = info.get('cubes') or []
    if cubes:
        text += '：' + '、'.join(cubes[:3])
    if log:
        text += '。血缘图同样不追踪日志写入'
    return text


def reads_text(write: dict | None) -> str:
    """一个写入点的读取依赖被收起多少、为什么——一句话。

    写「读取依赖被隐藏」而不解释的人，是在制造一个更坏的误解：
    读者看到定义链上只剩常量，会认定这个值不来自任何地方。
    """
    if not write:
        return ''
    hidden = write.get('reads_hidden') or []
    if not hidden:
        return ''
    log, system = write.get('reads_hidden_log', 0), write.get('reads_hidden_system', 0)
    parts = []
    if log:
        parts.append('%d 条指向日志' % log)
    if system:
        parts.append('%d 条指向系统立方体' % system)
    text = '另有 %d 条读取依赖未显示' % len(hidden)
    if parts:
        text += '（' + '、'.join(parts) + '）'
    cubes = write.get('reads_hidden_cubes') or []
    if cubes:
        text += '：' + '、'.join(cubes[:3])
    return text + '。隐藏不等于这个值没有来源'


def scope_lines(info: dict | None) -> list[str]:
    """把范围账写成导出正文里的几句话。

    没有隐藏时也要写一行「本次为全量」，否则读的人无法分辨
    「没有系统对象」和「被悄悄过滤掉了」。
    """
    if not info:
        return []
    if info.get('scope') == ALL:
        return ['- 范围：全量（含 } 前缀与日志立方体），未被页面范围过滤。']
    hidden = info.get('hidden') or 0
    reads = info.get('reads_hidden') or 0
    if not hidden and not reads:
        return ['- 范围：业务对象（不含 } 前缀与日志立方体）；本次没有需要隐藏的记录。']
    if hidden:
        parts = ['- 范围：业务对象（不含 } 前缀与日志立方体），另有 %d 条记录未包含在本文件内。'
                 % hidden]
        detail = []
        if info.get('log'):
            detail.append('%d 条日志写入' % info['log'])
        if info.get('system'):
            detail.append('%d 条系统立方体写入' % info['system'])
        if info.get('uses'):
            detail.append('其中 %d 条是参数使用位置' % info['uses'])
        if detail:
            parts.append('  - 构成：' + '、'.join(detail) + '。')
        cubes = info.get('cubes') or []
        if cubes:
            shown = '、'.join('`' + name.replace('`', "'") + '`' for name in cubes[:8])
            rest = ' 等 %d 个} 前缀立方体' % len(cubes) if len(cubes) > 8 else ''
            parts.append('  - 被隐藏的记录指向：%s%s。' % (shown, rest))
        if info.get('log'):
            parts.append('  - 日志写入是每跑一次就写一条的执行记录，血缘图有意不追踪；'
                         '它不代表业务数据流向。')
    else:
        # 写入点一条没少，读取依赖少了——这两句话必须分开：
        # 合成一句「有记录被隐藏」会让读者去列表里找一条并不存在的短项。
        parts = ['- 范围：业务对象（不含 } 前缀与日志立方体）；没有写入点因范围被排除。']
    if reads:
        parts.append('  - 另有 %d 条读取依赖指向日志或系统立方体，各写入点的「静态读取依赖」'
                     '一栏因此偏短；隐藏不等于该值没有来源。' % reads)
        parts.append('  - JSON 里 writes[].read_nodes 仍是完整定义链（节点不裁剪，否则推不出结论）；'
                     '同一写入点的 reads_shown 才是页面上那几条。')
    if info.get('bindings_affected'):
        parts.append('  - 其中 %d 个参数的「子 TI 使用」一栏因此变短；'
                     '空白不等于未使用，需按全量重新导出一份再判读。' % info['bindings_affected'])
    parts.append('  - 需要全量：同一地址加 `system=1`，本段会随之变成「全量」。')
    if hidden:
        parts.append('  - 编号沿用页面的原始编号，所以下面会出现跳号——缺的那几个就是上面被隐藏的记录。')
    return parts
