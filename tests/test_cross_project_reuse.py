"""跨项目复用验收：同一 Blueprint 用于两个完全不同的合成项目。

项目 A：汽车生产量（VehicleVolume / Vehicle / Plant）
项目 B：快消销量（SalesVolume / Product / Channel）

要求：B 的代码必须使用 B 的结构，不能残留 A 的业务名称。
"""
import json

from tm1_insight import assets as A
from tm1_insight import design as dg
from test_datasource_api import client  # noqa: F401


def project_a_design():
    dims = ['Scenario', 'Version', 'Year', 'Month', 'Vehicle', 'Plant', 'Measure']
    cube = dg.CubeDraft(id='draft-veh', name='VehicleVolume',
                        dimensions=[dg.DimensionRef(kind='existing', name=d) for d in dims])
    schema = dg.CsvSchema(id='csv-veh', name='VehicleProduction.csv', fields=[
        dg.CsvField(name='VehicleCode', type='string'),
        dg.CsvField(name='Plant', type='string'),
        dg.CsvField(name='Period', type='string'),
        dg.CsvField(name='Quantity', type='number'),
    ])
    mapping = [
        dg.MappingEntry(target_dimension='Scenario', kind='FIXED', fixed_member='Forecast', confirmed=True),
        dg.MappingEntry(target_dimension='Version', kind='FIXED', fixed_member='Working', confirmed=True),
        dg.MappingEntry(target_dimension='Year', kind='FIXED', fixed_member='2026', confirmed=True),
        dg.MappingEntry(target_dimension='Month', kind='FROM_SOURCE', source_field='Period', confirmed=True),
        dg.MappingEntry(target_dimension='Vehicle', kind='FROM_SOURCE', source_field='VehicleCode', confirmed=True),
        dg.MappingEntry(target_dimension='Plant', kind='FROM_SOURCE', source_field='Plant', confirmed=True),
        dg.MappingEntry(target_dimension='Measure', kind='FIXED', fixed_member='Quantity', confirmed=True),
    ]
    rel = dg.DesignRelation(id='rel-veh', source=dg.RelationEnd(kind='csv', ref='csv-veh'),
                            target=dg.RelationEnd(kind='cube_draft', ref='draft-veh'),
                            mapping=mapping, value_source='Quantity',
                            template='csv-to-cube', confirmed=True)
    return dg.Design(mode='design', cubes=[cube], schemas=[schema], relations=[rel])


BINDINGS_B = {
    'target_cube': 'SalesVolume',
    'dim_1': 'Scenario', 'dim_2': 'Version', 'dim_3': 'Year', 'dim_4': 'Month',
    'dim_5': 'Product', 'dim_6': 'Channel', 'dim_7': 'Measure',
    'member_1': 'Budget', 'member_2': 'Final', 'member_3': '2027',
    'field_4': 'SalesPeriod', 'field_5': 'SKU', 'field_6': 'ChannelCode',
    'member_7': 'SalesQuantity', 'value_field': 'SalesQuantity',
    'source_name': 'RetailSales.csv',
}


def blueprint_from_a():
    spec = A.roles_from_design(project_a_design(), 'rel-veh')
    return A.ReusableBlueprint(id='bp3-cross', name='Multidimensional Data Load',
                               summary='CSV → 多维事实装载', roles=spec['roles'],
                               dimension_order=spec['dimension_order'], mappings=spec['mappings'],
                               value_role=spec['value_role'],
                               template=A.TemplateRef(template=spec['template']),
                               write_policy=spec['write_policy'], clear_policy=spec['clear_policy'],
                               restricted=False, origin='EXTRACTED_FROM_PROJECT')


def test_same_blueprint_generates_different_code_for_two_projects():
    design_a = project_a_design()
    gen_a = dg.generate(design_a, 'rel-veh')
    assert gen_a['status'] == 'ok'

    bp = blueprint_from_a()
    bindings = [A.RoleBinding(role=k, value=v, confirmed=True) for k, v in BINDINGS_B.items()]
    assert A.validate_bindings(bp, bindings) == []
    inst = A.instantiate(bp, bindings, 'ProjectB')
    design_b = dg.Design.model_validate(inst['design'])
    gen_b = dg.generate(design_b, inst['relation_id'])
    assert gen_b['status'] == 'ok', gen_b['blockers']

    text_b = json.dumps(gen_b['code'], ensure_ascii=False)
    # B 使用自己的结构
    for token in ('SalesVolume', 'SalesPeriod', 'SKU', 'ChannelCode', 'SalesQuantity', 'RetailSales.csv'):
        assert token in text_b, token
    # 不能残留 A 的业务名称
    for token in ('VehicleVolume', 'VehicleCode', 'VehicleProduction', 'Plant', "'Forecast'"):
        assert token not in text_b, token

    # 维度顺序与代码指纹都必须不同
    assert gen_a['code']['tgt_dims'] == ['Scenario', 'Version', 'Year', 'Month', 'Vehicle', 'Plant', 'Measure']
    assert gen_b['code']['tgt_dims'] == ['Scenario', 'Version', 'Year', 'Month', 'Product', 'Channel', 'Measure']
    assert gen_a['summary']['code_fingerprint'] != gen_b['summary']['code_fingerprint']


