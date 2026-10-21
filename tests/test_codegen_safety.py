"""Sprint 3A：代码生成安全与可信度。

覆盖表达式子集、成员转义、变量碰撞、清空策略、依赖清单、预检阻断与失效检测。
"""
import pytest

from tm1_insight import codegen_safety as safe
from tm1_insight import design as dg


# ------------------------------------------------------------------ 表达式

@pytest.mark.parametrize('expr', [
    "'2026'",
    "vYear",
    "'A' | '-' | vBrand",
    "TimSt(Now, '\\Y')",
    "NumberToStringEx(vYear, '0000', '', '')",
    "IF_FLAG",  # 不是白名单函数，但也不是调用 → 应拒绝（见下方单独用例）
])
def test_expression_accepts_only_known_shapes(expr):
    ok, reason = safe.validate_expression(expr)
    if expr == 'IF_FLAG':
        assert not ok and '不允许' in reason
    else:
        assert ok, reason


@pytest.mark.parametrize('expr,keyword', [
    ("'2026';\nProcessQuit", '换行或分号'),
    ("'2026';\nCellPutN(1,'X','Y');", '换行或分号'),
    ("ProcessQuit", '不允许'),
    ("ItemSkip", '不允许'),
    ("'a' | 'b' # 注释", '注释'),
    ("TimSt(Now", '括号'),
    ("vYear = '2026'", '赋值'),
    ("'unterminated", '不支持的字符'),
])
def test_expression_rejects_injection_and_statements(expr, keyword):
    ok, reason = safe.validate_expression(expr)
    assert not ok
    assert keyword in reason


def test_member_quoting_escapes_single_quote_and_rejects_newline():
    assert safe.quote_member("O'Brien") == "'O''Brien'"
    with pytest.raises(safe.ExpressionError):
        safe.quote_member('a\nb')
    with pytest.raises(safe.ExpressionError):
        safe.quote_member('   ')
    with pytest.raises(safe.ExpressionError):
        safe.quote_member('a\x00b')


def test_variable_map_handles_collision_without_renaming_business_names():
    mapping, collisions = safe.build_var_map(['A B', 'A-B', 'Year'])
    assert mapping['A B'] != mapping['A-B']
    assert mapping['Year'] == 'vYear'
    assert len(collisions) == 1 and collisions[0]['dimension'] == 'A-B'
    assert collisions[0]['generated'].endswith('_2')


def test_variable_map_handles_unicode_and_reserved_words():
    mapping, _ = safe.build_var_map(['产品类别', 'Measure'])
    assert mapping['产品类别'] == 'vCol'
    assert mapping['Measure'] == 'vMeasure'


def test_variable_map_avoids_reserved_identifiers():
    mapping, _ = safe.build_var_map(['Value'])
    assert mapping['Value'].casefold() not in safe.RESERVED


# ------------------------------------------------------------------ 清空策略

def _cube_design(write='overwrite', clear='target_scope', mapping=None, value_source='Quantity'):
    draft = dg.CubeDraft(id='draft-t', name='Target', dimensions=[
        dg.DimensionRef(kind='existing', name='Scenario'),
        dg.DimensionRef(kind='existing', name='Measure')])
    schema = dg.CsvSchema(id='csv-t', name='src.csv', fields=[
        dg.CsvField(name='Scenario'), dg.CsvField(name='Quantity', type='number')])
    rel = dg.DesignRelation(
        id='rel-t', source=dg.RelationEnd(kind='csv', ref='csv-t'),
        target=dg.RelationEnd(kind='cube_draft', ref='draft-t'),
        mapping=mapping if mapping is not None else [
            dg.MappingEntry(target_dimension='Scenario', kind='FROM_SOURCE',
                            source_field='Scenario', confirmed=True),
            dg.MappingEntry(target_dimension='Measure', kind='FIXED',
                            fixed_member='Quantity', confirmed=True)],
        value_source=value_source, write_policy=write, clear_policy=clear,
        template='csv-to-cube', confirmed=True)
    return dg.Design(mode='design', cubes=[draft], schemas=[schema], relations=[rel])


def test_clear_policy_none_emits_no_delete_statement():
    result = dg.generate(_cube_design(clear='none'), 'rel-t')
    assert result['status'] == 'ok'
    assert '}bedrock.cube.data.clear' not in result['code']['prolog']
    assert '清空策略：none' in result['code']['prolog']
    assert result['summary']['clear_policy'] == 'none'


def test_clear_policy_target_scope_emits_clear_and_view_cleanup():
    result = dg.generate(_cube_design(clear='target_scope'), 'rel-t')
    assert '}bedrock.cube.data.clear' in result['code']['prolog']
    # 字符分隔模板没有源视图，因此不会销毁 cViewClr；Cube 模板才需要
    from tm1_insight.store import codegen as cg
    cube = cg.data_transfer(None, 'A', 'B', src_dims=['Y'], tgt_dims=['Y'], clear_policy='target_scope')
    assert 'cViewClr' in cube['epilog']


