"""Module Dossier P0 — synthetic General Ledger -> Expense Account Balance.

The tests assert reader-facing content, not only JSON shape: a stranger must be
able to learn sources, structure, transformations, results and open questions
from Module.md alone. No real model, credential or cell value is used.
"""
from __future__ import annotations

import io
import json
import zipfile

import duckdb
import pytest

import tm1_insight.config as config
from tm1_insight import module_dossier as md
from tm1_insight.config import get_settings
from module_dossier_fixture import seed, scope_kwargs


@pytest.fixture
def model():
    con = duckdb.connect(':memory:')
    seed(con)
    yield con
    con.close()


def build(con, **overrides):
    return md.build(con, scope_kwargs(**overrides))


def evidence_ids(model):
    return {item['id'] for item in model['evidence']}


def all_refs(model):
    refs = []
    for section in ('data_sources', 'data_model', 'transformation_steps', 'target_results',
                    'rules', 'feeders', 'execution_calls', 'verification_gaps'):
        for row in model[section]:
            refs.extend(row.get('evidence_refs') or [])
            for nested in ('variables', 'dimensions', 'conditions', 'assignments',
                           'field_mapping', 'coordinates', 'unresolved', 'references',
                           'parameters', 'sequence', 'known_references'):
                value = row.get(nested)
                if isinstance(value, dict):
                    value = value.get('items')
                if isinstance(value, list):
                    for child in value:
                        if isinstance(child, dict):
                            refs.extend(child.get('evidence_refs') or [])
    for call in model['execution_calls']:
        refs.extend(call.get('evidence_refs') or [])
    return [ref for ref in refs if ref]


# ---------------------------------------------------------------------------
# 1. Reader-facing document
# ---------------------------------------------------------------------------

def test_module_md_answers_the_five_reader_questions(model):
    text = md.markdown(build(model))
    for heading in ('## 0. 一页摘要', '## 1. 数据来源', '## 2. 数据模型', '## 3. 逐步转换',
                    '## 4. 目标结果', '## 5. Rule 与 Feeder', '## 6. 执行调用',
                    '## 7. 验证缺口', '## 8. 阅读边界与证据索引'):
        assert heading in text
    # where the data comes from
    assert 'General Ledger' in text and 'ExpenseInput' in text
    assert 'vAccount' in text and 'String' in text and '单元格值列' in text
    # the real dimension order, not an alphabetised guess
    assert 'Department → Account → Period → Version → Measure' in text
    # how values are formed
    assert 'nSigned = vAmount * pSign' in text
    assert 'NATIVE_VIEW_LAYOUT_AND_RECORDED_CUBE_ORDER' in text
    # write mode is explicit
    assert 'OVERWRITE_NUMERIC' in text and 'INCREMENT_NUMERIC' in text
    # Rule and Feeder are separate from TI writes
    assert "DB ( 'General Ledger'" in text and 'Feeder（非数值流）' in text
    # unresolved work is stated, not hidden
    assert 'AttrS' in text and 'RUNTIME_NOT_VERIFIED' in text


def test_markdown_does_not_dump_source_or_large_json(model):
    text = md.markdown(build(model))
    # The full Data section must not be embedded as a source block.
    assert 'sDept = AttrS' not in text
    assert 'SubsetElementInsert' not in text
    assert '```json' not in text
    # No raw dump of the machine model.
    assert 'data_row_value_dependencies' not in text
    assert len(text) < 40_000


def test_conditions_are_marked_unresolved_and_explained(model):
    result = build(model)
    write = next(r for r in result['target_results'] if r['operation'] == 'CellPutN')
    assert write['conditions'] and all(c['evaluated'] is False for c in write['conditions'])
    text = md.markdown(result)
    assert '字符串常量沿用既有解析契约' in text
    assert any(g['code'] == 'CONDITION_NOT_EVALUATED' for g in result['verification_gaps'])


# ---------------------------------------------------------------------------
# 2. Structural facts and evidence
# ---------------------------------------------------------------------------

def test_evidence_ids_resolve_and_runtime_is_never_claimed(model):
    result = build(model)
    ids = evidence_ids(result)
    assert ids and set(all_refs(result)) <= ids
    assert result['runtime_verified'] is False and result['coverage']['runtime_verified'] == 0
    assert all(not row['runtime_verified'] for row in result['target_results'])
    assert all(not row['runtime_verified'] for row in result['rules'])
    assert result['statements']['runtime'].startswith('0 项运行验证')


