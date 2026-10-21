"""Visual Development 2.0：设计模式契约与生成行为。

原则：
- 设计对象必须是 DESIGN_DRAFT，不能冒充快照对象。
- 生成复用 store.codegen，不产生第二套生成器。
- 未映射 / 未确认的坐标必须阻断生成，不静默产出空赋值。
"""
import pytest
from pydantic import ValidationError

from tm1_insight import design as dg
from tm1_insight import workbench as wb
from tm1_insight.store import codegen as cg
from test_datasource_api import client  # noqa: F401


def cube_draft(dim_names=None, draft_dims=None, name='SalesCost', cid='draft-sales'):
    refs = [dg.DimensionRef(kind='existing', name=n) for n in (dim_names or ['Scenario', 'Version', 'Year', 'Measure'])]
    drafts = [dg.DimensionRef(kind='draft', name=n, draft_id=i) for n, i in (draft_dims or [])]
    if drafts:
        # 草稿维度插在 Year 之后，保持「Scenario/Version/Year/Product/Measure」顺序
        at = refs.index(next(r for r in refs if r.name == 'Year')) + 1 if any(r.name == 'Year' for r in refs) else len(refs)
        refs[at:at] = drafts
    return dg.CubeDraft(id=cid, name=name, dimensions=refs)


def schema(sid='csv-src', name='ProductSource.csv'):
    return dg.CsvSchema(id=sid, name=name, fields=[
        dg.CsvField(name='ProductCode', type='string', required=True),
        dg.CsvField(name='Brand', type='string'),
        dg.CsvField(name='Quantity', type='number', required=True),
    ])


def relation(rid='rel-1', kind='csv', src='csv-src', tgt='draft-sales',
             mapping=None, value_source='Quantity', policy='overwrite', template='csv-to-cube'):
    if mapping is None:
        mapping = [
            dg.MappingEntry(target_dimension='Scenario', kind='FIXED', fixed_member='Forecast', confirmed=True),
            dg.MappingEntry(target_dimension='Version', kind='FIXED', fixed_member='Working', confirmed=True),
            dg.MappingEntry(target_dimension='Year', kind='EXPRESSION', expression="'2026'", confirmed=True),
            dg.MappingEntry(target_dimension='Product', kind='FROM_SOURCE', source_field='ProductCode', confirmed=True),
            dg.MappingEntry(target_dimension='Measure', kind='FIXED', fixed_member='Quantity', confirmed=True),
        ]
    return dg.DesignRelation(id=rid, source=dg.RelationEnd(kind=kind, ref=src),
                             target=dg.RelationEnd(kind='cube_draft', ref=tgt),
                             mapping=mapping, value_source=value_source,
                             write_policy=policy, template=template, confirmed=True)


def design(**over):
    base = dict(
        mode='design',
        dimensions=[dg.DimensionDraft(id='dimdraft-prod', name='Product', elements=['P1', 'P2'])],
        cubes=[cube_draft(draft_dims=[('Product', 'dimdraft-prod')])],
        schemas=[schema()],
        relations=[relation()],
    )
    base.update(over)
    return dg.Design(**base)


# ---------------------------------------------------------------- 模型契约

def test_cube_draft_preserves_declared_dimension_order():
    cube = cube_draft(dim_names=['Scenario', 'Version', 'Year', 'Measure'],
                      draft_dims=[('Product', 'dimdraft-prod')])
    assert cube.dim_names == ['Scenario', 'Version', 'Year', 'Product', 'Measure']
    assert cube.provenance == 'DESIGN_DRAFT'


def test_cube_draft_rejects_duplicate_or_empty_dimensions():
    with pytest.raises(ValidationError):
        dg.CubeDraft(id='draft-x', name='X', dimensions=[
            dg.DimensionRef(kind='existing', name='Year'),
            dg.DimensionRef(kind='existing', name='year')])
    with pytest.raises(ValidationError):
        dg.CubeDraft(id='draft-x', name='X', dimensions=[])


