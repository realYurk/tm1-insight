"""产品级打磨验收（Canvas Excellence）。

覆盖：布局质量客观指标（无碰撞 / 无越界 / 宽高比）、语义缩放、
键盘快捷键（Esc / Ctrl+S）、底部 Dock、图例折叠、紧凑窗口 1366x768。

用法：TM1_BASE=http://127.0.0.1:8011 python scripts/acceptance_excellence.py
"""
from __future__ import annotations

import os
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8011")
CUBE = os.environ.get("TM1_ACCEPT_CUBE", "General Ledger")
OUT = os.path.join("logs", "browser_acceptance")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

failures = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def open_workbench(page, suffix=""):
    page.goto(BASE + "/architecture?view=workbench&kind=cube&name=" + urllib.parse.quote(CUBE) + suffix,
              wait_until="networkidle")
    page.wait_for_timeout(2000)
    # 资源栏默认收起；先展开再搜索
    if page.locator("#ew-rail").evaluate("el => getComputedStyle(el).display") == "none":
        page.click("#ew-toggle-rail")
        page.wait_for_timeout(300)
    page.fill("#ew-search", CUBE)
    page.wait_for_timeout(600)
    if page.locator("#ew-resources button").count():
        page.locator("#ew-resources button").first.click()
        page.wait_for_timeout(2600)


