"""Background study reports and generic teaching templates."""
from __future__ import annotations

import io
import json
import zipfile

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response

from tm1_insight.api.knowledge_tasks import fingerprint, manager, _state, _result
from tm1_insight.config import get_settings
from tm1_insight.learning.catalog import CATALOG, template
from tm1_insight.learning.engine import VERSION, markdown
from tm1_insight.learning.worker import isolated_report
from tm1_insight.tasks import TaskBusy

router = APIRouter()


@router.get("/learn")
def learn_page(request: Request):
    from tm1_insight.api.app import templates, _store
    _store()
    return templates.TemplateResponse(request, "learn.html", {})


@router.post("/api/learning/tasks", status_code=202)
def start_learning(body: dict = Body(...)):
    from tm1_insight.datasource import ensure_demo_if_empty
    ensure_demo_if_empty()
    settings = get_settings().model_copy()
    source = fingerprint(settings)
    query = str(body.get("query") or "").strip()
    if not query or len(query) > 200:
        raise HTTPException(400, "请输入不超过 200 字的功能关键词，或用 * 选择整模型。")
    def work(progress):
        result = isolated_report(settings, query, progress)
        if fingerprint(settings) != source:
            raise ValueError("Model changed")
        result["source_fingerprint"] = source
        return result
    key = json.dumps({"engine":VERSION, "query":query}, sort_keys=True)
    try: return manager().submit(key, work, source=source)
    except TaskBusy as exc: raise HTTPException(429, str(exc)) from exc


@router.get("/api/learning/tasks/{task_id}")
def learning_state(task_id: str):
    return _state(task_id)


@router.post("/api/learning/tasks/{task_id}/cancel")
def cancel_learning(task_id: str):
    _state(task_id)
    return manager().cancel(task_id)


@router.get("/api/learning/tasks/{task_id}/result")
def learning_result(task_id: str, section: str = "chapters", offset: int = Query(0, ge=0),
                    limit: int = Query(20, ge=1, le=50), pattern: str = "", q: str = ""):
    report = _result(task_id)
    if report.get("version") != VERSION:
        raise HTTPException(400, "这不是项目学习任务。")
    if section not in {"chapters", "processes", "cubes", "findings", "duplicate_groups"}:
        raise HTTPException(400, "未知结果分类。")
    items = report[section]
    if pattern and section == "processes": items = [p for p in items if pattern in p["patterns"]]
    if q:
        term = q.casefold()
        items = [p for p in items if term in str(p.get("process", p.get("cube", p.get("title", "")))).casefold()]
    return {"summary":report["summary"], "query":report["query"], "sop":report["sop"],
            "limitations":report["limitations"], "total":len(items), "offset":offset,
            "items":items[offset:offset + limit]}


@router.post("/api/learning/tasks/{task_id}/export")
def export_learning(task_id: str):
    report = _result(task_id)
    if report.get("version") != VERSION: raise HTTPException(400, "这不是项目学习任务。")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("READ_ME_FIRST.md", markdown(report))
        archive.writestr("study.json", json.dumps(report, ensure_ascii=False, indent=2))
        archive.writestr("PRIVACY.txt", "Private customer/model knowledge. Publication is not authorized.\n")
    return Response(buffer.getvalue(), media_type="application/zip", headers={
        "Content-Disposition":"attachment; filename=TM1_Study.zip", "Cache-Control":"no-store"})


@router.get("/api/learning/templates")
def template_catalog():
    return CATALOG


@router.get("/api/learning/templates/{pattern_id}")
def get_template(pattern_id: str):
    try: return template(pattern_id)
    except KeyError as exc: raise HTTPException(404, "未找到教材模板。") from exc
