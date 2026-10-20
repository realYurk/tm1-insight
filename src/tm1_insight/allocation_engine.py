"""通用可配置分摊计算内核（合成数据原型）。

只对内存中的合成输入执行计算；不连接 TM1 Server，不读写任何真实 Cube。
设计要点：
- 按分组维度（如基地）严格隔离，分摊只发生在组内。
- 驱动因子缺失 / 负数 / 组内分母为零的行为明确记录，不静默丢弃。
- 金额按精确比例分配，最后一行吸收舍入尾差，保证组内总额守恒。
- 写入策略：覆盖（overwrite）或累加（increment）；结果表记录策略供对账。
- 计算是幂等的：同一输入重复执行得到同一结果，重跑不会二次累加
  （累加语义由调用方对"目标基准"负责，本内核每次从源值重新计算完整结果）。

边界（第一版）：
- 输入是显式数值表，不是 TM1 切面抓取。
- 不执行 TI，不写入任何 DuckDB / Cube。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

VERSION = 'allocation-engine-1'
CENT = Decimal('0.01')


def _dec(value):
    return Decimal(str(value))


def _money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def validate_config(config):
    """返回错误列表；空列表表示配置可用。"""
    errors = []
    for field in ('group_dimensions', 'allocation_dimensions', 'driver_field', 'value_field'):
        if not config.get(field):
            errors.append(f'缺少必填配置：{field}')
    source = config.get('source_rows') or []
    targets = config.get('target_rows') or []
    if not source:
        errors.append('源数据为空')
    if not targets:
        errors.append('目标数据为空')
    if config.get('write_policy') not in {'overwrite', 'increment'}:
        errors.append("write_policy 必须是 'overwrite' 或 'increment'")
    if config.get('rounding') not in {'half_up', None}:
        errors.append("rounding 仅支持 'half_up'")
    return errors


def _group_key(row, dims):
    return tuple(row.get(d) for d in dims)


def allocate(config):
    """执行分摊，返回结果字典（可 JSON 序列化）。

    源行：{<group_dims>, <allocation_dims 并非必须>, value_field, driver_field, ...}
    目标行：{<group_dims>, <allocation_dims>, ...}
    组内把源金额按目标驱动因子比例分配到各目标行。
    """
    errors = validate_config(config)
    if errors:
        return {'schema': VERSION, 'ok': False, 'errors': errors,
                'results': [], 'groups': [], 'anomalies': ['配置未通过校验，未执行计算。']}

    value_field = config['value_field']
    driver_field = config['driver_field']
    group_dims = config['group_dimensions']
    alloc_dims = config['allocation_dimensions']
    write_policy = config.get('write_policy', 'overwrite')

    anomalies, results = [], []
    # 目标行按组索引
    target_groups = {}
    for i, t in enumerate(config['target_rows']):
        target_groups.setdefault(_group_key(t, group_dims), []).append((i, t))

    # 驱动因子按组累加（同一目标坐标多次出现时取累加，模拟多来源驱动汇集）
    driver_sums = {}
    for t in config['target_rows']:
        key = _group_key(t, group_dims)
        d = t.get(driver_field)
        try:
            amount = _dec(d) if d is not None else None
        except Exception:
            amount = None
        if amount is not None:
            driver_sums[key] = driver_sums.get(key, Decimal(0)) + amount

    # 源行按组汇总金额
    source_groups = {}
    for s in config['source_rows']:
        key = _group_key(s, group_dims)
        try:
            amount = _dec(s[value_field])
        except Exception:
            anomalies.append(f"源行 {json.dumps(s, ensure_ascii=False, default=str)} 的 {value_field} 无法解析为数值，已跳过。")
            continue
        source_groups[key] = source_groups.get(key, Decimal(0)) + amount

    for key, total_amount in sorted(source_groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        group_label = dict(zip(group_dims, key))
        targets = target_groups.get(key, [])
        if not targets:
            anomalies.append(f"分组 {group_label} 有 {total_amount} 待分摊金额，但该组没有目标行；金额未分摊。")
            continue
        driver_total = driver_sums.get(key, Decimal(0))
        if driver_total == 0:
            anomalies.append(f"分组 {group_label} 驱动因子合计为零，{total_amount} 无法按比例分摊；已整组跳过。")
            continue
        if driver_total < 0:
            anomalies.append(f"分组 {group_label} 驱动因子合计为负（{driver_total}），比例无业务含义；已整组跳过。")
            continue

        # 逐目标行分配，最后一行吸收尾差，保证 total_amount 守恒。
        allocated_sum = Decimal(0)
        group_results = []
        negative = [t for _, t in targets if t.get(driver_field) is not None and _dec(t[driver_field]) < 0]
        if negative:
            anomalies.append(f"分组 {group_label} 有 {len(negative)} 个负驱动目标行；其分摊额按比例仍为负，请人工确认。")
        for pos, (_, t) in enumerate(targets):
            d = t.get(driver_field)
            if d is None:
                anomalies.append(f"分组 {group_label} 目标行 {json.dumps(t, ensure_ascii=False, default=str)} 缺少驱动因子，记 0 分摊。")
                ratio = Decimal(0)
            else:
                ratio = _dec(d) / driver_total
            if pos < len(targets) - 1:
                allocated = _money(total_amount * ratio)
            else:
                allocated = _money(total_amount - allocated_sum)  # 尾差吸收
            allocated_sum += allocated
            target_coord = {dim: t.get(dim) for dim in group_dims + alloc_dims}
            group_results.append(dict(
                target=target_coord, ratio=str(ratio), driver=str(d),
                allocated=str(allocated), write_policy=write_policy))
        if allocated_sum != _money(total_amount):
            anomalies.append(f"分组 {group_label} 守恒校验失败：分配合计 {allocated_sum} != 源金额 {total_amount}。")
        for r in group_results:
            r.update(group=group_label, source_total=str(total_amount))
        results.extend(group_results)
        # 守恒记录
        anomalies_group = None

    groups = []
    for key in sorted(source_groups, key=lambda k: tuple(str(x) for x in k)):
        label = dict(zip(group_dims, key))
        rows = [r for r in results if r['group'] == label]
        out_sum = sum(Decimal(r['allocated']) for r in rows)
        groups.append(dict(group=label, source_total=str(source_groups[key]),
                           allocated_total=str(out_sum),
                           conserved=str(out_sum == _money(source_groups[key])),
                           rows=len(rows)))

    config_hash = hashlib.sha256(json.dumps(
        {k: config.get(k) for k in ('group_dimensions', 'allocation_dimensions', 'driver_field',
                                    'value_field', 'write_policy', 'source_rows', 'target_rows')},
        ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return dict(schema=VERSION, ok=True, errors=[], config_hash=config_hash,
                write_policy=write_policy, results=results, groups=groups, anomalies=anomalies)


def reconcile(config, allocation):
    """对账：源合计 vs 分配合计，按组与总体。"""
    if not allocation.get('ok'):
        return {'schema': 'allocation-reconcile-1', 'ok': False, 'reason': '分摊未执行成功，无对账基础。'}
    value_field = config['value_field']
    group_dims = config['group_dimensions']
    source_total = Decimal(0)
    for s in config['source_rows']:
        try:
            source_total += _dec(s[value_field])
        except Exception:
            pass
    out_total = sum(Decimal(r['allocated']) for r in allocation['results'])
    unallocated = source_total - out_total
    lines = []
    for g in allocation['groups']:
        lines.append(dict(group=g['group'], source=g['source_total'], allocated=g['allocated_total'],
                          conserved=g['conserved']))
    return dict(schema='allocation-reconcile-1', ok=True,
                source_total=str(source_total), allocated_total=str(out_total),
                balanced=str(source_total == out_total), unallocated=str(unallocated),
                groups=lines, anomalies=allocation.get('anomalies', []))