def test_draft_dimension_ref_requires_existing_draft():
    with pytest.raises(ValidationError):
        dg.DimensionRef(kind='draft', name='Product')
    with pytest.raises(ValidationError):
        dg.Design(cubes=[dg.CubeDraft(id='draft-x', name='X', dimensions=[
            dg.DimensionRef(kind='draft', name='Product', draft_id='dimdraft-missing')])])


def test_csv_schema_rejects_duplicate_fields_and_keeps_origin():
    with pytest.raises(ValidationError):
        dg.CsvSchema(id='csv-x', name='a.csv', fields=[
            dg.CsvField(name='A'), dg.CsvField(name='a')])
    s = schema()
    assert s.origin == 'USER_INPUT' and s.provenance == 'DESIGN_DRAFT'


def test_parse_header_suggests_types_without_reading_rows():
    fields = dg.parse_header('ProductCode,Brand,Quantity,UnitCost')
    assert [f.name for f in fields] == ['ProductCode', 'Brand', 'Quantity', 'UnitCost']
    assert [f.type for f in fields] == ['unknown', 'unknown', 'number', 'number']
    assert dg.parse_header('') == []
    assert dg.parse_header('A\tB\tC') == [dg.CsvField(name='A'), dg.CsvField(name='B'), dg.CsvField(name='C')]


def test_incomplete_mapping_can_be_saved_but_blocks_generation():
    """编辑中允许暂存未填完的映射，但生成必须被阻断（不允许静默产出空坐标）。"""
    assert dg.MappingEntry(target_dimension='Scenario', kind='FIXED').fixed_member == ''
    d = design()
    d.relations[0].mapping[0] = dg.MappingEntry(target_dimension='Scenario', kind='FIXED', confirmed=True)
    blockers = dg.validate_relation(d, d.relations[0])
    assert any('固定成员为空' in b for b in blockers)
    assert dg.generate(d, 'rel-1')['status'] == 'blocked'


def test_relation_rejects_duplicate_target_mapping():
    with pytest.raises(ValidationError):
        dg.DesignRelation(id='rel-x', source=dg.RelationEnd(kind='csv', ref='csv-src'),
                          target=dg.RelationEnd(kind='cube_draft', ref='draft-sales'),
                          mapping=[dg.MappingEntry(target_dimension='Year', kind='FIXED', fixed_member='2026'),
                                   dg.MappingEntry(target_dimension='year', kind='FIXED', fixed_member='2027')])


# ---------------------------------------------------------------- 校验与阻断

def test_unconfirmed_mapping_blocks_generation():
    d = design()
    d.relations[0].mapping[0].confirmed = False
    blockers = dg.validate_relation(d, d.relations[0])
    assert any('尚未确认' in b and 'Scenario' in b for b in blockers)


def test_missing_target_coordinate_blocks_without_generating():
    d = design()
    d.relations[0].mapping = [m for m in d.relations[0].mapping if m.target_dimension != 'Year']
    result = dg.generate(d, 'rel-1')
    assert result['status'] == 'blocked' and result['code'] is None
    assert any('Year' in b for b in result['blockers'])


def test_missing_value_source_blocks():
    d = design()
    d.relations[0].value_source = ''
    result = dg.generate(d, 'rel-1')
    assert result['status'] == 'blocked'
    assert any('数值来源' in b for b in result['blockers'])


def test_source_field_not_in_schema_blocks():
    d = design()
    d.relations[0].mapping[3] = dg.MappingEntry(target_dimension='Product', kind='FROM_SOURCE',
                                               source_field='NotAColumn', confirmed=True)
    blockers = dg.validate_relation(d, d.relations[0])
    assert any('NotAColumn' in b for b in blockers)


def test_template_mismatch_blocks():
    d = design()
    d.relations[0].template = 'cube-data-transfer'
    blockers = dg.validate_relation(d, d.relations[0])
    assert any('csv-to-cube' in b for b in blockers)


