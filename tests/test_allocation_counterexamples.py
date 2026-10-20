"""分摊内核反例测试（合成数据）。

这些测试专门锁定审计中发现的真实缺陷，用「会失败的输入」验证修复，
而不是通过修改断言让旧行为通过。每一项对应一个明确的缺陷编号。
"""
from decimal import Decimal

from tm1_insight.allocation_engine import allocate, reconcile, validate_config


# ---------------------------------------------------------------------------
# 缺陷 1：尾差吸收导致缺失驱动的目标承接非零金额
# ---------------------------------------------------------------------------

def test_missing_driver_target_never_absorbs_tail():
    """源金额 0.01，目标驱动 1、1、缺失。缺失目标必须为 0，不得承接 -0.01 或 0.01。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '0.01'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'基地': 'A', '品牌': 'Y', '驱动': '1'},
            {'基地': 'A', '品牌': 'Z'},  # 缺失驱动
        ],
    )
    result = allocate(config)
    assert result['ok'], result['errors']
    by_brand = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results']}
    # 关键缺陷点：缺失驱动目标 Z 必须是 0，绝不承接尾差
    assert by_brand['Z'] == 0
    # 尾差只能由有效正驱动目标（X 或 Y）吸收，而不是缺失目标 Z
    assert by_brand['X'] + by_brand['Y'] == Decimal('0.01')
    assert by_brand['X'] >= 0 and by_brand['Y'] >= 0
    # 守恒：0.00 + 0.01 + 0.00 == 0.01
    assert sum(by_brand.values()) == Decimal('0.01')
    # 对账平衡
    rec = reconcile(config, result)
    assert rec['balanced'] == 'True'


def test_missing_driver_in_middle_does_not_break_tail_absorption():
    """缺失驱动目标位于中间时，尾差仍由有效正驱动目标吸收，缺失目标为 0。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '0.01'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'基地': 'A', '品牌': 'Y'},  # 缺失，位于中间
            {'基地': 'A', '品牌': 'Z', '驱动': '1'},
        ],
    )
    result = allocate(config)
    by_brand = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results']}
    # 关键缺陷点：缺失目标 Y 必须为 0
    assert by_brand['Y'] == 0
    # 尾差由有效正驱动目标（X 或 Z）吸收
    assert by_brand['X'] + by_brand['Z'] == Decimal('0.01')
    assert by_brand['X'] >= 0 and by_brand['Z'] >= 0
    assert sum(by_brand.values()) == Decimal('0.01')


# ---------------------------------------------------------------------------
# 缺陷 2：负驱动检测重复调用 _dec 导致非法字符串抛异常
# ---------------------------------------------------------------------------

def test_illegal_driver_string_does_not_raise():
    """驱动字段是非法字符串（如 'abc'、空串、NaN）时不得抛异常，应记 0 并记录异常。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '100'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'基地': 'A', '品牌': 'Y', '驱动': 'abc'},   # 非法字符串
            {'基地': 'A', '品牌': 'Z', '驱动': ''},      # 空串
            {'基地': 'A', '品牌': 'W', '驱动': 'NaN'},   # NaN 字符串
        ],
    )
    result = allocate(config)  # 不应抛异常
    assert result['ok']
    by_brand = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results']}
    assert by_brand['Y'] == 0 and by_brand['Z'] == 0 and by_brand['W'] == 0
    assert by_brand['X'] == Decimal('100')  # 唯一有效驱动，X 吸收全部


def test_driver_field_non_string_types_handled():
    """驱动字段为 None / list / dict / bool 时不抛异常。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '10'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': None},
            {'基地': 'A', '品牌': 'Y', '驱动': ['1']},
            {'基地': 'A', '品牌': 'Z', '驱动': {'k': '1'}},
            {'基地': 'A', '品牌': 'W', '驱动': True},
            {'基地': 'A', '品牌': 'V', '驱动': '2'},
        ],
    )
    result = allocate(config)
    assert result['ok']
    by_brand = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results']}
    assert by_brand['X'] == 0 and by_brand['Y'] == 0 and by_brand['Z'] == 0 and by_brand['W'] == 0
    assert by_brand['V'] == Decimal('10')  # 唯一有效驱动


