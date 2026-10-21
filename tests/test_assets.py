"""工程资产：存储、提取、绑定、实例化、打包导入。"""
import json
import zipfile
from io import BytesIO

import pytest

from tm1_insight import assets as A
from tm1_insight import asset_package as P
from tm1_insight import design as dg


def _design(target='VehicleVolume', dims=('Scenario', 'Version', 'Year', 'Month', 'Vehicle', 'Plant', 'Measure'),
            schema='VehicleProduction.csv',
            fields=(('VehicleCode', 'string'), ('Plant', 'string'), ('Period', 'string'), ('Quantity', 'number'))):
    cube = dg.CubeDraft(id='draft-v', name=target,
                        dimensions=[dg.DimensionRef(kind='existing', name=d) for d in dims])
    sch = dg.CsvSchema(id='csv-v', name=schema,
                       fields=[dg.CsvField(name=n, type=t) for n, t in fields])
    mapping = [
        dg.MappingEntry(target_dimension=dims[0], kind='FIXED', fixed_member='Forecast', confirmed=True),
        dg.MappingEntry(target_dimension=dims[1], kind='FIXED', fixed_member='Working', confirmed=True),
        dg.MappingEntry(target_dimension=dims[2], kind='FIXED', fixed_member='2026', confirmed=True),
        dg.MappingEntry(target_dimension=dims[3], kind='FROM_SOURCE', source_field='Period', confirmed=True),
        dg.MappingEntry(target_dimension=dims[4], kind='FROM_SOURCE', source_field='VehicleCode', confirmed=True),
        dg.MappingEntry(target_dimension=dims[5], kind='FROM_SOURCE', source_field='Plant', confirmed=True),
        dg.MappingEntry(target_dimension=dims[6], kind='FIXED', fixed_member='Quantity', confirmed=True),
    ]
    rel = dg.DesignRelation(id='rel-v', source=dg.RelationEnd(kind='csv', ref='csv-v'),
                            target=dg.RelationEnd(kind='cube_draft', ref='draft-v'),
                            mapping=mapping, value_source='Quantity',
                            write_policy='overwrite', clear_policy='target_scope',
                            template='csv-to-cube', confirmed=True)
    return dg.Design(mode='design', cubes=[cube], schemas=[sch], relations=[rel])


def _bp(**over):
    spec = A.roles_from_design(_design(), 'rel-v')
    base = dict(id='bp3-test', name='Production Volume Load', roles=spec['roles'],
                dimension_order=spec['dimension_order'], mappings=spec['mappings'],
                value_role=spec['value_role'], template=A.TemplateRef(template=spec['template']),
                write_policy=spec['write_policy'], clear_policy=spec['clear_policy'],
                restricted=False)
    base.update(over)
    return A.ReusableBlueprint(**base)


def _bindings(bp, values):
    return [A.RoleBinding(role=k, value=v, confirmed=True) for k, v in values.items()]


# ------------------------------------------------------------------ 存储

def test_asset_store_roundtrip_and_revision(tmp_path):
    bp = _bp()
    rev = A.save('blueprint', bp, tmp_path, '')
    loaded, current = A.load('blueprint', bp.id, tmp_path)
    assert current == rev and loaded.name == bp.name
    assert A.listing('blueprint', tmp_path)[0]['id'] == bp.id
    with pytest.raises(FileExistsError):
        A.save('blueprint', bp, tmp_path, 'stale')


def test_asset_store_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        A.load('blueprint', '../secret', tmp_path)
    with pytest.raises(ValueError):
        A.load('unknown', 'x', tmp_path)


def test_asset_store_keeps_broken_file_and_reports_it(tmp_path):
    folder = A.assets_root(tmp_path) / 'blueprints'
    folder.mkdir(parents=True)
    (folder / 'bp3-broken.json').write_text('{broken', encoding='utf-8')
    rows = A.listing('blueprint', tmp_path)
    assert rows and rows[0]['broken'] is True


def test_delete_removes_only_target(tmp_path):
    bp = _bp()
    A.save('blueprint', bp, tmp_path, '')
    A.delete('blueprint', bp.id, tmp_path)
    assert A.listing('blueprint', tmp_path) == []
    with pytest.raises(FileNotFoundError):
        A.delete('blueprint', bp.id, tmp_path)


# ------------------------------------------------------------------ 提取

def test_extract_roles_reflects_dimension_order_and_mapping_kinds():
    spec = A.roles_from_design(_design(), 'rel-v')
    assert spec['dimension_order'] == ['dim_1', 'dim_2', 'dim_3', 'dim_4', 'dim_5', 'dim_6', 'dim_7']
    kinds = {m.dim_role: m.kind for m in spec['mappings']}
    assert kinds['dim_1'] == 'FIXED' and kinds['dim_4'] == 'FROM_SOURCE'
    assert spec['value_role'] == 'value_field'
    assert spec['clear_policy'] == 'target_scope'


def test_extract_requires_cube_draft_target():
    d = _design()
    d.relations[0].target = dg.RelationEnd(kind='cube', ref='SomeCube')
    with pytest.raises(ValueError):
        A.roles_from_design(d, 'rel-v')


# ------------------------------------------------------------------ 绑定与实例化

def _values_a():
    return {'target_cube': 'VehicleVolume', 'dim_1': 'Scenario', 'dim_2': 'Version',
            'dim_3': 'Year', 'dim_4': 'Month', 'dim_5': 'Vehicle', 'dim_6': 'Plant',
            'dim_7': 'Measure', 'member_1': 'Forecast', 'member_2': 'Working',
            'member_3': '2026', 'field_4': 'Period', 'field_5': 'VehicleCode',
            'field_6': 'Plant', 'member_7': 'Quantity', 'value_field': 'Quantity',
            'source_name': 'VehicleProduction.csv'}


