"""资产包：导出预检、打包、导入校验。

安全边界：
- 导出分 private / public 两种范围；public 遇到阻断项直接拒绝。
- 导入只做结构校验与落盘候选，不执行任何包内代码，不覆盖同名资产。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from tm1_insight import assets as A

MAX_BYTES = 5 * 1024 * 1024
ALLOWED_DIRS = ('blueprints/', 'patterns/', 'verifications/', 'projects/')

ABS_PATH = re.compile(r'(?:[A-Za-z]:\\|[A-Za-z]:/|/home/|/Users/)')
CRED = re.compile(r'(?i)(password|passwd|secret|api[_-]?key|bearer\s+[A-Za-z0-9._-]{10,}|token\s*=)')


def _walk(value, path=''):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, path + '/' + str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, path + '[%d]' % i)
    else:
        yield path, value


def scan_blueprint(bp: A.ReusableBlueprint) -> list[dict]:
    """导出前内容审查。返回 findings：{code, severity, path, hint}。"""
    findings: list[dict] = []
    payload = bp.model_dump()
    for path, value in _walk(payload):
        text = str(value)
        if ABS_PATH.search(text):
            findings.append(dict(code='ABSOLUTE_PATH', severity='BLOCKER', path=path,
                                 hint='包含本机绝对路径，请改为相对或占位'))
        if CRED.search(text):
            findings.append(dict(code='CREDENTIAL_LIKE', severity='BLOCKER', path=path,
                                 hint='疑似凭据内容，必须移除'))
    if bp.restricted:
        findings.append(dict(code='RESTRICTED_SOURCE', severity='BLOCKER', path='restricted',
                             hint='该 Blueprint 标记为含项目信息；对外发布前需人工改为通用并解除限制'))
    members = [r for r in bp.roles if r.kind == 'member']
    if members:
        findings.append(dict(code='FIXED_MEMBERS', severity='WARNING', path='roles',
                             hint='包含固定业务成员：%d 个，发布前请确认是否可公开' % len(members)))
    dims = [r.label for r in bp.roles if r.kind == 'dimension']
    if dims:
        findings.append(dict(code='BUSINESS_NAMES', severity='WARNING', path='roles',
                             hint='包含业务维度名称：%s' % '、'.join(dims[:5])))
    if bp.source_project:
        findings.append(dict(code='PROJECT_REFERENCE', severity='WARNING', path='source_project',
                             hint='记录了来源项目名称'))
    return findings


def export_preflight(blueprints, patterns, verifications, scope: str) -> dict:
    findings = []
    for bp in blueprints:
        findings += [dict(item=dict(kind='blueprint', id=bp.id), **f) for f in scan_blueprint(bp)]
    blockers = [f for f in findings if f['severity'] == 'BLOCKER']
    if scope == 'public' and blockers:
        return dict(ok=False, scope=scope, findings=findings, blockers=blockers,
                    message='存在 %d 项阻断内容，不能生成可公开资产包；可改为私有范围导出。' % len(blockers))
    return dict(ok=True, scope=scope, findings=findings, blockers=[],
                message='可导出（%s）' % ('公开' if scope == 'public' else '私有'))


def build_package(blueprints, patterns, verifications, scope: str) -> bytes:
    buf = io.BytesIO()
    files: list[dict] = []
    groups = [('blueprints', blueprints), ('patterns', patterns), ('verifications', verifications)]
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for folder, items in groups:
            for item in items:
                payload = item.model_dump_json(indent=2).encode('utf-8')
                name = '%s/%s.json' % (folder, item.id)
                zf.writestr(name, payload)
                files.append(dict(kind=folder[:-1], id=item.id, name=item.name,
                                  file=name, sha256=hashlib.sha256(payload).hexdigest()))
        manifest = dict(schema=A.PACKAGE_SCHEMA, visibility=scope,
                        created_at=A.now(), tool='TM1 Insight', items=files)
        blob = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
        zf.writestr('manifest.json', blob)
        zf.writestr('README.txt',
                    'TM1 Insight 工程资产包\n'
                    '范围：%s\n'
                    '内容仅包含设计描述与验证记录，不含企业 TI/Rule 源码、快照或数据行。\n'
                    '导入后需重新绑定角色并重新生成代码。\n' % scope)
    return buf.getvalue()


def import_package(data: bytes, base: Path, *, max_bytes: int = MAX_BYTES) -> dict:
    """校验并导入。返回 {imported, skipped, errors}。不覆盖同名资产。"""
    if len(data) > max_bytes:
        return dict(imported=[], skipped=[], errors=['压缩包超过 %d 字节上限' % max_bytes])
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return dict(imported=[], skipped=[], errors=['不是有效的 zip 文件'])
    with zf:
        names = zf.namelist()
        if 'manifest.json' not in names:
            return dict(imported=[], skipped=[], errors=['缺少 manifest.json'])
        for name in names:
            if name.startswith('/') or '..' in Path(name).parts or ':' in name.split('/')[0]:
                return dict(imported=[], skipped=[], errors=['包含不安全路径：%s' % name])
            if name != 'README.txt' and name != 'manifest.json' and not name.startswith(ALLOWED_DIRS):
                return dict(imported=[], skipped=[], errors=['包含不允许的目录：%s' % name])
        try:
            manifest = json.loads(zf.read('manifest.json'))
        except Exception:
            return dict(imported=[], skipped=[], errors=['manifest.json 无法解析'])
        if manifest.get('schema') != A.PACKAGE_SCHEMA:
            return dict(imported=[], skipped=[], errors=['资产包版本不受支持：%s' % manifest.get('schema')])
        imported, skipped, errors = [], [], []
        for item in manifest.get('items', []):
            try:
                blob = zf.read(item['file'])
            except KeyError:
                errors.append('缺少文件：%s' % item.get('file'))
                continue
            if hashlib.sha256(blob).hexdigest() != item.get('sha256'):
                errors.append('校验和不匹配：%s' % item.get('file'))
                continue
            try:
                obj = _parse(item['kind'], blob)
            except Exception as exc:
                errors.append('内容不符合契约（%s）：%s' % (item.get('file'), exc))
                continue
            obj.id = _fresh_id(item['kind'], obj.id)
            if hasattr(obj, 'origin'):
                obj.origin = 'IMPORTED'
            try:
                A.save(item['kind'], obj, base, '')
                imported.append(dict(kind=item['kind'], id=obj.id, name=obj.name))
            except Exception as exc:
                errors.append('写入失败（%s）：%s' % (obj.id, exc))
        return dict(imported=imported, skipped=skipped, errors=errors,
                    visibility=manifest.get('visibility'))


def _parse(kind: str, blob: bytes):
    model = {'blueprint': A.ReusableBlueprint, 'pattern': A.Pattern,
             'verification': A.VerificationContract, 'project': A.ProjectInstance}[kind]
    return model.model_validate_json(blob)


def _fresh_id(kind: str, wanted: str) -> str:
    # 导入一律分配新 id，避免覆盖本地已有同名资产
    prefix = {'blueprint': 'bp3-', 'pattern': 'pat-', 'verification': 'vc-', 'project': 'proj-'}[kind]
    return A.uid(prefix)