def test_mapping_dimension_outside_target_blocks():
    d = design()
    d.relations[0].mapping.append(dg.MappingEntry(target_dimension='Plant', kind='FIXED', fixed_member='A', confirmed=True))
    blockers = dg.validate_relation(d, d.relations[0])
    assert any('不属于目标 Cube' in b for b in blockers)


# ---------------------------------------------------------------- 生成结果

def test_csv_generation_keeps_dimension_order_and_write_policy():
    result = dg.generate(design(), 'rel-1', generated_at='2026-10-21T00:00:00Z')
    assert result['status'] == 'ok'
    code = result['code']
    assert code['tgt_dims'] == ['Scenario', 'Version', 'Year', 'Product', 'Measure']
    data = code['data']
    assert "vScenario = 'Forecast';" in data
    assert "vVersion = 'Working';" in data
    assert 'vProduct = vProductCode;' in data
    assert 'StringToNumberEx( vQuantity' in data
    assert 'CellPutN(vValue, cCubTgt, vScenario, vVersion, vYear, vProduct, vMeasure);' in data
    assert 'DatasourceType' in code['prolog'] and 'CHARACTERDELIMITED' in code['prolog']
    assert result['artifact']['status'] == 'DESIGN_DRAFT'
    assert result['artifact']['validated'] is True


def test_accumulate_policy_switches_to_increment():
    d = design(relations=[relation(policy='accumulate')])
    result = dg.generate(d, 'rel-1')
    assert 'CellIncrementN(' in result['code']['data']


def test_cube_to_cube_generation_reuses_existing_generator():
    d = dg.Design(mode='design',
                  cubes=[cube_draft(name='TargetCube', cid='draft-target', draft_dims=[('Product', 'dimdraft-prod')]),
                         dg.CubeDraft(id='draft-source', name='SourceCube', dimensions=[
                             dg.DimensionRef(kind='existing', name='Scenario'),
                             dg.DimensionRef(kind='existing', name='Product'),
                             dg.DimensionRef(kind='existing', name='Measure')])],
                  dimensions=[dg.DimensionDraft(id='dimdraft-prod', name='Product', elements=['P1'])],
                  relations=[dg.DesignRelation(
                      id='rel-c2c', source=dg.RelationEnd(kind='cube_draft', ref='draft-source'),
                      target=dg.RelationEnd(kind='cube_draft', ref='draft-target'),
                      template='cube-data-transfer',
                      mapping=[dg.MappingEntry(target_dimension='Scenario', kind='FROM_SOURCE', source_field='Scenario', confirmed=True),
                               dg.MappingEntry(target_dimension='Version', kind='FIXED', fixed_member='WIP', confirmed=True),
                               dg.MappingEntry(target_dimension='Year', kind='FIXED', fixed_member='2026', confirmed=True),
                               dg.MappingEntry(target_dimension='Product', kind='FROM_SOURCE', source_field='Product', confirmed=True),
                               dg.MappingEntry(target_dimension='Measure', kind='FROM_SOURCE', source_field='Measure', confirmed=True)])])
    result = dg.generate(d, 'rel-c2c')
    assert result['status'] == 'ok', result['blockers']
    assert 'cCubSrc' in result['code']['prolog']
    assert result['code']['tgt_dims'] == ['Scenario', 'Version', 'Year', 'Product', 'Measure']
    assert 'vVersion = \'WIP\';' in result['code']['data']


def test_cube_spec_marks_which_dimensions_are_drafts():
    spec = dg.cube_creation_spec(design(), 'draft-sales')['spec']
    sources = [d['source'] for d in spec['dimensions']]
    assert sources.count('EXISTING_SNAPSHOT') == 4
    assert sources.count('DESIGN_DRAFT') == 1
    assert any('维度草稿 Product' in s for s in spec['steps'])
    assert dg.cube_creation_spec(design(), 'draft-missing')['status'] == 'missing'


