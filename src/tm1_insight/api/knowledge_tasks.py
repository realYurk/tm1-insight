"""Background Knowledge API. Results are private, bounded and bound to a model."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
import threading

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response

from tm1_insight.config import get_settings
from tm1_insight.knowledge import ENGINE_VERSION, development_context, extract, markdown
from tm1_insight.store.db import Store
from tm1_insight.tasks import TaskBusy, TaskManager

router = APIRouter()
_manager = None
_manager_lock = threading.Lock()


def fingerprint(settings=None) -> str:
    settings = settings or get_settings()
    db = settings.db_path
    pieces = [str(db.resolve())]
    for path in (db, db.with_suffix(db.suffix + ".wal")):
        try:
            stat = path.stat()
            pieces.append(f"{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            pieces.append("missing")
    return hashlib.sha256("|".join(pieces).encode()).hexdigest()


def manager() -> TaskManager:
    global _manager
    root = get_settings().user_data_root / "cache" / "analysis"
    with _manager_lock:
        if _manager is None or _manager.root != root:
            if _manager is not None:
                _manager.close()
            _manager = TaskManager(root)
        return _manager


@router.post("/api/knowledge/tasks", status_code=202)
def start_knowledge_task(body: dict = Body(...)):
    from tm1_insight.datasource import ensure_demo_if_empty
    ensure_demo_if_empty()
    settings = get_settings().model_copy()
    source = fingerprint(settings)
    prefix = str(body.get("prefix") or "").strip()
    if not prefix:
        raise HTTPException(400, "请输入前缀或关键词；使用 * 可以明确选择全部对象。")
    mode = body.get("match_mode", "prefix")
    if mode not in {"prefix", "keyword"}:
        raise HTTPException(400, "不支持的匹配模式。")
    if body.get("scope") is not None and not isinstance(body["scope"], dict):
        raise HTTPException(400, "scope 必须是对象。")
    options = {"scope":body.get("scope"), "include_dependencies":bool(body.get("include_dependencies", True)),
               "include_lineage":bool(body.get("include_lineage", True)), "include_source":False,
               "match_mode":mode}
    key = json.dumps({"engine":ENGINE_VERSION, "source":source, "prefix":prefix, **options}, sort_keys=True)

    def work(progress):
        con = Store(settings).connect(read_only=True)
        try:
            package = extract(con, prefix, progress=progress, **options)
            if fingerprint(settings) != source:
                raise ValueError("Model was updated during analysis")
            package["source_fingerprint"] = source
            return package
        finally:
            con.close()

    try:
        return manager().submit(key, work, source=source)
    except TaskBusy as exc:
        raise HTTPException(429, str(exc)) from exc


def _state(task_id: str):
    try:
        state = manager().state(task_id)
    except KeyError as exc:
        raise HTTPException(404, "任务不存在或服务已经重启，请重新分析。") from exc
    if state["source"] != fingerprint():
        raise HTTPException(409, "数据源已切换；请在当前模型重新分析。")
    return state


def _result(task_id: str):
    _state(task_id)
    try:
        return manager().result(task_id, source=fingerprint())
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, "结果尚未就绪或缓存已过期，请重新分析。") from exc


@router.get("/api/knowledge/tasks/{task_id}")
def knowledge_task_status(task_id: str):
    return _state(task_id)


@router.post("/api/knowledge/tasks/{task_id}/cancel")
def cancel_knowledge_task(task_id: str):
    _state(task_id)
    return manager().cancel(task_id)


@router.get("/api/knowledge/tasks/{task_id}/result")
def knowledge_task_result(task_id: str, section: str = "processes",
                          offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    package = _result(task_id)
    keys = {"processes":"processes", "patterns":"pattern_candidates", "flows":"data_flows", "facts":"facts"}
    if section not in keys:
        raise HTTPException(400, "未知的结果分区。")
    collection = package[keys[section]]
    items = collection[offset:offset + limit]
    if section == "processes":
        items = [{key:p[key] for key in ("process", "observed_role", "source_hash")} |
                 {"behavior":[event["behavior"] for event in p["behavior_sequence"]],
                  "evidence_count":len(p["behavior_sequence"])} for p in items]
    if section == "patterns":
        items = [{key:p[key] for key in ("id", "candidate_type", "behavior_signature", "processes", "confidence")}
                 for p in items]
    return {"matched":package["matched"], "privacy":package["privacy"], "limitations":package["limitations"],
            "pattern_count":len(package["pattern_candidates"]), "fact_count":len(package["facts"]),
            "section":section, "offset":offset, "limit":limit, "total":len(collection), "items":items}


@router.post("/api/knowledge/tasks/{task_id}/export")
def export_knowledge_task(task_id: str, body: dict = Body(default={})):
    package = _result(task_id)
    context = None
    if body.get("context_type"):
        try:
            context = development_context(package, body["context_type"], str(body.get("name", "")))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("knowledge.json", json.dumps(context or package, ensure_ascii=False, indent=2))
        archive.writestr("knowledge.md", markdown(context or package))
        if context:
            archive.writestr("development_context.json", json.dumps(context, ensure_ascii=False, indent=2))
            archive.writestr("development_context.md", markdown(context))
        archive.writestr("PRIVACY.txt", "Private local analysis. This export is not authorized for publication.\n")
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition":"attachment; filename=TM1_Knowledge.zip",
                             "Cache-Control":"no-store"})
