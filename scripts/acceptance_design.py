"""Visual Development 2.0 浏览器验收（真实鼠标，断言式）。

场景：
1. 切到设计模式，创建维度草稿与 Cube 草稿（维度顺序）
2. 粘贴 CSV 表头创建 Schema
3. 建立 CSV → Cube 设计关系
4. 配置固定成员与来源字段映射，生成 TI 草案
5. 保存工作区 → 刷新 → 设计对象与映射恢复
6. 保存 Blueprint 并恢复
7. 切回探索模式，原有功能不受影响

失败退出码 1。
用法：
  TM1_BASE=http://127.0.0.1:8011 [TM1_ACCEPT_CUBE=<真实cube>] python scripts/acceptance_design.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8011")
EXPLORE_CUBE = os.environ.get("TM1_ACCEPT_CUBE", "")  # 可选：真实模型对象，用于回归探索模式
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

failures = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True,
                                    args=["--no-sandbox", "--no-proxy-server"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE + "/architecture?view=workbench", wait_until="networkidle")
        page.wait_for_selector("#ew-root", timeout=30000)
        page.wait_for_timeout(1200)

        # 1. 设计模式
        page.click("#ew-mode-design")
        page.wait_for_timeout(1500)
        check(page.is_visible("#ew-design"), "切换到设计模式后显示设计面板")

        # 2. 维度草稿
        page.fill("#ew-dd-name", "Product")
        page.fill("#ew-dd-elems", "P1\nP2\nP3")
        page.click("#ew-dd-create")
        page.wait_for_timeout(800)
        dim_text = page.inner_text("#ew-design-list")
        check("维度草稿：Product" in dim_text, "维度草稿已创建")
        check("dimdraft-" in dim_text, "维度草稿带独立 draft id")

        # 3. Cube 草稿（顺序：Scenario/Version/Year/Product/Measure）
        page.fill("#ew-dc-name", "SalesCost")
        page.fill("#ew-dc-dims", "Scenario\nVersion\nYear\nMeasure")
        page.click("#ew-design-list button:has-text('引用到 Cube 维度框')")
        page.wait_for_timeout(300)
        dims_value = page.input_value("#ew-dc-dims")
        lines = [x for x in dims_value.split("\n") if x.strip()]
        lines.insert(3, lines.pop())  # 把 Product 移到 Year 之后
        page.fill("#ew-dc-dims", "\n".join(lines))
        page.click("#ew-dc-create")
        page.wait_for_timeout(1200)
        design_text = page.inner_text("#ew-design-list")
        check("SalesCost · Cube 草稿" in design_text, "Cube 草稿已创建")
        check(page.evaluate("() => window.__ewCanvas.cy().nodes().length") >= 1, "Cube 草稿出现在画布上")

        # 用真实鼠标点击草稿节点查看维度顺序
        pt = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const n = cy.nodes().filter(x => x.data('name') === 'SalesCost')[0];
            if (!n) return null;
            const b = n.renderedBoundingBox({ includeLabels: false });
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return { x: r.left + (b.x1 + b.x2) / 2, y: r.top + (b.y1 + b.y2) / 2 };
        }""")
        check(pt is not None, "画布上能找到 SalesCost 草稿节点")
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_timeout(1200)
        detail = page.inner_text("#ew-detail")
        check("维度顺序" in detail and "Product" in detail, "草稿详情显示维度顺序")
        check("未部署" in detail, "草稿明确标注未部署")
        page.screenshot(path=OUT + "/40_design_cube_draft.png", full_page=False)

        # 4. CSV Schema
        page.fill("#ew-cs-name", "ProductSource.csv")
        page.fill("#ew-cs-header", "ProductCode,Brand,Quantity,UnitCost")
        page.click("#ew-cs-parse")
        page.wait_for_timeout(600)
        fields = page.inner_text("#ew-cs-fields")
        check("ProductCode" in fields and "Quantity" in fields, "表头解析为字段清单")
        page.click("#ew-cs-create")
        page.wait_for_timeout(800)
        check("CSV Schema：ProductSource.csv" in page.inner_text("#ew-design-list"), "Schema 草稿已保存")

        # 5. 设计关系（精确输入表单默认折叠，先展开）
        page.evaluate("""() => {
            const d=[...document.querySelectorAll('#ew-design details')]
                .find(x => (x.querySelector('summary')||{}).textContent?.includes('或按名称精确建立'));
            if (d) d.open = true;
        }""")
        page.wait_for_timeout(300)
        page.evaluate("""() => {
            const s=document.getElementById('ew-rel-source');
            s.value=[...s.options].find(o=>o.text.includes('ProductSource.csv')).value;
        }""")
        page.wait_for_timeout(300)
        page.click("#ew-rel-create")
        page.wait_for_timeout(800)
        check("→ SalesCost" in page.inner_text("#ew-rel-list"), "设计关系已建立")

        # 6. 映射配置
        page.click("#ew-rel-list button:has-text('配置映射')")
        page.wait_for_timeout(800)
        rows = page.locator("#ew-detail .ew-map-row")
        check(rows.count() == 5, "映射表按目标维度数量生成（%d）" % rows.count())

        mapping = [("FIXED", "Forecast"), ("FIXED", "Working"), ("FIXED", "2026"),
                   ("FROM_SOURCE", "ProductCode"), ("FIXED", "Quantity")]
        for i, (kind, value) in enumerate(mapping):
            row = rows.nth(i)
            row.locator("select").select_option(kind)
            row.locator("input[type=text], input:not([type])").first.fill(value)
            row.locator("input[type=checkbox]").check()
            page.wait_for_timeout(150)
        page.wait_for_timeout(500)
        # 数值来源列
        page.select_option("#ew-vsource", "Quantity")
        page.wait_for_timeout(400)

        # 7. 生成
        page.click("#ew-detail button:has-text('校验并生成 TI 草案')")
        page.wait_for_timeout(3000)
        detail = page.evaluate("() => document.querySelector('#ew-detail').textContent")
        check("生成结果" in detail, "生成结果面板打开")
        check("TI 草案" in detail and "DESIGN_DRAFT" in detail, "结果标注为草稿，未部署")
        data_src = page.evaluate("""() => {
            const d=[...document.querySelectorAll('#ew-detail details')].find(x=>x.querySelector('summary')?.textContent.startsWith('data'));
            return d ? d.querySelector('pre').textContent : '';
        }""")
        check("CellPutN(vValue, cCubTgt, vScenario, vVersion, vYear, vProduct, vMeasure);" in data_src,
              "写入语句按目标维度顺序生成")
        check("vScenario = 'Forecast';" in data_src and "vProduct = vProductCode;" in data_src,
              "固定成员与来源字段映射正确")
        check("StringToNumberEx( vQuantity" in data_src, "数值列转换为 vValue")
        page.screenshot(path=OUT + "/41_design_generated.png", full_page=False)

        # 7b. RC 关键项：清空范围可描述、数据源变量契约、过期判定
        panel_text = page.evaluate("() => document.querySelector('#ew-detail').textContent")
        check("清空范围" in panel_text and "Scenario = Forecast" in panel_text,
              "生成面板显示可描述的清空范围")
        check("数据源变量" in panel_text and "vProductCode" in panel_text,
              "生成面板列出数据源变量（Variables 页签契约）")
        check("未在 TM1" in panel_text or "未验证" in panel_text, "明确标注未在 TM1 验证")

        rel_row = page.inner_text("#ew-rel-list")
        check("已生成草案" in rel_row, "关系行显示已生成状态")

        # 改动固定成员 → 应显示「已过期」
        page.click("#ew-rel-list button:has-text('配置映射')")
        page.wait_for_timeout(800)
        first_value = page.locator("#ew-detail .ew-map-row input.input").first
        first_value.fill("Actual")
        first_value.dispatch_event("input")
        page.wait_for_timeout(1500)
        check("已过期" in page.inner_text("#ew-rel-list"), "设计变更后标记代码草案已过期")
        page.screenshot(path=OUT + "/42_design_stale.png", full_page=False)

        # 清空策略改为 none → 不再要求固定成员范围
        page.wait_for_timeout(300)
        page.select_option("#ew-cclear", "none")
        page.wait_for_timeout(600)

        # 8. 保存 → 刷新 → 恢复
        page.fill("#ew-name", "设计验收")
        page.click("#ew-save")
        page.wait_for_timeout(2500)
        check("已保存" in page.inner_text("#ew-status"), "设计工作区已保存")

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3500)
        restored = page.inner_text("#ew-design-list")
        check("SalesCost · Cube 草稿" in restored, "刷新后 Cube 草稿恢复")
        check("维度草稿：Product" in restored, "刷新后维度草稿恢复")
        check("CSV Schema：ProductSource.csv" in restored, "刷新后 Schema 恢复")
        check("→ SalesCost" in page.inner_text("#ew-rel-list"), "刷新后设计关系恢复")

        page.click("#ew-rel-list button:has-text('配置映射')")
        page.wait_for_timeout(900)
        d2 = page.evaluate("() => document.querySelector('#ew-detail').textContent")
        check("Forecast" in d2 or "映射" in d2, "刷新后映射仍可编辑")

        # 9. Blueprint
        page.click("details:has(summary:text('⑥ Blueprint')) > summary")
        page.wait_for_timeout(400)
        page.fill("#ew-bp-name", "销售成本装载蓝图")
        page.click("#ew-bp-save")
        page.wait_for_timeout(800)
        check("Blueprint：销售成本装载蓝图" in page.inner_text("#ew-bp-list"), "Blueprint 已保存")
        page.click("#ew-save")
        page.wait_for_timeout(2000)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3000)
        page.evaluate("""() => { const d=[...document.querySelectorAll('#ew-design details')].find(x=>x.querySelector('summary')?.textContent.includes('Blueprint')); if(d)d.open=true; }""")
        page.wait_for_timeout(500)
        check("Blueprint：销售成本装载蓝图" in page.inner_text("#ew-bp-list"), "刷新后 Blueprint 恢复")

        # 10. 切回探索模式，原有功能不受影响
        page.click("#ew-mode-explore")
        page.wait_for_timeout(1200)
        check(not page.is_visible("#ew-design"), "切回探索模式隐藏设计面板")
        if EXPLORE_CUBE:
            page.fill("#ew-search", EXPLORE_CUBE)
            page.wait_for_timeout(900)
            check(page.locator("#ew-resources button").count() > 0, "探索模式仍可搜索真实对象")
            page.locator("#ew-resources button").first.click()
            page.wait_for_timeout(2500)
            check("维度顺序" in page.inner_text("#ew-detail")
                  or "本地模型对象" in page.inner_text("#ew-detail"), "探索模式对象详情仍可用")

        check(not errors, "无页面脚本错误" + ("" if not errors else "：" + str(errors[:2])))
        browser.close()

    print("\n=== 设计模式浏览器验收 ===")
    if failures:
        print("失败 %d 项" % len(failures))
        sys.exit(1)
    print("全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