# ---------------------------------------------------------------------------
# 缺陷 3：分组维度 row.get() 缺失导致不同非法记录归并到 None 组
# ---------------------------------------------------------------------------

def test_missing_group_dimension_does_not_merge_into_none_group():
    """两个缺失分组维度的目标行，不得被归并到同一个 None 组共享分摊。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '100'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'品牌': 'Y', '驱动': '1'},   # 缺基地
        ],
    )
    result = allocate(config)
    assert result['ok']
    # 缺失基地的目标行属于独立分组（哨兵键），不进入 A 组
    a_group = [r for r in result['results'] if r['group'] == {'基地': 'A'}]
    assert len(a_group) == 1
    assert Decimal(a_group[0]['allocated']) == Decimal('100')
    # 缺基地的目标没有对应源，不被分摊（且不应混入 A 组）
    assert all(r['target'].get('基地') == 'A' for r in a_group)


# ---------------------------------------------------------------------------
# 缺陷 4：金额两位小数契约（输入、计算、舍入、对账口径一致）
# ---------------------------------------------------------------------------

def test_money_inputs_rounded_to_two_decimals_consistently():
    """金额输入超过两位小数时，输入/计算/舍入/对账口径一致（统一 ROUND_HALF_UP）。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '10.005'}],  # 超过两位小数
        target_rows=[{'基地': 'A', '品牌': 'X', '驱动': '1'}],
    )
    result = allocate(config)
    assert result['ok']
    # 输入 10.005 → 归一为 10.01（ROUND_HALF_UP）
    rec = reconcile(config, result)
    assert Decimal(rec['source_total']) == Decimal('10.01')
    assert Decimal(rec['allocated_total']) == Decimal('10.01')
    assert rec['balanced'] == 'True'


def test_blank_and_illegal_money_source_skipped_not_zeroed():
    """空白 / 非法金额源行必须跳过并记录，不得静默置 0。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[
            {'基地': 'A', '费用': '100'},
            {'基地': 'A', '费用': ''},       # 空白
            {'基地': 'A', '费用': 'oops'},  # 非法
        ],
        target_rows=[{'基地': 'A', '品牌': 'X', '驱动': '1'}],
    )
    result = allocate(config)
    assert result['ok']
    # 只分配合法金额 100
    rec = reconcile(config, result)
    assert Decimal(rec['source_total']) == Decimal('100')
    assert any('无法解析为有限两位小数金额' in a for a in result['anomalies'])


# ---------------------------------------------------------------------------
# 缺陷 5：非有限数值 NaN / Infinity
# ---------------------------------------------------------------------------

def test_nan_and_infinity_rejected():
    """NaN / Infinity / -Infinity 金额与驱动都必须拒绝，不抛异常、不产出非有限结果。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[
            {'基地': 'A', '费用': '100'},
            {'基地': 'B', '费用': 'Infinity'},
            {'基地': 'C', '费用': 'NaN'},
        ],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'基地': 'A', '品牌': 'Y', '驱动': 'Infinity'},  # 非有限驱动
            {'基地': 'A', '品牌': 'Z', '驱动': '1'},
        ],
    )
    result = allocate(config)
    assert result['ok']
    # 非有限源被跳过（B、C 无结果）
    groups = {g['group']['基地']: g for g in result['groups']}
    assert 'B' not in groups and 'C' not in groups
    # 非有限驱动目标记 0
    by_brand = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results']}
    assert by_brand['Y'] == 0
    # X 和 Z 各 50
    assert by_brand['X'] == Decimal('50') and by_brand['Z'] == Decimal('50')


# ---------------------------------------------------------------------------
# 缺陷 6：重复目标坐标、负驱动、零分母、负源金额、一对多契约
# ---------------------------------------------------------------------------

