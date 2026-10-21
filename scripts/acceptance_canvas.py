"""架构画布验收：Cube 图标 + TI/Rule 连线 + 鼠标拖线建模。

全部使用真实 Chrome 与真实鼠标事件（mouse.move / down / up），
失败时返回非零退出码，可直接作为回归门禁。

环境变量：
  TM1_BASE          服务地址，默认 http://127.0.0.1:8011
  TM1_ACCEPT_CUBE   探索用的模型 Cube 名；为空时自动挑一个包含 Sales 的 Cube
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8011")
CUBE = os.environ.get("TM1_ACCEPT_CUBE", "")
OUT = os.path.join("logs", "browser_acceptance")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

failures: list[str] = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def api(path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=120) as resp:
        return json.load(resp)


def node_center(page, name):
    return page.evaluate(
        """(name) => {
            const cy = window.__ewCanvas.cy();
            const n = cy.nodes().filter(x => x.data('name') === name)[0];
            if (!n) return null;
            const b = n.renderedBoundingBox({ includeLabels: false });
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return { x: r.left + (b.x1 + b.x2) / 2, y: r.top + (b.y1 + b.y2) / 2 };
        }""",
        name,
    )


def edge_point(page, index=0):
    return page.evaluate(
        """(i) => {
            const cy = window.__ewCanvas.cy();
            const e = cy.edges()[i];
            if (!e) return null;
            const p = e.midpoint();
            const pan = cy.pan(), z = cy.zoom();
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return { x: r.left + p.x * z + pan.x, y: r.top + p.y * z + pan.y };
        }""",
        index,
    )


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True,
                                     args=["--no-sandbox", "--no-proxy-server"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        def open_workbench(suffix=""):
            page.goto(BASE + "/architecture?view=workbench" + suffix, wait_until="networkidle")
            page.wait_for_timeout(1800)

        # ---------------------------------------------------------- 演示一：探索
        print("\n[1] 探索模式：Cube 图标 + TI/Rule 连线", flush=True)
        target = CUBE
        if not target:
            listed = api("/api/workbench/objects?q=Sales&type=cube")["objects"]
            target = listed[0]["name"] if listed else ""
        open_workbench("&kind=cube&name=" + urllib.parse.quote(target) if target else "")
        if target:
            page.fill("#ew-search", target)
            page.wait_for_timeout(700)
            if page.locator("#ew-resources button").count():
                page.locator("#ew-resources button").first.click()
                page.wait_for_timeout(2600)

        check(page.evaluate("() => document.querySelectorAll('#ew-graph canvas').length") >= 1,
              "画布渲染（Cytoscape canvas 层存在）")
        check(page.evaluate("() => !document.querySelector('#ew-graph svg.flowchart')"),
              "不再用静态 Mermaid 图冒充画布")

        stats = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const nodes = cy.nodes();
            return {nodes: nodes.length, edges: cy.edges().length,
                    nonCube: nodes.filter(n => n.data('type') !== 'cube').length,
                    kinds: [...new Set(cy.edges().map(e => e.data('kind')))]};
        }""")
        check(stats["nodes"] >= 2, "画布上有 %d 个 Cube 图标" % stats["nodes"])
        check(stats["edges"] >= 1, "画布上有 %d 条关系连线" % stats["edges"])
        check(stats["nonCube"] == 0,
              "默认视图只画 Cube，不把每个 TI 画成同级方框（非 Cube 节点 %d）" % stats["nonCube"])
        check("TI_CANDIDATE" in stats["kinds"], "存在 TI 共同读写连线")
        check(bool(stats["kinds"]), "连线带类型（当前可见：%s）" % ",".join(stats["kinds"]))

        box = node_center(page, page.evaluate("() => window.__ewCanvas.cy().nodes()[0].data('name')"))
        page.mouse.click(box["x"], box["y"])
        page.wait_for_timeout(1500)
        detail = page.inner_text("#ew-detail")
        check("维度" in detail, "点击 Cube 后右侧显示维度信息")
        check(page.locator("#ew-detail").is_visible(), "详情以侧栏出现，画布仍在")
        page.screenshot(path=os.path.join(OUT, "50_canvas_explore_node.png"))

        zoom_before = page.evaluate("() => window.__ewCanvas.cy().zoom()")
        pt = edge_point(page, 0)
        if pt:
            page.mouse.click(pt["x"], pt["y"])
            page.wait_for_timeout(1500)
            edge_detail = page.inner_text("#ew-detail")
            check("共同读写" in edge_detail or "声明式" in edge_detail, "点击连线显示关系语义")
            check("→" in edge_detail, "连线详情标出来源与目标")
            page.screenshot(path=os.path.join(OUT, "51_canvas_edge_detail.png"))
        else:
            check(False, "画布上应有可点击的连线")

        page.click("#ew-detail button:has-text('关闭详情')")
        page.wait_for_timeout(900)
        zoom_after = page.evaluate("() => window.__ewCanvas.cy().zoom()")
        check(abs(zoom_before - zoom_after) < 0.001,
              "关闭详情后缩放保持（%.3f → %.3f）" % (zoom_before, zoom_after))
        check(not page.locator("#ew-detail").is_visible(), "关闭详情后画布占满主区域")

        # ---------------------------------------------------------- 演示二：鼠标建模
        print("\n[2] 设计模式：鼠标拖线建立关系 → 配置 → 生成", flush=True)
        page.click("#ew-mode-design")
        page.wait_for_timeout(900)
        check(page.is_visible("#ew-add-cube"), "设计模式出现 + Cube 入口")

        for name in ("SalesCost", "SalesVolume"):
            page.click("#ew-add-cube")
            page.wait_for_timeout(900)
            page.fill("#ew-detail input.input >> nth=0", name)
            page.fill("#ew-detail textarea", "Scenario\nVersion\nYear\nMeasure")
            page.click("#ew-detail button:has-text('保存草稿')")
            page.wait_for_timeout(700)
        page.click("#ew-fit")
        page.wait_for_timeout(600)
        check(page.evaluate(
            "() => window.__ewCanvas.cy().nodes().filter(n => n.data('type') === 'draft').length") == 2,
            "画布上出现两个 Cube 草稿图标")

        src = node_center(page, "SalesCost")
        tgt = node_center(page, "SalesVolume")
        page.mouse.move(src["x"], src["y"])
        page.wait_for_timeout(400)
        anchor = page.locator(".cn-anchor").bounding_box()
        check(anchor is not None, "悬停 Cube 出现连接锚点")
        page.mouse.move(anchor["x"] + 11, anchor["y"] + 11)
        page.wait_for_timeout(120)
        page.mouse.down()
        page.wait_for_timeout(120)
        check(page.evaluate("() => document.querySelector('.cn-connect-line').style.display !== 'none'"),
              "按下锚点后出现拖拽连线")
        for i in range(1, 11):
            page.mouse.move(anchor["x"] + (tgt["x"] - anchor["x"]) * i / 10,
                            anchor["y"] + (tgt["y"] - anchor["y"]) * i / 10)
            page.wait_for_timeout(25)
        page.mouse.up()
        page.wait_for_timeout(1300)
        check("映射" in page.inner_text("#ew-detail h2"), "松手后自动打开映射配置")
        check("SalesCost → SalesVolume" in page.inner_text("#ew-detail"),
              "设计关系方向正确（SalesCost → SalesVolume）")
        page.screenshot(path=os.path.join(OUT, "52_canvas_connect.png"))

        rows = page.locator("#ew-detail .ew-map-row")
        check(rows.count() == 4, "映射按目标维度顺序生成（%d 行）" % rows.count())
        for i, val in enumerate(["Forecast", "Working", "2026", "Amount"]):
            row = rows.nth(i)
            row.locator("select").select_option("FIXED")
            page.wait_for_timeout(100)
            row.locator("input.input").fill(val)
            page.wait_for_timeout(100)
            row.locator("input[type=checkbox]").check()
            page.wait_for_timeout(100)

        page.click("#ew-detail button:has-text('校验并生成 TI 草案')")
        page.wait_for_timeout(2800)
        gen = page.evaluate("() => document.querySelector('#ew-detail').textContent")
        check("TI 草案" in gen and "DESIGN_DRAFT" in gen, "生成 TI 草案（标注未部署）")
        check("清空范围" in gen and "Scenario = Forecast" in gen, "生成面板标明清空范围")
        check("未在 TM1" in gen or "未验证" in gen, "明确标注未在 TM1 验证")
        label = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const e = cy.edges().filter(x => x.data('kind') === 'DESIGN_RELATION')[0];
            return e ? e.data('label') : '';
        }""")
        check("TI Draft" in label, "连线标签反映生成状态（%s）" % label)
        page.screenshot(path=os.path.join(OUT, "53_canvas_generated.png"))

        page.fill("#ew-name", "画布验收工作区")
        page.click("#ew-save")
        page.wait_for_timeout(2600)
        check("已保存" in page.inner_text("#ew-status"), "工作区保存成功")
        workspace_id = page.evaluate("() => (new URLSearchParams(location.search)).get('workspace_id')")
        if not workspace_id:
            saved = api("/api/workbench/workspaces")["workspaces"]
            workspace_id = next((w["id"] for w in saved if w["name"] == "画布验收工作区"), "")
        check(bool(workspace_id), "可定位刚保存的工作区")

        positions_before = page.evaluate("() => window.__ewCanvas.getPositions()")
        if workspace_id:
            open_workbench("&workspace_id=" + workspace_id)
            page.wait_for_timeout(2600)
            restored = page.evaluate("""() => {
                const cy = window.__ewCanvas.cy();
                return {drafts: cy.nodes().filter(n => n.data('type') === 'draft').length,
                        design: cy.edges().filter(e => e.data('kind') === 'DESIGN_RELATION').length,
                        positions: window.__ewCanvas.getPositions()};
            }""")
            check(restored["drafts"] == 2, "刷新后两个 Cube 草稿恢复")
            check(restored["design"] == 1, "刷新后设计连线恢复")
            same = all(abs(positions_before[k]["x"] - restored["positions"].get(k, {}).get("x", 1e9)) < 2
                       for k in positions_before)
            check(same, "刷新后节点位置与保存时一致")
            page.screenshot(path=os.path.join(OUT, "54_canvas_restored.png"))

        # ---------------------------------------------------------- 自环与平行边
        print("\n[3] 自环与平行边（合成图元）", flush=True)
        page.evaluate("""() => {
            window.__ewCanvas.setGraph({nodes: [
                {id: 's-a', name: 'LoopCube', type: 'cube'},
                {id: 's-b', name: 'ParallelCube', type: 'cube'},
            ], edges: [
                {id: 'e-loop', source: 's-a', target: 's-a', kind: 'TI_CANDIDATE', process_names: ['Self.Load'], label: 'Self.Load'},
                {id: 'e-p1', source: 's-a', target: 's-b', kind: 'TI_CANDIDATE', process_names: ['P1'], label: 'P1'},
                {id: 'e-p2', source: 's-a', target: 's-b', kind: 'RULE_REFERENCE', process_names: [], label: 'Rule'},
            ], positions: {}, fit: true});
        }""")
        page.wait_for_timeout(900)
        synth = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const loop = cy.edges().filter(e => e.data('source') === e.data('target'));
            const par = cy.edges().filter(e => e.data('source') !== e.data('target'));
            const b0 = par.length === 2 ? par[0].renderedBoundingBox() : null;
            const b1 = par.length === 2 ? par[1].renderedBoundingBox() : null;
            return {loops: loop.length, parallel: par.length,
                    distinct: !!b0 && (Math.abs(b0.x1 - b1.x1) > 3 || Math.abs(b0.y1 - b1.y1) > 3
                                       || Math.abs(b0.x2 - b1.x2) > 3)};
        }""")
        check(synth["loops"] == 1, "同源同目标的关系渲染为自环，未被隐藏")
        check(synth["parallel"] == 2 and synth["distinct"], "同一对 Cube 的多条关系分开绘制")
        page.click("#ew-fit")
        page.wait_for_timeout(500)
        page.screenshot(path=os.path.join(OUT, "55_canvas_loop_parallel.png"))

        # ---------------------------------------------------------- 演示三：资产复用
        print("\n[4] 资产复用回到画布", flush=True)
        design = {
            "mode": "design",
            "cubes": [{"id": "draft-tgt", "name": "ReuseTarget",
                       "dimensions": [{"kind": "existing", "name": "Scenario"},
                                      {"kind": "existing", "name": "Measure"}]}],
            "schemas": [{"id": "csv-reuse", "name": "ReuseSource.csv",
                         "fields": [{"name": "Qty", "type": "number"}]}],
            "relations": [{"id": "rel-reuse",
                           "source": {"kind": "csv", "ref": "csv-reuse"},
                           "target": {"kind": "cube_draft", "ref": "draft-tgt"},
                           "mapping": [{"target_dimension": "Scenario", "kind": "FIXED",
                                        "fixed_member": "Forecast", "confirmed": True},
                                       {"target_dimension": "Measure", "kind": "FIXED",
                                        "fixed_member": "Amount", "confirmed": True}],
                           "value_source": "Qty", "write_policy": "overwrite",
                           "clear_policy": "target_scope", "template": "csv-to-cube"}],
        }
        bp = api("/api/assets/extract", {"design": design, "relation_id": "rel-reuse",
                                         "name": "Canvas Reuse", "mark_generic": True})
        values = {"target_cube": "ReuseTarget", "dim_1": "Scenario", "dim_2": "Measure",
                  "member_1": "Forecast", "member_2": "Amount", "value_field": "Qty",
                  "source_name": "ReuseSource.csv"}
        inst = api("/api/assets/instantiate", {
            "blueprint_id": bp["id"], "project_name": "画布复用项目",
            "bindings": [{"role": r["id"], "value": values.get(r["id"], ""), "confirmed": True}
                         for r in bp["blueprint"]["roles"]],
            "create_workspace": True})
        if inst.get("workspace_id"):
            open_workbench("&workspace_id=" + inst["workspace_id"])
            page.wait_for_timeout(2400)
            page.click("#ew-mode-design")
            page.wait_for_timeout(1400)
            reuse = page.evaluate("""() => {
                const cy = window.__ewCanvas.cy();
                return {drafts: cy.nodes().filter(n => n.data('type') === 'draft').length,
                        sources: cy.nodes().filter(n => n.data('type') === 'source').length,
                        design: cy.edges().filter(e => e.data('kind') === 'DESIGN_RELATION').length};
            }""")
            check(reuse["drafts"] >= 1, "Blueprint 实例化后画布出现 %d 个 Cube 图标" % reuse["drafts"])
            check(reuse["sources"] >= 1, "画布出现 CSV 数据来源图标")
            check(reuse["design"] >= 1, "画布出现对应的设计连线")
            page.click("#ew-fit")
            page.wait_for_timeout(500)
            page.screenshot(path=os.path.join(OUT, "56_canvas_blueprint.png"))
        else:
            check(False, "Blueprint 实例化应返回 workspace_id")

        real_errors = [e for e in errors if "favicon" not in e and "404" not in e]
        check(not real_errors, "无页面脚本错误" + ("" if not real_errors else "：" + str(real_errors[:3])))
        browser.close()

    print("\n=== 架构画布验收 ===", flush=True)
    if failures:
        print("失败 %d 项" % len(failures), flush=True)
        for f in failures:
            print(" · " + f, flush=True)
        return 1
    print("全部通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