def _values_b():
    return {'target_cube': 'SalesVolume', 'dim_1': 'Scenario', 'dim_2': 'Version',
            'dim_3': 'Year', 'dim_4': 'Month', 'dim_5': 'Product', 'dim_6': 'Channel',
            'dim_7': 'Measure', 'member_1': 'Budget', 'member_2': 'Final',
            'member_3': '2027', 'field_4': 'SalesPeriod', 'field_5': 'SKU',
            'field_6': 'ChannelCode', 'member_7': 'SalesQuantity', 'value_field': 'SalesQuantity',
            'source_name': 'RetailSales.csv'}


def test_bindings_require_all_roles():
    bp = _bp()
    issues = A.validate_bindings(bp, _bindings(bp, {'target_cube': 'X'}))
    assert any('必需角色未绑定' in i for i in issues)


def test_bindings_reject_duplicate_dimension_names():
    bp = _bp()
    values = _values_a()
    values['dim_6'] = 'Vehicle'  # 与 dim_5 重复
    issues = A.validate_bindings(bp, _bindings(bp, values))
    assert any('维度名重复' in i for i in issues)


def test_bindings_reject_unsafe_expression_role():
    d = _design()
    d.relations[0].mapping[3] = dg.MappingEntry(target_dimension='Month', kind='EXPRESSION',
                                                expression="'X';\nProcessQuit", confirmed=True)
    spec = A.roles_from_design(d, 'rel-v')
    bp = A.ReusableBlueprint(id='bp3-expr', name='E', roles=spec['roles'],
                             dimension_order=spec['dimension_order'], mappings=spec['mappings'],
                             value_role=spec['value_role'], restricted=False)
    values = _values_a()
    values.pop('field_4')
    values['expr_4'] = "'X';\nProcessQuit"
    issues = A.validate_bindings(bp, _bindings(bp, values))
    assert any('表达式角色不安全' in i for i in issues)


def test_instantiate_builds_design_from_bindings_only():
    bp = _bp()
    result = A.instantiate(bp, _bindings(bp, _values_b()), 'ProjectB')
    d = dg.Design.model_validate(result['design'])
    assert d.cubes[0].name == 'SalesVolume'
    assert d.cubes[0].dim_names == ['Scenario', 'Version', 'Year', 'Month', 'Product', 'Channel', 'Measure']
    assert d.schemas[0].name == 'RetailSales.csv'
    assert {f.name for f in d.schemas[0].fields} >= {'SKU', 'ChannelCode', 'SalesPeriod', 'SalesQuantity'}
    gen = dg.generate(d, result['relation_id'])
    assert gen['status'] == 'ok', gen['blockers']
    assert 'VehicleVolume' not in json.dumps(gen['code'], ensure_ascii=False)


# ------------------------------------------------------------------ 打包

def test_export_preflight_blocks_public_when_restricted():
    bp = _bp(restricted=True)
    report = P.export_preflight([bp], [], [], 'public')
    assert report['ok'] is False
    assert {f['code'] for f in report['blockers']} >= {'RESTRICTED_SOURCE'}


def test_export_preflight_allows_private_and_warns_about_members():
    bp = _bp(restricted=False)
    report = P.export_preflight([bp], [], [], 'private')
    assert report['ok'] is True
    assert any(f['code'] == 'FIXED_MEMBERS' for f in report['findings'])


def test_export_preflight_detects_absolute_path_and_credentials():
    bp = _bp(restricted=False)
    bp.roles[0].default = r'D:\secret\path'
    bp.summary = 'password=abc123'
    codes = {f['code'] for f in P.export_preflight([bp], [], [], 'private')['findings']}
    assert {'ABSOLUTE_PATH', 'CREDENTIAL_LIKE'} <= codes


def test_package_roundtrip_imports_as_new_ids(tmp_path):
    bp = _bp()
    blob = P.build_package([bp], [], [], 'private')
    assert zipfile.ZipFile(BytesIO(blob)).namelist()
    result = P.import_package(blob, tmp_path)
    assert not result['errors'] and len(result['imported']) == 1
    imported_id = result['imported'][0]['id']
    assert imported_id != bp.id
    loaded, _ = A.load('blueprint', imported_id, tmp_path)
    assert loaded.origin == 'IMPORTED'


def test_package_rejects_path_traversal(tmp_path):
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({'schema': P.A.PACKAGE_SCHEMA, 'items': []}))
        zf.writestr('../evil.json', '{}')
    result = P.import_package(buf.getvalue(), tmp_path)
    assert result['errors'] and '不安全路径' in result['errors'][0]


def test_package_rejects_bad_checksum(tmp_path):
    bp = _bp()
    blob = P.build_package([bp], [], [], 'private')
    # 重新打包并篡改内容，保持 manifest 的哈希不变
    src = zipfile.ZipFile(BytesIO(blob))
    out = BytesIO()
    with zipfile.ZipFile(out, 'w') as zf:
        for name in src.namelist():
            data = src.read(name)
            if name.startswith('blueprints/'):
                data = data.replace(b'Production Volume Load', b'Tampered Name')
            zf.writestr(name, data)
    result = P.import_package(out.getvalue(), tmp_path)
    assert any('校验和不匹配' in e for e in result['errors'])


def test_package_rejects_oversize():
    result = P.import_package(b'x' * 10, base=None, max_bytes=5)
    assert result['errors'] and '上限' in result['errors'][0]


def test_package_rejects_unknown_schema(tmp_path):
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({'schema': 'future-9', 'items': []}))
    result = P.import_package(buf.getvalue(), tmp_path)
    assert any('版本不受支持' in e for e in result['errors'])
