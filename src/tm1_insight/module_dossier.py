"""Readable, evidence-backed module dossier composed from existing engines.

This module adds no parser, graph engine or calculation engine. It projects
already-computed facts from:

- ``store.calculation.inspect``            TI statements, writes, coordinates
- ``store.data_row.context``               Variables, NativeView layout binding
- ``workflow_review.source_declaration``    DataSource declaration
- ``store.queries.cube_rule_semantics``    Rule / Feeder semantic IR
- ``store.dimensions``                     recorded dimension metadata

Every claim carries an evidence id, an object name and a source location.
Observation, static inference, user annotation, UNKNOWN and runtime proof are
kept apart. Nothing here executes TM1, mutates a snapshot or infers execution
order beyond real source locations.
"""
from __future__ import annotations

from collections import deque
from datetime import date
from html import escape
import hashlib
import io
import json
import tempfile
from typing import Literal
import zipfile

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tm1_insight import workflow
from tm1_insight.store import dimensions as dimension_store
from tm1_insight.store.queries import cube_rule_semantics

VERSION = 'module-dossier-1'
REQUEST_VERSION = 'module-dossier-request-1'
REVISION = 1

SECTIONS = ('data_sources', 'data_model', 'transformation_steps', 'target_results',
            'rules', 'feeders', 'execution_calls', 'verification_gaps')

SECTION_ORDER = {'prolog': 0, 'metadata': 1, 'data': 2, 'epilog': 3}

# Write mode is a migration-relevant fact, not a business interpretation.
WRITE_MODES = {
    'cellputn': ('OVERWRITE_NUMERIC', '覆盖数值'),
    'cellputs': ('OVERWRITE_TEXT', '覆盖文本'),
    'cellincrementn': ('INCREMENT_NUMERIC', '累加数值'),
}

PROVENANCE = {
    'SOURCE': 'OBSERVED_SOURCE',
    'MODEL': 'OBSERVED_MODEL',
    'INFERENCE': 'STATIC_INFERENCE',
    'USER': 'USER_ANNOTATION',
    'UNKNOWN': 'UNKNOWN',
}

CORE_BUDGET = dict(processes=(1, 20, 8), write_points=(1, 80, 20), rules=(1, 120, 40),
                   evidence=(500, 20000, 4000), objects=(1, 60, 24))

# Markdown stays readable: full detail for the first N writes, then a summary.
DETAIL_LIMIT = 20
RULE_ROW_LIMIT = 80


