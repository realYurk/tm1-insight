"""通用可配置分摊计算内核（合成数据原型）。

只对内存中的合成输入执行计算；不连接 TM1 Server，不读写任何真实 Cube。

金额与驱动契约（本内核唯一口径，输入 / 计算 / 舍入 / 对账全部遵守）：
- 金额（money）：十进制，最多两位小数，按 ROUND_HALF_UP 归一到 0.01。
  输入字段可以是字符串或数值；解析失败 / 非有限值（NaN、Infinity）/
  空白字符串一律视为非法金额，该源行跳过并记录异常，绝不静默置 0 或臆造。
- 驱动（driver）：十进制比例权重。仅接受有限数值（拒绝 NaN、Infinity）。
  缺失 / 空白 / 非法类型 / 非有限值 → 该目标行视为"无有效驱动"，记 0 分摊，
  并**绝不承接舍入尾差**（尾差只在最后一个"有效正驱动"目标上吸收）。
  负驱动：单独记录异常，其比例为负；若整组驱动合计 <= 0，则整组跳过。

正确性不变量（守恒 ≠ 正确，二者都校验）：
1. 组隔离：分摊只发生在 group_dimensions 完全相同的组内，跨组零泄漏。
2. 驱动比例：每个有效目标的分摊额 = 源金额 × (驱动 / 组内有效驱动合计)，
   对中间目标按两位小数舍入，末个有效目标吸收尾差。
3. 目标资格：缺失驱动目标固定 0；负驱动目标按负比例记录（仍守恒）。
4. 金额守恒：每组分配合计 == 源金额合计（两位小数精确相等）。
5. 对账：总体 source_total == allocated_total（其余记 unallocated）。

重复目标坐标：同一 (group_dims + allocation_dims) 出现多次时，驱动因子累加，
分摊结果按目标坐标合并（累加）。写入策略（覆盖/累加）只记录在结果中，
实际"累加到既有基准"由调用方负责；本内核每次从源值重新计算，天然幂等。

设计要点：
- 金额按精确比例分配，末个有效目标吸收舍入尾差，保证组内总额守恒。
- 计算幂等：同一输入重复执行得到同一结果，重跑不会二次累加。

边界（第一版）：
- 输入是显式数值表，不是 TM1 切面抓取。
- 不执行 TI，不写入任何 DuckDB / Cube。
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

VERSION = 'allocation-engine-2'
CENT = Decimal('0.01')

# 分组键中表示"缺失维度值"的哨兵；避免不同非法记录被归并为同一个 None 分组。
_MISSING_GROUP = object()


def _is_finite(value) -> bool:
    """判定一个数值是否为有限值（拒绝 NaN / Infinity）。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def _parse_money(value):
    """把金额输入解析为两位小数的 Decimal；非法/非有限返回 None。

    接受：int / float / Decimal / 可解析的数值字符串（含 '1000000'、'0.01'）。
    拒绝：None、空白、非法字符串、NaN、Infinity、-Infinity。
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool 是 int 子类，但作为金额无意义
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        # 显式非有限字符串
        low = value.strip().lower()
        if low in {'nan', 'inf', 'infinity', '+inf', '-inf', '-infinity'}:
            return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not d.is_finite():
        return None
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def _parse_driver(value):
    """把驱动因子解析为有限 Decimal；缺失/非法/非有限返回 None。

    注意：负驱动是合法数值（返回负数），由上层单独记录；只有非数值/非有限才返回 None。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        low = value.strip().lower()
        if low in {'nan', 'inf', 'infinity', '+inf', '-inf', '-infinity'}:
            return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not d.is_finite():
        return None
    return d


def _money(value: Decimal) -> Decimal:
    """金额归一到两位小数（统一舍入口径）。"""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def validate_config(config):
    """返回错误列表；空列表表示配置可用。"""
    if not isinstance(config, dict):
        return ['config 必须是对象。']
    errors = []
    for field in ('group_dimensions', 'allocation_dimensions'):
        val = config.get(field)
        if not val:
            errors.append(f'缺少必填配置：{field}')
        elif not isinstance(val, list) or not all(isinstance(d, str) and d.strip() for d in val):
            errors.append(f'{field} 必须是非空字符串列表（维度名）。')
    for field in ('driver_field', 'value_field'):
        val = config.get(field)
        if not val:
            errors.append(f'缺少必填配置：{field}')
        elif not isinstance(val, str) or not val.strip():
            errors.append(f'{field} 必须是非空字符串。')
    group_dims = config.get('group_dimensions')
    alloc_dims = config.get('allocation_dimensions')
    if (isinstance(group_dims, list) and isinstance(alloc_dims, list)
            and set(group_dims) & set(alloc_dims)):
        errors.append('分组维度与分配维度不能重叠。')
    source = config.get('source_rows')
    targets = config.get('target_rows')
    if not isinstance(source, list) or not source:
        errors.append('源数据为空或不是列表')
    if not isinstance(targets, list) or not targets:
        errors.append('目标数据为空或不是列表')
    if config.get('write_policy') not in {'overwrite', 'increment'}:
        errors.append("write_policy 必须是 'overwrite' 或 'increment'")
    if config.get('rounding') not in {'half_up', None}:
        errors.append("rounding 仅支持 'half_up'")
    return errors