def test_duplicate_target_coordinate_merges_and_conserves():
    """同一目标坐标出现两次，驱动累加，结果合并，守恒。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '100'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'基地': 'A', '品牌': 'X', '驱动': '3'},  # 重复坐标，驱动累加
            {'基地': 'A', '品牌': 'Y', '驱动': '1'},
        ],
    )
    result = allocate(config)
    assert result['ok']
    # X 有效驱动 1+3=4，Y=1，合计 5 → X 得 80，Y 得 20
    by_brand = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results']}
    assert by_brand['X'] == Decimal('80')
    assert by_brand['Y'] == Decimal('20')
    rec = reconcile(config, result)
    assert rec['balanced'] == 'True'


def test_negative_source_amount_preserved_conserved():
    """负源金额必须正常分摊（负值按比例分配），守恒而非报错。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '-100'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'基地': 'A', '品牌': 'Y', '驱动': '1'},
        ],
    )
    result = allocate(config)
    assert result['ok']
    by_brand = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results']}
    assert by_brand['X'] == Decimal('-50') and by_brand['Y'] == Decimal('-50')
    assert sum(by_brand.values()) == Decimal('-100')


def test_one_to_many_and_group_isolation_together():
    """一对多映射 + 组隔离：源只分给同组目标，跨组零泄漏，比例正确。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[
            {'基地': 'A', '费用': '100'},
            {'基地': 'B', '费用': '200'},
        ],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'基地': 'A', '品牌': 'Y', '驱动': '1'},
            {'基地': 'A', '品牌': 'Z', '驱动': '1'},
            {'基地': 'B', '品牌': 'X', '驱动': '1'},
        ],
    )
    result = allocate(config)
    assert result['ok']
    # A 组三目标各 1/3
    a = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results'] if r['group'] == {'基地': 'A'}}
    # 100 / 3 = 33.33, 33.33, 33.34（尾差吸收到最后一个）
    assert a['X'] == Decimal('33.33') and a['Y'] == Decimal('33.33') and a['Z'] == Decimal('33.34')
    # B 组只有 X，全量
    b = [r for r in result['results'] if r['group'] == {'基地': 'B'}]
    assert Decimal(b[0]['allocated']) == Decimal('200')
    # 跨组隔离：A 组金额不进 B，B 组不进 A
    assert sum(a.values()) == Decimal('100')
    assert sum(Decimal(r['allocated']) for r in b) == Decimal('200')


# ---------------------------------------------------------------------------
# 缺陷 7：守恒不代表正确 —— 驱动比例 / 目标资格 / 组隔离 / 对账同时成立
# ---------------------------------------------------------------------------

def test_conservation_plus_ratio_plus_eligibility_plus_isolation():
    """同时验证：比例正确、缺失目标资格为 0、组隔离、对账平衡。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '100'}, {'基地': 'B', '费用': '100'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '2'},
            {'基地': 'A', '品牌': 'Y', '驱动': '2'},
            {'基地': 'A', '品牌': 'NOMISS', },      # 缺失驱动 → 0
            {'基地': 'B', '品牌': 'X', '驱动': '3'},
            {'基地': 'B', '品牌': 'Y', '驱动': '1'},
        ],
    )
    result = allocate(config)
    assert result['ok']
    a = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results'] if r['group'] == {'基地': 'A'}}
    b = {r['target']['品牌']: Decimal(r['allocated']) for r in result['results'] if r['group'] == {'基地': 'B'}}
    # A 组：X:Y=2:2 → 各 50，缺失目标 0
    assert a['X'] == Decimal('50') and a['Y'] == Decimal('50') and a['NOMISS'] == 0
    # B 组：X:Y=3:1 → 75 / 25
    assert b['X'] == Decimal('75') and b['Y'] == Decimal('25')
    # 组隔离 + 守恒
    assert sum(a.values()) == Decimal('100')
    assert sum(b.values()) == Decimal('100')
    # 对账
    rec = reconcile(config, result)
    assert rec['balanced'] == 'True'


