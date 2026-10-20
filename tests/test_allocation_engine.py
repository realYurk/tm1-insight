"""通用分摊计算内核测试（合成数据）。

覆盖：基地内分摊、多维分组、组隔离、零分母、缺失驱动、负驱动、
尾差、一对多、累加/覆盖策略、重复执行幂等、守恒校验。
"""
from decimal import Decimal

import pytest

from tm1_insight.allocation_engine import VERSION, allocate, reconcile, validate_config


def base_config():
    source_rows = [
        {'基地': 'A', '费用': '1000000'},
        {'基地': 'B', '费用': '500000'},
    ]
    target_rows = [
        {'基地': 'A', '品牌': 'X', '驱动': '100'},
        {'基地': 'A', '品牌': 'Y', '驱动': '200'},
        {'基地': 'A', '品牌': 'Z', '驱动': '700'},
        {'基地': 'B', '品牌': 'X', '驱动': '50'},
        {'基地': 'B', '品牌': 'W', '驱动': '50'},
    ]
    return dict(group_dimensions=['基地'], allocation_dimensions=['品牌'],
                driver_field='驱动', value_field='费用',
                write_policy='overwrite', source_rows=source_rows, target_rows=target_rows)


def test_synthetic_two_site_conserved():
    config = base_config()
    result = allocate(config)
    assert result['ok'], result['errors']
    by_group = {g['group']['基地']: g for g in result['groups']}
    a, b = by_group['A'], by_group['B']
    assert Decimal(a['allocated_total']) == Decimal('1000000')
    assert Decimal(b['allocated_total']) == Decimal('500000')
    assert a['conserved'] == 'True' and b['conserved'] == 'True'


def test_ratio_output_matches_hand_computed():
    result = allocate(base_config())
    amounts = {r['target']['品牌']: Decimal(r['allocated'])
               for r in result['results'] if r['group'] == {'基地': 'A'}}
    assert amounts == {'X': Decimal('100000'), 'Y': Decimal('200000'), 'Z': Decimal('700000')}


def test_group_isolation_no_cross_site_leak():
    result = allocate(base_config())
    for r in result['results']:
        # A 组只分给 A 的目标，B 组只分给 B 的目标
        if r['group'] == {'基地': 'A'}:
            assert r['target']['基地'] == 'A'
        else:
            assert r['target']['基地'] == 'B'


def test_zero_driver_total_group_skipped_with_anomaly():
    config = base_config()
    config['source_rows'].append({'基地': 'C', '费用': '300'})
    config['target_rows'].append({'基地': 'C', '品牌': 'N', '驱动': '0'})
    result = allocate(config)
    assert result['ok']
    assert any('驱动因子合计为零' in a for a in result['anomalies'])
    assert not [r for r in result['results'] if r['group'] == {'基地': 'C'}]
    rec = reconcile(config, result)
    assert rec['balanced'] == 'False'  # 300 未分摊
    assert Decimal(rec['unallocated']) == Decimal('300')


def test_missing_driver_target_gets_zero():
    config = base_config()
    config['target_rows'].append({'基地': 'A', '品牌': 'NODRIVER'})  # 缺驱动
    result = allocate(config)
    assert result['ok']
    nodriver = [r for r in result['results'] if r['target'].get('品牌') == 'NODRIVER']
    assert nodriver and Decimal(nodriver[0]['allocated']) == 0
    assert any('缺失驱动因子' in a for a in result['anomalies'])
    # 守恒不受影响
    assert Decimal(sum(Decimal(r['allocated']) for r in result['results'])) == Decimal('1500000')


def test_negative_driver_total_skipped():
    config = base_config()
    config['source_rows'].append({'基地': 'D', '费用': '100'})
    config['target_rows'].append({'基地': 'D', '品牌': 'N', '驱动': '-5'})
    result = allocate(config)
    # 唯一目标为负驱动 → 有效驱动合计为零，整组跳过（含负驱动提示）
    assert any('有效驱动因子合计为零' in a and '负驱动' in a for a in result['anomalies'])
    assert not [r for r in result['results'] if r['group'] == {'基地': 'D'}]


def test_rounding_tail_absorbed_by_last_row():
    config = base_config()
    # 100 分 3 份，比例 1:1:1 → 33.33/33.33/33.34
    config['source_rows'] = [{'基地': 'A', '费用': '100'}]
    config['target_rows'] = [{'基地': 'A', '品牌': 'X', '驱动': '1'},
                             {'基地': 'A', '品牌': 'Y', '驱动': '1'},
                             {'基地': 'A', '品牌': 'Z', '驱动': '1'}]
    result = allocate(config)
    amounts = [Decimal(r['allocated']) for r in result['results']]
    assert amounts == [Decimal('33.33'), Decimal('33.33'), Decimal('33.34')]
    assert sum(amounts) == Decimal('100')


def test_increment_policy_recorded():
    config = base_config()
    config['write_policy'] = 'increment'
    result = allocate(config)
    assert result['write_policy'] == 'increment'
    assert all(r['write_policy'] == 'increment' for r in result['results'])


def test_rerun_is_idempotent_same_input_same_output():
    config = base_config()
    first = allocate(config)
    second = allocate(config)
    assert first['results'] == second['results']
    assert first['config_hash'] == second['config_hash']


def test_invalid_config_reports_errors_not_exception():
    result = allocate({})
    assert not result['ok']
    assert result['errors'] and result['results'] == []


def test_reconcile_balanced_for_valid_run():
    config = base_config()
    result = allocate(config)
    rec = reconcile(config, result)
    assert rec['ok'] and rec['balanced'] == 'True'
    assert Decimal(rec['source_total']) == Decimal(rec['allocated_total']) == Decimal('1500000')


def test_config_hash_changes_with_input():
    config = base_config()
    h1 = allocate(config)['config_hash']
    config['source_rows'][0]['费用'] = '1000001'
    h2 = allocate(config)['config_hash']
    assert h1 != h2


def test_version_tag():
    assert VERSION == 'allocation-engine-2'