def test_write_and_clear_policies_are_independent():
    overwrite_no_clear = dg.generate(_cube_design(write='overwrite', clear='none'), 'rel-t')
    assert 'CellPutN(' in overwrite_no_clear['code']['data']
    assert '}bedrock.cube.data.clear' not in overwrite_no_clear['code']['prolog']

    accumulate_clear = dg.generate(_cube_design(write='accumulate', clear='target_scope'), 'rel-t')
    assert 'CellIncrementN(' in accumulate_clear['code']['data']
    assert '}bedrock.cube.data.clear' in accumulate_clear['code']['prolog']


def test_invalid_clear_policy_is_rejected_at_codegen_level():
    from tm1_insight.store import codegen as cg
    with pytest.raises(ValueError):
        cg.csv_to_cube('T', ['Y'], [{'name': 'Q'}], {}, value_source='Q', clear_policy='drop-all')


# ------------------------------------------------------------------ 预检

def test_preflight_blocks_unsupported_lookup_mapping():
    mapping = [
        dg.MappingEntry(target_dimension='Scenario', kind='LOOKUP', source_field='Scenario', confirmed=True),
        dg.MappingEntry(target_dimension='Measure', kind='FIXED', fixed_member='Quantity', confirmed=True),
    ]
    result = dg.generate(_cube_design(mapping=mapping), 'rel-t')
    assert result['status'] == 'blocked'
    assert any(i['code'] == 'LOOKUP_UNSUPPORTED' for i in result['issues'])


def test_preflight_blocks_expression_injection():
    mapping = [
        dg.MappingEntry(target_dimension='Scenario', kind='EXPRESSION',
                        expression="'2026';\nCellPutN(1,'X','Y');", confirmed=True),
        dg.MappingEntry(target_dimension='Measure', kind='FIXED', fixed_member='Quantity', confirmed=True),
    ]
    result = dg.generate(_cube_design(mapping=mapping), 'rel-t')
    assert result['status'] == 'blocked' and result['code'] is None
    assert any(i['code'] == 'UNSAFE_EXPRESSION' for i in result['issues'])


def test_preflight_blocks_newline_in_fixed_member():
    mapping = [
        dg.MappingEntry(target_dimension='Scenario', kind='FIXED', fixed_member='A\nB', confirmed=True),
        dg.MappingEntry(target_dimension='Measure', kind='FIXED', fixed_member='Quantity', confirmed=True),
    ]
    result = dg.generate(_cube_design(mapping=mapping), 'rel-t')
    assert result['status'] == 'blocked'
    assert any(i['code'] == 'FIXED_MEMBER_UNSAFE' for i in result['issues'])


def test_preflight_returns_structured_codes():
    d = _cube_design()
    d.relations[0].mapping = []
    result = dg.generate(d, 'rel-t')
    codes = {i['code'] for i in result['issues']}
    assert {'DIM_UNMAPPED'} <= codes
    assert all('message' in i for i in result['issues'])


def test_safe_expression_mapping_generates_verbatim_subset():
    mapping = [
        dg.MappingEntry(target_dimension='Scenario', kind='EXPRESSION',
                        expression="'FY' | vYear", confirmed=True),
        dg.MappingEntry(target_dimension='Measure', kind='FIXED', fixed_member='Quantity', confirmed=True),
    ]
    result = dg.generate(_cube_design(mapping=mapping), 'rel-t')
    assert result['status'] == 'ok'
    assert "vScenario = 'FY' | vYear;" in result['code']['data']


# ------------------------------------------------------------------ 依赖与失效

def test_dependency_manifest_lists_framework_and_bedrock():
    deps = safe.dependency_manifest('csv-to-cube', target_cube='Target',
                                    target_dims=['Scenario', 'Measure'])
    names = {p['name'] for p in deps['processes']}
    assert '}bedrock.cube.data.clear' in names
    assert any(c['kind'] == 'FRAMEWORK_CUBE' for c in deps['cubes'])
    assert any(d['name'] == 'Scenario' for d in deps['dimensions'])
    assert deps['notes']


def test_generate_returns_dependency_manifest():
    result = dg.generate(_cube_design(), 'rel-t')
    assert result['status'] == 'ok'
    assert result['dependencies']['template'] == 'csv-to-cube'


def test_generation_is_deterministic_and_fingerprinted():
    a = dg.generate(_cube_design(), 'rel-t', generated_at='t1')
    b = dg.generate(_cube_design(), 'rel-t', generated_at='t2')
    assert a['summary']['code_fingerprint'] == b['summary']['code_fingerprint']
    assert a['summary']['design_fingerprint'] == b['summary']['design_fingerprint']


def test_artifact_becomes_stale_after_design_change():
    d = _cube_design()
    result = dg.generate(d, 'rel-t')
    assert dg.is_stale(result['artifact'], d) is False
    d.relations[0].mapping[0].source_field = 'Other'
    assert dg.is_stale(result['artifact'], d) is True


def test_artifact_without_fingerprint_is_treated_as_stale():
    assert dg.is_stale({'relation_id': 'rel-t', 'summary': {}}, _cube_design()) is True
