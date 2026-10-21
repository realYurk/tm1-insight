"""真实鼠标交互验收（不是程序派发事件）。

验证像素级命中：节点单击、Ctrl 多选、空白拖动平移、边点击、框选。
失败退出码 1。

用法：
  TM1_BASE=http://127.0.0.1:8011 TM1_ACCEPT_CUBE="<cube>" python scripts/acceptance_pointer.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8011")
CUBE = os.environ.get("TM1_ACCEPT_CUBE", "Sales Cost Driver")
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

failures = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def main():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(BASE + "/api/workbench/objects?q=&type=cube", timeout=60) as r:
        snap = json.load(r)["snapshot_id"]

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True,
                                    args=["--no-sandbox", "--no-proxy-server"])
        page = browser.new_page(viewport={"width": 1560, "height": 980})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/architecture?view=workbench&kind=cube&name=" + urllib.parse.quote(CUBE),
                  wait_until="networkidle")
        page.wait_for_selector("#ew-graph svg", timeout=30000)
        page.wait_for_timeout(2500)

        # 展开以得到足够的节点与边
        page.fill("#ew-search", CUBE)
        page.wait_for_timeout(600)
        page.locator("#ew-resources button").first.click()
        page.wait_for_timeout(2500)
        page.get_by_role("button", name="展开直接 TI / 调用关系").first.click()
        page.wait_for_timeout(3000)

        nodes = page.locator("#ew-graph svg .node")
        n = nodes.count()
        check(n >= 3, "画布存在可交互节点（%d）" % n)

        # 只选择完整落在视口内的节点，保证是真实的像素命中
        def visible_centers(limit=2):
            vp = page.locator("#ew-graph .mm-viewport").bounding_box()
            out = []
            for i in range(n):
                b = nodes.nth(i).bounding_box()
                if not b:
                    continue
                cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
                if (vp["x"] + 4 < cx < vp["x"] + vp["width"] - 4
                        and vp["y"] + 4 < cy < vp["y"] + vp["height"] - 4):
                    out.append((cx, cy))
                if len(out) >= limit:
                    break
            return out

        centers = visible_centers(2)
        check(len(centers) == 2, "视口内可见可点击节点不少于 2（%d）" % len(centers))

        # 1. 真实鼠标单击节点
        page.mouse.click(centers[0][0], centers[0][1])
        page.wait_for_timeout(1500)
        check(page.locator("#ew-graph svg .ew-selected").count() == 1,
              "真实鼠标单击节点后唯一选中（1）")
        check(len(page.inner_text("#ew-detail")) > 20, "单击后右侧详情有内容")

        # 2. 真实 Ctrl + 单击多选
        page.keyboard.down("Control")
        page.mouse.click(centers[1][0], centers[1][1])
        page.keyboard.up("Control")
        page.wait_for_timeout(1200)
        check(page.locator("#ew-graph svg .ew-selected").count() == 2,
              "Ctrl + 单击实现多选（2）")

        # 3. 空白处真实拖动平移
        before = page.evaluate("() => document.querySelector('#ew-graph .mm-inner').style.transform")
        vp = page.locator("#ew-graph .mm-viewport").bounding_box()
        spot = page.evaluate(
            """(vp) => {
                const bad = (x,y) => { const e=document.elementFromPoint(x,y); return e && e.closest('.node,.flowchart-link,.mm-toolbar'); };
                for (let dx=0.08; dx<0.5; dx+=0.06) for (let dy=0.08; dy<0.5; dy+=0.06) {
                    const x = vp.x + vp.width*dx, y = vp.y + vp.height*dy;
                    if (!bad(x,y)) return {x,y};
                }
                return null;
            }""", vp)
        if spot:
            page.mouse.move(spot["x"], spot["y"])
            page.mouse.down()
            page.mouse.move(spot["x"] + 90, spot["y"] + 50, steps=10)
            page.mouse.up()
            page.wait_for_timeout(600)
            after = page.evaluate("() => document.querySelector('#ew-graph .mm-inner').style.transform")
            check(before != after, "真实拖动空白处平移画布")
        else:
            check(False, "画布上找不到可拖动的空白区域")

        # 4. 真实点击边：取路径中点并按屏幕矩阵换算成像素坐标
        pt = page.evaluate(
            """() => {
                const link = document.querySelector('#ew-graph svg .flowchart-link');
                if (!link) return null;
                const len = link.getTotalLength();
                const p = link.getPointAtLength(len/2);
                const m = link.getScreenCTM();
                return {x: m.a*p.x + m.c*p.y + m.e, y: m.b*p.x + m.d*p.y + m.f};
            }""")
        check(pt is not None, "存在可取中点的关系边")
        if pt:
            hit = page.evaluate(
                """(p) => { const e=document.elementFromPoint(p.x,p.y); return e ? (e.getAttribute('class')||e.tagName) : 'none'; }""",
                pt)
            page.mouse.click(pt["x"], pt["y"])
            page.wait_for_timeout(1500)
            selected_rows = page.locator("#ew-relations tr[data-edge][aria-selected='true']").count()
            check(selected_rows == 1,
                  "真实点击边路径中点（命中 %s）联动关系表（%d 行）" % (hit[:28], selected_rows))

        # 5. 真实框选：进入框选模式后拖出矩形
        page.click("#ew-graph .mm-toolbar button:has-text('框选模式')")
        vp2 = page.locator("#ew-graph .mm-viewport").bounding_box()
        page.mouse.move(vp2["x"] + 6, vp2["y"] + 6)
        page.mouse.down()
        page.mouse.move(vp2["x"] + vp2["width"] - 6, vp2["y"] + vp2["height"] - 6, steps=12)
        page.mouse.up()
        page.wait_for_timeout(1200)
        boxed = page.locator("#ew-graph svg .ew-selected").count()
        check(boxed >= 2, "真实拖动框选命中多个节点（%d）" % boxed)

        page.screenshot(path=OUT + "/34_pointer_interaction.png", full_page=False)
        check(not [e for e in errors], "无页面脚本错误" + ("" if not errors else "：" + str(errors[:2])))
        browser.close()

    print("\n=== 真实鼠标交互验收 ===")
    if failures:
        print("失败 %d 项" % len(failures))
        sys.exit(1)
    print("全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
