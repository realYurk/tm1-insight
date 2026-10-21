"""工程资产 HTTP 接口：列表、详情、提取、实例化、打包与导入。"""
from __future__ import annotations

import json
from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from tm1_insight import assets as A
from tm1_insight import asset_package as pkg
from tm1_insight.config import get_settings

router = APIRouter()


def root():
    return get_settings().user_data_root


class SaveBody(BaseModel):
    item: dict
    revision: str = Field(default='', max_length=64)


def _model(kind: str):
    return {'pattern': A.Pattern, 'blueprint': A.ReusableBlueprint,
            'verification': A.VerificationContract, 'project': A.ProjectInstance}[kind]


@router.get('/assets', response_class=HTMLResponse)
def assets_page(request: Request):
    from tm1_insight.api.app import templates
    return templates.TemplateResponse(request, 'assets.html', {'active': 'assets'})


@router.get('/api/assets/summary')
def summary():
    data = {kind: A.listing(kind, root()) for kind in A.KINDS}
    return dict(schema=A.SCHEMA,
                counts={k: len(v) for k, v in data.items()},
                items=data,
                statuses=list(A.STATUS),
                package_schema=pkg.A.PACKAGE_SCHEMA)


class ExtractBody(BaseModel):
    design: dict
    relation_id: str = Field(max_length=80)
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(default='', max_length=1000)
    pattern_id: str = Field(default='', max_length=80)
    mark_generic: bool = False


