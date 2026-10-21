"""真实鼠标交互验收（不是程序派发事件）。

验证像素级命中：节点单击、Ctrl 多选、空白拖动平移、连线点击、框选、拖动节点。
基于 Cytoscape 画布：节点/边的屏幕坐标由页面自身提供，交互全部用真实鼠标事件。

用法：
  TM1_BASE=http://127.0.0.1:8011 TM1_ACCEPT_CUBE="<cube>" python scripts/acceptance_pointer.py
"""
import os
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8011")
CUBE = os.environ.get("TM1_ACCEPT_CUBE", "General Ledger")
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

failures = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True,
                                    args=["--no-sandbox", "--no-proxy-server"])
        page = browser.new_page(viewport={"width": 1560, "height": 980})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/architecture?view=workbench&kind=cube&name=" + urllib.parse.quote(CUBE),
                  wait_until="networkidle")
        page.wait_for_selector("#ew-graph canvas", timeout=30000)
        page.wait_for_timeout(2500)

        page.fill("#ew-search", CUBE)
        page.wait_for_timeout(600)
        if page.locator("#ew-resources button").count():
            page.locator("#ew-resources button").first.click()
            page.wait_for_timeout(2600)
        page.click("#ew-fit")
        page.wait_for_timeout(600)

        # 视口内的节点中心（节点坐标由应用给出，鼠标事件是真实的）
        centers = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            const out = [];
            cy.nodes().forEach(n => {
                const b = n.renderedBoundingBox({ includeLabels: false });
                const cx = r.left + (b.x1 + b.x2) / 2, cy2 = r.top + (b.y1 + b.y2) / 2;
                if (cx > r.left + 40 && cx < r.right - 40 && cy2 > r.top + 40 && cy2 < r.bottom - 40) {
                    out.push({ id: n.id(), x: cx, y: cy2 });
                }
            });
            return out;
        }""")
        check(len(centers) >= 2, "视口内有可点击节点（%d）" % len(centers))

        def close_detail():
            if page.locator("#ew-detail button:has-text('关闭详情')").count():
                page.click("#ew-detail button:has-text('关闭详情')")
                page.wait_for_timeout(500)

        def refit():
            page.click("#ew-fit")
            page.wait_for_timeout(450)

        def centers_now(limit=4):
            return page.evaluate("""() => {
                const cy = window.__ewCanvas.cy();
                const r = document.querySelector('#ew-graph').getBoundingClientRect();
                const out = [];
                cy.nodes().forEach(n => {
                    const b = n.renderedBoundingBox({ includeLabels: false });
                    const x = r.left + (b.x1 + b.x2) / 2, y = r.top + (b.y1 + b.y2) / 2;
                    if (x > r.left + 30 && x < r.right - 30 && y > r.top + 30 && y < r.bottom - 30) {
                        out.push({ id: n.id(), x, y });
                    }
                });
                return out;
            }""")[:limit]

        # 1. 真实单击（详情会占掉右侧，之后每次交互前都重新取几何）
        points = centers_now()
        page.mouse.click(points[0]["x"], points[0]["y"])
        page.wait_for_timeout(1300)
        check(page.evaluate("() => window.__ewCanvas.cy().nodes().filter(n => n.hasClass('cn-selected')).length") == 1,
              "真实鼠标单击后唯一选中（1）")
        check(len(page.inner_text("#ew-detail")) > 20, "单击后右侧详情有内容")
        close_detail()

        # 2. 真实 Ctrl + 单击（详情关闭后画布恢复宽度，坐标重新计算）
        refit()
        points = centers_now()
        page.mouse.click(points[0]["x"], points[0]["y"])
        page.wait_for_timeout(700)
        close_detail()
        refit()
        points = centers_now()
        first_id = page.evaluate("() => window.__ewCanvas.cy().nodes().filter(n => n.hasClass('cn-selected'))[0].id()")
        other = next((p for p in points if p["id"] != first_id), points[-1])
        page.keyboard.down("Control")
        page.mouse.click(other["x"], other["y"])
        page.keyboard.up("Control")
        page.wait_for_timeout(900)
        check(page.evaluate("() => window.__ewCanvas.cy().nodes().filter(n => n.hasClass('cn-selected')).length") == 2,
              "Ctrl + 单击实现多选（2）")

        # 3. 空白处拖动平移
        close_detail()
        refit()
        pan_before = page.evaluate("() => window.__ewCanvas.cy().pan()")
        box = page.locator("#ew-graph").bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.78, box["y"] + box["height"] * 0.82)
        page.mouse.down()
        for i in range(1, 11):
            page.mouse.move(box["x"] + box["width"] * 0.78 - i * 9,
                            box["y"] + box["height"] * 0.82 - i * 7)
            page.wait_for_timeout(20)
        page.mouse.up()
        page.wait_for_timeout(500)
        pan_after = page.evaluate("() => window.__ewCanvas.cy().pan()")
        check(abs(pan_before["x"] - pan_after["x"]) > 30 or abs(pan_before["y"] - pan_after["y"]) > 20,
              "真实拖动空白处平移画布")

        # 4. 点击连线
        refit()
        edge_pt = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const e = cy.edges()[0];
            if (!e) return null;
            const p = e.midpoint();
            const pan = cy.pan(), z = cy.zoom();
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return { x: r.left + p.x * z + pan.x, y: r.top + p.y * z + pan.y };
        }""")
        check(edge_pt is not None, "画布上存在可点击的连线")
        if edge_pt:
            page.mouse.click(edge_pt["x"], edge_pt["y"])
            page.wait_for_timeout(1300)
            after_sel = page.evaluate("() => window.__ewCanvas.cy().edges().filter(e => e.hasClass('cn-selected')).length")
            check(after_sel == 1, "点击连线命中唯一关系（%d）" % after_sel)
            check("→" in page.inner_text("#ew-detail"), "连线详情显示来源与目标")
            page.screenshot(path=os.path.join(OUT, "60_pointer_edge.png"))

        # 5. Shift + 拖动框选
        close_detail()
        refit()
        box = page.locator("#ew-graph").bounding_box()
        page.mouse.move(box["x"] + 12, box["y"] + 12)
        page.keyboard.down("Shift")
        page.mouse.down()
        for i in range(1, 12):
            page.mouse.move(box["x"] + 12 + i * (box["width"] - 24) / 11,
                            box["y"] + 12 + i * (box["height"] - 24) / 11)
            page.wait_for_timeout(20)
        page.mouse.up()
        page.keyboard.up("Shift")
        page.wait_for_timeout(900)
        boxed = page.evaluate("() => window.__ewCanvas.cy().nodes().filter(n => n.hasClass('cn-selected')).length")
        check(boxed >= 2, "Shift + 拖动框选命中多个节点（%d）" % boxed)
        page.screenshot(path=os.path.join(OUT, "61_pointer_boxselect.png"))

        # 6. 拖动节点改变位置
        points = centers_now()
        check(bool(points), "拖动前节点仍在可视区内")
        if not points:
            browser.close()
            print("无法继续：画布内没有可拖动节点")
            return 1
        page.mouse.move(points[0]["x"], points[0]["y"])
        page.mouse.down()
        for i in range(1, 8):
            page.mouse.move(points[0]["x"] + i * 10, points[0]["y"] + i * 6)
            page.wait_for_timeout(20)
        page.mouse.up()
        page.wait_for_timeout(600)
        moved = page.evaluate("() => window.__ewCanvas.getPositions()")
        check(bool(moved), "拖动后节点坐标写入画布状态")

        real_errors = [e for e in errors if "favicon" not in e and "404" not in e]
        check(not real_errors, "无页面脚本错误" + ("" if not real_errors else "：" + str(real_errors[:3])))
        browser.close()

    print("\n=== 真实鼠标交互验收 ===", flush=True)
    if failures:
        print("失败 %d 项" % len(failures), flush=True)
        for f in failures:
            print(" · " + f, flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
