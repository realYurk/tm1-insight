"""Release Candidate 3.0 攻击性测试。

这些用例针对「生成代码可能损坏目标数据 / 引用错误变量 / 被注入语句」的路径，
以及资产包的导入导出边界。每条都对应一次实际审计发现，防止回归。
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO

import pytest

from tm1_insight import asset_package as P
from tm1_insight import assets as A
from tm1_insight import codegen_safety as safety
from tm1_insight import design as dg
from tm1_insight.store import codegen as cg


# ---------------------------------------------------------------- 夹具

def cube_design(*, dims=('Scenario', 'Year', 'Measure'), tgt='TgtCube', src='SrcCube',
                clear='target_scope', write='overwrite', fixed=('Forecast', '2026', 'Amount'),
                confirmed=True, mapping=None):
    target = dg.CubeDraft(id='draft-t', name=tgt,
                          dimensions=[dg.DimensionRef(kind='existing', name=d) for d in dims])
    source = dg.CubeDraft(id='draft-s', name=src,
                          dimensions=[dg.DimensionRef(kind='existing', name=d) for d in dims])
    if mapping is None:
        mapping = [dg.MappingEntry(target_dimension=d, kind='FIXED', fixed_member=v, confirmed=confirmed)
                   for d, v in zip(dims, fixed)]
    rel = dg.DesignRelation(id='rel-t', source=dg.RelationEnd(kind='cube_draft', ref='draft-s'),
                            target=dg.RelationEnd(kind='cube_draft', ref='draft-t'),
                            mapping=mapping, write_policy=write, clear_policy=clear,
                            template='cube-data-transfer', confirmed=True)
    return dg.Design(mode='design', cubes=[source, target], relations=[rel])


def csv_design(*, fields=(('SKU', 'string'), ('Qty', 'number')), dims=('Scenario', 'Product', 'Measure'),
               tgt='SalesVolume', schema_name='RetailSales.csv', clear='target_scope',
               value_source='Qty', mapping=None, write='overwrite'):
    cube = dg.CubeDraft(id='draft-c', name=tgt,
                        dimensions=[dg.DimensionRef(kind='existing', name=d) for d in dims])
    sch = dg.CsvSchema(id='csv-c', name=schema_name,
                       fields=[dg.CsvField(name=n, type=t) for n, t in fields])
    if mapping is None:
        mapping = [
            dg.MappingEntry(target_dimension=dims[0], kind='FIXED', fixed_member='Budget', confirmed=True),
            dg.MappingEntry(target_dimension=dims[1], kind='FROM_SOURCE', source_field='SKU', confirmed=True),
            dg.MappingEntry(target_dimension=dims[2], kind='FIXED', fixed_member='Quantity', confirmed=True),
        ]
    rel = dg.DesignRelation(id='rel-c', source=dg.RelationEnd(kind='csv', ref='csv-c'),
                            target=dg.RelationEnd(kind='cube_draft', ref='draft-c'),
                            mapping=mapping, value_source=value_source, write_policy=write,
                            clear_policy=clear, template='csv-to-cube', confirmed=True)
    return dg.Design(mode='design', cubes=[cube], schemas=[sch], relations=[rel])


def codes(result):
    return {k: result['code'][k] for k in ('prolog', 'metadata', 'data', 'epilog')}


# ---------------------------------------------------------------- 清空范围

def test_unscoped_clear_is_blocked_for_design():
    """没有任何已确认固定成员时不得生成：空筛选会清空整个目标 Cube。"""
    d = cube_design(fixed=('', '', ''))
    result = dg.generate(d, 'rel-t')
    assert result['status'] == 'blocked'
    assert result['code'] is None
    assert any('清空' in b for b in result['blockers'])


def test_unconfirmed_fixed_member_cannot_define_clear_scope():
    d = cube_design(confirmed=False)
    result = dg.generate(d, 'rel-t')
    assert result['status'] == 'blocked'
    assert result['code'] is None


def test_clear_scope_is_derived_from_confirmed_fixed_members():
    result = dg.generate(cube_design(), 'rel-t')
    assert result['status'] == 'ok'
    prolog = result['code']['prolog']
    assert "sDelimDim | 'Scenario' | sDelimEleStart | 'Forecast'" in prolog
    assert "sDelimDim | 'Year' | sDelimEleStart | '2026'" in prolog
    assert result['summary']['clear_scope'] == 'SCOPED'
    assert 'Scenario = Forecast' in result['summary']['clear_scope_text']


def test_clear_policy_none_emits_no_delete_and_no_unscoped_warning():
    result = dg.generate(cube_design(clear='none'), 'rel-t')
    assert result['status'] == 'ok'
    assert '}bedrock.cube.data.clear' not in result['code']['prolog']
    assert result['summary']['clear_scope'] == 'NONE'
    assert result['warnings'] == []


def test_codegen_direct_call_reports_unscoped_scope():
    """底层模板也必须如实报告，而不是悄悄清空整库。"""
    out = cg.data_transfer(None, 'A', 'B', src_dims=['Y'], tgt_dims=['Y'], clear_policy='target_scope')
    assert out['clear_scope'] == 'UNSCOPED_WHOLE_CUBE'
    assert out['warnings']


def test_write_and_clear_policy_are_independent():
    put_none = cg.data_transfer(None, 'A', 'B', src_dims=['Y'], tgt_dims=['Y'],
                                operation='CellPutN', clear_policy='none')
    inc_scope = cg.data_transfer(None, 'A', 'B', src_dims=['Y'], tgt_dims=['Y'],
                                 operation='CellIncrementN', clear_policy='target_scope',
                                 tgt_filters=[{'dim': 'Y', 'elems': ['2026'], 'kind': 'const'}])
    assert 'CellPutN' in put_none['data'] and '}bedrock.cube.data.clear' not in put_none['prolog']
    assert 'CellIncrementN' in inc_scope['data'] and '}bedrock.cube.data.clear' in inc_scope['prolog']


def test_unknown_clear_policy_is_rejected():
    with pytest.raises(ValueError):
        cg.data_transfer(None, 'A', 'B', src_dims=['Y'], tgt_dims=['Y'], clear_policy='wipe')
    with pytest.raises(ValueError):
        cg.csv_to_cube('T', ['Y'], [{'name': 'Q'}], {'Y': {'fixed': "'X'"}},
                       value_source='Q', clear_policy='truncate')


# ---------------------------------------------------------------- 变量契约

def test_snake_case_field_matches_datasource_variable():
    """vUnitCost（变量表）与 vUnit_cost（旧拼接）曾不一致，会引用不存在的变量。"""
    d = csv_design(fields=(('unit_cost', 'number'), ('sales_qty', 'number')),
                   mapping=[dg.MappingEntry(target_dimension='Scenario', kind='FIXED',
                                            fixed_member='Budget', confirmed=True),
                            dg.MappingEntry(target_dimension='Product', kind='FIXED',
                                            fixed_member='P1', confirmed=True),
                            dg.MappingEntry(target_dimension='Measure', kind='FROM_SOURCE',
                                            source_field='unit_cost', confirmed=True)],
                   value_source='sales_qty')
    result = dg.generate(d, 'rel-c')
    assert result['status'] == 'ok'
    data = result['code']['data']
    assert 'vMeasure = vUnitCost;' in data
    names = {v['name'] for v in result['process_config']['data_source_variables']}
    assert names == {'vUnitCost', 'vSalesQty'}
    assert 'vValue = StringToNumberEx( vSalesQty' in data


def test_variable_collision_uses_suffixed_name_consistently():
    """两个列规范化后同名时，映射必须指向带后缀的实际变量。"""
    d = csv_design(fields=(('A B', 'string'), ('A-B', 'string'), ('Qty', 'number')),
                   dims=('Scenario', 'Product', 'Channel', 'Measure'),
                   mapping=[dg.MappingEntry(target_dimension='Scenario', kind='FIXED',
                                            fixed_member='Budget', confirmed=True),
                            dg.MappingEntry(target_dimension='Product', kind='FROM_SOURCE',
                                            source_field='A B', confirmed=True),
                            dg.MappingEntry(target_dimension='Channel', kind='FROM_SOURCE',
                                            source_field='A-B', confirmed=True),
                            dg.MappingEntry(target_dimension='Measure', kind='FIXED',
                                            fixed_member='Quantity', confirmed=True)])
    result = dg.generate(d, 'rel-c')
    assert result['status'] == 'ok'
    vars_ = [v['name'] for v in result['process_config']['data_source_variables']]
    assert len(set(vars_)) == len(vars_), '数据源变量名必须唯一'
    data = result['code']['data']
    assert 'vProduct = vAB;' in data
    assert ('vChannel = vAB_2;' in data) or any(x.endswith('_2') and x in data for x in vars_)
    assert result['code']['collisions'], '重名应被记录'


def test_unresolved_source_field_blocks_generation():
    d = csv_design(mapping=[dg.MappingEntry(target_dimension='Scenario', kind='FIXED',
                                            fixed_member='Budget', confirmed=True),
                            dg.MappingEntry(target_dimension='Product', kind='FROM_SOURCE',
                                            source_field='NotAColumn', confirmed=True),
                            dg.MappingEntry(target_dimension='Measure', kind='FIXED',
                                            fixed_member='Quantity', confirmed=True)])
    result = dg.generate(d, 'rel-c')
    assert result['status'] == 'blocked'
    assert result['code'] is None


def test_cube_source_field_must_exist_in_source_dims():
    d = cube_design(mapping=[dg.MappingEntry(target_dimension='Scenario', kind='FIXED',
                                             fixed_member='Forecast', confirmed=True),
                             dg.MappingEntry(target_dimension='Year', kind='FIXED',
                                             fixed_member='2026', confirmed=True),
                             dg.MappingEntry(target_dimension='Measure', kind='FROM_SOURCE',
                                             source_field='MeasureX', confirmed=True)])
    result = dg.generate(d, 'rel-t')
    assert result['status'] == 'blocked'
    assert any('MeasureX' in b for b in result['blockers'])


# ---------------------------------------------------------------- 语句注入

@pytest.mark.parametrize('bad', ['Tgt\nProcessQuit;', 'Tgt\x00', 'Tgt\rProcessQuit;'])
def test_unsafe_cube_name_is_rejected(bad):
    """换行/控制字符会截断注释或提前结束语句，必须阻断。"""
    d = cube_design(tgt=bad)
    result = dg.generate(d, 'rel-t')
    assert result['status'] == 'blocked'
    assert result['code'] is None
    assert any(i.get('code') == 'UNSAFE_NAME' for i in result['issues'])


def test_unsafe_dimension_name_is_rejected():
    d = cube_design(dims=('Scenario', 'Year\nProcessQuit;', 'Measure'))
    result = dg.generate(d, 'rel-t')
    assert result['status'] == 'blocked'
    assert result['code'] is None


def test_quoted_schema_name_is_escaped():
    """引号被成对转义后只是字面量内容，不构成语句注入。"""
    d = csv_design(schema_name="x';ProcessQuit;'")
    result = dg.generate(d, 'rel-c')
    assert result['status'] == 'ok'
    line = [l for l in result['code']['prolog'].split('\n') if l.startswith('cSrcFile')][0]
    assert line == "cSrcFile        = 'x'';ProcessQuit;''';"


def test_newline_in_schema_name_is_rejected():
    d = csv_design(schema_name='x.csv\nProcessQuit;')
    result = dg.generate(d, 'rel-c')
    assert result['status'] == 'blocked'
    assert result['code'] is None


def test_codegen_refuses_unsafe_names_directly():
    """绕过设计层直接调模板：换行必须拒绝，引号必须成对转义。"""
    with pytest.raises(ValueError):
        cg.csv_to_cube("T\nProcessQuit;", ['Y'], [{'name': 'Q'}], {'Y': {'fixed': "'X'"}},
                       value_source='Q')
    with pytest.raises(ValueError):
        cg.csv_to_cube('T', ['Y'], [{'name': 'Q'}], {'Y': {'fixed': "'X'"}},
                       value_source='Q', file_path="f\nProcessQuit;")
    with pytest.raises(ValueError):
        cg.data_transfer(None, 'A', "B\nProcessQuit;", src_dims=['Y'], tgt_dims=['Y'])

    escaped = cg.csv_to_cube("T';ProcessQuit;'", ['Y'], [{'name': 'Q'}], {'Y': {'fixed': "'X'"}},
                             value_source='Q', file_path="f';ProcessQuit;'")
    lines = {l.split('=')[0].strip(): l for l in escaped['prolog'].split('\n') if '=' in l}
    assert "'T'';ProcessQuit;'''" in lines['cCubTgt']
    assert "'f'';ProcessQuit;'''" in lines['cSrcFile']


def test_member_with_quote_is_escaped_not_injected():
    out = cg.data_transfer(None, 'A', 'B', src_dims=['Y'], tgt_dims=['Y'],
                           dim_mapping={'Y': {'fixed': "O'Brien"}})
    assert "vY = 'O''Brien';" in out['data']
    assert 'ProcessQuit' not in out['data']


def test_filter_member_with_quote_is_escaped():
    out = cg.data_transfer(None, 'A', 'B', src_dims=['Y'], tgt_dims=['Y'],
                           tgt_filters=[{'dim': 'Y', 'elems': ["O'Brien"], 'kind': 'const'}])
    assert "'O''Brien'" in out['prolog']


def test_no_generated_section_contains_raw_newline_from_name():
    out = cg.csv_to_cube('T', ['Scenario'], [{'name': 'Q'}],
                         {'Scenario': {'fixed': "'X'"}}, value_source='Q', file_path='a.csv')
    for section in codes({'code': out}).values():
        assert '\x00' not in section


# ---------------------------------------------------------------- 表达式子集

@pytest.mark.parametrize('expr', [
    "'A' | vYear",
    "TimSt(Now, '\\Y')",
    "TimSt(Now)",
    "NumberToStringEx(vValue, '.,', '', 2)",
    "SUBST(vProduct, 1, 3)",
    "UPPER(TRIM(vBrand))",
    "-1",
    "100.25",
])
def test_safe_expressions_accepted(expr):
    ok, reason = safety.validate_expression(expr)
    assert ok, (expr, reason)


@pytest.mark.parametrize('expr', [
    "vA; ProcessQuit",
    "vA\nProcessQuit",
    "'A' # 注释",
    "vA = 'X'",
    "vA @= 'X'",
    "ViewZeroOut('Cube')",
    "ExecuteProcess('x','p','y')",
    "CellPutN(1, 'C', 'a')",
    "unknownVar",
    "TimSt(Now,'\\Y'",
    "TimSt)",
    "()",
    "'unclosed",
    "vA |",
    "'a' | 'b';",
])
def test_unsafe_expressions_rejected(expr):
    ok, reason = safety.validate_expression(expr)
    assert not ok, expr
    assert reason


def test_deeply_nested_expression_is_bounded():
    expr = 'UPPER(' * 200 + "vA" + ')' * 200
    ok, _ = safety.validate_expression(expr)
    assert isinstance(ok, bool)  # 必须给出结论，不能挂死


def test_huge_expression_does_not_hang():
    expr = ' | '.join(["'x'"] * 2000)
    ok, _ = safety.validate_expression(expr)
    assert isinstance(ok, bool)


def test_unsafe_expression_blocks_generation_but_keeps_intent():
    d = cube_design(mapping=[
        dg.MappingEntry(target_dimension='Scenario', kind='FIXED', fixed_member='Forecast', confirmed=True),
        dg.MappingEntry(target_dimension='Year', kind='EXPRESSION', expression="'2026'; ProcessQuit", confirmed=True),
        dg.MappingEntry(target_dimension='Measure', kind='FIXED', fixed_member='Amount', confirmed=True),
    ])
    assert d.relations[0].mapping[1].expression == "'2026'; ProcessQuit"  # 意图被保留
    result = dg.generate(d, 'rel-t')
    assert result['status'] == 'blocked'
    assert any(i['code'] == 'UNSAFE_EXPRESSION' for i in result['issues'])


# ---------------------------------------------------------------- 写入口径

def test_cell_put_argument_order_follows_target_dimension_order():
    dims = ('Scenario', 'Measure', 'Year')  # Measure 在中间
    d = cube_design(dims=dims, fixed=('Forecast', 'Amount', '2026'))
    result = dg.generate(d, 'rel-t')
    assert result['status'] == 'ok'
    assert 'CellPutN(vValue, cCubTgt, vScenario, vMeasure, vYear);' in result['code']['data']


def test_swapping_mapping_roles_changes_assignment_order():
    dims = ('Scenario', 'Product')
    a = dg.generate(cube_design(dims=dims, fixed=('Forecast', 'P1')), 'rel-t')
    b = dg.generate(cube_design(dims=dims, fixed=('P1', 'Forecast')), 'rel-t')
    assert a['code']['data'] != b['code']['data']
    assert a['summary']['code_fingerprint'] != b['summary']['code_fingerprint']


def test_accumulate_policy_uses_increment():
    result = dg.generate(cube_design(write='accumulate'), 'rel-t')
    assert 'CellIncrementN' in result['code']['data']


def test_missing_mapping_never_produces_code():
    d = cube_design(mapping=[
        dg.MappingEntry(target_dimension='Scenario', kind='FIXED', fixed_member='Forecast', confirmed=True),
        dg.MappingEntry(target_dimension='Year', kind='UNMAPPED'),
        dg.MappingEntry(target_dimension='Measure', kind='FIXED', fixed_member='Amount', confirmed=True),
    ])
    result = dg.generate(d, 'rel-t')
    assert result['status'] == 'blocked'
    assert result['code'] is None


def test_extra_mapping_dimension_is_rejected():
    d = cube_design(mapping=[
        dg.MappingEntry(target_dimension='Scenario', kind='FIXED', fixed_member='Forecast', confirmed=True),
        dg.MappingEntry(target_dimension='Year', kind='FIXED', fixed_member='2026', confirmed=True),
        dg.MappingEntry(target_dimension='Measure', kind='FIXED', fixed_member='Amount', confirmed=True),
        dg.MappingEntry(target_dimension='NotADim', kind='FIXED', fixed_member='X', confirmed=True),
    ])
    result = dg.generate(d, 'rel-t')
    assert result['status'] == 'blocked'
    assert any(i['code'] == 'EXTRA_DIM_MAPPING' for i in result['issues'])


# ---------------------------------------------------------------- 指纹与过期

@pytest.mark.parametrize('mutate', [
    lambda d: d.relations[0].mapping[0].__setattr__('fixed_member', 'Actual'),
    lambda d: d.relations[0].mapping[2].__setattr__('fixed_member', 'Value'),
    lambda d: d.relations[0].__setattr__('value_source', 'Qty'),
    lambda d: d.relations[0].__setattr__('write_policy', 'accumulate'),
    lambda d: d.relations[0].__setattr__('clear_policy', 'none'),
    lambda d: d.relations[0].__setattr__('template', 'csv-to-cube'),
    lambda d: d.cubes[1].dimensions.reverse(),
    lambda d: d.cubes[1].__setattr__('name', 'OtherCube'),
])
def test_fingerprint_changes_for_generative_fields(mutate):
    d = cube_design()
    before = dg.design_fingerprint(d, 'rel-t')
    mutate(d)
    assert dg.design_fingerprint(d, 'rel-t') != before


def test_fingerprint_ignores_note_and_generated():
    d = cube_design()
    base = dg.design_fingerprint(d, 'rel-t')
    d.relations[0].note = '随手记一笔'
    d.relations[0].generated = {'design_fingerprint': base, 'generated_at': 'x'}
    assert dg.design_fingerprint(d, 'rel-t') == base


def test_stale_detection_after_design_change():
    d = cube_design()
    result = dg.generate(d, 'rel-t')
    d.relations[0].generated = {'design_fingerprint': result['summary']['design_fingerprint'],
                                'generated_at': '2026-10-21T00:00:00Z'}
    assert dg.stale_relations(d) == []
    d.relations[0].mapping[0].fixed_member = 'Actual'
    stale = dg.stale_relations(d)
    assert [s['relation_id'] for s in stale] == ['rel-t']


def test_generation_is_deterministic():
    a = dg.generate(cube_design(), 'rel-t')
    b = dg.generate(cube_design(), 'rel-t')
    assert a['summary']['code_fingerprint'] == b['summary']['code_fingerprint']
    assert codes(a) == codes(b)


# ---------------------------------------------------------------- Blueprint 绑定

def _bp(**over):
    spec = A.roles_from_design(csv_design(), 'rel-c')
    base = dict(id='bp3-rc', name='Mapped Load', roles=spec['roles'],
                dimension_order=spec['dimension_order'], mappings=spec['mappings'],
                restricted=False)
    base.update(over)
    return A.ReusableBlueprint(**base)


VALUES = {'target_cube': 'SalesVolume', 'dim_1': 'Scenario', 'dim_2': 'Product',
          'dim_3': 'Measure', 'member_1': 'Budget', 'field_2': 'SKU',
          'member_3': 'Quantity', 'value_field': 'Qty', 'source_name': 'RetailSales.csv'}


def _bindings(**over):
    values = dict(VALUES)
    values.update(over)
    return [{'role': k, 'value': v, 'confirmed': True}
            for k, v in values.items() if v is not None]


def test_duplicate_role_binding_is_rejected():
    bp = _bp()
    items = _bindings()
    items.append({'role': 'target_cube', 'value': 'Other', 'confirmed': True})
    issues = A.validate_bindings(bp, [A.RoleBinding(**b) for b in items])
    assert any('重复绑定' in i for i in issues)


def test_missing_required_role_is_rejected():
    bp = _bp()
    items = [b for b in _bindings() if b['role'] != 'field_2']
    issues = A.validate_bindings(bp, [A.RoleBinding(**b) for b in items])
    assert any('必需角色未绑定' in i for i in issues)


def test_unknown_role_is_rejected():
    bp = _bp()
    items = _bindings()
    items.append({'role': 'role_not_exists', 'value': 'X', 'confirmed': True})
    issues = A.validate_bindings(bp, [A.RoleBinding(**b) for b in items])
    assert any('未知角色' in i for i in issues)


def test_newline_in_role_value_is_rejected():
    bp = _bp()
    issues = A.validate_bindings(bp, [A.RoleBinding(**b) for b in _bindings(field_2='SK\nU')])
    assert any('换行' in i for i in issues)


def test_duplicate_dimension_after_binding_is_rejected():
    bp = _bp()
    issues = A.validate_bindings(bp, [A.RoleBinding(**b) for b in _bindings(dim_2='Scenario')])
    assert any('维度名重复' in i for i in issues)


def test_incomplete_binding_cannot_generate():
    bp = _bp()
    inst = A.instantiate(bp, [A.RoleBinding(**b) for b in _bindings()], 'proj-ok')
    assert dg.generate(dg.Design.model_validate(inst['design']), inst['relation_id'])['status'] == 'ok'
    bad = A.instantiate(bp, [A.RoleBinding(**b) for b in _bindings()], 'proj-bad')
    design_bad = dg.Design.model_validate(bad['design'])
    design_bad.relations[0].mapping = [m for m in design_bad.relations[0].mapping
                                       if m.target_dimension != 'Product']
    assert dg.generate(design_bad, bad['relation_id'])['status'] == 'blocked'


# ---------------------------------------------------------------- 资产包

def _package(scope='private', **over):
    bp = _bp(**over)
    return P.build_package([bp], [], [], scope)


def test_import_rejects_path_traversal():
    for name in ('../evil.json', 'blueprints/../../evil.json', 'blueprints\\..\\evil.json',
                 '/abs/evil.json', 'C:/evil.json'):
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr(name, '{}')
            zf.writestr('manifest.json', json.dumps({'schema': A.PACKAGE_SCHEMA, 'items': []}))
        out = P.import_package(buf.getvalue(), None)
        assert out['errors'], name
        assert not out['imported'], name


def test_import_rejects_disallowed_directory():
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('other/x.json', '{}')
        zf.writestr('manifest.json', json.dumps({'schema': A.PACKAGE_SCHEMA, 'items': []}))
    out = P.import_package(buf.getvalue(), None)
    assert out['errors']


def test_import_rejects_too_many_entries():
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i in range(P.MAX_ENTRIES + 5):
            zf.writestr('blueprints/x%d.json' % i, '{}')
        zf.writestr('manifest.json', json.dumps({'schema': A.PACKAGE_SCHEMA, 'items': []}))
    out = P.import_package(buf.getvalue(), None)
    assert any('条目过多' in e for e in out['errors'])


def test_import_rejects_decompression_bomb():
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('blueprints/bomb.json', b'0' * (P.MAX_UNCOMPRESSED + 1024))
        zf.writestr('manifest.json', json.dumps({'schema': A.PACKAGE_SCHEMA, 'items': []}))
    raw = buf.getvalue()
    assert len(raw) < P.MAX_BYTES, '压缩后应很小，才符合 zip bomb 形态'
    out = P.import_package(raw, None)
    assert out['errors']
    assert not out['imported']


def test_import_rejects_wrong_schema_version():
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({'schema': 'engineering-asset-package-99', 'items': []}))
    out = P.import_package(buf.getvalue(), None)
    assert any('版本' in e for e in out['errors'])


def test_import_rejects_hash_mismatch(tmp_path):
    data = _package()
    src = zipfile.ZipFile(BytesIO(data))
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as out:
        for name in src.namelist():
            blob = src.read(name)
            if name.startswith('blueprints/'):
                blob = blob.replace(b'Mapped Load', b'Mapped LoadX')
            out.writestr(name, blob)
    res = P.import_package(buf.getvalue(), tmp_path)
    assert any('校验和' in e for e in res['errors'])
    assert not res['imported']


def test_import_rejects_broken_json(tmp_path):
    buf = BytesIO()
    model = _bp()
    blob = b'{not json'
    item = dict(kind='blueprint', id='bp3-x', name='x', file='blueprints/bp3-x.json',
                sha256=hashlib.sha256(blob).hexdigest())
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('blueprints/bp3-x.json', blob)
        zf.writestr('manifest.json', json.dumps({'schema': A.PACKAGE_SCHEMA, 'items': [item]}))
    res = P.import_package(buf.getvalue(), tmp_path)
    assert any('契约' in e for e in res['errors'])


def test_import_rejects_missing_manifest():
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('blueprints/x.json', '{}')
    out = P.import_package(buf.getvalue(), None)
    assert any('manifest' in e for e in out['errors'])


def test_import_rejects_non_zip():
    out = P.import_package(b'not a zip', None)
    assert out['errors']


def test_export_public_blocks_sensitive_marker_in_pattern():
    """Pattern 描述此前不参与扫描，会把敏感内容带进「可公开」包。"""
    pat = A.Pattern(id='pat-rc', name='Load Pattern', summary='参考 D:/corp/model/secret.xlsx 实现',
                    problem='p', inputs=[], outputs=[], steps=[])
    report = P.export_preflight([], [pat], [], 'public')
    assert not report['ok']
    assert any(f['code'] == 'ABSOLUTE_PATH' for f in report['blockers'])


def test_export_public_blocks_credential_in_verification():
    vc = A.VerificationContract(id='vc-rc', name='Contract', requirements=[
        A.VerificationRequirement(id='req_1', label='password = hunter2', kind='mapping')])
    report = P.export_preflight([], [], [vc], 'public')
    assert not report['ok']


def test_export_public_blocks_restricted_blueprint():
    report = P.export_preflight([_bp(restricted=True)], [], [], 'public')
    assert not report['ok']
    assert any(f['code'] == 'RESTRICTED_SOURCE' for f in report['blockers'])


def test_private_export_allows_restricted_with_blockers_reported():
    report = P.export_preflight([_bp(restricted=True)], [], [], 'private')
    assert report['ok']
    assert report['findings']


def test_roundtrip_preserves_roles_mappings_and_policies(tmp_path):
    bp = _bp()
    data = P.build_package([bp], [], [], 'private')
    res = P.import_package(data, tmp_path)
    assert res['imported'] and not res['errors']
    new_id = res['imported'][0]['id']
    loaded, _ = A.load('blueprint', new_id, tmp_path)
    assert loaded.id != bp.id
    assert [r.id for r in loaded.roles] == [r.id for r in bp.roles]
    assert [m.dim_role for m in loaded.mappings] == [m.dim_role for m in bp.mappings]
    assert loaded.dimension_order == bp.dimension_order
    assert loaded.template.template == bp.template.template
    assert loaded.write_policy == bp.write_policy
    assert loaded.clear_policy == bp.clear_policy


def test_import_does_not_overwrite_existing(tmp_path):
    first = P.import_package(_package(), tmp_path)
    second = P.import_package(_package(), tmp_path)
    ids = {first['imported'][0]['id'], second['imported'][0]['id']}
    assert len(ids) == 2
    assert len(A.listing('blueprint', tmp_path)) == 2


# ---------------------------------------------------------------- 删除保护

def test_delete_guard_reports_referencing_projects(tmp_path, monkeypatch):
    from tm1_insight.api import assets as api
    monkeypatch.setattr(api, 'root', lambda: tmp_path)
    bp = _bp()
    A.save('blueprint', bp, tmp_path, '')
    proj = A.ProjectInstance(id='proj-rc', name='Proj', blueprint_id=bp.id, blueprint_version=1)
    A.save('project', proj, tmp_path, '')
    with pytest.raises(Exception) as exc:
        api.remove('blueprint', bp.id, force=False)
    assert '409' in str(exc.value) or '引用' in str(exc.value)
    api.remove('blueprint', bp.id, force=True)
    assert A.listing('blueprint', tmp_path) == []


# ---------------------------------------------------------------- API 契约

from test_datasource_api import client  # noqa: E402,F401


def _api_design():
    d = csv_design()
    return d.model_dump()


def test_api_stale_endpoint_reports_changed_relation(client):
    design = _api_design()
    gen = client.post('/api/workbench/design/generate',
                      json={'design': design, 'snapshot_id': '', 'relation_id': 'rel-c'}).json()
    assert gen['status'] == 'ok', gen.get('blockers')
    design['relations'][0]['generated'] = {
        'design_fingerprint': gen['summary']['design_fingerprint'],
        'generated_at': '2026-10-21T00:00:00Z'}
    out = client.post('/api/workbench/design/stale', json={'design': design}).json()
    assert out['stale'] == []

    design['relations'][0]['mapping'][0]['fixed_member'] = 'Actual'
    out = client.post('/api/workbench/design/stale', json={'design': design}).json()
    assert [s['relation_id'] for s in out['stale']] == ['rel-c']


def test_api_generate_exposes_clear_scope_and_variables(client):
    out = client.post('/api/workbench/design/generate',
                      json={'design': _api_design(), 'snapshot_id': '', 'relation_id': 'rel-c'}).json()
    assert out['status'] == 'ok'
    assert out['summary']['clear_scope'] == 'SCOPED'
    assert 'Scenario = Budget' in out['summary']['clear_scope_text']
    names = [v['name'] for v in out['process_config']['data_source_variables']]
    assert names == ['vSKU', 'vQty']
    assert 'Variables' in out['process_config']['note']


def test_api_generate_blocks_unscoped_clear(client):
    design = _api_design()
    design['relations'][0]['clear_policy'] = 'target_scope'
    design['relations'][0]['mapping'][0]['confirmed'] = False
    out = client.post('/api/workbench/design/generate',
                      json={'design': design, 'snapshot_id': '', 'relation_id': 'rel-c'}).json()
    assert out['status'] == 'blocked'
    assert out['code'] is None
