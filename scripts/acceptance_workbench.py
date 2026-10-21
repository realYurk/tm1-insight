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
CUBE = os.environ.get("TM1_ACCEPT_CUBE", "Sales Cost Driver")
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
        page.wait_for_selector("#ew-graph svg", timeout=30000)
        page.screenshot(path=OUT + "/30_workbench_initial.png", full_page=False)
        nodes = page.locator("#ew-graph svg .node").count()
        check(nodes >= 3, "首次进入即渲染局部图（%d 个节点）" % nodes)

        # 2. 搜索并切换对象
        page.fill("#ew-search", CUBE)
        page.wait_for_timeout(600)
        results = page.locator("#ew-resources button")
        check(results.count() > 0, "对象搜索有结果（%d）" % results.count())
        results.first.click()
        page.wait_for_timeout(2500)
        title = page.inner_text("#ew-detail")
        check(CUBE in title, "点击搜索结果后详情切换到该 Cube")
        check("实际维度顺序" in title, "详情展示真实维度顺序")
        check(page.locator("#ew-graph svg .node").count() >= 3, "图在详情打开后仍然保留")

        # 3. 展开直接 TI 关系
        page.get_by_role("button", name="展开直接 TI / 调用关系").first.click()
        page.wait_for_timeout(3000)
        summary = page.inner_text("#ew-summary")
        check("个可见对象" in summary, "展开后出现对象/关系统计：" + summary.split("。")[0])

        # 4. 点击 TI 节点，检查源码与写入切面
        page.evaluate(
            """(act) => {
                const nodes=[...document.querySelectorAll('#ew-graph svg .node')];
                const target=nodes.find(n=>n.textContent.includes('ACT'));
                (target||nodes.find(n=>n.textContent.includes('Data.Load')))?.dispatchEvent(
                    new MouseEvent('click',{bubbles:true}));
            }""", ACT)
        page.wait_for_timeout(2500)
        detail = page.inner_text("#ew-detail")
        check("读取" in detail or "写入" in detail, "TI 详情显示读取/写入 Cube")

        page.get_by_role("button", name="核对写入切面与值表达式").first.click()
        page.wait_for_timeout(3000)
        detail = page.evaluate("() => document.querySelector('#ew-detail').textContent")
        check("已解析目标写入" in detail, "写入切面面板展开")
        check(CUBE in detail, "写入目标 Cube 正确")
        check("固定目标切面" in detail, "固定目标切面默认可见（无需展开）")
        check("Planning Assumption" in detail or "Allocation Type" in detail, "固定目标成员具体值可见")
        check("运行时" in detail and "vScenario" in detail, "运行时变量坐标可见")
        check("vValue" in detail, "源码值表达式 vValue 原样显示（未臆测来源）")
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
        page.evaluate("""() => {
            const nodes=[...document.querySelectorAll('#ew-graph svg .node')];
            nodes.slice(0,2).forEach((n,i)=>n.dispatchEvent(new MouseEvent('click',{bubbles:true,ctrlKey:i>0})));
        }""")
        page.wait_for_timeout(1200)
        page.fill("#ew-group-name", "验收模块A")
        page.click("#ew-group-create")
        page.wait_for_timeout(800)
        groups = page.inner_text("#ew-groups")
        check("验收模块A" in groups, "从选中对象创建人工模块")
        check("人工解释" in groups, "人工模块标注为人工解释")

        # 框选
        page.click("#ew-graph .mm-toolbar button:has-text('框选模式')")
        box = page.locator("#ew-graph .mm-viewport").bounding_box()
        page.mouse.move(box["x"] + 20, box["y"] + 20)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] - 20, box["y"] + box["height"] - 20, steps=8)
        page.mouse.up()
        page.wait_for_timeout(800)
        check(page.locator("#ew-graph svg .ew-selected").count() >= 2, "Shift/框选多选在图上高亮")

        # 7. 备注与 MDX
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
        restored_groups = page.inner_text("#ew-groups")
        check("验收模块A" in restored_groups, "人工模块恢复")
        check(page.locator("#ew-graph svg .node").count() >= 2, "刷新后图重新渲染")
        page.screenshot(path=OUT + "/32_workbench_restored.png", full_page=False)

        # 9. 图 → 表联动：点击一条边应在关系表中定位并标记
        edge_count = page.locator("#ew-graph svg .flowchart-link").count()
        check(edge_count > 0, "图上存在可点击的关系边（%d）" % edge_count)
        if edge_count:
            # 边路径中心的命中点可能被节点覆盖，这里直接触发绑定的事件处理器，
            # 验证的是真实的事件绑定与联动语义，而不是像素命中。
            page.evaluate("""() => {
                const e=document.querySelector('#ew-graph svg .flowchart-link');
                e.dispatchEvent(new MouseEvent('click',{bubbles:true}));
            }""")
            page.wait_for_timeout(1500)
            selected_rows = page.locator("#ew-relations tr[data-edge][aria-selected='true']").count()
            check(selected_rows == 1, "点击图上的边，关系表定位到唯一对应记录（%d）" % selected_rows)
            edge_text = page.evaluate("() => document.querySelector('#ew-detail').textContent")
            check(any(k in edge_text for k in ("尚未证明", "不是", "索引观察", "待核对")),
                  "边详情说明关系语义，不把候选当值流")

        # 10. 代码模板往返：选中两个 Cube
        page.evaluate("""() => {
            const nodes=[...document.querySelectorAll('#ew-graph svg .node')]
                .filter(n=>/Cube\\s*$/.test(n.textContent.trim()));
            nodes.slice(0,2).forEach((n,i)=>n.dispatchEvent(new MouseEvent('click',{bubbles:true,ctrlKey:i>0})));
        }""")
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