def test_cross_project_bindings_drive_fixed_members():
    bp = blueprint_from_a()
    bindings = [A.RoleBinding(role=k, value=v, confirmed=True) for k, v in BINDINGS_B.items()]
    inst = A.instantiate(bp, bindings, 'ProjectB')
    design_b = dg.Design.model_validate(inst['design'])
    gen_b = dg.generate(design_b, inst['relation_id'])
    data = gen_b['code']['data']
    assert "vScenario = 'Budget';" in data
    assert "vVersion = 'Final';" in data
    assert "vYear = '2027';" in data
    assert 'vProduct = vSKU;' in data
    assert 'vChannel = vChannelCode;' in data


def test_blueprint_is_not_string_replacement():
    """角色顺序改变，生成的维度绑定必须随之改变（证明按角色而非按名字）。"""
    bp = blueprint_from_a()
    values = dict(BINDINGS_B)
    values['dim_5'], values['dim_6'] = 'Channel', 'Product'  # 交换两个维度角色
    values['field_5'], values['field_6'] = 'ChannelCode', 'SKU'
    inst = A.instantiate(bp, [A.RoleBinding(role=k, value=v, confirmed=True) for k, v in values.items()],
                         'ProjectB2')
    design_b = dg.Design.model_validate(inst['design'])
    assert design_b.cubes[0].dim_names[4:] == ['Channel', 'Product', 'Measure']
    gen = dg.generate(design_b, inst['relation_id'])
    assert 'vChannel = vChannelCode;' in gen['code']['data']
    assert 'vProduct = vSKU;' in gen['code']['data']


def test_artifact_of_b_is_stale_after_rebinding():
    bp = blueprint_from_a()
    bindings = [A.RoleBinding(role=k, value=v, confirmed=True) for k, v in BINDINGS_B.items()]
    inst = A.instantiate(bp, bindings, 'ProjectB')
    design_b = dg.Design.model_validate(inst['design'])
    gen = dg.generate(design_b, inst['relation_id'])
    assert dg.is_stale(gen['artifact'], design_b) is False
    design_b.relations[0].mapping[0].fixed_member = 'Actual'
    assert dg.is_stale(gen['artifact'], design_b) is True


# ------------------------------------------------------------------ API 级

def test_api_extract_instantiate_generate(client):
    design = project_a_design()
    extracted = client.post('/api/assets/extract', json={
        'design': design.model_dump(), 'relation_id': 'rel-veh',
        'name': 'Multidimensional Data Load', 'mark_generic': True}).json()
    bp_id = extracted['id']
    assert extracted['blueprint']['dimension_order'] == [f'dim_{i}' for i in range(1, 8)]

    inst = client.post('/api/assets/instantiate', json={
        'blueprint_id': bp_id, 'project_name': 'ProjectB',
        'bindings': [{'role': k, 'value': v, 'confirmed': True} for k, v in BINDINGS_B.items()],
        'create_workspace': True}).json()
    assert inst['workspace_id']

    gen = client.post('/api/assets/generate', json={'project_id': inst['project']['id']}).json()
    assert gen['status'] == 'ok'
    assert 'SalesVolume' in json.dumps(gen['code'], ensure_ascii=False)
    assert gen['project']['verification_status'] == 'CODE_STATIC_CHECKED'

    listing = client.get('/api/assets/project').json()['items']
    assert any(x['id'] == inst['project']['id'] for x in listing)

    # 工作区可被沙盘打开
    ws = client.get('/api/workbench/workspaces/' + inst['workspace_id']).json()
    assert ws['workspace']['design']['cubes'][0]['name'] == 'SalesVolume'


def test_api_rejects_binding_with_missing_roles(client):
    design = project_a_design()
    bp_id = client.post('/api/assets/extract', json={
        'design': design.model_dump(), 'relation_id': 'rel-veh', 'name': 'BP'}).json()['id']
    resp = client.post('/api/assets/instantiate', json={
        'blueprint_id': bp_id, 'project_name': 'Bad',
        'bindings': [{'role': 'target_cube', 'value': 'X', 'confirmed': True}]})
    assert resp.status_code == 422


def test_api_package_roundtrip(client):
    design = project_a_design()
    bp_id = client.post('/api/assets/extract', json={
        'design': design.model_dump(), 'relation_id': 'rel-veh',
        'name': 'BP', 'mark_generic': True}).json()['id']
    pre = client.post('/api/assets/export/preflight',
                      json={'blueprint_ids': [bp_id], 'scope': 'private'}).json()
    assert pre['ok'] is True
    resp = client.post('/api/assets/export', json={'blueprint_ids': [bp_id], 'scope': 'private'})
    assert resp.status_code == 200 and resp.headers['content-type'] == 'application/zip'
    files = {'file': ('assets.zip', resp.content, 'application/zip')}
    imported = client.post('/api/assets/import', files=files).json()
    assert len(imported['imported']) == 1
    assert imported['imported'][0]['id'] != bp_id