def test_cube_structure_dimension_metadata_and_grain(model):
    result = build(model)
    target = next(c for c in result['data_model'] if c['name'] == 'Expense Account Balance')
    assert target['role'] == 'TARGET'
    assert target['dimension_order'] == ['Department', 'Account', 'Period', 'Version', 'Measure']
    assert target['order_status'] == 'RECORDED_COMPLETE'
    assert target['grain_status'] == 'ORDER_RECORDED_GRANULARITY_UNVERIFIED'
    account = next(d for d in target['dimensions'] if d['name'] == 'Account')
    assert account['attributes']['status'] == 'recorded' and account['attributes']['count'] == 1
    assert account['attributes']['names'] == ['Department']
    assert account['hierarchies'] == ['Account', 'Account by Department']
    assert account['consolidation']['count'] == 3
    # Dimension order is recorded 0-based; the dossier reports a 1-based position.
    assert [d['position'] for d in target['dimensions']] == [1, 2, 3, 4, 5]
    source = next(c for c in result['data_model'] if c['name'] == 'General Ledger')
    assert source['role'] == 'SOURCE'


def test_ti_datasource_variables_parameters_and_writes(model):
    result = build(model)
    source = next(s for s in result['data_sources'] if s['process'] == 'TI.Load.ExpenseBalance')
    assert source['datasource']['declared_type'] == 'VIEW'
    assert source['datasource']['cube'] == 'General Ledger'
    assert source['datasource']['view'] == 'ExpenseInput'
    assert source['datasource']['binding_locations']
    variables = source['variables']['items']
    assert [(v['name'], v['type'], v['position']) for v in variables] == [
        ('vAccount', 'String', 1), ('vPeriod', 'String', 2), ('vVersion', 'String', 3),
        ('vMeasure', 'String', 4), ('vAmount', 'Numeric', 5)]
    assert [v['source_dimension'] for v in variables[:4]] == ['Account', 'Period', 'Version', 'Measure']
    assert variables[-1]['source_field_kind'] == 'CELL_VALUE'
    params = source['parameters']
    assert params['status'] == 'RECORDED'
    assert {p['name']: p['type'] for p in params['items']} == {'pSign': 'Numeric', 'pPeriod': 'String'}

    writes = [r for r in result['target_results'] if r['process'] == 'TI.Load.ExpenseBalance']
    assert [w['mode'] for w in writes] == ['OVERWRITE_NUMERIC', 'INCREMENT_NUMERIC']
    overwrite = writes[0]
    assert overwrite['cube'] == 'Expense Account Balance'
    coordinates = {c['dimension']: c for c in overwrite['coordinates']}
    assert coordinates['Account']['binding_kind'] == 'DATA_ROW_VARIABLE'
    assert coordinates['Department']['binding_kind'] == 'UNRESOLVED'
    assert coordinates['Department']['provenance'] == 'UNKNOWN'
    assert overwrite['coordinate_status'] == 'PARTIAL'
    mapping = {(m['source_dimension'], m['target_dimension']): m for m in overwrite['field_mapping']}
    assert ('Account', 'Account') in mapping and ('Measure', 'Measure') in mapping
    assert all(m['provenance'] == 'STATIC_INFERENCE' for m in overwrite['field_mapping'])
    # The value column is mapped to the written value, never to a dimension.
    value_rows = [m for m in overwrite['field_mapping'] if m.get('target') == '写入值']
    assert len(value_rows) == 1 and value_rows[0]['source_variable'] == 'vAmount'


def test_increment_write_mode_and_fixed_members(model):
    result = build(model)
    increment = next(r for r in result['target_results'] if r['operation'] == 'CellIncrementN')
    assert increment['mode_label'] == '累加数值'
    assert increment['coordinate_status'] == 'COMPLETE'
    fixed = {c['dimension']: c['value'] for c in increment['coordinates']
             if c['binding_kind'] == 'FIXED_MEMBER'}
    assert fixed == {'Department': 'UNASSIGNED', 'Account': '6200 Rent',
                     'Version': 'ACTUAL', 'Measure': 'QTY'}


# ---------------------------------------------------------------------------
# 3. Rule / Feeder semantics
# ---------------------------------------------------------------------------

def test_rules_and_feeders_are_separate_from_physical_writes(model):
    result = build(model)
    assert len(result['rules']) == 2 and len(result['feeders']) == 1
    rule = result['rules'][0]
    assert rule['area']['raw'] and rule['expression'].startswith('DB')
    assert rule['references'][0]['cube'] == 'General Ledger'
    assert rule['references'][0]['cube_resolved'] is True
    assert rule['status'] == 'PARTIAL'
    # Rule references never appear as TI write points.
    assert all(r['cube'] != 'General Ledger' for r in result['target_results'])
    # The dynamic rule cube is reported as unresolved, not named as a dependency.
    dynamic = next(r for r in result['rules'] if 'pSourceCube' in (r['expression'] or ''))
    assert dynamic['references'][0]['cube_resolved'] is False
    assert any(g['code'] == 'RULE_DYNAMIC_REFERENCE' for g in result['verification_gaps'])
    # Feeder carries its own note and is not a formula.
    assert '不直接产生业务数值' in result['feeders'][0]['note']
    assert result['rule_areas'] and 'PARTIAL' in result['rule_areas'][0]['coordinate_status']