@router.post('/api/assets/extract')
def extract(body: ExtractBody):
    from tm1_insight import design as dg

    try:
        design = dg.Design.model_validate(body.design)
    except Exception as exc:
        raise HTTPException(422, '设计不符合契约：%s' % exc) from exc
    try:
        spec = A.roles_from_design(design, body.relation_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    bp = A.ReusableBlueprint(
        id=A.uid('bp3-'), name=body.name, summary=body.summary,
        pattern_id=body.pattern_id, roles=spec['roles'],
        dimension_order=spec['dimension_order'], mappings=spec['mappings'],
        value_role=spec['value_role'],
        template=A.TemplateRef(template=spec['template']),
        write_policy=spec['write_policy'], clear_policy=spec['clear_policy'],
        restricted=not body.mark_generic,
        origin='EXTRACTED_FROM_PROJECT')
    A.save('blueprint', bp, root(), '')
    return dict(id=bp.id, blueprint=bp.model_dump(),
                findings=pkg.scan_blueprint(bp))


class InstantiateBody(BaseModel):
    blueprint_id: str = Field(max_length=80)
    bindings: list[A.RoleBinding] = Field(default_factory=list, max_length=200)
    project_name: str = Field(min_length=1, max_length=200)
    snapshot_id: str = Field(default='', max_length=128)
    create_workspace: bool = True


@router.post('/api/assets/instantiate')
def instantiate(body: InstantiateBody):
    from tm1_insight import workbench as wb
    from tm1_insight.api.knowledge_tasks import fingerprint

    try:
        bp, _ = A.load('blueprint', body.blueprint_id, root())
    except FileNotFoundError as exc:
        raise HTTPException(404, 'Blueprint 不存在') from exc
    try:
        result = A.instantiate(bp, body.bindings, body.project_name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    settings = get_settings()
    from tm1_insight.api.app import _store
    snapshot = body.snapshot_id or fingerprint(_store().settings)
    workspace_id = ''
    if body.create_workspace:
        workspace_id = uuid4().hex
        ws = wb.Workspace(snapshot_id=snapshot, name=body.project_name,
                          design=result['design'])
        wb.save_workspace(settings.user_data_root / 'workspaces', workspace_id, ws, '')

    project = A.ProjectInstance(
        id=A.uid('proj-'), name=body.project_name, blueprint_id=bp.id,
        blueprint_version=bp.version, snapshot_id=snapshot,
        bindings=body.bindings, design=result['design'],
        workspace_id=workspace_id, status='BOUND')
    A.save('project', project, root(), '')
    return dict(project=project.model_dump(), workspace_id=workspace_id)


class GenerateBody(BaseModel):
    project_id: str = Field(max_length=80)
    verify: bool = False


@router.post('/api/assets/generate')
def generate_project(body: GenerateBody):
    from tm1_insight import design as dg

    try:
        project, rev = A.load('project', body.project_id, root())
    except FileNotFoundError as exc:
        raise HTTPException(404, '项目不存在') from exc
    design = dg.Design.model_validate(project.design)
    rel = design.relations[0] if design.relations else None
    if rel is None:
        raise HTTPException(422, '项目设计缺少关系')
    result = dg.generate(design, rel.id, generated_at=A.now())
    if result['status'] == 'ok':
        project.status = 'GENERATED'
        project.generated_at = A.now()
        project.verification_status = 'CODE_STATIC_CHECKED'
        project.code_fingerprint = result['summary']['code_fingerprint']
    else:
        project.status = 'FAILED'
        project.verification_status = ''
    A.save('project', project, root(), rev)
    verification = dict(
        level=project.verification_status or '',
        label={'CODE_STATIC_CHECKED': '静态结构检查通过（未在 TM1 编译或执行）'}.get(
            project.verification_status, '未验证'),
        checked=['目标维度顺序', '映射完整性', '写入函数参数个数', '清空范围可描述'],
        not_verified=['TM1 编译', 'TM1 执行结果', '数值转换的区域设置', '}APQ / Bedrock 依赖是否就绪'],
    )
    return dict(project=project.model_dump(), status=result['status'],
                blockers=result['blockers'], issues=result.get('issues', []),
                code=result.get('code'), summary=result.get('summary'),
                dependencies=result.get('dependencies'),
                process_config=result.get('process_config'), warnings=result.get('warnings') or [],
                verification=verification)


class ExportBody(BaseModel):
    blueprint_ids: list[str] = Field(default_factory=list, max_length=60)
    pattern_ids: list[str] = Field(default_factory=list, max_length=60)
    verification_ids: list[str] = Field(default_factory=list, max_length=60)
    scope: str = Field(default='private', pattern='^(private|public)$')


def _load_many(kind, ids):
    out = []
    for key in ids:
        item, _ = A.load(kind, key, root())
        out.append(item)
    return out


@router.post('/api/assets/export/preflight')
def export_preflight(body: ExportBody):
    try:
        bps = _load_many('blueprint', body.blueprint_ids)
        pats = _load_many('pattern', body.pattern_ids)
        vcs = _load_many('verification', body.verification_ids)
    except FileNotFoundError as exc:
        raise HTTPException(404, '资产不存在：%s' % exc) from exc
    return pkg.export_preflight(bps, pats, vcs, body.scope)


@router.post('/api/assets/export')
def export(body: ExportBody):
    try:
        bps = _load_many('blueprint', body.blueprint_ids)
        pats = _load_many('pattern', body.pattern_ids)
        vcs = _load_many('verification', body.verification_ids)
    except FileNotFoundError as exc:
        raise HTTPException(404, '资产不存在：%s' % exc) from exc
    report = pkg.export_preflight(bps, pats, vcs, body.scope)
    if not report['ok']:
        raise HTTPException(409, report['message'])
    data = pkg.build_package(bps, pats, vcs, body.scope)
    return StreamingResponse(BytesIO(data), media_type='application/zip',
                             headers={'Content-Disposition': 'attachment; filename="tm1-insight-assets.zip"'})


@router.post('/api/assets/import')
async def import_assets(file: UploadFile = File(...)):
    raw = await file.read()
    result = pkg.import_package(raw, root())
    return result


# ---------------------------------------------------------------- 通用 CRUD（放在最后，避免吞掉上面的固定路径）
@router.get('/api/assets/{kind}')
def list_kind(kind: str):
    if kind not in A.KINDS:
        raise HTTPException(404, '未知资产类型')
    return dict(kind=kind, items=A.listing(kind, root()))


@router.get('/api/assets/{kind}/{key}')
def get_one(kind: str, key: str):
    if kind not in A.KINDS:
        raise HTTPException(404, '未知资产类型')
    try:
        item, revision = A.load(kind, key, root())
    except FileNotFoundError as exc:
        raise HTTPException(404, '资产不存在') from exc
    except Exception as exc:
        raise HTTPException(422, '资产损坏或格式不支持；原文件保留。') from exc
    return dict(kind=kind, revision=revision, item=item.model_dump())


@router.post('/api/assets/{kind}')
def create(kind: str, body: SaveBody):
    if kind not in A.KINDS:
        raise HTTPException(404, '未知资产类型')
    try:
        item = _model(kind).model_validate(body.item)
    except Exception as exc:
        raise HTTPException(422, '资产不符合契约：%s' % exc) from exc
    try:
        revision = A.save(kind, item, root(), '')
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    return dict(id=item.id, revision=revision)


@router.put('/api/assets/{kind}/{key}')
def update(kind: str, key: str, body: SaveBody):
    if kind not in A.KINDS:
        raise HTTPException(404, '未知资产类型')
    try:
        item = _model(kind).model_validate(body.item)
    except Exception as exc:
        raise HTTPException(422, '资产不符合契约：%s' % exc) from exc
    if item.id != key:
        raise HTTPException(422, 'id 与路径不一致')
    try:
        revision = A.save(kind, item, root(), body.revision)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    return dict(id=item.id, revision=revision)


@router.delete('/api/assets/{kind}/{key}')
def remove(kind: str, key: str, force: bool = False):
    """删除资产。被项目实例引用时拒绝，需显式 force 才删除。"""
    if kind not in A.KINDS:
        raise HTTPException(404, '未知资产类型')
    refs: list[dict] = []
    if kind in ('blueprint', 'pattern', 'verification'):
        for row in A.listing('project', root()):
            try:
                proj = A.load('project', row['id'], root())[0]
            except Exception:
                continue
            if getattr(proj, 'blueprint_id', '') == key:
                refs.append(dict(id=proj.id, name=proj.name))
    if refs and not force:
        raise HTTPException(409, {
            'message': '该资产仍被 %d 个项目引用；删除后这些项目将无法重新生成。'
                       '确认删除请附带 force=true。' % len(refs),
            'referencing_projects': refs,
        })
    try:
        A.delete(kind, key, root())
    except FileNotFoundError as exc:
        raise HTTPException(404, '资产不存在') from exc
    return dict(deleted=key, referencing_projects=refs)


