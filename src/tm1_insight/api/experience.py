"""Personal experience notes, deterministic comparison and source isolation."""
from __future__ import annotations
import json
import sqlite3
from typing import Literal
from fastapi import APIRouter,HTTPException,Query,Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,ConfigDict,Field,StrictBool
from tm1_insight.api.knowledge_tasks import fingerprint
from tm1_insight.api.learning import indexed_path
from tm1_insight.config import get_settings
from tm1_insight.learning import experience,pages
from tm1_insight.learning.engine import VERSION

router=APIRouter()


class Candidate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    task_id:str=Field(max_length=64)
    process:str=Field(min_length=1,max_length=1000)


class Review(BaseModel):
    model_config=ConfigDict(extra="forbid")
    expected_revision:int=Field(ge=1)
    title:str=Field(min_length=1,max_length=2000)
    problem:str=Field(default="",max_length=2000)
    applicability:str=Field(default="",max_length=2000)
    limitations:str=Field(default="",max_length=2000)
    validation_notes:str=Field(default="",max_length=2000)
    reviewer:str=Field(default="",max_length=2000)
    change_reason:str=Field(min_length=1,max_length=2000)
    method:str=Field(default="custom",max_length=40)
    status:Literal["candidate","reviewed","validated","deprecated"]


class Requirements(BaseModel):
    model_config=ConfigDict(extra="forbid")
    frequency:Literal["scheduled","interactive"]
    persist_results:StrictBool
    multi_stage:StrictBool
    varying_rules:StrictBool
    audit:StrictBool
    concurrent:StrictBool


def tagged(card,source):return {**card,"source_current":card["source_fingerprint"]==source}


@router.get("/experience")
def experience_page(request:Request):
    from tm1_insight.api.app import templates,_store
    _store()
    return templates.TemplateResponse(request,"experience.html",{})


@router.post("/api/experience/cards")
def save_candidate(body:Candidate):
    settings=get_settings().model_copy();source=fingerprint(settings)
    path=indexed_path(body.task_id);header,_,_=pages.page(path,"processes",0,1)
    if header.get("version")!=VERSION:raise HTTPException(400,"请从当前版本的项目学习结果保存经验。")
    if header.get("source_fingerprint")!=source:raise HTTPException(409,"模型已变化，请重新分析。")
    item=pages.process(path,body.process)
    if item is None:raise HTTPException(404,"该 TI 不在当前学习范围内。")
    try:return tagged(experience.create(settings,source,item),source)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except sqlite3.Error as exc:raise HTTPException(503,"本地经验库无法写入，请检查剩余空间。") from exc


@router.get("/api/experience/cards")
def list_cards(offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=50),q:str=Query("",max_length=200),status:str=""):
    if status and status not in experience.STATUSES:raise HTTPException(400,"未知整理状态。")
    settings=get_settings().model_copy();source=fingerprint(settings)
    total,cards=experience.listing(settings,offset,limit,q,status)
    return {"total":total,"items":[tagged(card,source) for card in cards],"offset":offset,"source_fingerprint":source}


@router.get("/api/experience/cards/{identifier}")
def get_card(identifier:str):
    try:return tagged(experience.get(get_settings(),identifier),fingerprint())
    except KeyError as exc:raise HTTPException(404,"当前项目没有这条经验。") from exc


@router.post("/api/experience/cards/{identifier}")
def review_card(identifier:str,body:Review):
    settings=get_settings().model_copy();source=fingerprint(settings)
    try:
        card=experience.update(settings,identifier,body.expected_revision,body.model_dump(exclude={"expected_revision"},exclude_unset=True),source)
        return tagged(card,source)
    except KeyError as exc:raise HTTPException(404,"当前项目没有这条经验。") from exc
    except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except sqlite3.Error as exc:raise HTTPException(503,"本地经验库无法写入，请检查剩余空间或稍后重试；已有记录保持不变。") from exc


@router.get("/api/experience/cards/{identifier}/history")
def review_history(identifier:str):
    try:return experience.history(get_settings(),identifier)
    except KeyError as exc:raise HTTPException(404,"当前项目没有这条经验。") from exc


@router.get("/api/experience/export")
def export_experience():
    settings=get_settings().model_copy()
    # Export only this model, never the SQLite file containing other projects.
    def stream():
        with experience.database(settings) as con:
            con.execute("BEGIN")
            yield '{"schema":"private-experiences-1","publishing_authorized":false,"cards":['
            queries=["SELECT payload FROM cards WHERE model_id=? ORDER BY id",
                     "SELECT h.payload FROM history h JOIN cards c ON c.id=h.card_id WHERE c.model_id=? ORDER BY h.card_id,h.revision"]
            for index,query in enumerate(queries):
                if index:yield '],"history":['
                first=True
                for row in con.execute(query,[experience.model_id(settings)]):
                    yield ('' if first else ',')+row[0]
                    first=False
            yield ']}'
    return StreamingResponse(stream(),media_type="application/json",headers={
        "Content-Disposition":"attachment; filename=private-experiences.json","Cache-Control":"no-store"})


@router.post("/api/experience/compare")
def compare_allocation(body:Requirements):
    settings=get_settings().model_copy();source=fingerprint(settings)
    result=experience.compare(body.model_dump())
    _,cards=experience.listing(settings,limit=1000,status="validated")
    for choice in result["choices"]:
        choice["reviewed_examples"]=[{"id":card["id"],"title":card["title"],"method":card["method"]} for card in cards
                                     if card["source_fingerprint"]==source and card["method"] in choice["methods"]][:10]
    result["rules_version"]="allocation-choice-1"
    return result