def test_clear_effect_is_reported_without_inventing_its_target(model):
    result = build(model)
    effect = next(e for e in result['target_effects'] if e['operation'] == 'ViewZeroOut')
    assert effect['target'] is None
    assert effect['target_status'] == 'PARAMETER_DRIVEN_UNKNOWN'
    assert any(g['code'] == 'CLEAR_TARGET_UNRESOLVED' for g in result['verification_gaps'])
    assert '参数决定（未解析）' in md.markdown(result)


# ---------------------------------------------------------------------------
# 4. Scope, exclusion and missing metadata
# ---------------------------------------------------------------------------

def test_exclusion_keeps_the_dependency_warning(model):
    result = build(model, exclude=[dict(type='process', name='}bedrock.synthetic.clear')])
    assert '}bedrock.synthetic.clear' not in result['scope']['processes']
    codes = {g['code'] for g in result['verification_gaps'] if g['object'] in
             {'}bedrock.synthetic.clear', 'Chore.MonthEndClose'}}
    assert 'EXCLUDED_BY_USER' in codes and 'EXCLUDED_DEPENDENCY' in codes
    excluded_call = next(c for c in result['execution_calls'] if c['callee'] == '}bedrock.synthetic.clear')
    assert excluded_call['in_scope'] is False
    assert any('排除' in g['reason'] for g in result['verification_gaps'])


def test_manual_include_adds_an_object_discovery_misses(model):
    baseline = build(model)
    assert 'TJ.Unrelated' not in baseline['scope']['processes']
    duckdb_seed = model.execute(
        "INSERT INTO processes(name,prolog,metadata,data,epilog,parameters) "
        "VALUES ('TJ.Unrelated','','','','','[]')")
    assert duckdb_seed is not None
    included = build(model, include=[dict(type='process', name='TJ.Unrelated')])
    assert 'TJ.Unrelated' in included['scope']['processes']
    assert any(g['code'] == 'PARAMETER_TYPE_NOT_COLLECTED' or g['object'] == 'TJ.Unrelated'
               for g in included['verification_gaps'])


def test_missing_variable_metadata_stays_unknown():
    con = duckdb.connect(':memory:')
    seed(con, with_metadata=False)
    result = md.build(con, scope_kwargs())
    con.close()
    loader = next(s for s in result['data_sources'] if s['process'] == 'TI.Load.ExpenseBalance')
    assert loader['variables']['items'] == []
    assert loader['variables']['layout_status'] == 'UNKNOWN'
    write = next(r for r in result['target_results'] if r['operation'] == 'CellPutN')
    assert write['field_mapping'] == []
    assert write['coordinate_status'] == 'PARTIAL'
    # No guessed source dimension and no guessed value column.
    assert all(c['binding_kind'] != 'DATA_ROW_VARIABLE' for c in write['coordinates'])
    assert any(g['code'] == 'VARIABLE_BINDING_MISSING' for g in result['verification_gaps'])
    text = md.markdown(result)
    assert '未采集到可用定义' in text


def test_cube_entry_uses_target_cube_and_bounded_discovery(model):
    result = md.build(model, scope_kwargs(entry_kind='cube', entry='Expense Account Balance',
                                          target_cube=None))
    assert result['scope']['target_cubes'] == ['Expense Account Balance']
    assert 'TI.Load.ExpenseBalance' in result['scope']['processes']
    assert result['coverage']['write_points'] >= 2


# ---------------------------------------------------------------------------
# 5. Export package
# ---------------------------------------------------------------------------

def test_zip_has_exactly_the_five_contract_files(model):
    payload = md.package(build(model))
    archive = zipfile.ZipFile(io.BytesIO(payload))
    assert archive.namelist() == ['Module.md', 'Module.json', 'Evidence.json',
                                  'Diagnostics.json', 'Questions.md']
    module = json.loads(archive.read('Module.json'))
    evidence = json.loads(archive.read('Evidence.json'))
    diagnostics = json.loads(archive.read('Diagnostics.json'))
    questions = archive.read('Questions.md').decode('utf-8')
    assert module['schema_version'] == md.VERSION
    assert evidence['items'] and evidence['runtime_verified'] is False
    assert diagnostics['coverage']['gaps'] == len(module['verification_gaps'])
    assert questions.startswith('# 待确认问题') and 'GAP-' in questions
    assert 'AttrS' in questions


