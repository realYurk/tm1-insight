"""浏览器验收：连续探索工作台（断言式，失败退出码 1）。

真实 Chrome + Playwright，离线，只读访问本地快照，不连接任何 TM1 Server。
覆盖：图渲染、节点/边点击、TI 源码、写入切面、多选与人工模块、
      工作区保存-刷新-恢复、代码模板往返、快照隔离、控制台错误。
"""
import json
import os
import sys
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8011")
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 默认使用合成示例名；真实模型验收请用环境变量覆盖，避免企业对象名进入公开仓库。
CUBE = os.environ.get("TM1_ACCEPT_CUBE", "General Ledger")
ACT = os.environ.get("TM1_ACCEPT_TI", "Cub.Sales Cost Driver.Data.Load.From.Planning PnL.ACT")

failures = []


def check(cond, msg):
    if cond:
        print("  OK  " + msg)
    else:
        failures.append(msg)
        print("  FAIL " + msg)


def api(path, body=None):
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=180) as resp:
        return json.load(resp)


def main():
    snapshot = api("/api/workbench/objects?q=&type=cube")["snapshot_id"]
    print("snapshot=" + snapshot[:16])

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True,
                                    args=["--no-sandbox", "--no-proxy-server"])
        page = browser.new_page(viewport={"width": 1560, "height": 980})
        errors = []
        page.on("pageerror", lambda e: errors.append("PAGEERROR: " + str(e)))
        page.on("console", lambda m: errors.append("CONSOLE: " + m.text) if m.type == "error" else None)

        # 1. 打开工作台
        page.goto(BASE + "/architecture?view=workbench&kind=cube&name=" + urllib.parse.quote(CUBE),
                  wait_until="networkidle")
        page.wait_for_selector("#ew-graph canvas", timeout=30000)

        def node_count():
            return page.evaluate("() => window.__ewCanvas.cy().nodes().length")

        def edge_count():
            return page.evaluate("() => window.__ewCanvas.cy().edges().length")

        def click_node(pattern, ctrl=False):
            """按名称片段在画布上做真实鼠标点击。"""
            pt = page.evaluate("""(pat) => {
                const cy = window.__ewCanvas.cy();
                const n = cy.nodes().filter(x => (x.data('fullName') || '').includes(pat))[0];
                if (!n) return null;
                const b = n.renderedBoundingBox({ includeLabels: false });
                const r = document.querySelector('#ew-graph').getBoundingClientRect();
                return { x: r.left + (b.x1 + b.x2) / 2, y: r.top + (b.y1 + b.y2) / 2 };
            }""", pattern)
            if not pt:
                return False
            if ctrl:
                page.keyboard.down("Control")
            page.mouse.click(pt["x"], pt["y"])
            if ctrl:
                page.keyboard.up("Control")
            page.wait_for_timeout(1200)
            return True

        def close_detail():
            if page.locator("#ew-detail button[aria-label='关闭详情']").count():
                page.click("#ew-detail button[aria-label='关闭详情']")
                page.wait_for_timeout(500)

        def refit():
            page.click("#ew-fit")
            page.wait_for_timeout(450)
        page.screenshot(path=OUT + "/30_workbench_initial.png", full_page=False)
        nodes = node_count()
        check(nodes >= 3, "首次进入即渲染局部图（%d 个 Cube 图标）" % nodes)

        # 2. 搜索并切换对象（资源栏默认收起，先展开）
        if page.locator("#ew-rail").evaluate("el => getComputedStyle(el).display") == "none":
            page.click("#ew-toggle-rail")
            page.wait_for_timeout(300)
        page.fill("#ew-search", CUBE)
        page.wait_for_timeout(600)
        results = page.locator("#ew-resources button")
        check(results.count() > 0, "对象搜索有结果（%d）" % results.count())
        results.first.click()
        page.wait_for_timeout(2500)
        title = page.inner_text("#ew-detail")
        check(CUBE in title, "点击搜索结果后详情切换到该 Cube")
        check("实际维度顺序" in title, "详情展示真实维度顺序")
        check(node_count() >= 3, "图在详情打开后仍然保留")

        # 3. 展开直接 TI 关系
        page.get_by_role("button", name="展开直接 TI / 调用关系").first.click()
        page.wait_for_timeout(3000)
        summary = page.inner_text("#ew-summary")
        check("个可见对象" in summary, "展开后出现对象/关系统计：" + summary.split("。")[0])

        # 4. 点击 TI 节点，检查源码与写入切面
        close_detail()
        refit()
        if not (click_node("General Ledger.Data.Load.From.CSV") or click_node("Data.Load")):
            check(False, "画布上应能找到目标 TI 节点")
        page.wait_for_timeout(1500)
        detail = page.inner_text("#ew-detail")
        check("读取" in detail or "写入" in detail, "TI 详情显示读取/写入 Cube")

        # 写入切面在 process 详情打开时已自动分析（loadWrites.click()），
        # 详细切面渲染在「源码与证据」标签页，切换到该标签查看。
        page.get_by_role("tab", name="源码与证据").first.click()
        page.wait_for_timeout(3000)
        detail = page.evaluate("() => document.querySelector('#ew-detail').textContent")
        check("已解析目标写入" in detail, "写入切面面板展开")
        check(CUBE in detail, "写入目标 Cube 正确")
        check("固定目标切面" in detail, "固定目标切面默认可见（无需展开）")
        check("Planning Assumption" in detail or "No Cost Center" in detail, "固定目标成员具体值可见")
        check("运行时" in detail and ("vScenario" in detail or "vYear" in detail), "运行时变量坐标可见")
        check("源码值表达式" in detail and ("vValue" in detail or "vAmount" in detail or "vBalance" in detail),
              "源码值表达式原样显示（未臆测来源）")
        check("待确认" in detail or "未" in detail, "未确认项有明确标注")
        page.screenshot(path=OUT + "/31_workbench_act_writes.png", full_page=False)

        # 5. 打开源码区块（行号由共享源码组件提供）
        page.evaluate("""() => {
            const d=[...document.querySelectorAll('#ew-detail details')].find(x=>(x.querySelector('summary')||{}).textContent.includes('源码'));
            if(d){d.open=true;}
        }""")
        page.wait_for_timeout(1800)
        lines = page.locator("#ew-detail .code-line").count()
        check(lines > 5, "源码区块可展开并渲染行号（%d 行）" % lines)

        # 6. 多选 + 框选 + 人工模块
        close_detail()
        refit()
        first = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const n = cy.nodes().filter(x => x.data('type') === 'cube')[0];
            if (!n) return null;
            const b = n.renderedBoundingBox({ includeLabels: false });
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return { id: n.id(), x: r.left + (b.x1 + b.x2) / 2, y: r.top + (b.y1 + b.y2) / 2 };
        }""")
        page.mouse.click(first["x"], first["y"])
        page.wait_for_timeout(900)
        close_detail()
        refit()
        second = page.evaluate("""(skip) => {
            const cy = window.__ewCanvas.cy();
            const n = cy.nodes().filter(x => x.data('type') === 'cube' && x.id() !== skip)[0];
            if (!n) return null;
            const b = n.renderedBoundingBox({ includeLabels: false });
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return { x: r.left + (b.x1 + b.x2) / 2, y: r.top + (b.y1 + b.y2) / 2 };
        }""", first["id"])
        page.keyboard.down("Control")
        page.mouse.click(second["x"], second["y"])
        page.keyboard.up("Control")
        page.wait_for_timeout(1000)
        check(page.evaluate("() => window.__ewCanvas.cy().nodes().filter(n => n.hasClass('cn-selected')).length") == 2,
              "真实鼠标 Ctrl 多选两个 Cube")
        # 人工模块在侧栏「人工模块」details 中（默认折叠），先展开并确保资源栏可见
        if page.locator("#ew-rail").evaluate("el => getComputedStyle(el).display") == "none":
            page.click("#ew-toggle-rail")
            page.wait_for_timeout(300)
        page.evaluate("() => { const d=document.getElementById('ew-module-tools'); if(d) d.open = true; }")
        page.wait_for_timeout(300)
        page.fill("#ew-group-name", "验收模块A")
        page.click("#ew-group-create")
        page.wait_for_timeout(800)
        groups = page.inner_text("#ew-groups")
        check("验收模块A" in groups, "从选中对象创建人工模块")
        check("人工解释" in groups, "人工模块标注为人工解释")

        # 框选（Shift + 拖动）
        close_detail()
        refit()
        box = page.locator("#ew-graph").bounding_box()
        page.mouse.move(box["x"] + 12, box["y"] + 12)
        page.keyboard.down("Shift")
        page.mouse.down()
        for i in range(1, 10):
            page.mouse.move(box["x"] + 12 + i * (box["width"] - 24) / 9,
                            box["y"] + 12 + i * (box["height"] - 24) / 9)
            page.wait_for_timeout(20)
        page.mouse.up()
        page.keyboard.up("Shift")
        page.wait_for_timeout(800)
        check(page.evaluate("() => window.__ewCanvas.cy().nodes().filter(n => n.hasClass('cn-selected')).length") >= 2,
              "Shift + 框选在画布上高亮多个 Cube")

        # 7. 备注与 MDX
        # 研究笔记收在底部 Dock 的「研究笔记」页签里，先展开再填写
        page.click("#ew-dock .cx-dock-tab[data-docktab='notes']")
        page.wait_for_timeout(400)
        page.fill("#ew-mdx", "SELECT {[Scenario].[SP75]} ON 0")
        page.fill("#ew-notes", "验收备注：只保存不执行")
        page.fill("#ew-name", "验收工作区")

        # 8. 保存 → 刷新 → 恢复
        page.click("#ew-save")
        page.wait_for_timeout(2500)
        check("已保存" in page.inner_text("#ew-status"), "工作区保存成功")
        workspace_id = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query).get("workspace_id", [""])[0]
        check(bool(workspace_id), "保存后 URL 带 workspace_id")

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3500)
        check(page.input_value("#ew-name") == "验收工作区", "刷新后自动恢复同名工作区")
        check("SP75" in page.input_value("#ew-mdx"), "MDX 研究文本原文恢复")
        check("SELECT" in page.input_value("#ew-mdx"), "MDX 结构完整（未被截断或改写）")
        check("验收备注" in page.input_value("#ew-notes"), "设计笔记恢复")
        page.evaluate("() => { const d=document.getElementById('ew-module-tools'); if(d) d.open = true; }")
        page.wait_for_timeout(300)
        restored_groups = page.inner_text("#ew-groups")
        check("验收模块A" in restored_groups, "人工模块恢复")
        check(node_count() >= 2, "刷新后画布重新渲染")
        page.screenshot(path=OUT + "/32_workbench_restored.png", full_page=False)

        # 9. 图 → 表联动：点击一条边应在关系表中定位并标记
        edges_now = edge_count()
        check(edges_now > 0, "画布上存在可点击的关系边（%d）" % edges_now)
        if edges_now:
            close_detail()
            refit()
            pt = page.evaluate("""() => {
                const cy = window.__ewCanvas.cy();
                const e = cy.edges()[0];
                const p = e.midpoint();
                const pan = cy.pan(), z = cy.zoom();
                const r = document.querySelector('#ew-graph').getBoundingClientRect();
                return { x: r.left + p.x * z + pan.x, y: r.top + p.y * z + pan.y };
            }""")
            page.mouse.click(pt["x"], pt["y"])
            page.wait_for_timeout(1500)
            selected_rows = page.locator("#ew-relations tr[data-edge][aria-selected='true']").count()
            check(selected_rows == 1, "点击画布上的边，关系表定位到唯一对应记录（%d）" % selected_rows)
            edge_text = page.evaluate("() => document.querySelector('#ew-detail').textContent")
            check(any(k in edge_text for k in ("尚未证明", "不是", "索引观察", "待核对")),
                  "边详情说明关系语义，不把候选当值流")

        # 10. 代码模板往返：选中两个 Cube
        close_detail()
        refit()
        cube_pts = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return cy.nodes().filter(n => n.data('type') === 'cube').slice(0, 2).map(n => {
                const b = n.renderedBoundingBox({ includeLabels: false });
                return { x: r.left + (b.x1 + b.x2) / 2, y: r.top + (b.y1 + b.y2) / 2 };
            });
        }""")
        page.mouse.click(cube_pts[0]["x"], cube_pts[0]["y"])
        page.wait_for_timeout(700)
        close_detail()
        refit()
        cube_pts = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return cy.nodes().filter(n => n.data('type') === 'cube').slice(0, 2).map(n => {
                const b = n.renderedBoundingBox({ includeLabels: false });
                return { x: r.left + (b.x1 + b.x2) / 2, y: r.top + (b.y1 + b.y2) / 2 };
            });
        }""")
        page.keyboard.down("Control")
        page.mouse.click(cube_pts[1]["x"], cube_pts[1]["y"])
        page.keyboard.up("Control")
        page.wait_for_timeout(1500)
        link = page.locator("#ew-detail button:has-text('将两个 Cube 带入现有代码模板')")
        check(link.count() > 0, "两个 Cube 选中后出现代码模板入口")
        if link.count():
            link.first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            check("/codegen" in page.url, "进入代码模板页并携带工作区")
            status = page.inner_text("#cg-action-status")
            check("已从工作区带入" in status or "不匹配" in status or "不在工作区" in status, "模板页给出来源/目标带入状态：" + status[:40])
            back = page.locator("a:has-text('返回原工作区')")
            check(back.count() > 0, "模板页提供返回原工作区入口")
            if back.count():
                back.first.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(3000)
                check("view=workbench" in page.url, "返回原工作区 URL")
                check(page.input_value("#ew-name") == "验收工作区", "返回后仍为同一工作区")
            page.screenshot(path=OUT + "/33_codegen_roundtrip.png", full_page=False)
        else:
            check(False, "两个 Cube 选中后应出现代码模板入口")

        # 10. 快照隔离（API 级，浏览器上下文内）
        isolated = page.evaluate("""async () => {
            const r=await fetch('/api/workbench/graph',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({snapshot_id:'deadbeef'})});
            return r.status;
        }""")
        check(isolated == 409, "其他 Snapshot 的工作区被拒绝（HTTP %s）" % isolated)

        real_errors = [e for e in errors if "favicon" not in e and "404" not in e and "409" not in e]
        check(not real_errors, "无页面脚本错误" + ("" if not real_errors else "：" + str(real_errors[:3])))
        browser.close()

    print("\n=== 工作台浏览器验收结果 ===")
    if failures:
        print("失败 %d 项" % len(failures))
        sys.exit(1)
    print("全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
