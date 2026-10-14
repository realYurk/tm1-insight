"""Private personal notes with revision history. Original models stay read-only."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import json
import sqlite3
import uuid
from tm1_insight.learning.engine import VERSION

STATUSES={"candidate","reviewed","validated","deprecated"}


def model_id(settings):return hashlib.sha256(str(settings.db_path.resolve()).encode()).hexdigest()


@contextmanager
def database(settings):
    root=settings.user_data_root / "experiences";root.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(root/"reviews.sqlite3",timeout=3)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA max_page_count=65536")
        con.execute("CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY,model_id TEXT,revision INTEGER,payload TEXT,updated TEXT,search TEXT,status TEXT,evidence_key TEXT)")
        con.execute("CREATE INDEX IF NOT EXISTS model_cards ON cards(model_id,updated)")
        con.execute("CREATE TABLE IF NOT EXISTS history(card_id TEXT,revision INTEGER,payload TEXT,PRIMARY KEY(card_id,revision))")
        yield con
    finally:con.close()


def create(settings,source,item):
    now=datetime.now(timezone.utc).isoformat()
    card={"id":uuid.uuid4().hex,"revision":1,"title":item["process"],"process":item["process"],
          "status":"candidate","method":"custom","problem":"","applicability":"","limitations":"",
          "validation_notes":"","reviewer":"","change_reason":"从本地分析保存候选",
          "source_fingerprint":source,"source_hash":item["source_hash"],"engine_version":VERSION,
          "patterns":list(item["patterns"]),"evidence":{key:item[key][:50] for key in ("reads","writes","calls")},
          "created":now,"updated":now,"validation_origin":"human_record_only","publishing_authorized":False}
    with database(settings) as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT count(*) FROM cards WHERE model_id=?",[model_id(settings)]).fetchone()[0]>=1000:
            raise ValueError("当前项目已达到 1000 条经验记录上限，请先导出备份并整理。")
        key=hashlib.sha256((card["process"]+"\0"+card["source_hash"]+"\0"+source).encode()).hexdigest()
        existing=con.execute("SELECT payload FROM cards WHERE model_id=? AND evidence_key=?",[model_id(settings),key]).fetchone()
        if existing:return json.loads(existing[0])
        payload=json.dumps(card,ensure_ascii=False)
        con.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?)",[card["id"],model_id(settings),1,payload,now,card["title"].casefold(),"candidate",key])
        con.execute("INSERT INTO history VALUES (?,?,?)",[card["id"],1,payload]);con.commit()
    return card


def get(settings,identifier):
    with database(settings) as con:
        row=con.execute("SELECT payload FROM cards WHERE id=? AND model_id=?",[identifier,model_id(settings)]).fetchone()
    if not row:raise KeyError(identifier)
    return json.loads(row[0])


def listing(settings,offset=0,limit=20,q="",status=""):
    conditions=["model_id=?"];args=[model_id(settings)]
    if q:conditions.append("instr(search,?)>0");args.append(q.casefold())
    if status:conditions.append("status=?");args.append(status)
    where=" AND ".join(conditions)
    with database(settings) as con:
        total=con.execute("SELECT count(*) FROM cards WHERE "+where,args).fetchone()[0]
        rows=con.execute("SELECT payload FROM cards WHERE "+where+" ORDER BY updated DESC,id LIMIT ? OFFSET ?",args+[limit,offset]).fetchall()
    return total,[json.loads(row[0]) for row in rows]


def update(settings,identifier,expected_revision,fields,current_source):
    from tm1_insight.learning.catalog import CATALOG
    with database(settings) as con:
        con.execute("BEGIN IMMEDIATE")
        row=con.execute("SELECT revision,payload FROM cards WHERE id=? AND model_id=?",[identifier,model_id(settings)]).fetchone()
        if not row:raise KeyError(identifier)
        if row[0]!=expected_revision:raise RuntimeError("经验已被另一页面更新，请重新打开后编辑。")
        if row[0]>=100:raise ValueError("此经验已达到 100 个历史版本上限，请导出备份后建立新的候选。")
        card=json.loads(row[1]);card.update(fields)
        if card["status"] not in STATUSES:raise ValueError("未知整理状态。")
        if card["method"] not in {c["id"] for c in CATALOG}|{"custom"}:raise ValueError("未知设计方法。")
        for key in ("title","problem","applicability","limitations","validation_notes","reviewer","change_reason"):
            if not isinstance(card[key],str) or len(card[key])>2000:raise ValueError("文本字段不能超过 2000 字。")
            card[key]=card[key].strip()
        if not card["title"] or not card["change_reason"]:raise ValueError("请填写标题与本次修改原因。")
        if card["status"] in {"reviewed","validated"}:
            if card["source_fingerprint"]!=current_source:raise RuntimeError("模型已变化，请重新分析并保存新候选；旧经验仍可阅读和导出。")
            if not all(card[key] for key in ("problem","applicability","limitations")):
                raise ValueError("标记已整理前，请写清问题、适用条件与限制。")
        if card["status"]=="validated" and not card["validation_notes"]:
            raise ValueError("请记录测试输入、预期输出、实际结果与异常用例；软件不代替执行验证。")
        card["revision"]+=1;card["updated"]=datetime.now(timezone.utc).isoformat()
        payload=json.dumps(card,ensure_ascii=False)
        con.execute("UPDATE cards SET revision=?,payload=?,updated=?,search=?,status=? WHERE id=?",[card["revision"],payload,card["updated"],(card["title"]+" "+card["problem"]+" "+card["applicability"]).casefold(),card["status"],identifier])
        con.execute("INSERT INTO history VALUES (?,?,?)",[identifier,card["revision"],payload]);con.commit()
    return card


def history(settings,identifier):
    get(settings,identifier)
    with database(settings) as con:
        return [json.loads(row[0]) for row in con.execute("SELECT payload FROM history WHERE card_id=? ORDER BY revision DESC",[identifier])]


def compare(requirements):
    """Explain independent design choices; never claim a universal best answer."""
    nightly=requirements["frequency"]=="scheduled"
    choices=[{"id":"batch","title":"TI 批量计算并保存结果","axis":"计算方式","status":"consider",
              "reasons":["适合显式批次、结果保留和逐批对账。"],"conditions":["先明确读写切片、清理或去重、失败恢复与精度契约。"],"methods":["proportion","accumulate","rebuild"]},
             {"id":"rule","title":"Rule 派生计算","axis":"计算方式","status":"needs_review",
              "reasons":["可用于随依赖变化计算派生值；是否满足性能要求需要实测。"],"conditions":["核对 Rule 优先级、N/C、STET/CONTINUE、层级与 Feeder 语义。"],"methods":[]},
             {"id":"configuration","title":"配置规则与分步骤执行","axis":"规则管理与流程组织","status":"consider" if requirements["varying_rules"] or requirements["multi_stage"] else "optional",
              "reasons":["可与批处理或 Rule 方案组合；用于管理变化规则和步骤依赖。"],"conditions":["配置需要版本、校验、默认值政策和失败传播。"],"methods":["configuration","pipeline","mapping"]}]
    if nightly:choices[0]["reasons"].append("需求选择了定时更新，可以集中计算。")
    else:choices[0]["conditions"].append("需求选择交互更新，需要验证批次触发到结果可用的时间。");choices[1]["reasons"].append("需求选择交互更新，可评估依赖驱动的派生计算。")
    if requirements["persist_results"]:
        choices[1]["status"]="excluded_as_standalone";choices[1]["reasons"].append("需求要求保存独立结果；单独的派生 Rule 不满足结果物化契约，需要额外快照或写入机制。")
    for choice in choices:
        if requirements["audit"]:choice["conditions"].append("记录规则版本、输入范围、结果和对账证据。")
        if requirements["concurrent"]:choice["conditions"].append("证明写入切片不冲突，并验证锁、隔离和失败汇总。")
    return {"requirements":requirements,"choices":choices,"decision":"先排除硬条件冲突，再验证剩余方案；未计算质量总分。",
            "limits":["候选方案属于不同设计维度，可以组合；不是互斥的最佳方案排名。",
                      "当前没有自动运行性能或金额验证；经验中的验证状态来自人工记录。"]}