class Ref(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['process', 'cube'] = 'process'
    name: str = Field(min_length=1, max_length=1000)


class Scope(BaseModel):
    """Analysis request. Membership is explicit; discovery is only a suggestion."""

    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['module-dossier-request-1'] = REQUEST_VERSION
    name: str = Field(min_length=1, max_length=200)
    snapshot_id: str = Field(default='', max_length=128)
    entry_kind: Literal['process', 'cube'] = 'process'
    entry: str = Field(min_length=1, max_length=1000)
    target_cube: str | None = Field(default=None, max_length=1000)
    include: list[Ref] = Field(default_factory=list, max_length=40)
    exclude: list[Ref] = Field(default_factory=list, max_length=40)
    notes: str = Field(default='', max_length=4000)
    analyst: str = Field(default='', max_length=200)
    max_processes: int = Field(default=8, ge=1, le=20, strict=True)
    max_write_points: int = Field(default=20, ge=1, le=80, strict=True)
    max_rules: int = Field(default=40, ge=1, le=120, strict=True)
    max_evidence: int = Field(default=4000, ge=500, le=20000, strict=True)

    @model_validator(mode='after')
    def consistent(self):
        for field in ('include', 'exclude'):
            values = getattr(self, field)
            if len({(r.type, r.name) for r in values}) != len(values):
                raise ValueError('Duplicate object reference in ' + field)
        overlap = {(r.type, r.name) for r in self.include} & {(r.type, r.name) for r in self.exclude}
        if overlap:
            raise ValueError('Included and excluded overlap')
        if (self.entry_kind, self.entry) in {(r.type, r.name) for r in self.exclude}:
            raise ValueError('Entry cannot be excluded')
        return self


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def request_id(scope: Scope) -> str:
    return hashlib.sha256(canonical(scope.model_dump(mode='json')).encode()).hexdigest()


class Evidence:
    """Deterministic, content-deduplicated evidence ledger with a hard budget."""

    def __init__(self, snapshot: str, limit: int):
        self.snapshot = snapshot
        self.limit = limit
        self.items: list[dict] = []
        self._by_key: dict[str, str] = {}
        self.truncated = 0

    def add(self, kind: str, obj: str, **detail) -> str | None:
        key = canonical(dict(kind=kind, object=obj, **detail))
        if key in self._by_key:
            return self._by_key[key]
        if len(self.items) >= self.limit:
            self.truncated += 1
            return None
        eid = 'EV-%04d' % (len(self.items) + 1)
        item = dict(id=eid, kind=kind, object=obj, snapshot_id=self.snapshot, **detail)
        self.items.append(item)
        self._by_key[key] = eid
        return eid

    def refs(self, *ids) -> list[str]:
        return [i for i in ids if i]

    def any(self, *ids) -> list[str]:
        return self.refs(*ids)


def _tables(con) -> set[str]:
    try:
        return {row[0] for row in con.execute('SHOW TABLES').fetchall()}
    except Exception:  # noqa: BLE001  # 只读旧库或无表时降级
        return set()


def _catalogs(con) -> dict:
    return {kind: {r[0] for r in con.execute('SELECT name FROM ' + table).fetchall()}
            for kind, table in (('process', 'processes'), ('cube', 'cubes'), ('dimension', 'dimensions'))}


def _location(evidence: dict | None) -> str:
    if not evidence:
        return '来源待确认'
    if 'section' not in evidence and 'line' not in evidence:
        table = evidence.get('table')
        return ('模型表 ' + str(table)) if table else '模型定义'
    section = evidence.get('section', 'source')
    line = evidence.get('line')
    column = evidence.get('column', 1)
    if line is None:
        return str(section)
    return '%s:%s:%s' % (section, line, column)


# ---------------------------------------------------------------------------
# Discovery and membership
# ---------------------------------------------------------------------------

def discover(con, scope: Scope) -> dict:
    """Bounded candidate discovery from existing relation tables, never a new traversal."""
    catalogs = _catalogs(con)
    if scope.entry_kind == 'process' and scope.entry not in catalogs['process']:
        raise KeyError('Process ' + scope.entry)
    if scope.entry_kind == 'cube' and scope.entry not in catalogs['cube']:
        raise KeyError('Cube ' + scope.entry)
    if scope.target_cube and scope.target_cube not in catalogs['cube']:
        raise KeyError('Cube ' + scope.target_cube)

    candidates: dict[tuple, dict] = {}

    def add(kind, name, reason, basis, detail=None):
        key = (kind, name)
        if key in candidates:
            if reason not in candidates[key]['reasons']:
                candidates[key]['reasons'].append(reason)
            candidates[key]['bases'].append(dict(reason=reason, basis=basis, detail=detail or {}))
            return
        candidates[key] = dict(type=kind, name=name, reasons=[reason],
                               bases=[dict(reason=reason, basis=basis, detail=detail or {})])

    add(scope.entry_kind, scope.entry, 'ENTRY', 'user_entry')
    targets = {scope.target_cube} if scope.target_cube else set()
    if scope.entry_kind == 'cube' and not targets:
        targets = {scope.entry}

    if scope.entry_kind == 'process':
        rows = con.execute('SELECT caller FROM process_calls_process WHERE callee=? ORDER BY caller LIMIT 41',
                           [scope.entry]).fetchall()
        for (name,) in rows:
            add('process', name, 'ENTRY_CALLER', 'process_calls_process', dict(callee=scope.entry))
        rows = con.execute('SELECT callee FROM process_calls_process WHERE caller=? ORDER BY callee LIMIT 41',
                           [scope.entry]).fetchall()
        for (name,) in rows:
            add('process', name, 'ENTRY_CALLEE', 'process_calls_process', dict(caller=scope.entry))
        # One bounded hop of callees-of-callees; never an unbounded crawl.
        direct = sorted({c['name'] for c in candidates.values() if c['type'] == 'process'})[:11]
        if direct:
            marks = ','.join('?' for _ in direct)
            rows = con.execute('SELECT DISTINCT callee FROM process_calls_process WHERE caller IN (' + marks +
                               ') ORDER BY callee LIMIT 41', direct).fetchall()
            for (name,) in rows:
                add('process', name, 'SECOND_HOP_CALLEE', 'process_calls_process',
                    dict(via='entry callees', depth=2))

    for cube in sorted(targets):
        rows = con.execute('SELECT DISTINCT process_name FROM process_writes_cube WHERE cube_name=? '
                           'ORDER BY process_name LIMIT 41', [cube]).fetchall()
        for (name,) in rows:
            add('process', name, 'TARGET_CUBE_WRITER', 'process_writes_cube', dict(cube=cube))
        rows = con.execute('SELECT DISTINCT process_name FROM process_reads_cube WHERE cube_name=? '
                           'ORDER BY process_name LIMIT 41', [cube]).fetchall()
        for (name,) in rows:
            add('process', name, 'TARGET_CUBE_READER', 'process_reads_cube', dict(cube=cube))
        add('cube', cube, 'TARGET', 'user_target')

    for ref in scope.include:
        add(ref.type, ref.name, 'MANUALLY_INCLUDED', 'user_include')

    items = sorted(candidates.values(), key=lambda c: (c['type'], c['name']))
    return dict(entry=dict(type=scope.entry_kind, name=scope.entry), target_cubes=sorted(targets),
                candidates=items, catalog_missing=[c['name'] for c in items
                                                   if c['name'] not in catalogs[c['type']]])


def resolve_membership(scope: Scope, discovery: dict) -> dict:
    """Apply explicit include/exclude on top of discovery, keeping some ordering rules.

    Excluded objects never disappear silently: they are returned separately so
    the builder can keep an unresolved-dependency warning for each real edge.
    """
    excluded = {(r.type, r.name) for r in scope.exclude}
    included: dict[tuple, dict] = {}
    for candidate in discovery['candidates']:
        if (candidate['type'], candidate['name']) in excluded:
            continue
        included[(candidate['type'], candidate['name'])] = candidate
    processes = sorted(n for (t, n) in included if t == 'process')
    cubes = sorted(n for (t, n) in included if t == 'cube')
    dropped = []
    if len(processes) > scope.max_processes:
        keep = set(processes[:scope.max_processes]) | ({scope.entry} if scope.entry_kind == 'process' else set())
        dropped = [n for n in processes if n not in keep]
        processes = [n for n in processes if n in keep]
    entry = scope.entry
    if scope.entry_kind == 'process' and entry not in processes:
        processes = sorted(set(processes) | {entry})
    for name in discovery['catalog_missing']:
        pass
    excluded_items = [r.model_dump() for r in scope.exclude]
    return dict(processes=processes, cubes=cubes, excluded=excluded_items,
                budget_dropped=dropped,
                excluded_candidates=[c for c in discovery['candidates']
                                     if (c['type'], c['name']) in excluded])


# ---------------------------------------------------------------------------
# Per-process projection
# ---------------------------------------------------------------------------

def _parameter_details(con, name: str, tables: set[str], parts: tuple) -> dict:
    if 'process_source_metadata' not in tables:
        return dict(items=[], status='MISSING_PARAMETER_METADATA',
                    reason='旧快照未保存 Process 参数定义；仅有参数名可用。')
    row = con.execute('SELECT payload FROM process_source_metadata WHERE process_name=? AND length(payload)<=200000',
                      [name]).fetchone()
    if row is None:
        return dict(items=[], status='MISSING_PARAMETER_METADATA',
                    reason='未采集该 Process 的参数定义；仅有参数名可用。')
    try:
        meta = json.loads(row[0]) if row else {}
    except (ValueError, TypeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    from tm1_insight.store.data_row import SECTIONS, source_hash
    if meta.get('source_hash') != source_hash(dict(zip(SECTIONS, parts))):
        return dict(items=[], status='PARAMETER_METADATA_MISMATCH',
                    reason='参数元数据与当前四段源码哈希不一致，不能当作本版本参数。')
    values = meta.get('parameters')
    if not isinstance(values, list):
        return dict(items=[], status='MISSING_PARAMETER_METADATA', reason='参数定义数组缺失。')
    items = []
    for value in values[:200]:
        if not isinstance(value, dict):
            continue
        items.append(dict(name=value.get('name') or value.get('Name'), type=value.get('type') or value.get('Type'),
                          default=value.get('default_value', value.get('DefaultValue', value.get('default_value'))),
                          status='RECORDED'))
    for item in items:
        if item['type'] is None:
            item['type'] = 'UNKNOWN'
        if item['default'] is None:
            item['default'] = None
    return dict(items=items, status='RECORDED' if items else 'EMPTY')


def _process_facts(con, name: str, tables: set[str], evidence: Evidence, diagnostics: list,
                   limits: dict) -> dict | None:
    from tm1_insight.store.calculation import inspect
    from tm1_insight.workflow_review import source_declaration
    from tm1_insight import workflow as wf

    row = con.execute('SELECT prolog,metadata,data,epilog,parameters FROM processes WHERE name=?', [name]).fetchone()
    if row is None:
        return None
    parts = tuple(value or '' for value in row[:4])
    declaration = source_declaration(con, name)
    params = _parameter_details(con, name, tables, parts)
    declaration_ref = evidence.add('TI_DATASOURCE_DECLARATION', name,
                                   declared_type=(declaration or {}).get('type'),
                                   status=(declaration or {}).get('status'),
                                   cube=(declaration or {}).get('cube'),
                                   view=(declaration or {}).get('view'),
                                   locations=(declaration or {}).get('evidence') or [],
                                   note=(declaration or {}).get('reason'))
    try:
        report = inspect(con, name)
    except Exception as exc:  # noqa: BLE001  # 单个 TI 失败不能毁掉整份档案
        diagnostics.append(dict(stage='ti_analysis', object=name, severity='error',
                                message='TI 分析失败：' + type(exc).__name__ + '：' + str(exc)[:300]))
        return dict(name=name, report=None, declaration=declaration, parameters=params,
                    declaration_ref=declaration_ref, nodes={}, writes=[], write_total=0,
                    datasource_state='UNKNOWN', error='ANALYZER_FAILED',
                    variables=dict(items=[], total=0, layout_status='UNKNOWN', view=None, cube=None,
                                   membership_status='UNKNOWN', coordinate_mapping=[], reasons=[],
                                   note=None))
    for message in (report or {}).get('diagnostics', [])[:40]:
        diagnostics.append(dict(stage='ti_parser', object=name, severity='warning',
                                message=str(message)[:500]))
    nodes = {n['id']: n for n in (report or {}).get('nodes', [])}
    writes = (report or {}).get('writes', [])
    if len(writes) > limits['write_points']:
        diagnostics.append(dict(stage='write_budget', object=name, severity='warning',
                                message='写入点 %d 项，仅输出前 %d 项。' % (len(writes), limits['write_points'])))
    # A process with no DataSourceType statement and no recorded source is simply
    # a non-loading process; it must not be reported as an unresolved source.
    source_text = ' '.join(parts).casefold()
    declared = (declaration or {})
    declared_type = str(declared.get('type') or 'UNKNOWN').upper()
    # A recorded datasource type is a declaration even when the Cube/View could
    # not be bound; only a truly absent declaration is "no datasource".
    if declared.get('cube') or declared.get('external_type') or declared_type not in {'UNKNOWN', 'NONE', ''}:
        datasource_state = 'DECLARED'
    elif 'datasourcetype' in source_text:
        datasource_state = 'DECLARED_UNRESOLVED'
    else:
        datasource_state = 'NONE'
    facts = dict(name=name, report=report, declaration=declaration, parameters=params,
                 declaration_ref=declaration_ref, nodes=nodes, writes=writes[:limits['write_points']],
                 write_total=len(writes), datasource_state=datasource_state, error=None)
    facts['variables'] = _variables(con, facts, evidence)
    return facts


def _dataset_row_binding(report: dict) -> dict:
    return report.get('data_row_lineage') or {}


def _variables(con, facts: dict, evidence: Evidence) -> dict:
    """Expose recorded Variables and the layout status, never a name-based guess."""
    report = facts.get('report') or {}
    context = _dataset_row_binding(report)
    binding = context.get('source_view_binding') or {}
    variables = []
    for variable in context.get('data_source_variable_bindings', []):
        field = variable.get('source_field') or {}
        ref = evidence.add('DATASOURCE_VARIABLE', facts['name'],
                           variable=variable['name'], type=variable['type'], position=variable['position'],
                           start_byte=variable.get('start_byte'), end_byte=variable.get('end_byte'),
                           layout_status=binding.get('row_layout_status'),
                           field_kind=field.get('kind'), field_dimension=field.get('dimension'))
        variables.append(dict(name=variable['name'], type=variable['type'], position=variable['position'],
                              start_byte=variable.get('start_byte'), end_byte=variable.get('end_byte'),
                              definition_status=variable.get('definition_status'),
                              position_status=variable.get('position_status'),
                              source_field_kind=field.get('kind'),
                              source_dimension=field.get('dimension'),
                              source_field_status=variable.get('source_field_status'),
                              evidence_refs=evidence.refs(ref)))
    return dict(items=variables, total=len(variables),
                layout_status=binding.get('row_layout_status', 'UNKNOWN'),
                view=binding.get('view'), cube=binding.get('cube'),
                membership_status=binding.get('membership_status', 'UNKNOWN'),
                coordinate_mapping=context.get('source_coordinate_mapping', []),
                reasons=[str(r) for r in context.get('unresolved_binding_reasons', [])][:12],
                note=binding.get('note'))


def _coordinate_rows(write: dict, evidence: Evidence, process: str) -> tuple[list[dict], str]:
    mapping = write.get('coordinate_mapping') or {}
    rows = []
    for item in mapping.get('items', []):
        bound = item.get('binding') or {}
        kind = bound.get('kind', 'UNRESOLVED')
        if kind == 'FIXED_MEMBER':
            value = bound.get('value')
            provenance = PROVENANCE['SOURCE']
        elif kind in {'PARAMETER', 'DATA_ROW_VARIABLE', 'NUMBER'}:
            value = bound.get('expression')
            provenance = PROVENANCE['SOURCE']
        elif kind == 'LOOKUP_COORDINATE':
            value = bound.get('expression')
            provenance = PROVENANCE['INFERENCE']
        else:
            value = bound.get('expression') or bound.get('reason') or '未解析'
            provenance = PROVENANCE['UNKNOWN']
        ref = evidence.add('WRITE_COORDINATE', process, write_id=write['id'],
                           position=item.get('position'), dimension=item.get('dimension'),
                           binding_kind=kind, value=str(value)[:200],
                           location=_location(write.get('evidence')))
        rows.append(dict(position=item.get('position'), dimension=item.get('dimension'),
                         dimension_exists=item.get('dimension_exists'), binding_kind=kind,
                         value=value, provenance=provenance,
                         member_evidence=bound.get('member_evidence'),
                         evidence_refs=evidence.refs(ref)))
    status = 'COMPLETE' if mapping.get('status') == 'recorded_order' and all(
        row['binding_kind'] not in {'UNRESOLVED'} for row in rows) else 'UNKNOWN'
    if mapping.get('status') != 'recorded_order':
        status = 'UNKNOWN'
    elif any(row['binding_kind'] == 'UNRESOLVED' for row in rows):
        status = 'PARTIAL'
    return rows, status


def _field_mapping(write: dict, coordinates: list[dict], variables: dict, evidence: Evidence,
                   process: str) -> list[dict]:
    """Join recorded source columns with target coordinate bindings.

    No positional guessing: a dimension mapping exists only when a target
    coordinate is bound to a Data row variable AND that variable's recorded
    source column is a dimension member of the source NativeView.
    """
    rows = []
    by_name = {v['name']: v for v in variables.get('items', [])}
    source_cube = variables.get('cube')
    for coordinate in coordinates:
        if coordinate['binding_kind'] != 'DATA_ROW_VARIABLE':
            continue
        name = str(coordinate['value']).strip('“”"\'')
        variable = by_name.get(name)
        if not variable or variable.get('source_field_kind') != 'DIMENSION_MEMBER':
            continue
        ref = evidence.add('FIELD_TO_COORDINATE', process, write_id=write['id'],
                           source_cube=source_cube, source_dimension=variable.get('source_dimension'),
                           variable=name, target_dimension=coordinate['dimension'],
                           target_position=coordinate['position'],
                           basis='NATIVE_VIEW_LAYOUT_AND_RECORDED_CUBE_ORDER')
        rows.append(dict(source_cube=source_cube, source_view=variables.get('view'),
                         source_dimension=variable.get('source_dimension'), source_variable=name,
                         source_column=variable.get('position'),
                         target_dimension=coordinate['dimension'],
                         target_position=coordinate['position'],
                         basis='NATIVE_VIEW_LAYOUT_AND_RECORDED_CUBE_ORDER',
                         provenance=PROVENANCE['INFERENCE'],
                         note='静态列布局对应；不证明成员变换、汇总或实际行数。',
                         evidence_refs=evidence.refs(ref)))
    seen_value = set()
    for dependency in write.get('data_row_value_dependencies') or []:
        field = dependency.get('source_field') or {}
        if field.get('kind') != 'CELL_VALUE':
            continue
        variable = dependency.get('variable')
        if variable in seen_value:
            continue
        seen_value.add(variable)
        ref = evidence.add('VALUE_FIELD_TO_WRITE', process, write_id=write['id'],
                           source_cube=dependency.get('source_cube'), variable=variable,
                           basis='ENDMOST_VALUE_COLUMN')
        rows.append(dict(source_cube=dependency.get('source_cube'),
                         source_view=dependency.get('source_view'),
                         source_dimension=None, source_variable=variable,
                         source_column=by_name.get(variable, {}).get('position'),
                         target_dimension=None, target_position=None, target='写入值',
                         basis='ENDMOST_VALUE_COLUMN', provenance=PROVENANCE['INFERENCE'],
                         note='末列值字段进入写入值表达式；字符串/数值转换与聚合未验证。',
                         evidence_refs=evidence.refs(ref)))
    return rows


def _write_projections(facts: dict, evidence: Evidence) -> list[dict]:
    report = facts.get('report') or {}
    nodes = facts.get('nodes') or {}
    variables = facts.get('variables') or {}
    reads_by_id = {n['id']: n for n in report.get('nodes', []) if n.get('kind') == 'read'}
    results = []
    for write in facts['writes']:
        operation = (write.get('operation') or 'UNKNOWN')
        mode, mode_label = WRITE_MODES.get(operation.casefold(), ('UNKNOWN', '未支持或未分类'))
        coordinates, coordinate_status = _coordinate_rows(write, evidence, facts['name'])
        field_mapping = _field_mapping(write, coordinates, variables, evidence, facts['name'])
        confirmed_reads, confirmed_rows = workflow.confirmed_write_sources(write, reads_by_id)
        conditions = []
        for item in write.get('control_context') or []:
            ref = evidence.add('WRITE_CONDITION', facts['name'], write_id=write['id'],
                               condition_kind=item.get('kind'), condition=item.get('condition'),
                               section=item.get('section'), line=item.get('line'))
            conditions.append(dict(kind=item.get('kind'), condition=item.get('condition'),
                                   location={'section': item.get('section'), 'line': item.get('line')},
                                   note=item.get('note'), evaluated=False,
                                   evidence_refs=evidence.refs(ref)))
        assignments = []
        for index in (write.get('definition_nodes') or [])[:12]:
            node = nodes.get(index)
            if not node:
                continue
            ref = evidence.add('VALUE_DEFINITION', facts['name'], write_id=write['id'],
                               variable=node.get('variable'), expression=node.get('expression'),
                               location=_location(node.get('evidence')))
            assignments.append(dict(variable=node.get('variable'), expression=node.get('expression'),
                                    location=node.get('evidence') or {},
                                    evidence_refs=evidence.refs(ref)))
        unresolved = []
        for index in (write.get('unknown_nodes') or [])[:12]:
            node = nodes.get(index) or {}
            unresolved.append(dict(kind=node.get('kind'), name=node.get('name'),
                                   reason=node.get('reason') or '对象尚未解析'))
        for reason in write.get('unresolved_binding_reasons') or []:
            unresolved.append(dict(kind='binding', name=None, reason=str(reason)[:400]))
        location = write.get('evidence') or {}
        ref = evidence.add('TI_WRITE', facts['name'], write_id=write['id'], cube=write.get('cube'),
                           operation=operation, mode=mode, section=location.get('section'),
                           line=location.get('line'), column=location.get('column'),
                           coordinate_status=coordinate_status, trace_status=write.get('trace_status'))
        results.append(dict(write_id='%s#%s' % (facts['name'], write['id']), process=facts['name'],
                            cube=write.get('cube'), operation=operation, mode=mode, mode_label=mode_label,
                            value_expression=write.get('value_expression'),
                            formula_expression=write.get('formula_expression'),
                            coordinates=coordinates, coordinate_status=coordinate_status,
                            conditions=conditions, assignments=assignments,
                            field_mapping=field_mapping,
                            data_row_status=write.get('data_row_binding_status'),
                            source_reads=[dict(cube=r.get('cube'), operation=r.get('operation'),
                                               coordinates=(r.get('coordinate_mapping') or {}).get('items'),
                                               evidence=_location(r.get('evidence')))
                                          for r in confirmed_reads],
                            row_value_dependencies=[dict(variable=r.get('variable'),
                                                         source_cube=r.get('source_cube'),
                                                         source_field=(r.get('source_field') or {}).get('kind'),
                                                         field_dimension=(r.get('source_field') or {}).get('dimension'))
                                                    for r in confirmed_rows],
                            unresolved=unresolved,
                            location=dict(section=location.get('section'), line=location.get('line'),
                                          column=location.get('column')),
                            trace_status=write.get('trace_status'), runtime_verified=False,
                            evidence_refs=evidence.refs(ref)))
    return results


def _sequence(facts: dict, writes: list[dict], evidence: Evidence) -> list[dict]:
    """Source-ordered actions inside one TI. Never a runtime order claim."""
    report = facts.get('report') or {}
    actions = []
    for node in report.get('nodes', []):
        if node.get('kind') != 'read':
            continue
        location = node.get('evidence') or {}
        actions.append((SECTION_ORDER.get(location.get('section'), 9), location.get('line') or 0,
                        location.get('column') or 0, 'READ',
                        '读取 %s' % (node.get('cube') or '未知 Cube'),
                        dict(cube=node.get('cube'), resolution=node.get('resolution'))))
    for observation in report.get('observations', []):
        from tm1_insight.architecture import OPERATIONS, LABELS
        category = OPERATIONS.get((observation.get('operation') or '').casefold())
        if category is None or category in {'DATA_TRANSFORMATION', 'OTHER'}:
            continue
        location = observation
        actions.append((SECTION_ORDER.get(location.get('section'), 9), location.get('line') or 0,
                        location.get('column') or 0, category,
                        '%s：%s' % (LABELS.get(category, category), observation.get('target') or observation.get('operation')),
                        dict(target=observation.get('target'))))
    for item in facts.get('writes', []):
        location = item.get('evidence') or {}
        mode = WRITE_MODES.get((item.get('operation') or '').casefold(), ('UNKNOWN', '未分类'))[1]
        actions.append((SECTION_ORDER.get(location.get('section'), 9), location.get('line') or 0,
                        location.get('column') or 0, 'WRITE',
                        '%s → %s' % (mode, item.get('cube') or '未知 Cube'),
                        dict(cube=item.get('cube'))))
    for call in report.get('calls', []):
        actions.append((SECTION_ORDER.get(call.get('section'), 9), call.get('line') or 0,
                        call.get('column') or 0, 'CALL',
                        '调用 %s' % (call.get('target') or '动态目标待确认'),
                        dict(target=call.get('target'))))
    actions.sort(key=lambda a: (a[0], a[1], a[2], a[3]))
    rows = []
    for index, action in enumerate(actions[:60]):
        ref = evidence.add('TI_SOURCE_ACTION', facts['name'], action_kind=action[3],
                           section=('prolog', 'metadata', 'data', 'epilog')[action[0]]
                           if action[0] < 4 else 'source',
                           line=action[1], column=action[2], description=action[4])
        rows.append(dict(order=index + 1, kind=action[3], description=action[4],
                         detail=action[5], location=dict(
                             section=('prolog', 'metadata', 'data', 'epilog')[action[0]] if action[0] < 4 else 'source',
                             line=action[1], column=action[2]),
                         order_basis='SOURCE_LOCATION_ORDER', evidence_refs=evidence.refs(ref)))
    return rows


# ---------------------------------------------------------------------------
# Cube and rule projection
# ---------------------------------------------------------------------------

def _cube_model(con, cube: str, evidence: Evidence, tables: set[str], role: str) -> dict:
    dims = con.execute('SELECT dimension_name,dim_order FROM cube_has_dimension WHERE cube_name=? '
                       'ORDER BY dim_order', [cube]).fetchall()
    declared = con.execute('SELECT dimension_count,length(coalesce(rules,\'\')),has_rules FROM cubes WHERE name=?',
                           [cube]).fetchone()
    order = [row[0] for row in dims]
    complete = bool(declared and declared[0] == len(order) and len(set(order)) == len(order)
                    and [row[1] for row in dims] == list(range(len(order))))
    model_ref = evidence.add('CUBE_STRUCTURE', cube, dimension_order=order, declared_count=declared[0] if declared else None,
                             order_status='RECORDED_COMPLETE' if complete else 'INCOMPLETE')
    dimensions = []
    for name, position in dims:
        meta = dimension_store.metadata(con, name) or {}
        fields = meta.get('fields') or {}
        attribute_names = []
        if fields.get('attributes', {}).get('status') == 'recorded':
            try:
                page = dimension_store.records(con, name, 'attributes', page=1)
                attribute_names = [item.get('name') for item in page.get('items', []) if item.get('name')][:10]
            except Exception:  # noqa: BLE001
                attribute_names = []
        hierarchies = []
        if 'dimension_metadata' in tables:
            row = con.execute("SELECT hierarchy_names FROM dimension_metadata WHERE name=?", [name]).fetchone()
            if row and row[0]:
                try:
                    value = json.loads(row[0])
                    hierarchies = [str(x) for x in value][:20] if isinstance(value, list) else []
                except (ValueError, TypeError):
                    hierarchies = []
        ref = evidence.add('DIMENSION_METADATA', name, cube=cube, position=position,
                           element_count=(meta.get('element_count')),
                           attributes=fields.get('attributes'), edges=fields.get('edges'),
                           hierarchies=hierarchies)
        grain = 'RECORDED_ELEMENTS_ONLY' if fields.get('elements', {}).get('status') == 'recorded' else 'UNKNOWN'
        dimensions.append(dict(name=name, position=position + 1, recorded_dim_order=position,
                               element_count=meta.get('element_count'),
                               attributes=dict(status=fields.get('attributes', {}).get('status', 'UNKNOWN'),
                                               count=fields.get('attributes', {}).get('count'),
                                               names=attribute_names),
                               hierarchies=hierarchies,
                               hierarchy_status='RECORDED_NAMES_ONLY' if hierarchies else 'NOT_COLLECTED',
                               consolidation=dict(status=fields.get('edges', {}).get('status', 'UNKNOWN'),
                                                  count=fields.get('edges', {}).get('count')),
                               grain_status=grain,
                               grain_note=('仅记录元素清单；每维度唯一粒度层级、权重与汇总未验证。'
                                           if grain != 'UNKNOWN' else '元素/层级未采集，粒度不可确认。'),
                               warnings=(meta.get('warnings') or [])[:5],
                               evidence_refs=evidence.refs(ref)))
    references = []
    for source in con.execute('SELECT DISTINCT source_cube FROM rule_references_cube WHERE cube_name=? '
                              'ORDER BY 1 LIMIT 60', [cube]).fetchall():
        ref = evidence.add('RULE_INDEX_REFERENCE', cube, source_cube=source[0],
                           basis='rule_references_cube')
        references.append(dict(kind='RULE_OR_FEEDER_REFERENCE', cube=source[0],
                               basis='INDEX_OBSERVED', evidence_refs=evidence.refs(ref)))
    for process in con.execute('SELECT DISTINCT process_name FROM process_reads_cube WHERE cube_name=? '
                               'ORDER BY 1 LIMIT 60', [cube]).fetchall():
        ref = evidence.add('CUBE_READER', cube, process=process[0])
        references.append(dict(kind='TI_READ', process=process[0], evidence_refs=evidence.refs(ref)))
    for process in con.execute('SELECT DISTINCT process_name FROM process_writes_cube WHERE cube_name=? '
                               'ORDER BY 1 LIMIT 60', [cube]).fetchall():
        ref = evidence.add('CUBE_WRITER', cube, process=process[0])
        references.append(dict(kind='TI_WRITE', process=process[0], evidence_refs=evidence.refs(ref)))
    return dict(name=cube, role=role, dimension_order=order, dimensions=dimensions,
                order_status='RECORDED_COMPLETE' if complete else 'INCOMPLETE',
                declared_dimension_count=declared[0] if declared else None,
                grain_status='ORDER_RECORDED_GRANULARITY_UNVERIFIED' if complete else 'UNKNOWN',
                grain_note=('维度顺序定义坐标粒度；未采集层级/权重时不推断汇总结果，也不把 Cube 等同关系表。'
                            if complete else '维度数量或顺序不完整，写入坐标可能错位。'),
                rule_source_characters=declared[1] if declared else 0,
                has_rules=bool(declared and declared[1]),
                known_references=references,
                evidence_refs=evidence.refs(model_ref))


def _rule_projections(con, cube: str, evidence: Evidence, limit: int, diagnostics: list) -> dict:
    parsed = cube_rule_semantics(con, cube)
    if not parsed.get('available'):
        return dict(rules=[], feeders=[], areas=[], directives=[], unknowns=[
            dict(reason=str(parsed.get('reason') or 'Cube 不在当前范围'), status='UNKNOWN')], total=0)
    if parsed.get('error'):
        diagnostics.append(dict(stage='rule_parser', object=cube, severity='error',
                                message='Rule 解析失败：' + str(parsed['error'])[:300]))
        return dict(rules=[], feeders=[], areas=[], directives=[], unknowns=[
            dict(reason='Rule 解析器异常，计算结构未知', status='UNKNOWN')], total=0)
    source_hash = parsed.get('source_hash')
    rules, feeders, areas = [], [], []
    for item in parsed.get('rules', [])[:limit]:
        coordinates = (item.get('lhs') or {}).get('coordinates') or []
        area = dict(raw=(item.get('lhs') or {}).get('raw'), coordinates=[
            dict(kind=c.get('kind'), dimension=c.get('dimension'), declared_dimension=c.get('declared_dimension'),
                 member=c.get('member'), members=c.get('members'), raw=c.get('raw'), status=c.get('status'))
            for c in coordinates])
        refs = []
        for db in item.get('db_references', []):
            ref = evidence.add('RULE_REFERENCE', cube, source_hash=source_hash, line=item.get('line_start'),
                               target_cube=db.get('cube'), cube_resolved=db.get('cube_resolved'),
                               coordinates=db.get('coordinates'))
            refs.append(dict(cube=db.get('cube'), cube_resolved=db.get('cube_resolved'),
                             coordinates=db.get('coordinates'), line=db.get('line'),
                             evidence_refs=evidence.refs(ref)))
        ref = evidence.add('RULE_TARGET', cube, source_hash=source_hash,
                           line_start=item.get('line_start'), line_end=item.get('line_end'),
                           area_raw=area.get('raw'), qualifier=item.get('qualifier'),
                           expression=(item.get('rhs') or {}).get('expression'), status=item.get('status'))
        rules.append(dict(line_start=item.get('line_start'), line_end=item.get('line_end'),
                          area=area, qualifier=item.get('qualifier'),
                          rhs_kind=item.get('rhs_kind'),
                          expression=(item.get('rhs') or {}).get('expression'),
                          special=item.get('special'), references=refs,
                          conditions=(item.get('conditions') or [])[:8],
                          attribute_calls=(item.get('attribute_calls') or [])[:8],
                          status=item.get('status'),
                          unresolved_reasons=[str(x)[:300] for x in (item.get('unresolved_reasons') or [])][:8],
                          runtime_verified=False, evidence_refs=evidence.refs(ref)))
        areas.append(dict(line_start=item.get('line_start'), raw=area.get('raw'),
                          coordinate_status='PARTIAL' if any(c.get('dimension') is None for c in area['coordinates']) else 'PARSED',
                          unresolved=sum(c.get('dimension') is None for c in area['coordinates'])))
    for item in parsed.get('feeders', [])[:limit]:
        refs = []
        for db in item.get('db_references', []):
            ref = evidence.add('FEEDER_REFERENCE', cube, source_hash=source_hash, line=item.get('line_start'),
                               target_cube=db.get('cube'), cube_resolved=db.get('cube_resolved'))
            refs.append(dict(cube=db.get('cube'), cube_resolved=db.get('cube_resolved'),
                             evidence_refs=evidence.refs(ref)))
        ref = evidence.add('FEEDER', cube, source_hash=source_hash, line_start=item.get('line_start'),
                           source_area=(item.get('source_area') or {}).get('raw'),
                           target_area=(item.get('target_area') or {}).get('raw'))
        feeders.append(dict(line_start=item.get('line_start'),
                            source_area=(item.get('source_area') or {}).get('raw'),
                            target_area=(item.get('target_area') or {}).get('raw'),
                            references=refs, status=item.get('status'),
                            unresolved_reasons=[str(x)[:300] for x in (item.get('unresolved_reasons') or [])][:8],
                            note='Feeder 只声明稀疏计算支持关系，不直接产生业务数值。',
                            runtime_verified=False, evidence_refs=evidence.refs(ref)))
    total = len(parsed.get('rules', [])) + len(parsed.get('feeders', []))
    if len(parsed.get('rules', [])) > limit or len(parsed.get('feeders', [])) > limit:
        diagnostics.append(dict(stage='rule_budget', object=cube, severity='warning',
                                message='Rule/Feeder 超过 %d 条展示预算，其余未输出。' % limit))
    return dict(rules=rules, feeders=feeders, areas=areas,
                directives=parsed.get('directives', [])[:20],
                unknowns=[dict(reason=str(x.get('reason'))[:300], line=x.get('line'), kind=x.get('kind'))
                          for x in (parsed.get('unknowns') or [])][:20],
                source_hash=source_hash, total=total)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build(con, scope: Scope, progress=None) -> dict:
    tables = _tables(con)
    catalogs = _catalogs(con)
    snapshot = scope.snapshot_id or 'local'
    evidence = Evidence(snapshot, scope.max_evidence)
    diagnostics: list[dict] = []
    gaps: list[dict] = []
    gap_keys = set()

    def tick(stage, index, current=0, total=None):
        if progress:
            progress(stage=stage, stage_index=index, stages_total=6, current=current, total=total)

    def gap(obj, obj_type, section, code, reason, impact, verification, refs=(), severity='warning'):
        key = (obj, code, reason)
        if key in gap_keys:
            return
        gap_keys.add(key)
        gaps.append(dict(gap_id='GAP-%03d' % (len(gaps) + 1), object=obj, object_type=obj_type,
                         section=section, code=code, reason=reason, impact=impact,
                         verification=verification, severity=severity,
                         provenance=PROVENANCE['UNKNOWN'], evidence_refs=evidence.refs(*refs)))

    tick('核对入口与候选范围', 1)
    discovery = discover(con, scope)
    membership = resolve_membership(scope, discovery)
    for name in discovery['catalog_missing']:
        gap(name, 'object', 'scope', 'OBJECT_NOT_IN_SNAPSHOT',
            '当前快照不包含该对象', '无法核对实现或结构', '切回正确快照或重新采集该对象',
            severity='error')
    for name in membership['budget_dropped']:
        gap(name, 'process', 'scope', 'PROCESS_BUDGET_DROPPED',
            '候选 TI 超过进程预算，未纳入分析', '档案不覆盖该 TI 的实现',
            '提高进程预算或单独生成该 TI 的档案')
    for item in membership['excluded_candidates']:
        ref = evidence.add('USER_EXCLUSION', item['name'], type=item['type'],
                           reasons=item['reasons'], bases=item['bases'])
        gap(item['name'], item['type'], 'scope', 'EXCLUDED_BY_USER',
            '用户排除该对象（原因：%s）' % '、'.join(item['reasons']),
            '该对象自身的实现与副作用不在档案内；与之相关的依赖仍然保留告警',
            '确认排除是否成立；如相关，请重新纳入后再解读依赖', evidence.refs(ref),
            severity='info')

    targets = list(discovery['target_cubes'])
    if scope.entry_kind == 'cube' and scope.entry not in targets:
        targets.append(scope.entry)

    facts: list[dict] = []
    tick('分析 TI 声明、变量与写入', 2)
    for index, name in enumerate(membership['processes']):
        item = _process_facts(con, name, tables, evidence, diagnostics,
                              dict(write_points=scope.max_write_points))
        if item is None:
            gap(name, 'process', 'data_sources', 'PROCESS_MISSING',
                '流程目录中不存在该 TI', '无法分析其数据来源与写入', '核对对象名与快照范围', severity='error')
            continue
        if item.get('error'):
            gap(name, 'process', 'data_sources', 'ANALYZER_FAILED',
                '现有 TI 分析器未能完成该流程', '该流程的写入与依赖未进入档案',
                '单独检查该 TI 的语法与预算；不要据名称补全', severity='error')
        facts.append(item)
        tick('分析 TI 声明、变量与写入', 2, index + 1, len(membership['processes']))
    fact_by_name = {f['name']: f for f in facts}

    # Reads and written cubes come from the existing worksheet, never from names.
    reads: set[str] = set()
    writes: set[str] = set()
    for item in facts:
        report = item.get('report') or {}
        for node in report.get('nodes', []):
            if node.get('kind') == 'read' and node.get('cube'):
                reads.add(node['cube'])
        # A recorded VIEW datasource is a real source structure even though it
        # never appears as a CellGetN node.
        declared_cube = (item.get('declaration') or {}).get('cube')
        if declared_cube:
            reads.add(declared_cube)
        for write in item.get('writes', []):
            if write.get('cube'):
                writes.add(write['cube'])
    scope_cubes = sorted(set(targets) | writes | (reads & writes) | reads | set(membership['cubes']))
    # Keep the model bounded: reads/writes beyond the object budget stay as gaps.
    if len(scope_cubes) > CORE_BUDGET['objects'][1]:
        for name in scope_cubes[CORE_BUDGET['objects'][1]:]:
            gap(name, 'cube', 'data_model', 'CUBE_BUDGET',
                'Cube 数量超过档案预算，未展开结构', '该 Cube 的维度与 Rule 未纳入档案',
                '缩小范围或单独为相关 Cube 建档')
        scope_cubes = scope_cubes[:CORE_BUDGET['objects'][1]]

    target_writers = {w['cube'] for item in facts for w in item.get('writes', []) if w.get('cube')}
    target_set = set(targets) | target_writers

    tick('组装 Cube 与维度事实', 3)
    models = []
    rules, feeders, rule_areas, directives, rule_unknowns = [], [], [], [], []
    analyzed_rules: set[str] = set()
    for index, cube in enumerate(scope_cubes):
        if cube not in catalogs['cube']:
            gap(cube, 'cube', 'data_model', 'CUBE_NOT_IN_SNAPSHOT',
                '当前快照不包含该 Cube', '无法确认维度顺序与 Rule', '重新采集该 Cube 结构', severity='error')
            continue
        role = ('TARGET' if cube in target_set else
                'SOURCE' if cube in reads else 'REFERENCE')
        model = _cube_model(con, cube, evidence, tables, role)
        models.append(model)
        if not model['has_rules']:
            # Empty rules can mean "no Rule" or "not collected". Never decide
            # which one from an empty string.
            gap(cube, 'cube', 'rules', 'RULE_SOURCE_NOT_RECORDED',
                '本快照未记录该 Cube 的 Rule 源码（has_rules=false）',
                '不能据此断定该 Cube 没有 Rule；若存在 Rule，计算关系缺失',
                '在源模型中确认该 Cube 是否有 Rule，并补采其源码',
                model['evidence_refs'], severity='info')
            continue
        parsed = _rule_projections(con, cube, evidence, scope.max_rules, diagnostics)
        analyzed_rules.add(cube)
        rules.extend([dict(cube=cube, **item) for item in parsed['rules']])
        feeders.extend([dict(cube=cube, **item) for item in parsed['feeders']])
        rule_areas.extend([dict(cube=cube, **item) for item in parsed['areas']])
        directives.extend([dict(cube=cube, **item) for item in parsed.get('directives', [])])
        for unknown in parsed['unknowns']:
            rule_unknowns.append(dict(cube=cube, **unknown))
        # Per-line gaps come first so a cube-level duplicate of the same reason
        # never hides where the gap actually is.
        covered: set[str] = set()
        for item in parsed['rules']:
            for why in item['unresolved_reasons']:
                covered.add(str(why))
                gap(cube, 'cube', 'rules', 'RULE_PARTIAL',
                    '第 %s–%s 行：%s' % (item['line_start'], item['line_end'], why),
                    '该条 Rule 的完整区域或表达式未确认', '核对该行源码与成员索引', item['evidence_refs'])
            for reference in item['references']:
                if reference.get('cube_resolved') is False or not reference.get('cube'):
                    gap(cube, 'cube', 'rules', 'RULE_DYNAMIC_REFERENCE',
                        'Rule 引用了未解析的 Cube 名（动态表达式）',
                        '跨 Cube 依赖与目标坐标不完整', '确认该 DB() 参数的取值来源', item['evidence_refs'])
                elif reference['cube'] not in scope_cubes:
                    gap(cube, 'cube', 'rules', 'RULE_REFERENCE_OUTSIDE_SCOPE',
                        'Rule 引用范围外 Cube：%s' % reference['cube'],
                        '该引用 Cube 的结构未纳入本档案', '必要时显式纳入该 Cube', item['evidence_refs'])
        for item in parsed['feeders']:
            for why in item['unresolved_reasons']:
                covered.add(str(why))
                gap(cube, 'cube', 'feeders', 'FEEDER_PARTIAL',
                    '第 %s 行：%s' % (item['line_start'], why),
                    'Feeder 目标区域未完全确认', '核对该行源码与区域成员', item['evidence_refs'])
        for reference in parsed['feeders']:
            for target in reference['references']:
                if target.get('cube_resolved') is False:
                    gap(cube, 'cube', 'feeders', 'FEEDER_DYNAMIC_REFERENCE',
                        'Feeder 目标 Cube 未解析', '稀疏支持范围不确定', '确认 Feeder 目标表达式', reference['evidence_refs'])
        for unknown in parsed['unknowns']:
            reason = str(unknown.get('reason'))
            if reason in covered:
                continue
            gap(cube, 'cube', 'rules', 'RULE_UNRESOLVED', reason,
                '部分 Rule/Feeder 计算结构未确认', '按 Rule 行号核对成员归属、动态坐标与函数支持')
        tick('组装 Cube 与维度事实', 3, index + 1, len(scope_cubes))

    for cube in scope_cubes:
        row = con.execute('SELECT length(coalesce(rules,\'\')) FROM cubes WHERE name=?', [cube]).fetchone()
        if row and row[0] and cube not in analyzed_rules:
            gap(cube, 'cube', 'rules', 'RULE_NOT_ANALYZED',
                '该 Cube 有 Rule 源码但不在本次规则分析范围',
                '计算关系未纳入档案', '提高规则预算或单独为该 Cube 分析 Rule')

    tick('整理逐步转换与目标结果', 4)
    steps, results = [], []
    depth = _depths(scope, facts)
    ordered = sorted(facts, key=lambda f: (depth.get(f['name'], 99), f['name']))
    for index, item in enumerate(ordered):
        projected = _write_projections(item, evidence)
        for write in projected:
            write['result_id'] = 'RES-%03d' % (len(results) + 1)
            results.append(write)
        sequence = _sequence(item, projected, evidence)
        report = item.get('report') or {}
        sources = []
        for node in report.get('nodes', []):
            if node.get('kind') == 'read' and node.get('cube') and node['cube'] not in sources:
                sources.append(node['cube'])
        declared_cube = (item.get('declaration') or {}).get('cube')
        if declared_cube and declared_cube not in sources:
            sources.insert(0, declared_cube)
        no_source = item.get('datasource_state') == 'NONE'
        step_ref = evidence.add('TRANSFORMATION_STEP', item['name'], depth=depth.get(item['name'], 0),
                                inputs=sorted(sources), outputs=sorted({w['cube'] for w in projected if w['cube']}))
        steps.append(dict(step_id='STEP-%02d' % (index + 1), process=item['name'],
                          depth=depth.get(item['name'], 0),
                          technical=item['name'].startswith('}'),
                          declared_role=('TECHNICAL_NAMESPACE' if item['name'].startswith('}') else 'APPLICATION'),
                          datasource=dict(type='NONE' if no_source else (item['declaration'] or {}).get('type'),
                                          cube=(item['declaration'] or {}).get('cube'),
                                          view=(item['declaration'] or {}).get('view'),
                                          status=('NO_DATASOURCE_RECORDED' if no_source
                                                  else (item['declaration'] or {}).get('status'))),
                          inputs=sorted(sources),
                          outputs=sorted({w['cube'] for w in projected if w['cube']}),
                          write_points=len(projected),
                          sequence=sequence,
                          order_basis='SOURCE_LOCATION_ORDER_WITHIN_TI',
                          cross_process_order='STATIC_CALL_DEPTH_NOT_RUNTIME_ORDER',
                          evidence_refs=evidence.refs(step_ref) +
                          [ref for write in projected for ref in write['evidence_refs'][:1]][:6]))
        for write in projected:
            if write['coordinate_status'] != 'COMPLETE':
                gap(item['name'], 'process', 'target_results', 'COORDINATE_UNRESOLVED',
                    '写入 %s → %s 的目标坐标未完整确认（%s）' % (write['operation'], write['cube'], write['coordinate_status']),
                    '实际写入的成员范围不确定', '核对目标维度顺序、动态坐标与成员目录', write['evidence_refs'])
            for reason in write['unresolved']:
                gap(item['name'], 'process', 'target_results', 'WRITE_VALUE_UNRESOLVED',
                    '写入值或依赖未解析：%s' % (reason.get('reason') or reason.get('kind')),
                    '该写入点无法给出完整公式', '核对该位置的变量定义链与来源字段', write['evidence_refs'])
            if write['conditions']:
                gap(item['name'], 'process', 'target_results', 'CONDITION_NOT_EVALUATED',
                    '写入受条件/循环控制但未求值：%s' % '；'.join(
                        (c.get('condition') or c.get('kind') or '')[:80] for c in write['conditions'])[:300],
                    '不能确认实际写入次数与哪一行会执行', '用覆盖该条件的测试夹具验证可达性',
                    write['evidence_refs'])
        tick('整理逐步转换与目标结果', 4, index + 1, len(ordered))

    tick('整理数据来源、调用与缺口', 5)
    data_sources = []
    for item in sorted(facts, key=lambda f: f['name']):
        row_context = _dataset_row_binding(item.get('report') or {})
        variables = item.get('variables') or _variables(con, item, evidence)
        declaration = item.get('declaration') or {}
        parameters = item.get('parameters') or {}
        state = item.get('datasource_state', 'UNKNOWN')
        if state == 'NONE':
            declaration = dict(declaration, type='NONE', status='NO_DATASOURCE_RECORDED',
                               reason='快照未记录数据源属性，源码中也没有 DataSourceType 赋值；不能据此断定该流程没有数据源。')
            variables = dict(variables, items=[], layout_status='NOT_APPLICABLE',
                             reasons=[], note='该流程没有数据源，因此不存在 Data 行变量。')
        if parameters.get('status') != 'RECORDED' and item.get('report', {}).get('parameter_names'):
            gap(item['name'], 'process', 'data_sources', 'PARAMETER_TYPE_NOT_COLLECTED',
                parameters.get('reason') or '参数类型/默认值未采集',
                '只能列出参数名，无法确认可接受取值范围',
                '用 collect-process-metadata 补采该 TI 的参数定义',
                [item.get('declaration_ref')])
        if state != 'NONE' and not variables['items']:
            for reason in variables['reasons'] or ['变量元数据缺失']:
                gap(item['name'], 'process', 'data_sources', 'VARIABLE_BINDING_MISSING', str(reason),
                    'Data 行字段不能对应到源 Cube 维度或值列',
                    '补采与当前源码哈希一致的 Variables 与 NativeView 布局，不得凭变量名推定',
                    [item.get('declaration_ref')])
        elif variables['items'] and variables['layout_status'] != 'NATIVE_CELL_ROW':
            gap(item['name'], 'process', 'data_sources', 'ROW_LAYOUT_UNKNOWN',
                '行变量已记录，但行布局不满足 NativeView 单元格行契约',
                '源列到 Cube 维度的对应关系不可用', '核对视图类型（Native/MDX）、维度顺序与值列数量',
                [item.get('declaration_ref')])
        if not declaration.get('cube') and declaration.get('external_type'):
            gap(item['name'], 'process', 'data_sources', 'EXTERNAL_SOURCE_FIELDS_UNKNOWN',
                '外部数据源（%s）仅确认类型，未解析路径、SQL 与字段' % declaration.get('external_type'),
                '外部字段到目标坐标的映射缺失', '需要单独采集数据源定义与字段结构', [item.get('declaration_ref')])
        if state == 'NONE' and item.get('writes'):
            gap(item['name'], 'process', 'data_sources', 'SOURCE_NOT_RECORDED',
                '该流程有写入，但快照未记录数据源属性，源码也没有 DataSourceType 赋值',
                '写入值的来源（视图/文件/SQL）与字段映射无法追溯',
                '补采该 TI 的数据源属性与 Variables，或核对 Prolog 是否动态设置数据源',
                [item.get('declaration_ref')])
        data_sources.append(dict(
            process=item['name'],
            datasource=dict(declared_type=declaration.get('type'),
                            cube=declaration.get('cube'), view=declaration.get('view'),
                            status=declaration.get('status'),
                            external_type=declaration.get('external_type'),
                            binding_locations=declaration.get('evidence') or [],
                            note=declaration.get('reason'),
                            provenance=PROVENANCE['SOURCE'],
                            evidence_refs=evidence.refs(item.get('declaration_ref'))),
            variables=variables,
            parameters=dict(items=parameters.get('items', []), status=parameters.get('status'),
                            reason=parameters.get('reason'),
                            declared_names=(item.get('report') or {}).get('parameter_names') or [],
                            note='参数值属于运行时输入；档案只记录声明。'),
            source_cubes=sorted({n['cube'] for n in (item.get('report') or {}).get('nodes', [])
                                 if n.get('kind') == 'read' and n.get('cube')}),
            target_cubes=sorted({w['cube'] for w in item.get('writes', []) if w.get('cube')}),
            row_context=dict(membership_status=(row_context.get('source_view_binding') or {}).get('membership_status'),
                             note='行集合（Subset 成员、MDX、隐式切片器）未求值。')))

    calls = []
    call_targets: set[str] = set()
    for item in sorted(facts, key=lambda f: f['name']):
        report = item.get('report') or {}
        for call in report.get('calls', []):
            location = dict(section=call.get('section'), line=call.get('line'), column=call.get('column'))
            ref = evidence.add('PROCESS_CALL', item['name'], callee=call.get('target'),
                               section=location['section'], line=location['line'])
            in_scope = bool(call.get('target') and call['target'] in fact_by_name)
            if call.get('target'):
                call_targets.add(call['target'])
            calls.append(dict(caller=item['name'], callee=call.get('target'),
                              target_expression=(call.get('target_expression') or '')[:200],
                              parameters=[dict(position=index + 1, expression=a.get('expression'),
                                               binding_status='STATIC_NAME_BINDING')
                                          for index, a in enumerate((call.get('arguments') or [])[:10])],
                              conditions=[dict(kind=c.get('kind'), condition=c.get('condition'),
                                               location=dict(section=c.get('section'), line=c.get('line')))
                                          for c in (call.get('control_context') or [])][:6],
                              location=location, in_scope=in_scope,
                              classification='INVOCATION_NOT_DATA_FLOW',
                              runtime_verified=False, evidence_refs=evidence.refs(ref)))
            if not call.get('target'):
                gap(item['name'], 'process', 'execution_calls', 'DYNAMIC_CALL_TARGET',
                    '动态调用目标未确认：%s' % (call.get('target_expression') or 'UNKNOWN'),
                    '被调用流程、参数契约与副作用未知', '核对该位置的调用目标表达式与参数来源',
                    evidence.refs(ref))
            elif call['target'] in {r.name for r in scope.exclude if r.type == 'process'}:
                gap(item['name'], 'process', 'execution_calls', 'EXCLUDED_DEPENDENCY',
                    '调用目标 %s 被用户排除，但调用事实仍然存在' % call['target'],
                    '该被调用流程的实现与副作用未分析；依赖不能因排除而消失',
                    '确认是否重新纳入该 TI，或在档案外单独审查', evidence.refs(ref))
            elif call['target'] not in fact_by_name:
                gap(item['name'], 'process', 'execution_calls', 'CALL_TARGET_OUTSIDE_SCOPE',
                    '调用目标 %s 不在本次分析范围' % call['target'],
                    '被调用流程的实现与参数约束未核对', '显式纳入该 TI 或登记为外部接口',
                    evidence.refs(ref))
    schedules = []
    for item in sorted(facts, key=lambda f: f['name']):
        rows = con.execute('SELECT chore_name,step_order FROM chore_runs_process WHERE process_name=? '
                           'ORDER BY chore_name,step_order LIMIT 21', [item['name']]).fetchall()
        for chore, order in rows:
            ref = evidence.add('CHORE_SCHEDULE', chore, process=item['name'], step_order=order)
            schedules.append(dict(chore=chore, process=item['name'], step_order=order,
                                  note='采集的调度定义；未证明启用状态或实际运行',
                                  evidence_refs=evidence.refs(ref)))
    callers = []
    if scope.entry_kind == 'process':
        rows = con.execute('SELECT caller FROM process_calls_process WHERE callee=? ORDER BY caller LIMIT 21',
                           [scope.entry]).fetchall()
        for (caller,) in rows:
            ref = evidence.add('ENTRY_CALLER', caller, callee=scope.entry)
            callers.append(dict(caller=caller, callee=scope.entry,
                                basis='INDEX_OBSERVED', evidence_refs=evidence.refs(ref)))

    for cube in sorted(analyzed_rules):
        pass

    # Clear/prepare effects are part of "how the result is formed", but a
    # parameter-driven target is not silently attributed to the target cube.
    from tm1_insight.architecture import LABELS, OPERATIONS
    effects = []
    for item in sorted(facts, key=lambda f: f['name']):
        for observation in (item.get('report') or {}).get('observations', []):
            category = OPERATIONS.get((observation.get('operation') or '').casefold())
            if category not in {'CLEAR', 'VIEW_PREPARATION', 'SUBSET_PREPARATION', 'CLEANUP'}:
                continue
            target = observation.get('target')
            if target is not None and target not in target_set:
                continue
            ref = evidence.add('EFFECT_OBSERVATION', item['name'], category=category,
                               operation=observation.get('operation'), target=target,
                               status=observation.get('status'), section=observation.get('section'),
                               line=observation.get('line'))
            effects.append(dict(process=item['name'], category=category,
                                label=LABELS.get(category, category),
                                operation=observation.get('operation'), target=target,
                                target_status='RECORDED_CUBE' if target else 'PARAMETER_DRIVEN_UNKNOWN',
                                location=dict(section=observation.get('section'), line=observation.get('line')),
                                note=('目标是参数表达式，静态未解析；不能据此断定已清空哪个 Cube'
                                      if target is None else '操作目标来自源码静态绑定'),
                                evidence_refs=evidence.refs(ref)))
            if category == 'CLEAR' and target is None:
                gap(item['name'], 'process', 'target_results', 'CLEAR_TARGET_UNRESOLVED',
                    '清空操作（%s）的目标由参数决定，未解析到具体 Cube' % observation.get('operation'),
                    '不能确认目标 Cube 是否先被清空，也就不能推断结果是覆盖还是叠加',
                    '核对调用方传入了哪个 Cube 参数，或在授权环境记录清空前后范围', evidence.refs(ref))
    effects = effects[:40]

    gap(scope.name, 'module', 'verification', 'EXECUTION_ORDER_UNPROVEN',
        '跨独立 TI 的全局执行顺序、重复执行与清空范围未验证',
        '不能据此推断最终数值、幂等性或覆盖结果',
        '在授权测试环境按调用参数、清空成员范围与重复累加建立金标测试')
    gap(scope.name, 'module', 'verification', 'RUNTIME_NOT_VERIFIED',
        '本档案为静态源码与采集模型事实，未执行 TM1',
        '所有公式与映射都不是运行贡献或迁移等价证明',
        '需要隔离环境的运行记录、数值对账与等价测试')
    if evidence.truncated:
        diagnostics.append(dict(stage='evidence_budget', object=scope.name, severity='warning',
                                message='证据条目超过预算，%d 条未登记。' % evidence.truncated))

    tick('生成档案与证据索引', 6)
    model = dict(
        schema_version=VERSION, revision=REVISION,
        module=dict(id=request_id(scope), name=scope.name,
                    analysis_date=date.today().isoformat(), analyst=scope.analyst,
                    user_note=scope.notes, provenance=PROVENANCE['USER'] if scope.notes else None),
        snapshot_ref=snapshot, runtime_verified=False, runtime_checks=0,
        scope=dict(entry=dict(type=scope.entry_kind, name=scope.entry),
                   target_cubes=targets,
                   processes=membership['processes'], cubes=scope_cubes,
                   excluded=membership['excluded'],
                   candidates=discovery['candidates'],
                   budget=dict(max_processes=scope.max_processes,
                               max_write_points=scope.max_write_points,
                               max_rules=scope.max_rules, max_evidence=scope.max_evidence),
                   discovery_basis='PROCESS_CALL_AND_CUBE_ACCESS_RELATIONS',
                   membership_frozen=True),
        data_sources=data_sources, data_model=models,
        transformation_steps=steps, target_results=results, target_effects=effects,
        rules=rules, feeders=feeders, rule_areas=rule_areas,
        rule_directives=directives, rule_unknowns=rule_unknowns,
        execution_calls=sorted(calls, key=lambda c: (c['caller'], (c['location'].get('line') or 0))),
        schedules=schedules, entry_callers=callers,
        verification_gaps=gaps,
        coverage=dict(processes_analyzed=len(facts),
                      processes_in_scope=len(membership['processes']),
                      cubes_modeled=len(models), cubes_with_rules=len(analyzed_rules),
                      write_points=len(results), rules=len(rules), feeders=len(feeders),
                      gaps=len(gaps), evidence=len(evidence.items),
                      runtime_verified=0, complete=False),
        evidence=evidence.items,
        diagnostics=diagnostics,
        statements=dict(
            observation='源码与已采集模型事实，逐项带 EV 编号与 Section/行号。',
            inference='静态推断（本档案中仅用于源列→目标的列布局对应），标注 STATIC_INFERENCE。',
            user='人工说明只出现在 module.user_note 与 analyst 字段，不影响事实。',
            runtime='0 项运行验证；本档案未执行 TI、未读取单元格、未证明数值贡献。',
            unknown='UNKNOWN 与缺口项单列于 verification_gaps，不参与任何确定结论。'),
        limitations=[
            '步骤顺序为 TI 内源码位置顺序；跨 TI 的顺序只是静态调用深度，不是运行顺序。',
            '同名维度不证明同粒度；目标新增维度不证明自动汇总。',
            'Rule 是声明式计算，不是 TI 的物理写入；Feeder 不是数值流。',
            '行集合（Subset/MDX/隐式切片器）、参数实际值与覆盖/累加次数未求值。',
            '表达式中的字符串常量沿用既有解析契约，统一显示为 <常量>；目标成员只在成员目录确认后展示。',
            '未被写入或调用引用的读取可能已被既有分析器裁剪，本档案不补造该动作。',
        ])
    return model


def _depths(scope: Scope, facts: list[dict]) -> dict:
    """Static call depth from the entry, used only for reading order."""
    names = {f['name'] for f in facts}
    edges: dict[str, set[str]] = {}
    for item in facts:
        for call in (item.get('report') or {}).get('calls', []):
            target = call.get('target')
            if target and target in names:
                edges.setdefault(item['name'], set()).add(target)
    roots = [scope.entry] if scope.entry_kind == 'process' and scope.entry in names else sorted(names)
    depth = {r: 0 for r in roots}
    queue = deque(roots)
    while queue:
        node = queue.popleft()
        for target in sorted(edges.get(node, ())):
            if target not in depth:
                depth[target] = depth[node] + 1
                queue.append(target)
    for name in names:
        depth.setdefault(name, 99)
    return depth


# ---------------------------------------------------------------------------
# Markdown / Questions projection
# ---------------------------------------------------------------------------

def _cell(value) -> str:
    if isinstance(value, (dict, list)):
        value = canonical(value)
    text = str(value if value is not None else '未确认')
    return escape(text).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')


def _plain(value) -> str:
    """Prose text without HTML escaping; only strip table/newline hazards."""
    return str(value if value is not None else '未确认').replace('|', '／').replace('\r', ' ').replace('\n', ' ')


def _code(value) -> str:
    """Code-span text: keep literal characters readable, only break the span."""
    text = str(value if value is not None else '未确认')
    return text.replace('|', '\\|').replace('`', '\\`').replace('\r', ' ').replace('\n', ' ')


def _table(heads, rows):
    if not rows:
        return ['_无已确认记录。_', '']
    lines = ['| ' + ' | '.join(heads) + ' |', '|' + '|'.join('---' for _ in heads) + '|']
    lines += ['| ' + ' | '.join(_cell(c) for c in row) + ' |' for row in rows]
    lines.append('')
    return lines


def _coord_text(coordinates: list[dict]) -> str:
    parts = []
    for item in coordinates:
        label = '固定' if item['binding_kind'] == 'FIXED_MEMBER' else \
            '参数' if item['binding_kind'] == 'PARAMETER' else \
            '行变量' if item['binding_kind'] == 'DATA_ROW_VARIABLE' else \
            '查找坐标' if item['binding_kind'] == 'LOOKUP_COORDINATE' else '待确认'
        parts.append('%s=%s（%s）' % (item.get('dimension') or '维度待确认', item.get('value'), label))
    return '；'.join(parts) or '未确认'


def _evidence_where(item: dict) -> str:
    """Best available source anchor for the evidence index; never invented."""
    section = item.get('section')
    line = item.get('line')
    if section and line is not None:
        return '%s:%s' % (section, line)
    if item.get('line_start') is not None:
        return 'rule:%s' % item['line_start']
    if isinstance(item.get('location'), str) and item['location']:
        return item['location']
    locations = item.get('locations')
    if isinstance(locations, list) and locations:
        first = locations[0]
        if isinstance(first, dict):
            return _location(first)
    if line is not None:
        return ('rule 第 %s 行' % line) if str(item.get('kind', '')).startswith(('RULE', 'FEEDER')) \
            else 'line %s' % line
    if item.get('position') is not None:
        if item.get('kind') == 'DIMENSION_METADATA':
            return 'Cube 内第 %s 位' % (int(item['position']) + 1)
        return '列位置 %s' % item['position']
    return '模型事实（无源码行）'


def markdown(model: dict) -> str:
    """Reader-first report. No full source, no large JSON dumps."""
    lines: list[str] = []
    module = model['module']
    coverage = model['coverage']
    entry = model['scope']['entry']
    lines += ['# 模块档案 · ' + _cell(module['name']), '',
              '> 入口：%s `%s` ｜ 目标 Cube：%s ｜ 分析日期：%s ｜ 契约：%s' % (
                  '流程' if entry['type'] == 'process' else 'Cube', _cell(entry['name']),
                  '、'.join(_cell(x) for x in model['scope']['target_cubes']) or '未指定',
                  module['analysis_date'], model['schema_version']), '',
              '本档案是**静态源码与已采集模型事实**的说明，不是运行记录。'
              '未执行 TM1、未读取单元格、未证明数值贡献或迁移等价。', '']

    lines += ['## 0. 一页摘要', '']
    lines += ['- 覆盖：流程 %d / %d 个，Cube 结构 %d 个，写入点 %d 处，Rule %d 条，Feeder %d 条。' % (
        coverage['processes_analyzed'], coverage['processes_in_scope'], coverage['cubes_modeled'],
        coverage['write_points'], coverage['rules'], coverage['feeders'])]
    lines += ['- 未确认事项：%d 项（见第 7 节与 Questions.md）。运行验证：0 项。' % coverage['gaps']]
    sources = sorted({s['datasource'].get('cube') for s in model['data_sources'] if s['datasource'].get('cube')})
    lines += ['- 已确认的数据来源 Cube：%s。' % ('、'.join(_cell(x) for x in sources) or '未确认')]
    lines += ['- 已确认的写入目标：%s。' % ('、'.join(_cell(x) for x in sorted({r['cube'] for r in model['target_results'] if r.get('cube')})) or '未确认')]
    lines += ['- 人工说明：%s' % (_cell(module['user_note']) if module.get('user_note') else '无（本档案未加入业务解释）'), '']
    if module.get('user_note'):
        lines += ['> 人工说明属于 USER_ANNOTATION，与源码事实分开记录，不作为证据。', '']

    # 1 数据来源
    lines += ['## 1. 数据来源', '',
              '每行是一个流程的真实声明或记录，**声明不等于值流**。变量位置是源列序号，不是维度序号。', '']
    for source in model['data_sources']:
        ds = source['datasource']
        lines += ['### ' + _cell(source['process']), '']
        if ds.get('status') == 'NO_DATASOURCE_RECORDED':
            lines += ['- 数据源：**未记录**（源码无 `DataSourceType` 赋值，快照也无数据源属性）。']
        else:
            lines += ['- 数据源类型：**%s**（状态 %s）%s' % (
                _cell(ds.get('declared_type') or '未确认'), _cell(ds.get('status')),
                '；外部类型 ' + _cell(ds['external_type']) if ds.get('external_type') else '')]
        if ds.get('cube'):
            lines += ['- 绑定来源：Cube `%s` ｜ View `%s` ｜ 行布局 %s ｜ 行集合 %s' % (
                _cell(ds['cube']), _cell(ds.get('view')), _cell(source['variables'].get('layout_status')),
                _cell(source['row_context'].get('membership_status')))]
        if ds.get('binding_locations') and ds.get('status') != 'NO_DATASOURCE_RECORDED':
            lines += ['- 源码位置：%s' % '；'.join(_cell(_location(x) if isinstance(x, dict) else x) for x in ds['binding_locations'][:5])]
        if ds.get('note') and ds.get('status') != 'NO_DATASOURCE_RECORDED':
            lines += ['- 说明：' + _cell(ds['note'])]
        if source['variables']['items']:
            lines += ['', '| 行变量 | 类型 | 源列 | 来源字段 | 状态 | 证据 |',
                      '|---|---|---|---|---|---|']
            for variable in source['variables']['items'][:40]:
                field = ('维度 ' + variable['source_dimension']) if variable.get('source_dimension') else \
                    ('单元格值列' if variable.get('source_field_kind') == 'CELL_VALUE' else '未确认')
                lines += ['| %s | %s | %s | %s | %s | %s |' % (
                    _cell(variable['name']), _cell(variable['type']), _cell(variable['position']),
                    _cell(field), _cell(variable.get('source_field_status')),
                    _cell(' '.join(variable['evidence_refs'])))]
            lines.append('')
        elif ds.get('status') != 'NO_DATASOURCE_RECORDED':
            lines += ['- 行变量：未采集到可用定义。原因：%s' % '；'.join(
                _cell(x) for x in (source['variables']['reasons'] or ['未记录']))]
            lines.append('')
        params = source['parameters']
        if params['items']:
            lines += ['- 参数：' + '；'.join(
                '%s（%s，默认 %s）' % (_cell(p['name']), _cell(p.get('type')), _cell(p.get('default')))
                for p in params['items'][:20])]
        elif params.get('declared_names'):
            lines += ['- 参数（仅名称，类型未采集）：' + '、'.join(_cell(x) for x in params['declared_names'][:20])]
        else:
            lines += ['- 参数：无声明。']
        lines.append('')

    # 2 数据模型
    lines += ['## 2. 数据模型', '',
              '维度顺序即坐标粒度。层级、属性与权重只报采集状态，不推断汇总结果。', '']
    for cube in model['data_model']:
        lines += ['### %s（%s）' % (_cell(cube['name']), _cell(cube['role'])), '',
                  '- 维度顺序（%d）：%s' % (len(cube['dimension_order']),
                                           ' → '.join(_cell(x) for x in cube['dimension_order']) or '未采集'),
                  '- 顺序状态：%s ｜ 粒度状态：%s' % (_cell(cube['order_status']), _cell(cube['grain_status'])),
                  '- 粒度说明：' + _cell(cube['grain_note'])]
        if cube['order_status'] != 'RECORDED_COMPLETE':
            lines += ['- **注意**：维度数量或顺序不完整，写入坐标可能错位。']
        lines += ['', '| # | 维度 | 元素数 | 层级 | 属性 | 汇总边 | 证据 |', '|---|---|---|---|---|---|---|']
        for dim in cube['dimensions']:
            lines += ['| %s | %s | %s | %s | %s | %s | %s |' % (
                dim['position'], _cell(dim['name']), _cell(dim['element_count']),
                _cell('、'.join(dim['hierarchies']) if dim['hierarchies'] else dim['hierarchy_status']),
                _cell('%s / %s' % (dim['attributes']['status'], dim['attributes']['count'])),
                _cell('%s / %s' % (dim['consolidation']['status'], dim['consolidation']['count'])),
                _cell(' '.join(dim['evidence_refs'])))]
        lines.append('')
        rules_here = [r for r in model['rules'] if r['cube'] == cube['name']]
        if cube['has_rules']:
            lines += ['- Rule 作用区域：%d 条（按区域见第 5 节）%s' % (
                len(rules_here), '；区域定位：' + '、'.join(
                    '第 %s 行' % r['line_start'] for r in rules_here[:6]) if rules_here else '')]
        else:
            lines += ['- Rule：本快照未记录 Rule 源码（`has_rules=false`，不等于该 Cube 一定没有 Rule）。']
        references = [r for r in cube['known_references']]
        if references:
            described = []
            for reference in references[:10]:
                if reference['kind'] == 'RULE_OR_FEEDER_REFERENCE':
                    described.append('Rule/Feeder 引用 %s' % reference.get('cube'))
                elif reference['kind'] == 'TI_READ':
                    described.append('被 TI 读取：%s' % reference.get('process'))
                else:
                    described.append('被 TI 写入：%s' % reference.get('process'))
            lines += ['- 已知引用：' + '；'.join(_cell(x) for x in described)]
        lines.append('')

    # 3 逐步转换
    lines += ['## 3. 逐步转换', '',
              '步骤按静态调用深度排序，TI 内部按源码位置排序。**这不是运行顺序**，也不代表条件一定成立。', '']
    for step in model['transformation_steps']:
        lines += ['### %s · %s' % (_cell(step['step_id']), _cell(step['process'])), '']
        lines += ['- 类型：%s ｜ 数据源：%s ｜ 读：%s ｜ 写：%s' % (
            _cell(step['declared_role']), _cell(step['datasource'].get('type')),
            '、'.join(_cell(x) for x in step['inputs']) or '未观察到',
            '、'.join(_cell(x) for x in step['outputs']) or '未观察到')]
        if step['sequence']:
            lines += ['', '源码位置顺序（不代表执行顺序）：', '']
            for action in step['sequence'][:18]:
                lines += ['%d. `%s` %s · %s' % (action['order'], _code(_location(action['location'])),
                                                _cell(action['description']), _cell(' '.join(action['evidence_refs'])))]
            if len(step['sequence']) > 18:
                lines += ['_（其余 %d 条动作见 Module.json）_' % (len(step['sequence']) - 18)]
            lines.append('')
        else:
            lines += ['', '_该流程未观察到影响输出的读写动作（未被后续引用的读取不计入）。_', '']

    # 4 目标结果
    lines += ['## 4. 目标结果', '',
              '每处写入独立成项：写入模式、目标坐标、值表达式、字段映射与条件分开陈述。', '',
              '> 表达式中的字符串常量由解析层统一脱敏为 `<常量>`；已在成员目录中确认的固定成员会直接出现在坐标表里。'
              '需要原值时按 Section/行号回到源码核对。', '']
    if model.get('target_effects'):
        lines += ['### 结果形成前的清空与准备', '',
                  '| 程序 | 类别 | 操作 | 目标 | 位置 | 证据 |', '|---|---|---|---|---|---|']
        for effect in model['target_effects']:
            lines += ['| %s | %s | %s | %s | %s | %s |' % (
                _cell(effect['process']), _cell(effect['label']), _cell(effect['operation']),
                _cell(effect['target'] or '参数决定（未解析）'),
                _cell(_location(effect['location'])), _cell(' '.join(effect['evidence_refs'])))]
        lines += ['', '> 清空/准备动作只证明源码中发生过该调用；目标 Cube 若由参数决定，则未确认实际清空范围。', '']
    detail = model['target_results'][:DETAIL_LIMIT]
    rest = model['target_results'][DETAIL_LIMIT:]
    for result in detail:
        lines += ['### %s · %s → %s' % (_cell(result['result_id']), _cell(result['operation']), _cell(result['cube'])), '',
                  '- 写入模式：**%s**（%s）｜ 来源：%s ｜ 确认度：%s' % (
                      _cell(result['mode']), _cell(result['mode_label']),
                      _cell(_location(result['location'])), _cell(result['coordinate_status'])),
                  '- 值表达式：`%s`' % _code(result.get('value_expression'))]
        if result.get('formula_expression') and result['formula_expression'] != result.get('value_expression'):
            lines += ['- 值定义链：`%s`' % _code(result['formula_expression'])]
        lines += ['- 目标坐标：' + _cell(_coord_text(result['coordinates']))]
        if result['conditions']:
            lines += ['- 条件（未求值）：' + '；'.join(
                '`%s`' % _code(c.get('condition') or c.get('kind')) for c in result['conditions'])]
        if result['field_mapping']:
            lines += ['', '| 来源 Cube | 来源维度 | 源列 | 行变量 | 目标维度 | 依据 |', '|---|---|---|---|---|---|']
            for row in result['field_mapping']:
                lines += ['| %s | %s | %s | %s | %s | %s |' % (
                    _cell(row.get('source_cube')), _cell(row.get('source_dimension') or '（值列）'),
                    _cell(row.get('source_column')), _cell(row.get('source_variable')),
                    _cell(row.get('target_dimension') or row.get('target') or '—'), _cell(row['basis']))]
            lines += ['', '> 上表是**静态列布局对应**（NativeView 列 + 记录的维度顺序），不证明成员变换、汇总或实际行数。', '']
        else:
            lines += ['- 字段到目标坐标映射：无数据行来源（%s）' % (
                '写入值为静态常量或表达式' if not result['source_reads'] else '写入值来自单元格读取')]
        if result['source_reads']:
            lines += ['- 已确认的静态读取依赖：' + '；'.join(
                '%s（%s）' % (_cell(r.get('cube')), _cell(r.get('operation'))) for r in result['source_reads'][:8])]
        if result['row_value_dependencies']:
            lines += ['- 行值依赖：' + '；'.join(
                '%s（%s）' % (_cell(r['variable']), _cell(r.get('source_cube'))) for r in result['row_value_dependencies'][:8])]
        if result['unresolved']:
            lines += ['- 未确认：' + '；'.join(_cell(u.get('reason')) for u in result['unresolved'][:6])]
        lines += ['- 证据：%s' % _cell(' '.join(result['evidence_refs'])), '']
    if rest:
        lines += ['### 其余写入点（摘要）', '',
                  '为保持可读性，正文只展开前 %d 处写入；下列 %d 处保留在 Module.json 中。' % (
                      DETAIL_LIMIT, len(rest)), '',
                  '| # | 程序 | 写入模式 | 目标坐标确认 | 值表达式 | 证据 |', '|---|---|---|---|---|---|']
        for result in rest:
            lines += ['| %s | %s | %s | %s | `%s` | %s |' % (
                _cell(result['result_id']), _cell(result['process']),
                _cell('%s（%s）' % (result['mode'], result['mode_label'])),
                _cell(result['coordinate_status']), _code(result.get('value_expression')),
                _cell(' '.join(result['evidence_refs'][:1])))]
        lines.append('')

    # 5 Rule / Feeder
    lines += ['## 5. Rule 与 Feeder', '',
              'Rule 是声明式计算，**不是 TI 的物理写入**；Feeder 只声明稀疏支持关系，不产生业务数值。', '']
    if model['rules']:
        lines += ['### Rule', '', '| 行 | 目标区域 | 条件 | 表达式 | 状态 | 引用 | 证据 |',
                  '|---|---|---|---|---|---|---|']
        for rule in model['rules'][:RULE_ROW_LIMIT]:
            references = '；'.join('%s%s' % (_cell(r.get('cube')),
                                            '' if r.get('cube_resolved') else '（未解析）')
                                   for r in rule['references']) or '无'
            lines += ['| %s | `%s` | %s | `%s` | %s | %s | %s |' % (
                _cell('%s-%s' % (rule['line_start'], rule['line_end'])),
                _code(rule['area'].get('raw')), _cell(rule.get('qualifier')),
                _code(rule.get('expression')), _cell(rule['status']), _cell(references),
                _cell(' '.join(rule['evidence_refs'])))]
        lines.append('')
        if len(model['rules']) > RULE_ROW_LIMIT:
            lines += ['_其余 %d 条 Rule 见 Module.json。_' % (len(model['rules']) - RULE_ROW_LIMIT), '']
        unresolved = [(r['cube'], r['line_start'], x) for r in model['rules'] for x in r['unresolved_reasons']]
        if unresolved:
            lines += ['Rule 未确认项：', '']
            lines += ['- %s 第 %s 行：%s' % (_cell(a), _cell(b), _cell(c)) for a, b, c in unresolved[:12]]
            lines.append('')
    else:
        lines += ['_范围内 Cube 未记录可解析的 Rule 源码；这不等于该 Cube 一定没有 Rule（见第 7 节）。_', '']
    if model['feeders']:
        lines += ['### Feeder（非数值流）', '', '| 行 | 源区域 | 目标区域 | 状态 | 证据 |', '|---|---|---|---|---|']
        for feeder in model['feeders']:
            lines += ['| %s | `%s` | `%s` | %s | %s |' % (
                _cell(feeder['line_start']), _code(feeder.get('source_area')),
                _code(feeder.get('target_area')), _cell(feeder['status']),
                _cell(' '.join(feeder['evidence_refs'])))]
        lines.append('')
    if model.get('rule_directives'):
        lines += ['Rule 指令：' + '、'.join(_cell(d.get('kind')) for d in model['rule_directives'][:8]), '']

    # 6 执行调用
    lines += ['## 6. 执行调用', '',
              '调用关系不是数据流；参数值不执行，条件不求值。'
              '参数按其源码位置编号显示（参数名与字符串值沿用既有脱敏契约）。', '']
    if model['execution_calls']:
        lines += ['| 调用方 | 被调用方 | 参数 | 条件 | 位置 | 证据 |', '|---|---|---|---|---|---|']
        for call in model['execution_calls']:
            lines += ['| %s | %s | %s | %s | %s | %s |' % (
                _cell(call['caller']), _cell(call.get('callee') or '动态目标待确认'),
                '`%s`' % _code('；'.join('#%s %s' % (p.get('position'), p.get('expression'))
                                         for p in call['parameters'][:4]) or '无'),
                '`%s`' % _code('；'.join(str(c.get('condition')) for c in call['conditions'][:2]) or '未观察到'),
                _cell(_location(call['location'])), _cell(' '.join(call['evidence_refs'])))]
        lines.append('')
    else:
        lines += ['_未观察到流程调用。_', '']
    if model['schedules']:
        lines += ['调度定义：' + '；'.join('%s → %s（步骤 %s）' % (_cell(s['chore']), _cell(s['process']),
                                                              _cell(s['step_order'])) for s in model['schedules'][:10]), '']
    if model['entry_callers']:
        lines += ['入口 Caller（索引观察）：' + '、'.join(_cell(c['caller']) for c in model['entry_callers'][:10]), '']

    # 7 验证缺口
    lines += ['## 7. 验证缺口', '',
              '每条缺口都说明「为什么不知道」和「需要补什么」，不静默补值。', '',
              '| # | 对象 | 环节 | 代码 | 原因 | 影响 | 如何确认 |', '|---|---|---|---|---|---|---|']
    for gap in model['verification_gaps']:
        lines += ['| %s | %s | %s | %s | %s | %s | %s |' % (
            gap['gap_id'], _cell(gap['object']), _cell(gap['section']), _cell(gap['code']),
            _cell(gap['reason']), _cell(gap['impact']), _cell(gap['verification']))]
    lines.append('')

    # 8 阅读边界
    lines += ['## 8. 阅读边界与证据索引', '', '### 事实分层', '',
              '- **观察**：源码与已采集模型事实，带 EV 编号与 Section/行号。',
              '- **静态推断**：仅源列→目标的列布局对应（标注 STATIC_INFERENCE）。',
              '- **人工说明**：仅出现在模块摘要，不影响任何事实字段。',
              '- **UNKNOWN**：第 7 节，不参与确定结论。',
              '- **运行验证**：0 项。本档案没有执行证据。', '',
              '### 证据索引（前 60 条，完整列表见 Evidence.json）', '',
              '| 证据 | 类型 | 对象 | 定位 |', '|---|---|---|---|']
    for item in model['evidence'][:60]:
        lines += ['| %s | %s | %s | %s |' % (item['id'], _cell(item['kind']), _cell(item['object']),
                                             _cell(_evidence_where(item)))]
    if len(model['evidence']) > 60:
        lines += ['', '_其余 %d 条证据见 Evidence.json。_' % (len(model['evidence']) - 60)]
    lines += ['', '### 已知限制', '']
    lines += ['- ' + _cell(x) for x in model['limitations']]
    lines += ['', '模块 ID：`%s` ｜ Snapshot：%s' % (module['id'], _cell(model['snapshot_ref'])), '']
    return '\n'.join(lines)


def questions(model: dict) -> str:
    """Human-confirmation list derived from gaps; never a new claim."""
    lines = ['# 待确认问题 · ' + _plain(model['module']['name']), '',
             '以下问题全部来自档案中的缺口项。每项说明「要确认什么」和「为什么现在不能确定」。',
             '回答这些问题不会自动改写事实；请把结论作为人工标注另行保存。', '']
    groups = {
        'data_sources': '数据来源与字段',
        'data_model': '数据模型与粒度',
        'target_results': '目标结果与坐标',
        'rules': 'Rule 计算',
        'feeders': 'Feeder 支持',
        'execution_calls': '执行调用',
        'verification': '验证与运行',
        'scope': '分析范围',
    }
    by_section: dict[str, list] = {}
    for gap in model['verification_gaps']:
        by_section.setdefault(gap['section'], []).append(gap)
    for key, title in groups.items():
        items = by_section.get(key, [])
        if not items:
            continue
        lines += ['## ' + title, '']
        for gap in items:
            lines += ['### %s · %s' % (gap['gap_id'], _plain(gap['object'])), '',
                      '- 现象：' + _plain(gap['reason']),
                      '- 影响：' + _plain(gap['impact']),
                      '- 需要：' + _plain(gap['verification']),
                      '- 证据：%s' % _plain(' '.join(gap['evidence_refs']) or '无（结构性缺口）'), '']
    if len(lines) <= 5:
        lines += ['_本次没有待确认问题；这并不表示模型已被运行验证。_', '']
    return '\n'.join(lines)


def diagnostics_document(model: dict) -> dict:
    return dict(schema_version=VERSION, module=model['module']['name'],
                snapshot_ref=model['snapshot_ref'], coverage=model['coverage'],
                diagnostics=model['diagnostics'],
                budgets=model['scope']['budget'],
                evidence_truncated=any(d.get('stage') == 'evidence_budget' for d in model['diagnostics']),
                statements=model['statements'])


def dumps(model: dict) -> bytes:
    return json.dumps(model, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')


def package(model: dict) -> bytes:
    """ZIP with the five contractual files; deterministic entries, no extra copies."""
    files = [('Module.md', markdown(model).encode('utf-8')),
             ('Module.json', dumps(model)),
             ('Evidence.json', json.dumps(dict(
                 schema_version=VERSION, module=model['module']['name'],
                 snapshot_ref=model['snapshot_ref'], runtime_verified=False,
                 statements=model['statements'], items=model['evidence']),
                 ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')),
             ('Diagnostics.json', json.dumps(diagnostics_document(model), ensure_ascii=False,
                                             sort_keys=True, indent=2).encode('utf-8')),
             ('Questions.md', questions(model).encode('utf-8'))]
    buffer = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    buffer.seek(0)
    return buffer.read()


def write_package(payload: bytes, directory) -> list:
    """Extract the five contractual files into a fresh local directory.

    Flat extraction only: archive names are local contracts, but a tampered
    archive must still never escape the chosen directory.
    """
    from pathlib import Path
    target = Path(directory)
    if target.exists() and any(target.iterdir()):
        raise ValueError('输出目录非空；请选择一个新目录，避免覆盖既有档案。')
    target.mkdir(parents=True, exist_ok=True)
    written = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            name = Path(info.filename).name
            if not name or name.startswith('.'):
                continue
            path = target / name
            path.write_bytes(archive.read(info))
            written.append(path)
    return written
