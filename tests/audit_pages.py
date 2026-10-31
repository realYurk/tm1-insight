"""端到端巡检：屏幕上说的、下载下来的、库里记的，三者是否同一件事。

与 audit_scope_e2e.py 的分工：
  那个验 store 层内自洽（账本对不对）；
  这个验**渲染层**——模板与端点有没有各算一遍（历史上出问题的地方都在这层）。

只读。跑法：

    ./.venv/Scripts/python.exe tests/audit_pages.py [TI 名 …]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from tm1_insight.api.app import app  # noqa: E402
from tm1_insight.config import get_settings  # noqa: E402
from tm1_insight.store.db import Store  # noqa: E402

PROBLEMS: list[str] = []
CHECKED: dict[str, int] = {}


def bad(kind: str, name: str, detail: str) -> None:
    PROBLEMS.append(f"[{kind}] {name} · {detail}")


def text_of(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def scope_bar(html: str) -> dict:
    """状态条结构里有嵌套 div，用固定窗口截取比非贪婪正则可靠。"""
    at = html.find('class="scope-bar"')
    if at < 0:
        return {}
    window = html[max(0, at - 80):at + 1200]
    body = text_of(window)
    nums: dict = {}
    mode = re.search(r'data-mode="(\w+)"', window)
    if mode:
        nums["mode"] = mode.group(1)
    m2 = re.search(r"当前范围：(\d+)", body)
    if m2:
        nums["visible"] = int(m2.group(1))
    m3 = re.search(r"另有 (\d+) 条", body)
    if m3:
        nums["hidden"] = int(m3.group(1))
    nums["text"] = body.strip()[:200]
    return nums


def page_total(html: str) -> int | None:
    """列表标题旁的总数（分页用的那个）。"""
    m = re.search(r"选择写入点\s*</?[^>]*>\s*(\d+)", html)
    if m:
        return int(m.group(1))
    m = re.search(r"选择写入点[^0-9]{0,40}(\d+)", text_of(html))
    return int(m.group(1)) if m else None


def audit_calculation(client, name: str) -> None:
    page = client.get("/calculation", params={"name": name})
    if page.status_code != 200:
        bad("页面", name, f"/calculation 返回 {page.status_code}")
        return
    src = re.search(r"source=([0-9a-f]{64})", page.text)
    if not src:
        bad("页面", name, "页面里找不到模型指纹，无法取导出")
        return
    source = src.group(1)
    bar = scope_bar(page.text)
    if not bar:
        bad("页面", name, "没有渲染范围状态条")
        return

    narrow = client.get("/api/calculation/export", params={"name": name, "source": source})
    wide = client.get("/api/calculation/export", params={"name": name, "source": source, "system": 1})
    if narrow.status_code != 200 or wide.status_code != 200:
        bad("导出", name, f"导出返回 {narrow.status_code}/{wide.status_code}")
        return
    n_data, w_data = narrow.json(), wide.json()

    CHECKED["cal"] = CHECKED.get("cal", 0) + 1
    n_sv, w_sv = n_data["scope_view"], w_data["scope_view"]

    if bar.get("visible") != len(n_data["writes"]):
        bad("条数", name, f"状态条说 {bar['visible']} 条，导出实际 {len(n_data['writes'])} 条")
    if n_sv["visible"] != len(n_data["writes"]):
        bad("条数", name, f"导出账本 {n_sv['visible']} != 导出实际 {len(n_data['writes'])}")
    total = page_total(page.text)
    if total is not None and total != bar.get("visible"):
        bad("条数", name, f"列表页脚 {total} != 状态条 {bar.get('visible')}")

    full_page = client.get("/calculation", params={"name": name, "system": 1})
    wide_bar = scope_bar(full_page.text)
    if not wide_bar:
        bad("页面", name, "全量视图没有状态条")
    else:
        if wide_bar.get("visible") != len(w_data["writes"]):
            bad("条数", name, f"全量状态条 {wide_bar.get('visible')} != 全量导出 {len(w_data['writes'])}")
        if wide_bar.get("mode") != "all":
            bad("状态", name, f"system=1 的状态条 mode 是 {wide_bar.get('mode')}")
        # 切到全量后必须单调增加，且增量等于窄视图说的隐藏量
        if bar.get("hidden") is not None:
            delta = wide_bar.get("visible", 0) - bar.get("visible", 0)
            if delta != bar["hidden"]:
                bad("条数", name, f"切到全量多了 {delta} 条，状态条却说隐藏 {bar['hidden']} 条")
    if w_sv["visible"] != len(w_data["writes"]):
        bad("条数", name, f"全量账本 {w_sv['visible']} != 全量实际 {len(w_data['writes'])}")

    # 全量必须真的更全：hidden=0 且条数 >= 窄视图
    if w_sv["hidden"]:
        bad("状态", name, f"全量视图仍报告隐藏 {w_sv['hidden']} 条")
    if n_sv["hidden"] and len(w_data["writes"]) <= len(n_data["writes"]):
        bad("状态", name, "全量导出没有比默认导出多出记录")

    # markdown 里的数字必须与 JSON 一致
    md = client.get("/api/calculation/export",
                    params={"name": name, "source": source, "format": "markdown"})
    if md.status_code != 200:
        bad("导出", name, f"markdown 返回 {md.status_code}")
    else:
        m = re.search(r"另有 (\d+) 条记录未包含在本文件内", md.text)
        if n_sv["hidden"] and not m:
            bad("导出", name, "markdown 没有说明隐藏了几条")
        elif m and int(m.group(1)) != n_sv["hidden"]:
            bad("导出", name, f"markdown 说 {m.group(1)} 条，JSON 说 {n_sv['hidden']} 条")
        # 正文跳号提醒：有隐藏就必须说他为什么会跳号
        if n_sv["hidden"] and "跳号" not in md.text:
            bad("导出", name, "有隐藏但正文没解释编号跳号")


def audit_tree(client, name: str) -> None:
    page = client.get(f"/explorer/process/{name}/call-tree", params={"scope": "business"})
    if page.status_code != 200:
        bad("调用树", name, f"返回 {page.status_code}")
        return
    CHECKED["tree"] = CHECKED.get("tree", 0) + 1
    sites = re.findall(r'<a class="tree-site"[^>]*href="([^"]+)"[^>]*>([^<]*)</a>', page.text)
    m = re.search(r"节点后的.*?是调用点", page.text)
    unlocated = re.search(r"另有 (\d+) 个节点没标位置", page.text)
    for href, label in sites:
        if not re.match(r"^/explorer/process/[^/]+#(prolog|metadata|data|epilog)-L\d+$", href):
            bad("调用树", name, f"位置链接格式不对：{href}")
        if not re.search(r":\d+$", label):
            bad("调用树", name, f"位置标签不像行号：{label}")
    if sites and not m:
        bad("调用树", name, "画了位置却没有图例解释")
    if unlocated and not sites:
        bad("调用树", name, "有未定位节点，但一个位置都没标")


def audit_excluded(client, con) -> None:
    """「未收录」这个说法在页面上出现几次，库里就该有多少个名字。"""
    n = con.execute("SELECT count(*) FROM excluded_objects").fetchone()[0] \
        if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='excluded_objects'").fetchone()[0] else 0
    CHECKED["excluded_rows"] = n
    page = client.get("/processes")
    if page.status_code != 200:
        bad("未收录", "/processes", f"返回 {page.status_code}")
        return
    body = text_of(page.text)
    m = re.search(r"未收录\s*(\d+)", body)
    if n and not m:
        bad("未收录", "/processes", f"库里有 {n} 个未收录对象，列表页没提")


def main(argv: list[str]) -> int:
    settings = get_settings()
    print(f"库：{settings.db_path}")
    client = TestClient(app)
    con = Store(settings).connect(read_only=True)

    names = argv[1:]
    if not names:
        src = ("lower(coalesce(prolog,'')||coalesce(metadata,'')||coalesce(data,'')||coalesce(epilog,''))")
        names = [r[0] for r in con.execute(
            "SELECT name FROM processes WHERE NOT starts_with(name,'}') AND "
            + src + " LIKE '%cellput%''}%' ORDER BY length(name) LIMIT 20").fetchall()]
        names += [r[0] for r in con.execute(
            "SELECT name FROM processes WHERE NOT starts_with(name,'}') AND "
            + src + " LIKE '%cellget%''}%' ORDER BY length(name) LIMIT 10").fetchall()]
        names = list(dict.fromkeys(names))
    print(f"样本：{len(names)} 个 TI\n")

    for name in names:
        try:
            audit_calculation(client, name)
        except Exception as exc:  # noqa: BLE001
            bad("异常", name, f"{type(exc).__name__}: {exc}")
    for name in names[:10]:
        try:
            audit_tree(client, name)
        except Exception as exc:  # noqa: BLE001
            bad("异常", name, f"调用树 {type(exc).__name__}: {exc}")
    try:
        audit_excluded(client, con)
    except Exception as exc:  # noqa: BLE001
        bad("异常", "未收录", f"{type(exc).__name__}: {exc}")
    con.close()

    print("检查：" + "、".join(f"{k} {v}" for k, v in CHECKED.items()))
    if not PROBLEMS:
        print("渲染层一致性：全部通过")
        return 0
    print(f"\n发现问题 {len(PROBLEMS)} 条：")
    for line in PROBLEMS[:40]:
        print("  ", line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