def test_config_dimension_overlap_rejected():
    """分组维度与分配维度重叠必须被校验拒绝（否则目标坐标语义混乱）。"""
    config = dict(
        group_dimensions=['品牌'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'品牌': 'A', '费用': '100'}],
        target_rows=[{'品牌': 'A', '驱动': '1'}],
    )
    assert validate_config(config)


# ---------------------------------------------------------------------------
# 缺陷 8：尾差策略的确定性契约（顺序 / 100 目标 / 等额 / 幂等）
# ---------------------------------------------------------------------------

def test_tail_difference_deterministic_for_fixed_input_order():
    """同一输入（含目标顺序）重复运行，尾差吸收位置与结果必须完全一致（幂等）。"""
    def build():
        return dict(
            group_dimensions=['基地'], allocation_dimensions=['品牌'],
            driver_field='驱动', value_field='费用', write_policy='overwrite',
            source_rows=[{'基地': 'A', '费用': '0.01'}],
            target_rows=[
                {'基地': 'A', '品牌': 'X', '驱动': '1'},
                {'基地': 'A', '品牌': 'Y', '驱动': '1'},
                {'基地': 'A', '品牌': 'Z', '驱动': '1'},
            ],
        )
    r1 = allocate(build())
    r2 = allocate(build())
    assert r1['results'] == r2['results'], "同一输入重复运行必须得到完全一致的结果（幂等）"
    # 尾差 0.01 只落到一个有效目标，其余为 0，总额守恒
    by = {x['target']['品牌']: Decimal(x['allocated']) for x in r1['results']}
    assert sum(by.values()) == Decimal('0.01')
    assert sum(1 for v in by.values() if v != 0) == 1


def test_tail_difference_with_100_equal_driver_targets_conserves():
    """100 个等驱动目标、源 0.01：总额必须精确守恒，且只有一个目标承接 0.01。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '0.01'}],
        target_rows=[{'基地': 'A', '品牌': f'B{i}', '驱动': '1'} for i in range(100)],
    )
    result = allocate(config)
    assert result['ok']
    by = {x['target']['品牌']: Decimal(x['allocated']) for x in result['results']}
    assert len(by) == 100
    assert sum(by.values()) == Decimal('0.01')
    nonzero = [v for v in by.values() if v != 0]
    assert len(nonzero) == 1 and nonzero[0] == Decimal('0.01')
    rec = reconcile(config, result)
    assert rec['balanced'] == 'True'


def test_equal_drivers_split_evenly_no_spurious_bias():
    """驱动相等时按比例均分，尾差最多集中到末个有效目标，不产生系统性偏差。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '100'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'基地': 'A', '品牌': 'Y', '驱动': '1'},
            {'基地': 'A', '品牌': 'Z', '驱动': '1'},
        ],
    )
    result = allocate(config)
    by = {x['target']['品牌']: Decimal(x['allocated']) for x in result['results']}
    # 33.33 / 33.33 / 33.34 —— 前两个按两位小数舍入，末个吸收尾差
    assert by['X'] == Decimal('33.33') and by['Y'] == Decimal('33.33') and by['Z'] == Decimal('33.34')
    assert sum(by.values()) == Decimal('100')


def test_all_drivers_equal_and_one_should_get_zero_never_negative():
    """尾差吸收不得使任何目标金额变为负数（即使源金额极小）。"""
    config = dict(
        group_dimensions=['基地'], allocation_dimensions=['品牌'],
        driver_field='驱动', value_field='费用', write_policy='overwrite',
        source_rows=[{'基地': 'A', '费用': '0.01'}],
        target_rows=[
            {'基地': 'A', '品牌': 'X', '驱动': '1'},
            {'基地': 'A', '品牌': 'Y', '驱动': '1'},
        ],
    )
    result = allocate(config)
    by = {x['target']['品牌']: Decimal(x['allocated']) for x in result['results']}
    assert all(v >= 0 for v in by.values()), "尾差吸收不得产生负数结果"
    assert sum(by.values()) == Decimal('0.01')
