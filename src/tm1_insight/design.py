"""设计模式（Visual Development）数据契约与生成编排。

边界：
- 设计对象永远标记 ``DESIGN_DRAFT``，不是快照中的真实对象，也不参与血缘计算。
- 生成只调用既有 ``store.codegen``，不另建代码生成器。
- 任何未映射的目标维度都会阻止生成，不静默产出空赋值。
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DIM_ID = r'^dimdraft-[a-zA-Z0-9_-]{1,64}$'
CUBE_ID = r'^draft-[a-zA-Z0-9_-]{1,64}$'
CSV_ID = r'^csv-[a-zA-Z0-9_-]{1,64}$'
REL_ID = r'^rel-[a-zA-Z0-9_-]{1,64}$'
BP_ID = r'^bp-[a-zA-Z0-9_-]{1,64}$'

TEMPLATE_IDS = ('cube-data-transfer', 'csv-to-cube', 'cube-creation')


class DimensionDraft(BaseModel):
    """尚不存在于快照的维度草稿。不可被当作真实 Dimension 使用。"""
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=DIM_ID)
    name: str = Field(min_length=1, max_length=200)
    elements: list[str] = Field(default_factory=list, max_length=500)
    element_type: Literal['N', 'S'] = 'S'
    note: str = Field(default='', max_length=2000)
    provenance: Literal['DESIGN_DRAFT'] = 'DESIGN_DRAFT'

    @model_validator(mode='after')
    def _clean(self):
        if any(not e.strip() or len(e) > 200 for e in self.elements):
            raise ValueError('维度草稿元素不能为空且不超过 200 字符')
        if len({e.casefold() for e in self.elements}) != len(self.elements):
            raise ValueError('维度草稿元素不能重复')
        return self


class DimensionRef(BaseModel):
    """Cube 草稿中的一个维度位：引用快照已有维度，或引用维度草稿。"""
    model_config = ConfigDict(extra='forbid')
    kind: Literal['existing', 'draft']
    name: str = Field(min_length=1, max_length=200)
    draft_id: str = Field(default='', max_length=80)

    @model_validator(mode='after')
    def _consistent(self):
        if self.kind == 'draft' and not re.fullmatch(DIM_ID, self.draft_id):
            raise ValueError('草稿维度必须提供合法 draft_id')
        if self.kind == 'existing' and self.draft_id:
            raise ValueError('已有维度不应携带 draft_id')
        return self


class CubeDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=CUBE_ID)
    name: str = Field(min_length=1, max_length=200)
    note: str = Field(default='', max_length=4000)
    dimensions: list[DimensionRef] = Field(min_length=1, max_length=60)
    measures: list[str] = Field(default_factory=list, max_length=100)
    provenance: Literal['DESIGN_DRAFT'] = 'DESIGN_DRAFT'

    @model_validator(mode='after')
    def _unique_order(self):
        names = [d.name.casefold() for d in self.dimensions]
        if len(set(names)) != len(names):
            raise ValueError('Cube 草稿维度不能重复（顺序必须明确且唯一）')
        return self

    @property
    def dim_names(self) -> list[str]:
        return [d.name for d in self.dimensions]


class CsvField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=200)
    type: Literal['string', 'number', 'date', 'boolean', 'unknown'] = 'unknown'
    required: bool = False
    note: str = Field(default='', max_length=500)


class CsvSchema(BaseModel):
    """用户主动提供的表头结构。不读取任何真实数据行。"""
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=CSV_ID)
    name: str = Field(min_length=1, max_length=200)
    fields: list[CsvField] = Field(min_length=1, max_length=500)
    origin: Literal['USER_INPUT', 'USER_IMPORT', 'TI_METADATA', 'UNKNOWN'] = 'USER_INPUT'
    note: str = Field(default='', max_length=2000)
    provenance: Literal['DESIGN_DRAFT'] = 'DESIGN_DRAFT'

    @model_validator(mode='after')
    def _unique(self):
        names = [f.name.casefold() for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError('Schema 字段名不能重复')
        return self


class MappingEntry(BaseModel):
    """一个目标维度的来源声明。未声明即视为未映射。"""
    model_config = ConfigDict(extra='forbid')
    target_dimension: str = Field(min_length=1, max_length=200)
    kind: Literal['FIXED', 'FROM_SOURCE', 'FROM_CONTEXT', 'LOOKUP', 'EXPRESSION', 'UNMAPPED'] = 'UNMAPPED'
    fixed_member: str = Field(default='', max_length=200)
    source_field: str = Field(default='', max_length=200)
    expression: str = Field(default='', max_length=500)
    confirmed: bool = False

    def as_codegen_spec(self) -> dict:
        if self.kind == 'FIXED':
            return {'fixed': "'" + self.fixed_member.replace("'", "''") + "'"}
        if self.kind == 'FROM_SOURCE':
            # 只声明来源字段名，变量名由 codegen 的变量映射表解析，
            # 保证与 Data Source 变量定义完全一致（含重名去重后缀）。
            return {'source_field': self.source_field}
        if self.kind == 'EXPRESSION':
            return {'source': self.expression}
        return {}


class RelationEnd(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['cube', 'cube_draft', 'csv']
    ref: str = Field(min_length=1, max_length=200)


class DesignRelation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=REL_ID)
    source: RelationEnd
    target: RelationEnd
    mapping: list[MappingEntry] = Field(default_factory=list, max_length=80)
    value_source: str = Field(default='', max_length=200)
    write_policy: Literal['overwrite', 'accumulate'] = 'overwrite'
    clear_policy: Literal['target_scope', 'none'] = 'target_scope'
    template: Literal['cube-data-transfer', 'csv-to-cube'] = 'csv-to-cube'
    confirmed: bool = False
    note: str = Field(default='', max_length=2000)
    provenance: Literal['DESIGN_RELATION'] = 'DESIGN_RELATION'
    # 最近一次生成结果摘要（含 design_fingerprint）；随工作区持久化，用于判定是否过期
    generated: dict | None = None

    @model_validator(mode='after')
    def _no_duplicate_mapping(self):
        dims = [m.target_dimension.casefold() for m in self.mapping]
        if len(set(dims)) != len(dims):
            raise ValueError('同一目标维度只能有一条映射')
        return self


class GeneratedArtifact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    relation_id: str = Field(max_length=80)
    template: str = Field(max_length=60)
    template_version: str = Field(default='1', max_length=20)
    generated_at: str = Field(max_length=40)
    status: Literal['DESIGN_DRAFT'] = 'DESIGN_DRAFT'
    validated: bool = False
    blockers: list[str] = Field(default_factory=list, max_length=100)
    summary: dict[str, str] = Field(default_factory=dict)


class Blueprint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=BP_ID)
    name: str = Field(min_length=1, max_length=200)
    note: str = Field(default='', max_length=4000)
    version: int = Field(default=1, ge=1, le=1000)
    cube_ids: list[str] = Field(default_factory=list, max_length=60)
    dimension_ids: list[str] = Field(default_factory=list, max_length=60)
    schema_ids: list[str] = Field(default_factory=list, max_length=60)
    relation_ids: list[str] = Field(default_factory=list, max_length=60)
    artifacts: list[GeneratedArtifact] = Field(default_factory=list, max_length=60)
    created_at: str = Field(default='', max_length=40)
    updated_at: str = Field(default='', max_length=40)
    provenance: Literal['DESIGN_DRAFT'] = 'DESIGN_DRAFT'


class Design(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['explore', 'design'] = 'explore'
    cubes: list[CubeDraft] = Field(default_factory=list, max_length=60)
    dimensions: list[DimensionDraft] = Field(default_factory=list, max_length=60)
    schemas: list[CsvSchema] = Field(default_factory=list, max_length=60)
    relations: list[DesignRelation] = Field(default_factory=list, max_length=60)
    blueprints: list[Blueprint] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def _refs(self):
        dim_ids = {d.id for d in self.dimensions}
        for cube in self.cubes:
            for ref in cube.dimensions:
                if ref.kind == 'draft' and ref.draft_id not in dim_ids:
                    raise ValueError('Cube 草稿引用了不存在的维度草稿')
        cube_ids = {c.id for c in self.cubes}
        schema_ids = {s.id for s in self.schemas}
        rel_ids = {r.id for r in self.relations}
        for rel in self.relations:
            if rel.source.kind == 'csv' and rel.source.ref not in schema_ids:
                raise ValueError('设计关系引用了不存在的 CSV Schema')
            if rel.source.kind == 'cube_draft' and rel.source.ref not in cube_ids:
                raise ValueError('设计关系引用了不存在的 Cube 草稿')
            if rel.target.kind == 'cube_draft' and rel.target.ref not in cube_ids:
                raise ValueError('设计关系指向了不存在的 Cube 草稿')
        for bp in self.blueprints:
            if set(bp.cube_ids) - cube_ids or set(bp.dimension_ids) - dim_ids \
                    or set(bp.schema_ids) - schema_ids or set(bp.relation_ids) - rel_ids:
                raise ValueError('Blueprint 引用了不存在的设计对象')
        if len({c.id for c in self.cubes}) != len(self.cubes) \
                or len({r.id for r in self.relations}) != len(self.relations) \
                or len({b.id for b in self.blueprints}) != len(self.blueprints):
            raise ValueError('设计对象 id 必须唯一')
        return self

    def cube(self, cube_id: str) -> CubeDraft | None:
        return next((c for c in self.cubes if c.id == cube_id), None)

    def schema(self, schema_id: str) -> CsvSchema | None:
        return next((s for s in self.schemas if s.id == schema_id), None)

    def relation(self, rel_id: str) -> DesignRelation | None:
        return next((r for r in self.relations if r.id == rel_id), None)


def parse_header(text: str, delimiter: str = '') -> list[CsvField]:
    """解析用户粘贴的表头行，生成字段清单。

    只处理表头文本；**不读取任何数据行**。类型为建议值，需用户确认后使用。
    """
    line = next((ln for ln in (text or '').splitlines() if ln.strip()), '')
    if not line:
        return []
    if delimiter:
        parts = line.split(delimiter)
    else:
        parts = re.split(r'[,;\t|]', line)
    fields: list[CsvField] = []
    for raw in parts:
        name = raw.strip().strip('"').strip("'").strip()
        if not name:
            continue
        low = name.casefold()
        if any(k in low for k in ('qty', 'quantity', 'amount', 'cost', 'price', 'value', 'number', 'amt')):
            kind = 'number'
        elif 'date' in low:
            kind = 'date'
        elif low.startswith('is') or low.endswith('flag'):
            kind = 'boolean'
        else:
            kind = 'unknown'
        fields.append(CsvField(name=name, type=kind))
    return fields


def _source_variables(design: Design, rel: DesignRelation) -> list[str]:
    if rel.source.kind == 'csv':
        schema = design.schema(rel.source.ref)
        return [f.name for f in schema.fields] if schema else []
    cube = design.cube(rel.source.ref) if rel.source.kind == 'cube_draft' else None
    return cube.dim_names if cube else []


def clear_scope_filters(rel: DesignRelation, dims: list[str]) -> list[dict]:
    """从已确认的固定成员派生清空筛选条件。

    只有用户明确确认过的固定成员才会进入清空范围——未确认的映射不参与，
    避免把「还没想清楚的坐标」当成删除范围。
    """
    out: list[dict] = []
    for dim in dims:
        entry = next((m for m in rel.mapping if m.target_dimension == dim), None)
        if entry and entry.kind == 'FIXED' and entry.confirmed and entry.fixed_member.strip():
            out.append({'dim': dim, 'elems': [entry.fixed_member.strip()], 'kind': 'const'})
    return out


def describe_clear_scope(filters: list[dict]) -> str:
    if not filters:
        return '整个目标 Cube（无筛选）'
    return '；'.join('%s = %s' % (f['dim'], ', '.join(f.get('elems') or [])) for f in filters)


def preflight(design: Design, rel: DesignRelation,
              existing_cube_dims: dict[str, list[str]] | None = None) -> list[dict]:
    """生成前预检：返回结构化问题列表（空 = 可以生成）。

    每条：{code, message, dimension?}。message 面向用户；code 供测试与 UI 分类。
    """
    from tm1_insight.codegen_safety import validate_expression

    issues: list[dict] = []

    def add(code, message, dim=None):
        item = {'code': code, 'message': message}
        if dim:
            item['dimension'] = dim
        issues.append(item)

    target = design.cube(rel.target.ref) if rel.target.kind == 'cube_draft' else None
    if rel.target.kind == 'cube_draft' and target is None:
        add('TARGET_MISSING', '目标 Cube 草稿不存在')
        return issues
    if rel.target.kind == 'cube':
        dims = (existing_cube_dims or {}).get(rel.target.ref) or []
        if not dims:
            add('TARGET_NOT_IN_SNAPSHOT', '目标 Cube 不在当前快照中，无法取得维度顺序')
            return issues
    else:
        dims = target.dim_names
    if not dims:
        add('DIM_ORDER_EMPTY', '目标 Cube 没有维度顺序')
        return issues

    fields = set()
    if rel.source.kind == 'csv':
        schema = design.schema(rel.source.ref)
        if schema is None:
            add('SOURCE_MISSING', 'CSV Schema 不存在')
            return issues
        fields = {f.name for f in schema.fields}
        if rel.template != 'csv-to-cube':
            add('TEMPLATE_MISMATCH', 'CSV 来源必须使用 csv-to-cube 模板')
        if not rel.value_source:
            add('VALUE_SOURCE_MISSING', '未指定数值来源列（vValue 无法确定）')
        elif rel.value_source not in fields:
            add('VALUE_SOURCE_UNKNOWN', '数值来源列不在 Schema 字段中：%s' % rel.value_source)
    else:
        if rel.template != 'cube-data-transfer':
            add('TEMPLATE_MISMATCH', 'Cube 来源必须使用 cube-data-transfer 模板')
        src_dims = _source_variables(design, rel)
        if not src_dims:
            add('SOURCE_DIMS_MISSING', '源 Cube 缺少维度顺序')
        else:
            fields = {d for d in src_dims}

    declared = {m.target_dimension for m in rel.mapping}
    for dim in dims:
        entry = next((m for m in rel.mapping if m.target_dimension == dim), None)
        if entry is None or entry.kind == 'UNMAPPED':
            add('DIM_UNMAPPED', '目标维度未映射：%s' % dim, dim)
            continue
        if entry.kind == 'FIXED':
            if not entry.fixed_member.strip():
                add('FIXED_MEMBER_EMPTY', '固定成员为空：%s' % dim, dim)
            elif any(ch in entry.fixed_member for ch in '\r\n') or any(ord(c) < 32 for c in entry.fixed_member):
                add('FIXED_MEMBER_UNSAFE', '固定成员包含换行或控制字符：%s' % dim, dim)
        elif entry.kind == 'FROM_SOURCE':
            if not entry.source_field.strip():
                add('SOURCE_FIELD_EMPTY', '来源字段为空：%s' % dim, dim)
            elif entry.source_field not in fields:
                add('SOURCE_FIELD_UNKNOWN', '映射的源字段不在 Schema 中：%s' % entry.source_field, dim)
        elif entry.kind == 'LOOKUP':
            add('LOOKUP_UNSUPPORTED', '查找映射（LOOKUP）当前模板不支持生成：%s' % dim, dim)
        elif entry.kind == 'FROM_CONTEXT':
            add('CONTEXT_UNSUPPORTED', '上下文映射（FROM_CONTEXT）当前模板不支持生成：%s' % dim, dim)
        elif entry.kind == 'EXPRESSION':
            if not entry.expression.strip():
                add('EXPRESSION_EMPTY', '表达式为空：%s' % dim, dim)
            else:
                ok, reason = validate_expression(entry.expression)
                if not ok:
                    add('UNSAFE_EXPRESSION', '表达式不在安全子集内（%s）：%s' % (reason, dim), dim)
        if entry.kind != 'UNMAPPED' and not entry.confirmed:
            add('DIM_UNCONFIRMED', '目标维度映射尚未确认：%s' % dim, dim)

    for extra in sorted(declared - set(dims)):
        add('EXTRA_DIM_MAPPING', '映射维度不属于目标 Cube：%s' % extra, extra)

    # 名称进入代码字面量 / 注释前必须无换行与控制字符，否则会拼接出额外语句
    from tm1_insight.codegen_safety import unsafe_name_reason

    names: list[tuple[str, str]] = []
    if rel.target.kind == 'cube_draft' and target is not None:
        names.append(('目标 Cube 名称', target.name))
    if rel.source.kind == 'cube_draft':
        src_cube = design.cube(rel.source.ref)
        if src_cube is not None:
            names.append(('源 Cube 名称', src_cube.name))
    else:
        schema = design.schema(rel.source.ref)
        if schema is not None:
            names.append(('来源文件名称', schema.name))
            for f in schema.fields:
                names.append(('字段名', f.name))
    for dim in dims:
        names.append(('目标维度名称', dim))
    for label, value in names:
        reason = unsafe_name_reason(value)
        if reason:
            add('UNSAFE_NAME', '%s不可用于生成：%s（%s）' % (label, reason, value))

    # 清空范围：无法确定范围时必须阻断，不能依赖「空筛选 = 清空整库」的默认行为
    if rel.clear_policy == 'target_scope':
        scope = clear_scope_filters(rel, dims)
        if not scope:
            add('CLEAR_SCOPE_UNDEFINED',
                '清空策略为「清空目标范围」，但没有任何已确认的固定成员可用于限定范围；'
                '空筛选会让 Bedrock 清空整个目标 Cube。请设置固定成员，或把清空策略改为「不清空」。')

    return issues


def validate_relation(design: Design, rel: DesignRelation,
                      existing_cube_dims: dict[str, list[str]] | None = None) -> list[str]:
    """兼容接口：只返回消息文本。"""
    return [i['message'] for i in preflight(design, rel, existing_cube_dims)]


def _mapping_dict(rel: DesignRelation) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in rel.mapping:
        spec = m.as_codegen_spec()
        if spec:
            out[m.target_dimension] = spec
    return out


def design_fingerprint(design: Design, rel_id: str) -> str:
    """与生成结果绑定的设计指纹：仅覆盖影响代码的字段。"""
    import hashlib, json

    rel = design.relation(rel_id)
    if rel is None:
        return ''
    payload = {
        'relation': rel.model_dump(exclude={'note', 'generated'}),
        'target': design.cube(rel.target.ref).model_dump() if design.cube(rel.target.ref) else rel.target.ref,
        'source_cube': design.cube(rel.source.ref).model_dump() if design.cube(rel.source.ref) else None,
        'schema': design.schema(rel.source.ref).model_dump() if design.schema(rel.source.ref) else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def code_fingerprint(code: dict) -> str:
    import hashlib
    body = '\n'.join(code.get(s, '') for s in ('prolog', 'metadata', 'data', 'epilog'))
    return hashlib.sha256(body.encode('utf-8')).hexdigest()[:32]


def stale_relations(design: Design, rel_ids: list[str] | None = None) -> list[dict]:
    """返回已生成但设计已变化的关系（代码草案不再代表当前设计）。"""
    out: list[dict] = []
    for rel in design.relations:
        if rel_ids and rel.id not in rel_ids:
            continue
        gen = rel.generated or {}
        stored = gen.get('design_fingerprint')
        if not stored:
            continue
        current = design_fingerprint(design, rel.id)
        if current != stored:
            out.append(dict(relation_id=rel.id, generated_at=gen.get('generated_at', ''),
                            stored_fingerprint=stored, current_fingerprint=current))
    return out


def is_stale(artifact: dict, design: Design) -> bool:
    """生成结果是否因设计变化而失效。"""
    stored = (artifact or {}).get('summary', {}).get('design_fingerprint')
    if not stored:
        return True
    return stored != design_fingerprint(design, artifact.get('relation_id', ''))


def generate(design: Design, rel_id: str, *, existing_cube_dims: dict[str, list[str]] | None = None,
             operation: str | None = None, generated_at: str = '') -> dict:
    """调用既有 codegen 生成 TI 草案。预检不过时不返回任何代码。"""
    from tm1_insight.codegen_safety import dependency_manifest
    from tm1_insight.store import codegen as cg

    rel = design.relation(rel_id)
    if rel is None:
        return dict(status='blocked', blockers=['设计关系不存在'], issues=[
            {'code': 'RELATION_MISSING', 'message': '设计关系不存在'}], code=None)

    issues = preflight(design, rel, existing_cube_dims)
    if issues:
        blockers = [i['message'] for i in issues]
        artifact = GeneratedArtifact(relation_id=rel.id, template=rel.template,
                                     generated_at=generated_at, blockers=blockers)
        return dict(status='blocked', blockers=blockers, issues=issues, code=None,
                    artifact=artifact.model_dump())

    op = operation or ('CellPutN' if rel.write_policy == 'overwrite' else 'CellIncrementN')
    mapping = _mapping_dict(rel)
    clear = rel.clear_policy
    if rel.target.kind == 'cube_draft':
        _tgt = design.cube(rel.target.ref)
        _tgt_dims = _tgt.dim_names if _tgt else []
    else:
        _tgt_dims = (existing_cube_dims or {}).get(rel.target.ref, [])
    clear_filters = clear_scope_filters(rel, _tgt_dims) if clear == 'target_scope' else []

    if rel.source.kind == 'csv':
        schema = design.schema(rel.source.ref)
        cube = design.cube(rel.target.ref)
        dims = cube.dim_names if cube else existing_cube_dims[rel.target.ref]
        result = cg.csv_to_cube(
            rel.target.ref if cube is None else cube.name,
            dims,
            [{'name': f.name, 'type': f.type if f.type != 'unknown' else 'string'} for f in schema.fields],
            mapping, value_source=rel.value_source, operation=op, clear_policy=clear,
            file_path=schema.name, tgt_filters=clear_filters,
        )
        if result.get('unresolved'):
            issues = [{'code': 'CODEGEN_UNRESOLVED', 'message': m} for m in result['unresolved']]
            return dict(status='blocked', code=None, issues=issues,
                        blockers=[i['message'] for i in issues],
                        artifact=GeneratedArtifact(relation_id=rel.id, template=rel.template,
                                                   generated_at=generated_at,
                                                   blockers=[i['message'] for i in issues]).model_dump())
    else:
        src_cube = design.cube(rel.source.ref) if rel.source.kind == 'cube_draft' else None
        src_name = src_cube.name if src_cube else rel.source.ref
        src_dims = src_cube.dim_names if src_cube else (existing_cube_dims or {}).get(rel.source.ref, [])
        tgt_cube = design.cube(rel.target.ref) if rel.target.kind == 'cube_draft' else None
        tgt_name = tgt_cube.name if tgt_cube else rel.target.ref
        tgt_dims = tgt_cube.dim_names if tgt_cube else (existing_cube_dims or {}).get(rel.target.ref, [])
        result = cg.data_transfer(None, src_name, tgt_name,
                                  src_dims=src_dims, tgt_dims=tgt_dims,
                                  dim_mapping=mapping, operation=op, clear_policy=clear,
                                  tgt_filters=clear_filters)
        if result.get('unmapped'):
            issues = [{'code': 'DIM_UNMAPPED', 'message': '目标维度未映射：%s' % d} for d in result['unmapped']]
            return dict(status='blocked', code=None, issues=issues,
                        blockers=[i['message'] for i in issues],
                        artifact=GeneratedArtifact(relation_id=rel.id, template=rel.template,
                                                   generated_at=generated_at,
                                                   blockers=[i['message'] for i in issues]).model_dump())

    fp = design_fingerprint(design, rel.id)
    clear_scope = result.get('clear_scope', 'NONE')
    if clear_scope == 'UNSCOPED_WHOLE_CUBE':
        # 理论上预检已挡住；这里是纵深防御，绝不返回可执行的危险草案
        msg = ('清空范围无法限定：生成结果会清空整个目标 Cube，已阻止返回代码。'
               '请设置固定成员改为可描述的切片，或把清空策略改为「不清空」。')
        return dict(status='blocked', code=None,
                    issues=[{'code': 'CLEAR_SCOPE_UNDEFINED', 'message': msg}],
                    blockers=[msg],
                    artifact=GeneratedArtifact(relation_id=rel.id, template=rel.template,
                                               generated_at=generated_at,
                                               blockers=[msg]).model_dump())
    summary = {
        'source': rel.source.ref,
        'target': result.get('tgt_cube', ''),
        'dimensions': ' → '.join(result.get('tgt_dims', [])),
        'operation': op,
        'write_policy': rel.write_policy,
        'clear_policy': clear,
        'clear_scope': clear_scope,
        'clear_scope_text': describe_clear_scope(result.get('clear_filters') or []),
        'design_fingerprint': fp,
        'code_fingerprint': code_fingerprint(result),
    }
    artifact = GeneratedArtifact(relation_id=rel.id, template=rel.template, generated_at=generated_at,
                                 validated=True, blockers=[], summary=summary)
    deps = dependency_manifest(rel.template, target_cube=summary['target'],
                               target_dims=result.get('tgt_dims', []),
                               clear_policy=clear)
    process_config = {
        'datasource': result.get('datasource'),
        'data_source_variables': result.get('data_source_variables') or [],
        'note': ('四段代码不包含 Process 的 Parameters / Data Source / Variables 三处配置；'
                 '数据源变量必须在 Process 的 Variables 页签按顺序创建，名称与上表一致，'
                 '否则生成代码会引用不存在的变量。'),
    }
    return dict(status='ok', blockers=[], issues=[], code=result, artifact=artifact.model_dump(),
                summary=summary, dependencies=deps, process_config=process_config,
                warnings=result.get('warnings') or [])


def cube_creation_spec(design: Design, cube_id: str) -> dict:
    """Cube 创建说明。只给规格与步骤，不声称已部署。"""
    cube = design.cube(cube_id)
    if cube is None:
        return dict(status='missing', spec=None)
    steps = []
    dims = []
    for i, ref in enumerate(cube.dimensions, 1):
        if ref.kind == 'existing':
            dims.append(dict(position=i, name=ref.name, source='EXISTING_SNAPSHOT', draft_id=None))
            steps.append('%d. 复用已有维度 %s（当前快照存在）' % (i, ref.name))
        else:
            draft = next((d for d in design.dimensions if d.id == ref.draft_id), None)
            elements = draft.elements if draft else []
            dims.append(dict(position=i, name=ref.name, source='DESIGN_DRAFT',
                             draft_id=ref.draft_id, element_type=draft.element_type if draft else 'S',
                             elements=len(elements)))
            steps.append('%d. 先创建维度草稿 %s（%d 个元素），再加入 Cube'
                         % (i, ref.name, len(elements)))
    steps.append('%d. 按上述顺序创建 Cube %s（顺序即 TM1 维度顺序）' % (len(dims) + 1, cube.name))
    return dict(status='DESIGN_DRAFT', spec=dict(name=cube.name, note=cube.note, dimensions=dims,
                                                 steps=steps, provenance='DESIGN_DRAFT'))
