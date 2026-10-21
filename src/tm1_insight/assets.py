"""工程资产库：Pattern / Blueprint / Verification / Project Instance。

原则
----
- 独立持久化，绝不写入采集库或工作区文件。
- Blueprint 以**逻辑角色**表达，实例化时按绑定重新构建设计，不做字符串替换。
- 角色绑定必须由用户确认；缺少绑定即拒绝实例化。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA = 'engineering-asset-1'
PACKAGE_SCHEMA = 'engineering-asset-package-1'

PATTERN_ID = r'^pat-[a-zA-Z0-9_-]{1,64}$'
BP_ID = r'^bp3-[a-zA-Z0-9_-]{1,64}$'
VC_ID = r'^vc-[a-zA-Z0-9_-]{1,64}$'
PROJ_ID = r'^proj-[a-zA-Z0-9_-]{1,64}$'
ROLE_ID = r'^[a-z][a-z0-9_]{1,40}$'

KINDS = ('pattern', 'blueprint', 'verification', 'project')
DIRS = {'pattern': 'patterns', 'blueprint': 'blueprints',
        'verification': 'verifications', 'project': 'projects'}

STATUS = ('DESIGN_VALIDATED', 'CODE_GENERATED', 'CODE_STATIC_CHECKED',
          'SYNTHETIC_TESTED', 'RUNTIME_VERIFIED')


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def uid(prefix: str) -> str:
    return prefix + hashlib.sha256(os.urandom(16)).hexdigest()[:12]


class RoleSpec(BaseModel):
    """Blueprint 中的一个逻辑角色（技术无关）。"""
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=ROLE_ID)
    label: str = Field(min_length=1, max_length=200)
    kind: Literal['cube', 'dimension', 'field', 'member', 'measure', 'value']
    required: bool = True
    hint: str = Field(default='', max_length=500)
    default: str = Field(default='', max_length=200)


class RoleBinding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: str = Field(pattern=ROLE_ID)
    value: str = Field(min_length=1, max_length=200)
    confirmed: bool = False


class TemplateRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    template: Literal['csv-to-cube', 'cube-data-transfer'] = 'csv-to-cube'
    version: str = Field(default='1', max_length=20)


class Pattern(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=PATTERN_ID)
    schema_version: Literal['engineering-asset-1'] = SCHEMA
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(default='', max_length=1000)
    problem: str = Field(default='', max_length=2000)
    inputs: list[str] = Field(default_factory=list, max_length=40)
    outputs: list[str] = Field(default_factory=list, max_length=40)
    steps: list[str] = Field(default_factory=list, max_length=40)
    applies_when: list[str] = Field(default_factory=list, max_length=20)
    not_applicable: list[str] = Field(default_factory=list, max_length=20)
    template: TemplateRef | None = None
    verification_ids: list[str] = Field(default_factory=list, max_length=20)
    blueprint_ids: list[str] = Field(default_factory=list, max_length=40)
    version: int = Field(default=1, ge=1, le=1000)
    status: Literal['DRAFT', 'REVIEWED', 'VERIFIED'] = 'DRAFT'
    origin: Literal['USER_INPUT', 'EXTRACTED_FROM_PROJECT', 'IMPORTED'] = 'USER_INPUT'
    created_at: str = Field(default_factory=now, max_length=40)
    updated_at: str = Field(default_factory=now, max_length=40)


class VerificationRequirement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=ROLE_ID)
    label: str = Field(min_length=1, max_length=300)
    kind: Literal['structure', 'mapping', 'type', 'dependency', 'idempotency',
                  'clear_scope', 'precision', 'write_target'] = 'structure'
    severity: Literal['BLOCKER', 'WARNING', 'INFO'] = 'BLOCKER'
    checked_by: Literal['preflight', 'static', 'synthetic', 'manual'] = 'preflight'


class VerificationContract(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=VC_ID)
    schema_version: Literal['engineering-asset-1'] = SCHEMA
    name: str = Field(min_length=1, max_length=200)
    requirements: list[VerificationRequirement] = Field(default_factory=list, max_length=60)
    revision: int = Field(default=1, ge=1, le=1000)
    created_at: str = Field(default_factory=now, max_length=40)


class BlueprintMapping(BaseModel):
    """目标维度（以角色表达）→ 该维度如何取值。"""
    model_config = ConfigDict(extra='forbid')
    dim_role: str = Field(pattern=ROLE_ID)
    kind: Literal['FIXED', 'FROM_SOURCE', 'EXPRESSION'] = 'FIXED'
    source_role: str = Field(default='', max_length=80)   # field/member/value 角色
    confirmed: bool = False


class ReusableBlueprint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=BP_ID)
    schema_version: Literal['engineering-asset-1'] = SCHEMA
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(default='', max_length=1000)
    pattern_id: str = Field(default='', max_length=80)
    template: TemplateRef = Field(default_factory=TemplateRef)
    roles: list[RoleSpec] = Field(min_length=1, max_length=120)
    dimension_order: list[str] = Field(min_length=1, max_length=60)
    mappings: list[BlueprintMapping] = Field(default_factory=list, max_length=60)
    value_role: str = Field(default='value_field', max_length=80)
    write_policy: Literal['overwrite', 'accumulate'] = 'overwrite'
    clear_policy: Literal['target_scope', 'none'] = 'target_scope'
    verification_id: str = Field(default='', max_length=80)
    version: int = Field(default=1, ge=1, le=1000)
    status: Literal['DRAFT', 'REVIEWED', 'VERIFIED'] = 'DRAFT'
    origin: Literal['USER_INPUT', 'EXTRACTED_FROM_PROJECT', 'IMPORTED'] = 'USER_INPUT'
    source_project: str = Field(default='', max_length=200)
    restricted: bool = True   # 默认视为含项目信息，导出需人工确认
    created_at: str = Field(default_factory=now, max_length=40)
    updated_at: str = Field(default_factory=now, max_length=40)

    @model_validator(mode='after')
    def _refs(self):
        ids = {r.id for r in self.roles}
        if len(ids) != len(self.roles):
            raise ValueError('角色 id 不能重复')
        if not set(self.dimension_order) <= ids:
            raise ValueError('维度顺序引用了不存在的角色')
        for m in self.mappings:
            if m.dim_role not in self.dimension_order:
                raise ValueError('映射引用了不在维度顺序中的角色')
            if m.source_role and m.source_role not in ids:
                raise ValueError('映射引用了不存在的来源角色')
        if self.value_role not in ids:
            raise ValueError('数值角色不存在')
        return self

    def role(self, role_id: str) -> RoleSpec | None:
        return next((r for r in self.roles if r.id == role_id), None)


class ProjectInstance(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=PROJ_ID)
    schema_version: Literal['engineering-asset-1'] = SCHEMA
    name: str = Field(min_length=1, max_length=200)
    blueprint_id: str = Field(default='', max_length=80)
    blueprint_version: int = Field(default=0, ge=0, le=1000)
    snapshot_id: str = Field(default='', max_length=128)
    bindings: list[RoleBinding] = Field(default_factory=list, max_length=200)
    design: dict = Field(default_factory=dict)
    workspace_id: str = Field(default='', max_length=64)
    status: Literal['BOUND', 'GENERATED', 'FAILED'] = 'BOUND'
    verification_status: Literal['', *STATUS] = ''
    generated_at: str = Field(default='', max_length=40)
    code_fingerprint: str = Field(default='', max_length=64)
    note: str = Field(default='', max_length=2000)
    created_at: str = Field(default_factory=now, max_length=40)
    updated_at: str = Field(default_factory=now, max_length=40)


# ---------------------------------------------------------------- 存储

_lock = threading.Lock()


def assets_root(base: Path) -> Path:
    return Path(base) / 'assets'


def _path(root: Path, kind: str, key: str) -> Path:
    if kind not in DIRS:
        raise ValueError('未知资产类型')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', key):
        raise ValueError('非法资产 id')
    return assets_root(root) / DIRS[kind] / (key + '.json')


def _atomic_write(path: Path, data: bytes, expected: str = '') -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        if path.exists():
            old = path.read_bytes()
            current = hashlib.sha256(old).hexdigest()
            if expected and current != expected:
                raise FileExistsError('资产已变化，请重新加载后再保存')
            backup = path.with_suffix('.json.bak')
            backup.write_bytes(old)
        elif expected:
            raise FileExistsError('资产已不存在')
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.asset-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return hashlib.sha256(data).hexdigest()


def save(kind: str, obj: BaseModel, base: Path, expected: str = '') -> str:
    obj.updated_at = now()
    path = _path(base, kind, obj.id)
    return _atomic_write(path, obj.model_dump_json(indent=2).encode('utf-8'), expected)


def load(kind: str, key: str, base: Path) -> tuple[BaseModel, str]:
    path = _path(base, kind, key)
    raw = path.read_bytes()
    if len(raw) > 512 * 1024:
        raise ValueError('资产文件超限')
    model = {'pattern': Pattern, 'blueprint': ReusableBlueprint,
             'verification': VerificationContract, 'project': ProjectInstance}[kind]
    return model.model_validate_json(raw), hashlib.sha256(raw).hexdigest()


def listing(kind: str, base: Path) -> list[dict]:
    folder = assets_root(base) / DIRS[kind]
    out = []
    if not folder.exists():
        return out
    for path in sorted(folder.glob('*.json')):
        try:
            item, rev = load(kind, path.stem, base)
        except Exception:
            out.append(dict(id=path.stem, name='不可读取（原文件保留）', broken=True))
            continue
        row = dict(id=item.id, name=item.name, revision=rev,
                   version=getattr(item, 'version', 1),
                   status=getattr(item, 'status', ''))
        if kind == 'blueprint':
            row.update(template=item.template.template, roles=len(item.roles),
                       dimension_order=len(item.dimension_order))
        out.append(row)
    return out


def delete(kind: str, key: str, base: Path) -> None:
    path = _path(base, kind, key)
    if not path.exists():
        raise FileNotFoundError('资产不存在')
    path.unlink()


# ---------------------------------------------------------------- 角色与实例化

def roles_from_design(design, relation_id: str) -> dict:
    """从已完成的实例中提炼角色（不做业务语义推测）。

    角色标签沿用原名称，用户需要在导出前确认哪些应改为通用描述。
    """
    rel = design.relation(relation_id)
    if rel is None:
        raise ValueError('设计关系不存在')
    target = design.cube(rel.target.ref)
    if target is None:
        raise ValueError('仅支持从 Cube 草稿关系提炼 Blueprint')
    roles: list[RoleSpec] = [RoleSpec(id='target_cube', label=target.name, kind='cube',
                                      hint='目标分析 Cube 的名称')]
    order: list[str] = []
    mappings: list[BlueprintMapping] = []
    for i, ref in enumerate(target.dimensions, 1):
        dim_role = 'dim_%d' % i
        order.append(dim_role)
        roles.append(RoleSpec(id=dim_role, label=ref.name, kind='dimension',
                              hint='第 %d 个目标维度（顺序固定）' % i))
        entry = next((m for m in rel.mapping if m.target_dimension == ref.name), None)
        if entry is None:
            mappings.append(BlueprintMapping(dim_role=dim_role, kind='FIXED', confirmed=False))
            continue
        if entry.kind == 'FIXED':
            role_id = 'member_%d' % i
            roles.append(RoleSpec(id=role_id, label=entry.fixed_member, kind='member',
                                  hint='%s 的固定成员' % ref.name))
            mappings.append(BlueprintMapping(dim_role=dim_role, kind='FIXED',
                                             source_role=role_id, confirmed=entry.confirmed))
        elif entry.kind == 'FROM_SOURCE':
            role_id = 'field_%d' % i
            roles.append(RoleSpec(id=role_id, label=entry.source_field, kind='field',
                                  hint='%s 的来源字段' % ref.name))
            mappings.append(BlueprintMapping(dim_role=dim_role, kind='FROM_SOURCE',
                                             source_role=role_id, confirmed=entry.confirmed))
        elif entry.kind == 'EXPRESSION':
            role_id = 'expr_%d' % i
            roles.append(RoleSpec(id=role_id, label=entry.expression, kind='value',
                                  hint='%s 的表达式（安全子集）' % ref.name))
            mappings.append(BlueprintMapping(dim_role=dim_role, kind='EXPRESSION',
                                             source_role=role_id, confirmed=entry.confirmed))
        else:
            mappings.append(BlueprintMapping(dim_role=dim_role, kind='FIXED', confirmed=False))
    roles.append(RoleSpec(id='value_field', label=rel.value_source or '', kind='field',
                          hint='提供数值的字段'))
    roles.append(RoleSpec(id='source_name', label=design.schema(rel.source.ref).name
                          if design.schema(rel.source.ref) else 'source.csv',
                          kind='value', hint='来源数据集名称', required=False))
    return dict(roles=roles, dimension_order=order, mappings=mappings,
                value_role='value_field', template=rel.template,
                write_policy=rel.write_policy, clear_policy=rel.clear_policy)


def validate_bindings(blueprint: ReusableBlueprint, bindings: list[RoleBinding]) -> list[str]:
    """返回阻断问题（空 = 可以实例化）。"""
    issues: list[str] = []
    given = {b.role: b for b in bindings}
    known = {r.id for r in blueprint.roles}
    seen: set[str] = set()
    for b in bindings:
        if b.role in seen:
            issues.append('角色被重复绑定：%s（同一角色只能有一个值）' % b.role)
        seen.add(b.role)
    for extra in sorted(set(given) - known):
        issues.append('未知角色：%s' % extra)
    for role in blueprint.roles:
        if not role.required:
            continue
        b = given.get(role.id)
        if b is None or not b.value.strip():
            issues.append('必需角色未绑定：%s（%s）' % (role.label, role.id))
        elif role.kind in ('dimension', 'field', 'member') and any(ch in b.value for ch in '\r\n'):
            issues.append('角色绑定值包含换行：%s' % role.id)
    dims = [given[r].value.strip() for r in blueprint.dimension_order if r in given]
    if len({d.casefold() for d in dims}) != len(dims):
        issues.append('绑定后的目标维度名重复')
    for m in blueprint.mappings:
        if m.kind != 'EXPRESSION' and m.source_role:
            b = given.get(m.source_role)
            if b is None or not b.value.strip():
                issues.append('映射来源角色未绑定：%s' % m.source_role)
        if m.kind == 'EXPRESSION' and m.source_role:
            from tm1_insight.codegen_safety import validate_expression
            b = given.get(m.source_role)
            ok, reason = validate_expression(b.value if b else '')
            if not ok:
                issues.append('表达式角色不安全（%s）：%s' % (reason, m.source_role))
    return issues


def instantiate(blueprint: ReusableBlueprint, bindings: list[RoleBinding],
                project_name: str, *, object_id: str = '') -> dict:
    """按绑定生成一份设计（Design dict）。不做任何字符串替换。"""
    issues = validate_bindings(blueprint, bindings)
    if issues:
        raise ValueError('；'.join(issues))
    given = {b.role: b.value.strip() for b in bindings}
    roles = {r.id: r for r in blueprint.roles}

    dim_names = [given[r] for r in blueprint.dimension_order]
    cube_id = object_id or uid('draft-')
    schema_id = uid('csv-')

    dims = []
    mapping = []
    fields: dict[str, dict] = {}
    for dim_role, dim_name in zip(blueprint.dimension_order, dim_names):
        dims.append({'kind': 'existing', 'name': dim_name})
        m = next((x for x in blueprint.mappings if x.dim_role == dim_role), None)
        if m is None:
            continue
        if m.kind == 'FIXED':
            value = given.get(m.source_role, '')
            if not value:
                raise ValueError('固定成员未绑定：%s' % dim_name)
            mapping.append({'target_dimension': dim_name, 'kind': 'FIXED',
                            'fixed_member': value, 'source_field': '', 'expression': '',
                            'confirmed': True})
        elif m.kind == 'FROM_SOURCE':
            value = given.get(m.source_role, '')
            if not value:
                raise ValueError('来源字段未绑定：%s' % dim_name)
            mapping.append({'target_dimension': dim_name, 'kind': 'FROM_SOURCE',
                            'fixed_member': '', 'source_field': value, 'expression': '',
                            'confirmed': True})
            fields.setdefault(value, {'name': value, 'type': 'string', 'required': False, 'note': ''})
        elif m.kind == 'EXPRESSION':
            value = given.get(m.source_role, '')
            mapping.append({'target_dimension': dim_name, 'kind': 'EXPRESSION',
                            'fixed_member': '', 'source_field': '', 'expression': value,
                            'confirmed': True})

    value_field = given.get(blueprint.value_role, '')
    if not value_field:
        raise ValueError('数值来源字段未绑定')
    fields.setdefault(value_field, {'name': value_field, 'type': 'number', 'required': True, 'note': ''})

    schema_name = given.get('source_name') or (project_name + '.csv')
    design = {
        'mode': 'design',
        'dimensions': [],
        'cubes': [{'id': cube_id, 'name': given['target_cube'], 'note': '',
                   'dimensions': dims, 'measures': [], 'provenance': 'DESIGN_DRAFT'}],
        'schemas': [{'id': schema_id, 'name': schema_name, 'fields': list(fields.values()),
                     'origin': 'USER_INPUT', 'note': '', 'provenance': 'DESIGN_DRAFT'}],
        'relations': [{
            'id': uid('rel-'),
            'source': {'kind': 'csv', 'ref': schema_id},
            'target': {'kind': 'cube_draft', 'ref': cube_id},
            'mapping': mapping,
            'value_source': value_field,
            'write_policy': blueprint.write_policy,
            'clear_policy': blueprint.clear_policy,
            'template': blueprint.template.template,
            'confirmed': True,
            'note': '由 Blueprint %s v%d 实例化，需重新验证' % (blueprint.name, blueprint.version),
            'provenance': 'DESIGN_RELATION',
        }],
        'blueprints': [],
    }
    return dict(design=design, cube_id=cube_id, schema_id=schema_id,
                relation_id=design['relations'][0]['id'])