LAYOUT_METRICS = """() => {
    const cy = window.__ewCanvas.cy();
    const r = document.querySelector('#ew-graph').getBoundingClientRect();
    const nodes = cy.nodes().filter(n => !n.hidden() && n.data('type') !== 'group');
    let overlap = 0, clipped = 0, pairs = 0;
    const boxes = [];
    nodes.forEach(n => {
        const b = n.renderedBoundingBox({ includeLabels: true });
        boxes.push({ id: n.id(), x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 });
        const rp = n.renderedPosition();
        if (rp.x < 0 || rp.y < 0 || rp.x > r.width || rp.y > r.height) clipped += 1;
    });
    for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
            const a = boxes[i], b = boxes[j];
            pairs += 1;
            const ox = Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1);
            const oy = Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1);
            if (ox > 6 && oy > 6) overlap += 1;   // 容忍 6px 内的边框相切
        }
    }
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    boxes.forEach(b => {
        minX = Math.min(minX, b.x1); minY = Math.min(minY, b.y1);
        maxX = Math.max(maxX, b.x2); maxY = Math.max(maxY, b.y2);
    });
    const w = maxX - minX, h = maxY - minY;
    return { nodes: nodes.length, overlap, clipped, aspect: h > 0 ? w / h : 0,
             inView: clipped === 0 };
}"""


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True,
                                     args=["--no-sandbox", "--no-proxy-server"])

        # ======================= 1. 布局质量（1920x1080） =======================
        print("\n[1] 布局质量客观指标（General Ledger + 17 邻居）", flush=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        open_workbench(page)
        m = page.evaluate(LAYOUT_METRICS)
        print("   指标:", m, flush=True)
        check(m["nodes"] >= 10, "图规模足够（%d 节点）" % m["nodes"])
        check(m["overlap"] == 0, "节点/标签无碰撞（重叠对 %d）" % m["overlap"])
        check(m["inView"], "无节点被画布裁切（越界 %d）" % m["clipped"])
        check(0.25 <= m["aspect"] <= 4.0,
              "图形宽高比合理（%.2f，不再是一字长蛇阵）" % m["aspect"])
        strat = page.evaluate("() => window.__ewCanvas.layoutStrategy()")
        check(strat in ("radial", "layered"), "布局策略明确（%s）" % strat)
        page.screenshot(path=os.path.join(OUT, "60_hub_radial_1920.png"))

        # ======================= 2. 边标签降噪 =======================
        # Polish 2.0 起：边标签默认不渲染（画布去噪），hover / 选中该边时才显示。
        print("\n[2] 边标签降噪：默认隐藏，聚焦显示", flush=True)
        edge_state = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const withLabel = cy.edges().filter(e => e.data('label')).length;
            if (!withLabel) return { withLabel: 0 };
            const e = cy.edges().filter(x => x.data('label'))[0];
            const defaultLabel = String(e.style('label') || '');
            e.addClass('cn-hover');
            const hoverLabel = String(e.style('label') || '');
            e.removeClass('cn-hover');
            return { withLabel, defaultLabel, hoverLabel };
        }""")
        check(edge_state["withLabel"] > 0 and not edge_state["defaultLabel"] and edge_state["hoverLabel"],
              "边标签默认隐藏、hover 显示（%d 条带标签；默认=%r，hover=%r）"
              % (edge_state["withLabel"], edge_state["defaultLabel"], edge_state["hoverLabel"]))

        # ======================= 3. 键盘与 Dock =======================
        print("\n[3] 键盘快捷键与底部 Dock", flush=True)
        # Esc 关闭详情
        box = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const n = cy.nodes()[0];
            const b = n.renderedBoundingBox({includeLabels:false});
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return { x: r.left + (b.x1+b.x2)/2, y: r.top + (b.y1+b.y2)/2 };
        }""")
        page.mouse.click(box["x"], box["y"])
        page.wait_for_timeout(1200)
        opened = page.evaluate("() => !document.getElementById('ew-root').classList.contains('detail-hidden')")
        check(opened, "点击节点打开详情")
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        closed = page.evaluate("() => document.getElementById('ew-root').classList.contains('detail-hidden')")
        check(closed, "Esc 关闭详情")
        # Ctrl+S 保存（不触发浏览器另存）
        page.fill("#ew-name", "打磨验收工作区")
        page.keyboard.press("Control+s")
        page.wait_for_timeout(2500)
        state = page.evaluate("() => (document.getElementById('ew-save-state')||{}).dataset?.state || ''")
        check(state == "saved", "Ctrl+S 触发保存（状态 %s）" % state)
        # Dock 研究笔记页签
        page.click("#ew-dock .cx-dock-tab[data-docktab='notes']")
        page.wait_for_timeout(400)
        check(page.is_visible("#ew-mdx"), "Dock 笔记页签可展开 MDX 输入")
        page.fill("#ew-mdx", "SELECT {} ON 0")
        page.click("#ew-dock-collapse")
        page.wait_for_timeout(400)
        hidden_dock = page.evaluate("() => document.getElementById('ew-dock').dataset.open === '0'")
        check(hidden_dock, "Dock 可收起")
        # 图例折叠
        page.click("#ew-legend-head")
        page.wait_for_timeout(300)
        legend_open = page.evaluate("() => !document.getElementById('ew-legend-body').hidden")
        check(legend_open, "图例可展开")
        page.click("#ew-legend-head")
        page.wait_for_timeout(200)
        page.screenshot(path=os.path.join(OUT, "61_polish_1920.png"))
        page.close()

        # ======================= 4. 紧凑窗口 1366x768 =======================
        print("\n[4] 紧凑窗口 1366x768", flush=True)
        page2 = browser.new_page(viewport={"width": 1366, "height": 768})
        open_workbench(page2)
        fits = page2.evaluate("""() => {
            const root = document.getElementById('ew-root').getBoundingClientRect();
            return { w: root.width, h: root.height, winH: innerHeight,
                     noScroll: document.documentElement.scrollHeight <= innerHeight + 2 };
        }""")
        check(fits["noScroll"], "页面无纵向长滚动（内容高 %d / 视口 %d）" % (fits["h"], fits["winH"]))
        m2 = page2.evaluate(LAYOUT_METRICS)
        check(m2["overlap"] == 0, "紧凑窗口下仍无节点碰撞（%d）" % m2["overlap"])
        # 点搜索结果后资源栏自动收起让位画布（showNode→TM1Shell.hideRail）；toggle 可再展开
        rail_auto_hidden = page2.evaluate("""() => {
            const root = document.getElementById('ew-root');
            const rail = document.querySelector('.cx-rail');
            return root.classList.contains('rail-collapsed') && rail && getComputedStyle(rail).display === 'none';
        }""")
        check(rail_auto_hidden, "紧凑窗口点搜索结果后资源栏自动收起让位画布")
        page2.screenshot(path=os.path.join(OUT, "62_compact_1366.png"))
        real_errors = [e for e in errors if "favicon" not in e and "404" not in e]
        check(not real_errors, "无页面脚本错误" + ("" if not real_errors else "：" + str(real_errors[:2])))
        page2.close()
        browser.close()

    print("\n=== 产品级打磨验收 ===", flush=True)
    if failures:
        print("失败 %d 项" % len(failures), flush=True)
        for f in failures:
            print(" · " + f, flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