# ---------------------------------------------------------------- Blueprint 与持久化

def test_blueprint_rejects_dangling_references():
    with pytest.raises(ValidationError):
        dg.Design(blueprints=[dg.Blueprint(id='bp-1', name='B', relation_ids=['rel-missing'])])


def test_blueprint_keeps_design_refs_and_version():
    bp = dg.Blueprint(id='bp-1', name='销售成本装载', version=2,
                      cube_ids=['draft-sales'], schema_ids=['csv-src'],
                      relation_ids=['rel-1'], dimension_ids=['dimdraft-prod'])
    d = design(blueprints=[bp])
    assert d.blueprints[0].version == 2
    assert d.blueprints[0].provenance == 'DESIGN_DRAFT'


def test_workspace_roundtrip_keeps_design(tmp_path):
    ws = wb.Workspace(snapshot_id='snap', name='设计', design=design())
    key = 'c' * 32
    rev = wb.save_workspace(tmp_path, key, ws, '')
    loaded, r = wb.load_workspace(tmp_path, key)
    assert r == rev
    assert loaded.design.cubes[0].dim_names == ws.design.cubes[0].dim_names
    assert loaded.design.relations[0].mapping[0].fixed_member == 'Forecast'
    assert loaded.design.schemas[0].fields[2].type == 'number'


def test_workspace_v1_file_still_loads(tmp_path):
    key = 'd' * 32
    legacy = {'schema_version': 'architecture-workspace-1', 'snapshot_id': 'snap', 'name': '旧工作区'}
    (tmp_path / (key + '.json')).write_text(__import__('json').dumps(legacy), encoding='utf-8')
    loaded, _ = wb.load_workspace(tmp_path, key)
    assert loaded.name == '旧工作区'
    assert loaded.design.mode == 'explore'
    assert loaded.design.cubes == []


def test_design_objects_never_claim_model_fact():
    d = design()
    assert d.cubes[0].provenance == 'DESIGN_DRAFT'
    assert d.schemas[0].provenance == 'DESIGN_DRAFT'
    assert d.relations[0].provenance == 'DESIGN_RELATION'
    assert d.relations[0].target.kind == 'cube_draft'


# ---------------------------------------------------------------- API

def test_design_api_meta_and_generation(client):
    meta = client.get('/api/workbench/design/meta').json()
    assert meta['dimensions'] and meta['cubes']
    assert {t['id'] for t in meta['templates']} >= {'csv-to-cube', 'cube-data-transfer'}

    payload = {'design': design().model_dump(), 'relation_id': 'rel-1'}
    ok = client.post('/api/workbench/design/generate', json=payload).json()
    assert ok['status'] == 'ok' and ok['code']['tgt_dims'][-1] == 'Measure'

    d = design()
    d.relations[0].value_source = ''
    blocked = client.post('/api/workbench/design/generate',
                          json={'design': d.model_dump(), 'relation_id': 'rel-1'}).json()
    assert blocked['status'] == 'blocked' and blocked['code'] is None

    spec = client.post('/api/workbench/design/cube-spec',
                       json={'design': design().model_dump(), 'cube_id': 'draft-sales'}).json()
    assert spec['status'] == 'DESIGN_DRAFT'


def test_design_api_rejects_unknown_snapshot(client):
    payload = {'design': design().model_dump(), 'relation_id': 'rel-1', 'snapshot_id': 'other'}
    assert client.post('/api/workbench/design/generate', json=payload).status_code == 409


def test_codegen_extension_is_backward_compatible():
    """原有调用（不传 src_dims/tgt_dims/dim_mapping）保持相同签名语义。"""
    import inspect
    sig = inspect.signature(cg.data_transfer)
    for name in ('src_dims', 'tgt_dims', 'dim_mapping'):
        assert sig.parameters[name].default is None