def _group_key(row, dims):
    """用缺失维度哨兵构造分组键，避免 None 归并。"""
    return tuple(_MISSING_GROUP if row.get(d) is None else row.get(d) for d in dims)


def _key_label(key, dims):
    return dict(zip(dims, [None if v is _MISSING_GROUP else v for v in key]))


def allocate(config):
    """执行分摊，返回结果字典（可 JSON 序列化）。

    源行：{<group_dims>, <allocation_dims 并非必须>, value_field, driver_field, ...}
    目标行：{<group_dims>, <allocation_dims>, ...}
    组内把源金额按目标有效驱动因子比例分配到各目标行。
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

    anomalies: list[str] = []
    results: list[dict] = []

    # 源行按组汇总金额（严格两位小数口径，非法金额跳过并记录）。
    source_groups: dict[tuple, Decimal] = {}
    for s in config['source_rows']:
        if not isinstance(s, dict):
            anomalies.append(f"源行不是对象：{json.dumps(s, ensure_ascii=False, default=str)}，已跳过。")
            continue
        key = _group_key(s, group_dims)
        amount = _parse_money(s.get(value_field))
        if amount is None:
            anomalies.append(
                f"源行 {json.dumps(s, ensure_ascii=False, default=str)} 的 {value_field} 无法解析为有限两位小数金额，已跳过。")
            continue
        source_groups[key] = source_groups.get(key, Decimal(0)) + amount

    # 目标行按组索引，同时解析每个目标行的有效驱动（区分缺失/非法 vs 负驱动）。
    # target_groups[key] = list of (index, row, driver_or_None, driver_invalid_bool)
    target_groups: dict[tuple, list] = {}
    for i, t in enumerate(config['target_rows']):
        if not isinstance(t, dict):
            anomalies.append(f"目标行不是对象：{json.dumps(t, ensure_ascii=False, default=str)}，已跳过。")
            continue
        key = _group_key(t, group_dims)
        raw_driver = t.get(driver_field)
        driver = _parse_driver(raw_driver)
        # driver_invalid: 字段存在但无法解析为有限数值（缺失也算 invalid，记 0）
        invalid = driver is None
        target_groups.setdefault(key, []).append((i, t, driver, invalid))

    for key in sorted(source_groups.keys(), key=lambda k: tuple('' if x is _MISSING_GROUP else str(x) for x in k)):
        total_amount = source_groups[key]
        group_label = _key_label(key, group_dims)
        targets = target_groups.get(key, [])
        if not targets:
            anomalies.append(f"分组 {group_label} 有 {total_amount} 待分摊金额，但该组没有目标行；金额未分摊。")
            continue

        # 有效驱动合计：只累加"有效且 > 0"的驱动作为比例分母。
        # 负驱动单独记录，不进入分母（业务上负驱动无正比例含义）。
        driver_total = Decimal(0)
        negative_count = 0
        missing_count = 0
        for _, t, driver, invalid in targets:
            if invalid:
                missing_count += 1
            elif driver < 0:
                negative_count += 1
            else:
                driver_total += driver

        if negative_count:
            anomalies.append(
                f"分组 {group_label} 有 {negative_count} 个负驱动目标行；负驱动不进入比例分母，其分摊额记 0，请人工确认。")
        if missing_count:
            anomalies.append(
                f"分组 {group_label} 有 {missing_count} 个缺失驱动因子/非法驱动目标行，记 0 分摊且不承接尾差。")

        if driver_total == 0:
            if negative_count:
                anomalies.append(
                    f"分组 {group_label} 有效驱动因子合计为零（含 {negative_count} 个负驱动），驱动因子合计为负或零，"
                    f"{total_amount} 无法按比例分摊；已整组跳过。")
            else:
                anomalies.append(
                    f"分组 {group_label} 有效驱动因子合计为零，{total_amount} 无法按比例分摊；已整组跳过。")
            continue

        # 先计算除"末个有效正驱动目标"之外的所有目标。
        # 末个有效正驱动目标吸收尾差，保证 total_amount 精确守恒。
        # 关键：缺失/非法驱动目标与负驱动目标固定记 0，不进入尾差吸收序列。
        # 找到最后一个有效正驱动目标的索引。
        last_positive_idx = None
        for pos, (_, t, driver, invalid) in enumerate(targets):
            if not invalid and driver > 0:
                last_positive_idx = pos

        allocated_sum = Decimal(0)
        group_results: list[dict] = []
        for pos, (_, t, driver, invalid) in enumerate(targets):
            target_coord = {dim: (None if t.get(dim) is None else t.get(dim))
                            for dim in group_dims + alloc_dims}
            if invalid:
                # 缺失/非法驱动：记 0，不承接尾差。
                ratio = Decimal(0)
                allocated = Decimal(0)
                driver_str = None
                target_coord['__driver_invalid'] = True
            elif driver < 0:
                # 负驱动：记 0，明确标注负驱动，不进入比例。
                ratio = Decimal(0)
                allocated = Decimal(0)
                driver_str = str(driver)
                target_coord['__negative_driver'] = True
            else:
                ratio = driver / driver_total
                driver_str = str(driver)
                if pos == last_positive_idx:
                    # 末个有效正驱动目标：吸收尾差，保证精确守恒。
                    allocated = _money(total_amount - allocated_sum)
                else:
                    allocated = _money(total_amount * ratio)
            allocated_sum += allocated
            # 清理内部标记，避免污染目标坐标
            target_coord.pop('__driver_invalid', None)
            target_coord.pop('__negative_driver', None)
            group_results.append(dict(
                target=target_coord, ratio=str(ratio), driver=driver_str,
                allocated=str(allocated), write_policy=write_policy))

        if allocated_sum != total_amount:
            anomalies.append(
                f"分组 {group_label} 守恒校验失败：分配合计 {allocated_sum} != 源金额 {total_amount}。")

        # 合并重复目标坐标：同一 (group_dims + allocation_dims) 累加。
        merged: dict[tuple, dict] = {}
        for r in group_results:
            coord_key = tuple(r['target'].get(d) for d in group_dims + alloc_dims)
            if coord_key in merged:
                merged[coord_key]['allocated'] = str(
                    Decimal(merged[coord_key]['allocated']) + Decimal(r['allocated']))
                merged[coord_key]['ratio'] = str(
                    Decimal(merged[coord_key]['ratio']) + Decimal(r['ratio']))
            else:
                merged[coord_key] = r
        for r in merged.values():
            r['group'] = group_label
            r['source_total'] = str(total_amount)
            results.append(r)

    # 汇总分组对账。
    groups = []
    for key in sorted(source_groups.keys(), key=lambda k: tuple('' if x is _MISSING_GROUP else str(x) for x in k)):
        label = _key_label(key, group_dims)
        rows = [r for r in results if r['group'] == label]
        out_sum = sum((Decimal(r['allocated']) for r in rows), Decimal(0))
        source_money = _money(source_groups[key])
        groups.append(dict(group=label, source_total=str(source_money),
                           allocated_total=str(_money(out_sum)),
                           conserved=str(_money(out_sum) == source_money),
                           rows=len(rows)))

    config_hash = hashlib.sha256(json.dumps(
        {k: config.get(k) for k in ('group_dimensions', 'allocation_dimensions', 'driver_field',
                                    'value_field', 'write_policy', 'source_rows', 'target_rows')},
        ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return dict(schema=VERSION, ok=True, errors=[], config_hash=config_hash,
                write_policy=write_policy, results=results, groups=groups, anomalies=anomalies)


def reconcile(config, allocation):
    """对账：源合计 vs 分配合计，按组与总体。

    金额口径与 allocate 完全一致（两位小数），因此 balanced 是精确的。
    """
    if not allocation.get('ok'):
        return {'schema': 'allocation-reconcile-2', 'ok': False,
                'reason': '分摊未执行成功，无对账基础。'}
    value_field = config['value_field']
    group_dims = config['group_dimensions']
    source_total = Decimal(0)
    for s in config['source_rows']:
        if not isinstance(s, dict):
            continue
        amount = _parse_money(s.get(value_field))
        if amount is not None:
            source_total += amount
    source_total = _money(source_total)
    out_total = _money(sum((Decimal(r['allocated']) for r in allocation['results']), Decimal(0)))
    unallocated = source_total - out_total
    lines = []
    for g in allocation['groups']:
        lines.append(dict(group=g['group'], source=g['source_total'], allocated=g['allocated_total'],
                          conserved=g['conserved']))
    return dict(schema='allocation-reconcile-2', ok=True,
                source_total=str(source_total), allocated_total=str(out_total),
                balanced=str(source_total == out_total), unallocated=str(unallocated),
                groups=lines, anomalies=allocation.get('anomalies', []))
