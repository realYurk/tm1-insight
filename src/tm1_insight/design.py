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
            var = re.sub(r'[^0-9A-Za-z_]', '', self.source_field)
            return {'source': 'v' + (var[:1].upper() + var[1:] if var else 'Value')}
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
    template: Literal['cube-data-transfer', 'csv-to-cube'] = 'csv-to-cube'
    confirmed: bool = False
    note: str = Field(default='', max_length=2000)
    provenance: Literal['DESIGN_RELATION'] = 'DESIGN_RELATION'

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


def validate_relation(design: Design, rel: DesignRelation,
                      existing_cube_dims: dict[str, list[str]] | None = None) -> list[str]:
    """返回阻断问题列表（空 = 可以生成）。消息面向用户，不暴露内部异常。"""
    blockers: list[str] = []
    target = design.cube(rel.target.ref) if rel.target.kind == 'cube_draft' else None
    if rel.target.kind == 'cube_draft' and target is None:
        return ['目标 Cube 草稿不存在']
    if rel.target.kind == 'cube':
        dims = (existing_cube_dims or {}).get(rel.target.ref) or []
        if not dims:
            return ['目标 Cube 不在当前快照中，无法取得维度顺序']
    else:
        dims = target.dim_names

    if rel.source.kind == 'csv':
        schema = design.schema(rel.source.ref)
        if schema is None:
            return ['CSV Schema 不存在']
        if rel.template != 'csv-to-cube':
            blockers.append('CSV 来源必须使用 csv-to-cube 模板')
        if not rel.value_source:
            blockers.append('未指定数值来源列')
        elif rel.value_source not in {f.name for f in schema.fields}:
            blockers.append('数值来源列不在 Schema 字段中：%s' % rel.value_source)
    else:
        if rel.template != 'cube-data-transfer':
            blockers.append('Cube 来源必须使用 cube-data-transfer 模板')
        src_dims = _source_variables(design, rel)
        if not src_dims:
            blockers.append('源 Cube 缺少维度顺序')

    declared = {m.target_dimension for m in rel.mapping}
    for dim in dims:
        entry = next((m for m in rel.mapping if m.target_dimension == dim), None)
        if entry is None or entry.kind == 'UNMAPPED':
            blockers.append('目标维度未映射：%s' % dim)
        elif entry.kind == 'FIXED' and not entry.fixed_member.strip():
            blockers.append('固定成员为空：%s' % dim)
        elif entry.kind in ('FROM_SOURCE', 'LOOKUP') and not entry.source_field.strip():
            blockers.append('来源字段为空：%s' % dim)
        elif entry.kind == 'EXPRESSION' and not entry.expression.strip():
            blockers.append('表达式为空：%s' % dim)
        elif not entry.confirmed:
            blockers.append('目标维度映射尚未确认：%s' % dim)
    for extra in sorted(declared - set(dims)):
        blockers.append('映射维度不属于目标 Cube：%s' % extra)

    if rel.source.kind == 'csv':
        fields = {f.name for f in (design.schema(rel.source.ref).fields if design.schema(rel.source.ref) else [])}
        for m in rel.mapping:
            if m.kind == 'FROM_SOURCE' and m.source_field not in fields:
                blockers.append('映射的源字段不在 Schema 中：%s' % m.source_field)
    return blockers


def _mapping_dict(rel: DesignRelation) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in rel.mapping:
        spec = m.as_codegen_spec()
        if spec:
            out[m.target_dimension] = spec
    return out


def generate(design: Design, rel_id: str, *, existing_cube_dims: dict[str, list[str]] | None = None,
             operation: str | None = None, generated_at: str = '') -> dict:
    """调用既有 codegen 生成 TI 草案。阻断时不返回代码。"""
    from tm1_insight.store import codegen as cg

    rel = design.relation(rel_id)
    if rel is None:
        return dict(status='blocked', blockers=['设计关系不存在'], code=None)

    blockers = validate_relation(design, rel, existing_cube_dims)
    if blockers:
        return dict(status='blocked', blockers=blockers, code=None,
                    artifact=GeneratedArtifact(relation_id=rel.id, template=rel.template,
                                               generated_at=generated_at, blockers=blockers).model_dump())

    op = operation or ('CellPutN' if rel.write_policy == 'overwrite' else 'CellIncrementN')
    mapping = _mapping_dict(rel)

    if rel.source.kind == 'csv':
        schema = design.schema(rel.source.ref)
        cube = design.cube(rel.target.ref)
        dims = cube.dim_names if cube else existing_cube_dims[rel.target.ref]
        result = cg.csv_to_cube(
            rel.target.ref if cube is None else cube.name,
            dims,
            [{'name': f.name, 'type': f.type if f.type != 'unknown' else 'string'} for f in schema.fields],
            mapping, value_source=rel.value_source, operation=op,
        )
    else:
        src_cube = design.cube(rel.source.ref) if rel.source.kind == 'cube_draft' else None
        src_name = src_cube.name if src_cube else rel.source.ref
        src_dims = src_cube.dim_names if src_cube else (existing_cube_dims or {}).get(rel.source.ref, [])
        tgt_cube = design.cube(rel.target.ref) if rel.target.kind == 'cube_draft' else None
        tgt_name = tgt_cube.name if tgt_cube else rel.target.ref
        tgt_dims = tgt_cube.dim_names if tgt_cube else (existing_cube_dims or {}).get(rel.target.ref, [])
        result = cg.data_transfer(None, src_name, tgt_name,
                                  src_dims=src_dims, tgt_dims=tgt_dims,
                                  dim_mapping=mapping, operation=op)
        if result.get('unmapped'):
            return dict(status='blocked', code=None,
                        blockers=['目标维度未映射：%s' % d for d in result['unmapped']],
                        artifact=GeneratedArtifact(relation_id=rel.id, template=rel.template,
                                                   generated_at=generated_at,
                                                   blockers=result['unmapped']).model_dump())

    summary = {
        'source': rel.source.ref,
        'target': result.get('tgt_cube', ''),
        'dimensions': ' → '.join(result.get('tgt_dims', [])),
        'operation': op,
        'write_policy': rel.write_policy,
    }
    artifact = GeneratedArtifact(relation_id=rel.id, template=rel.template, generated_at=generated_at,
                                 validated=True, blockers=[], summary=summary)
    return dict(status='ok', blockers=[], code=result, artifact=artifact.model_dump(), summary=summary)


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