def test_write_package_refuses_to_overwrite(tmp_path, model):
    payload = md.package(build(model))
    written = md.write_package(payload, tmp_path / 'out')
    assert {p.name for p in written} == {'Module.md', 'Module.json', 'Evidence.json',
                                         'Diagnostics.json', 'Questions.md'}
    with pytest.raises(ValueError):
        md.write_package(payload, tmp_path / 'out')


# ---------------------------------------------------------------------------
# 6. API: read-only, paginated, fingerprint-guarded
# ---------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, '_USER_DATA_ROOT', tmp_path)
    monkeypatch.setattr(config, '_PROJECT_ROOT', tmp_path / 'app')
    # 不用 set_data_dir()：它会落盘（写到临时根下算侥幸），而且把模块级
    # _DATA_DIR_OVERRIDE 置空之后 monkeypatch 管不到它，fixture 结束全局就
    # 永久指向空目录——同一次 pytest 里后跑的 test_cube_scope 读真实库时
    # 会读到零条，把「折叠视图必须给出回全量的链接」判成失败。
    # monkeypatch 改这个变量既能生效又会被还原。
    monkeypatch.setattr(config, '_DATA_DIR_OVERRIDE', None)
    get_settings.cache_clear()
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(settings.db_path))
    seed(con)
    con.close()
    from fastapi.testclient import TestClient
    from tm1_insight.api.app import app
    yield TestClient(app)
    # 下一个测试必须按恢复后的真实路径重建，而不是继续用在临时目录构建的缓存。
    get_settings.cache_clear()


def wait(client, task):
    for _ in range(200):
        state = client.get('/api/module-dossier/tasks/' + task).json()
        if state['status'] in {'completed', 'failed', 'cancelled'}:
            return state
    raise AssertionError('task did not finish')


def test_api_discover_task_result_export(api):
    body = scope_kwargs(snapshot_id='').model_dump(mode='json')
    discovered = api.post('/api/module-dossier/discover', json=body)
    assert discovered.status_code == 200
    payload = discovered.json()
    assert payload['entry'] == {'type': 'process', 'name': 'Chore.MonthEndClose'}
    assert any(c['name'] == 'TI.Load.ExpenseBalance' for c in payload['candidates'])
    assert payload['resolved']['processes']

    started = api.post('/api/module-dossier/tasks', json=body)
    assert started.status_code == 202
    task = started.json()['task_id']
    assert wait(api, task)['status'] == 'completed'

    page = api.get('/api/module-dossier/tasks/%s/result' % task,
                   params=dict(section='target_results', offset=0, limit=1)).json()
    assert page['total'] >= 2 and len(page['items']) == 1
    assert page['items'][0]['mode'] in {'OVERWRITE_NUMERIC', 'INCREMENT_NUMERIC'}

    full = api.get('/api/module-dossier/tasks/%s/result' % task).json()
    assert full['runtime_verified'] is False
    document = api.get('/api/module-dossier/tasks/%s/result' % task, params=dict(format='markdown'))
    assert document.status_code == 200 and '## 1. 数据来源' in document.text

    bundle = api.get('/api/module-dossier/tasks/%s/export' % task)
    assert bundle.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(bundle.content)).namelist()
    assert names == ['Module.md', 'Module.json', 'Evidence.json', 'Diagnostics.json', 'Questions.md']
    assert api.get('/api/module-dossier/tasks/%s/result' % task,
                   params=dict(section='not_a_section')).status_code == 422
    assert api.get('/api/module-dossier/tasks/nonexistent').status_code == 404


def test_api_rejects_unknown_entry(api):
    body = scope_kwargs(snapshot_id='', entry='No.Such.Process', target_cube=None).model_dump(mode='json')
    assert api.post('/api/module-dossier/tasks', json=body).status_code == 404
    bad = dict(body, entry='Chore.MonthEndClose', target_cube='No Such Cube')
    response = api.post('/api/module-dossier/tasks', json=bad)
    assert response.status_code in {404, 422}


# ---------------------------------------------------------------------------
# 7. Determinism and analysis safety
# ---------------------------------------------------------------------------

def test_build_is_deterministic_and_read_only(model):
    before = model.execute('SELECT count(*) FROM processes').fetchone()[0]
    first = build(model)
    second = build(model)
    assert md.dumps(first) == md.dumps(second)
    assert model.execute('SELECT count(*) FROM processes').fetchone()[0] == before
    # Every observation keeps a source location; nothing is invented.
    for step in first['transformation_steps']:
        for action in step['sequence']:
            assert action['location']['section'] in {'prolog', 'metadata', 'data', 'epilog'}
            assert action['order_basis'] == 'SOURCE_LOCATION_ORDER'
    assert all(g['provenance'] == 'UNKNOWN' for g in first['verification_gaps'])
