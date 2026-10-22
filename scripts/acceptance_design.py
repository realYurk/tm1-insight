"""Visual Development 2.0 浏览器验收（真实鼠标，断言式）。

场景（匹配「＋ 创建」单 section 交互模型）：
1. 经「＋ 创建 → 维度草稿」创建维度草稿
2. 经「＋ 创建 → Cube 草稿」在 Inspector 编辑器创建 Cube 草稿（维度顺序）
3. 经「＋ 创建 → CSV Schema 草稿」粘贴表头解析字段并保存
4. 经「＋ 创建 → 设计关系」精确建立 CSV → Cube 关系
5. 配置固定成员与来源字段映射，生成 TI 草案
6. 改动映射触发「已过期」STALE 判定
7. 保存工作区 → 刷新 → 设计对象与映射恢复
8. 保存 Blueprint 并恢复
9. 关闭详情保留图与选择；探索模式原有功能不受影响

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


def open_section(page, menu_item_id, wait=600):
    """点「＋ 创建」展开菜单，再点对应菜单项，进入对应单 section。

    openCreateSection 会 setMode('design') + 展开侧栏 + 只显示当前 section。
    #ew-create-cube 走 addCubeDraft（Inspector 编辑器），侧栏保持隐藏。
    """
    page.click("#ew-create")
    page.wait_for_timeout(250)
    page.click(menu_item_id)
    page.wait_for_timeout(wait)


def ensure_design_rail(page):
    """确保设计侧栏（#ew-design）可见，并显示全部设计 section。

    用于需要跨 section 操作（关系清单 / Blueprint）时，把 openCreateSection
    造成的「只显示单 section」恢复为完整面板。
    """
    if not page.is_visible("#ew-design"):
        open_section(page, "#ew-create-dimension")
        # 关闭详情，避免 Inspector 面板遮挡
        close = page.locator("#ew-detail button[aria-label='关闭详情']")
        if close.count():
            close.first.click()
            page.wait_for_timeout(300)
    # 恢复所有顶层 section 可见（openCreateSection 会隐藏非当前 section）
    page.evaluate("""() => {
        document.querySelectorAll('#ew-design > details').forEach(d => { d.hidden = false; });
    }""")


def open_design_section(page, label, open=True):
    """在 #ew-design 中定位指定标题的顶层 section 并展开（恢复其可见性）。"""
    page.evaluate("""(args) => {
        const sec=[...document.querySelectorAll('#ew-design > details')]
            .find(d => (d.querySelector('summary')||{}).textContent?.includes(args.label));
        if (sec) { sec.hidden = false; if (args.open) sec.open = true; }
    }""", {"label": label, "open": open})
    page.wait_for_timeout(300)


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

        # 1. 维度草稿（经「＋ 创建 → 维度草稿」，展开侧栏 section ①）
        open_section(page, "#ew-create-dimension", 800)
        check(page.is_visible("#ew-design"), "进入设计模式后显示设计面板")
        page.fill("#ew-dd-name", "Product")
        page.fill("#ew-dd-elems", "P1\nP2\nP3")
        page.click("#ew-dd-create")
        page.wait_for_timeout(800)
        dim_text = page.inner_text("#ew-design-list")
        check("维度草稿：Product" in dim_text, "维度草稿已创建")
        check("dimdraft-" in dim_text, "维度草稿带独立 draft id")

        # 2. Cube 草稿（经「＋ 创建 → Cube 草稿」，Inspector 编辑器；维度顺序）
        open_section(page, "#ew-create-cube", 1000)
        # addCubeDraft 自动创建 NewCube 并打开编辑器
        page.fill("#ew-edit-cube-name", "SalesCost")
        page.fill("#ew-edit-cube-dims", "Scenario\nVersion\nYear\nProduct\nMeasure")
        page.click("#ew-detail button:has-text('保存草稿')")
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
        if pt:
            page.mouse.click(pt["x"], pt["y"])
            page.wait_for_timeout(1200)
            detail = page.inner_text("#ew-detail")
            check("维度顺序" in detail and "Product" in detail, "草稿详情显示维度顺序")
            check("未部署" in detail, "草稿明确标注未部署")
            page.screenshot(path=OUT + "/40_design_cube_draft.png", full_page=False)

        # 3. CSV Schema（经「＋ 创建 → CSV Schema 草稿」，section ③）
        open_section(page, "#ew-create-source", 800)
        page.fill("#ew-cs-name", "ProductSource.csv")
        page.fill("#ew-cs-header", "ProductCode,Brand,Quantity,UnitCost")
        page.click("#ew-cs-parse")
        page.wait_for_timeout(600)
        fields = page.inner_text("#ew-cs-fields")
        check("ProductCode" in fields and "Quantity" in fields, "表头解析为字段清单")
        page.click("#ew-cs-create")
        page.wait_for_timeout(800)
        check("CSV Schema：ProductSource.csv" in page.inner_text("#ew-design-list"), "Schema 草稿已保存")

        # 4. 设计关系（经「＋ 创建 → 设计关系」，section ④；精确输入表单默认折叠，先展开）
        open_section(page, "#ew-create-relation", 800)
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

        # 5. 映射配置（关系行「配置映射」→ Inspector 映射表）
        # openCreateSection 只显示 section ④，关系清单在 section ⑤（hidden），先恢复其可见性
        open_design_section(page, "设计关系与生成")
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

        # 6. 生成
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

        # 6b. RC 关键项：清空范围可描述、数据源变量契约、过期判定
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

        # 7. 保存 → 刷新 → 恢复
        page.fill("#ew-name", "设计验收")
        page.click("#ew-save")
        page.wait_for_timeout(2500)
        check("已保存" in page.inner_text("#ew-status"), "设计工作区已保存")

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3500)
        # 刷新后设计侧栏默认隐藏，重新展开并恢复全部 section
        ensure_design_rail(page)
        restored = page.inner_text("#ew-design-list")
        check("SalesCost · Cube 草稿" in restored, "刷新后 Cube 草稿恢复")
        check("维度草稿：Product" in restored, "刷新后维度草稿恢复")
        check("CSV Schema：ProductSource.csv" in restored, "刷新后 Schema 恢复")
        check("→ SalesCost" in page.inner_text("#ew-rel-list"), "刷新后设计关系恢复")

        page.click("#ew-rel-list button:has-text('配置映射')")
        page.wait_for_timeout(900)
        d2 = page.evaluate("() => document.querySelector('#ew-detail').textContent")
        check("Forecast" in d2 or "映射" in d2, "刷新后映射仍可编辑")

        # 8. Blueprint（section ⑥）
        open_design_section(page, "Blueprint")
        page.fill("#ew-bp-name", "销售成本装载蓝图")
        page.click("#ew-bp-save")
        page.wait_for_timeout(800)
        check("Blueprint：销售成本装载蓝图" in page.inner_text("#ew-bp-list"), "Blueprint 已保存")
        page.click("#ew-save")
        page.wait_for_timeout(2000)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3000)
        ensure_design_rail(page)
        open_design_section(page, "Blueprint")
        page.wait_for_timeout(500)
        check("Blueprint：销售成本装载蓝图" in page.inner_text("#ew-bp-list"), "刷新后 Blueprint 恢复")

        # 9. 关闭详情保留图与选择；探索模式原有功能不受影响
        # 先点开一个草稿节点（打开详情），再关闭详情，验证画布对象仍在（图与选择不被清空）
        pt = page.evaluate("""() => {
            const cy = window.__ewCanvas.cy();
            const n = cy.nodes().filter(x => x.data('name') === 'SalesCost')[0];
            if (!n) return null;
            const b = n.renderedBoundingBox({ includeLabels: false });
            const r = document.querySelector('#ew-graph').getBoundingClientRect();
            return { x: r.left + (b.x1 + b.x2) / 2, y: r.top + (b.y1 + b.y2) / 2 };
        }""")
        if pt:
            page.mouse.click(pt["x"], pt["y"])
            page.wait_for_timeout(1200)
        check(page.is_visible("#ew-detail"), "点开草稿节点后详情面板打开")
        page.click("#ew-detail button[aria-label='关闭详情']")
        page.wait_for_timeout(500)
        check(not page.is_visible("#ew-detail"), "关闭详情后画布回到主视图（设计对象仍保留）")
        check(page.evaluate("() => window.__ewCanvas.cy().nodes().length") >= 1, "关闭详情后画布节点仍保留")
        if EXPLORE_CUBE:
            # 展开资源栏后搜索
            if not page.is_visible("#ew-rail"):
                page.click("#ew-toggle-rail")
                page.wait_for_timeout(500)
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
