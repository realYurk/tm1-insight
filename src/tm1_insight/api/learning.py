"""Background study reports and generic teaching templates."""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response,FileResponse
from starlette.background import BackgroundTask

from tm1_insight.api.knowledge_tasks import fingerprint, manager, _state
from tm1_insight.config import get_settings
from tm1_insight.learning.catalog import CATALOG, template
from tm1_insight.learning.engine import VERSION
from tm1_insight.learning.worker import isolated_report,isolated_export
from tm1_insight.learning import pages
from tm1_insight.tasks import TaskBusy

router = APIRouter()


def indexed_path(task_id):
    state=_state(task_id)
    if state["status"]!="completed":raise HTTPException(409,"分析尚未完成。")
    try:return manager().result_path(task_id,source=state["source"])
    except FileNotFoundError as exc:raise HTTPException(410,"缓存已清理，请重新分析。") from exc


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
        result = isolated_report(settings, query, progress,as_artifact=True,source=source)
        if fingerprint(settings) != source:
            result.cleanup()
            raise ValueError("Model changed")
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
    path=indexed_path(task_id)
    if section not in pages.SECTIONS:raise HTTPException(400,"未知结果分类。")
    try:report,total,items=pages.page(path,section,offset,limit,pattern,q)
    except (OSError,ValueError,sqlite3.Error) as exc:raise HTTPException(410,"分页缓存不可用，请重新分析。") from exc
    if report.get("version") != VERSION:
        raise HTTPException(400, "这不是项目学习任务。")
    from tm1_insight.api.app import _process_search_source
    settings = get_settings().model_copy()
    expected = fingerprint(settings)
    if report.get('source_fingerprint') != expected:
        raise HTTPException(409, "教材来源已变化，请重新分析当前模型。")
    inspection_source = _process_search_source(settings)
    for item in items:
        if section=="processes":
            ir=item["understanding"]
            ir["reference_total"]=len(ir["references"])
            ir["references"]=ir["references"][:8];ir["controls"]=ir["controls"][:6];ir["call_bindings"]=ir["call_bindings"][:5]
    if expected != fingerprint() or inspection_source != _process_search_source():
        raise HTTPException(409, "读取期间模型已变化，请重新分析。")
    return {"inspection_source":inspection_source, "summary":report["summary"], "query":report["query"], "sop":report["sop"],"coverage":report["coverage"],
            "limitations":report["limitations"], "total":total, "offset":offset,"items":items}


@router.get("/api/learning/tasks/{task_id}/contract")
def migration_contract(task_id: str, process: str):
    path=indexed_path(task_id)
    report,_,_=pages.page(path,"processes",0,1)
    if report.get("version")!=VERSION:raise HTTPException(400,"这不是项目学习任务。")
    item=pages.process(path,process)
    if item is None:raise HTTPException(404,"当前分析范围没有这个 TI。")
    value={"schema":"migration-contract-1","source_fingerprint":report["source_fingerprint"],
           "process":item["process"],"source_hash":item["source_hash"],"parameters":item["parameters"],
           "catalog_reads":item["reads"],"catalog_writes":item["writes"],"catalog_calls":item["calls"],
           "structure":item["understanding"],"formula_candidates":item["formulas"],
           "status":"requires_human_review","equivalence_verified":False,
           "required_validation":["提供本地输入样本与逐坐标预期输出","确认零值、负数、精度、舍入与尾差政策",
                                  "核对 TI 生命周期、Rule/Feeder 与层级汇总语义","验证重跑、并发、失败恢复与批次隔离"],
           "privacy":report["privacy"]}
    return Response(json.dumps(value,ensure_ascii=False,indent=2),media_type="application/json",headers={
        "Content-Disposition":"attachment; filename=migration-contract.json","Cache-Control":"no-store"})


@router.post("/api/learning/tasks/{task_id}/export")
def export_learning(task_id: str):
    path=indexed_path(task_id)
    header,_,_=pages.page(path,"processes",0,1)
    if header.get("version")!=VERSION:raise HTTPException(400,"这不是项目学习任务。")
    try:archive,owner=isolated_export(get_settings().model_copy(),path)
    except Exception as exc:raise HTTPException(503,"私有教材暂时无法导出，请检查空间后重试。") from exc
    return FileResponse(archive,media_type="application/zip",filename="TM1_Study.zip",
                        headers={"Cache-Control":"no-store"},background=BackgroundTask(owner.cleanup))


@router.get("/api/learning/templates")
def template_catalog():
    return CATALOG


@router.get("/api/learning/templates/{pattern_id}")
def get_template(pattern_id: str):
    try: return template(pattern_id)
    except KeyError as exc: raise HTTPException(404, "未找到教材模板。") from exc
