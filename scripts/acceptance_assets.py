"""工程资产 3.0 浏览器验收（真实 Chrome + 真实鼠标）。

链路：合成项目 A 设计 → 提炼 Blueprint → 资产页绑定项目 B → 生成 → 导出 → 导入 → 刷新恢复。
失败退出码 1。
"""
import json
import os
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8011")
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

failures = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def enter_design(page):
    """经可见「＋ 创建」进入设计模式，展开侧栏并恢复全部设计 section。

    旧顶层切换已收进创建菜单。用「维度草稿」入口可 setMode('design') + 展开侧栏，
    再恢复全部 section 可见（openCreateSection 会隐藏非当前 section），
    以便后续操作 #ew-rel-list（section ⑤）。
    """
    page.click("#ew-create")
    page.wait_for_timeout(300)
    page.click("#ew-create-dimension")
    page.wait_for_timeout(900)
    page.evaluate("""() => {
        document.querySelectorAll('#ew-design > details').forEach(d => { d.hidden = false; });
    }""")
    page.wait_for_timeout(300)


def api(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    with OPENER.open(req, timeout=120) as resp:
        return json.load(resp)


def project_a_design():
    """合成项目 A：汽车生产量。与单元测试保持同一结构，但不依赖测试代码。"""
    dims = ["Scenario", "Version", "Year", "Month", "Vehicle", "Plant", "Measure"]
    mapping = [
        dict(target_dimension="Scenario", kind="FIXED", fixed_member="Forecast", source_field="", expression="", confirmed=True),
        dict(target_dimension="Version", kind="FIXED", fixed_member="Working", source_field="", expression="", confirmed=True),
        dict(target_dimension="Year", kind="FIXED", fixed_member="2026", source_field="", expression="", confirmed=True),
        dict(target_dimension="Month", kind="FROM_SOURCE", fixed_member="", source_field="Period", expression="", confirmed=True),
        dict(target_dimension="Vehicle", kind="FROM_SOURCE", fixed_member="", source_field="VehicleCode", expression="", confirmed=True),
        dict(target_dimension="Plant", kind="FROM_SOURCE", fixed_member="", source_field="Plant", expression="", confirmed=True),
        dict(target_dimension="Measure", kind="FIXED", fixed_member="Quantity", source_field="", expression="", confirmed=True),
    ]
    return {
        "mode": "design",
        "dimensions": [],
        "cubes": [{"id": "draft-veh", "name": "VehicleVolume", "note": "",
                   "dimensions": [{"kind": "existing", "name": d, "draft_id": ""} for d in dims],
                   "measures": [], "provenance": "DESIGN_DRAFT"}],
        "schemas": [{"id": "csv-veh", "name": "VehicleProduction.csv", "origin": "USER_INPUT", "note": "",
                     "provenance": "DESIGN_DRAFT",
                     "fields": [{"name": "VehicleCode", "type": "string", "required": False, "note": ""},
                                {"name": "Plant", "type": "string", "required": False, "note": ""},
                                {"name": "Period", "type": "string", "required": False, "note": ""},
                                {"name": "Quantity", "type": "number", "required": True, "note": ""}]}],
        "relations": [{"id": "rel-veh", "source": {"kind": "csv", "ref": "csv-veh"},
                       "target": {"kind": "cube_draft", "ref": "draft-veh"},
                       "mapping": mapping, "value_source": "Quantity", "write_policy": "overwrite",
                       "clear_policy": "target_scope", "template": "csv-to-cube", "confirmed": True,
                       "note": "", "provenance": "DESIGN_RELATION"}],
        "blueprints": [],
    }


BINDINGS_B = [
    ("target_cube", "SalesVolume"), ("dim_1", "Scenario"), ("dim_2", "Version"), ("dim_3", "Year"),
    ("dim_4", "Month"), ("dim_5", "Product"), ("dim_6", "Channel"), ("dim_7", "Measure"),
    ("member_1", "Budget"), ("member_2", "Final"), ("member_3", "2027"),
    ("field_4", "SalesPeriod"), ("field_5", "SKU"), ("field_6", "ChannelCode"),
    ("member_7", "SalesQuantity"), ("value_field", "SalesQuantity"),
    ("source_name", "RetailSales.csv"),
]


def main():
    snap = api("/api/workbench/objects?q=&type=cube")["snapshot_id"]
    ws = api("/api/workbench/workspaces", {
        "workspace": {"schema_version": "architecture-workspace-2", "snapshot_id": snap,
                      "name": "项目A-汽车生产量", "design": project_a_design()},
        "revision": ""})
    workspace_id = ws["id"]

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True,
                                    args=["--no-sandbox", "--no-proxy-server"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        prompts = ["Production Volume Load"]
        page.on("dialog", lambda d: d.accept(prompts.pop(0) if d.type == "prompt" else None)
                if d.type in ("prompt", "confirm") else d.accept())

        # 1. 沙盘打开项目 A，提炼 Blueprint
        page.goto(BASE + "/architecture?view=workbench&workspace_id=" + workspace_id,
                  wait_until="networkidle")
        page.wait_for_timeout(2500)
        enter_design(page)
        page.wait_for_timeout(1200)
        rel_text = page.inner_text("#ew-rel-list")
        check("→" in rel_text, "项目 A 的设计关系已加载")
        page.click("#ew-rel-list button:has-text('提炼为 Blueprint')")
        page.wait_for_timeout(2500)
        check("Blueprint 已创建" in page.inner_text("#ew-detail"), "从设计关系提炼出 Blueprint")

        # 2. 资产页：Blueprint 可见
        page.goto(BASE + "/assets", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check("Production Volume Load" in page.inner_text("#as-items"), "工程资产页列出新建 Blueprint")
        page.locator(".asset-item", has_text="Production Volume Load").first.click()
        page.wait_for_timeout(1200)
        detail = page.inner_text("#as-detail")
        check("角色绑定" in detail, "Blueprint 详情显示角色绑定")
        check("dim_5" in detail, "角色按维度顺序生成")

        # 3. 绑定项目 B 并实例化
        for role, value in BINDINGS_B:
            inp = page.locator(f"input[aria-label='{role}']")
            if inp.count():
                inp.first.fill(value)
                page.locator(f"input[aria-label='{role}']").first.evaluate(
                    "el => el.parentElement.querySelector('input[type=checkbox]').checked = true")
        prompts.append("项目B-快消销量")
        page.click("#as-detail button:has-text('在新项目中使用')")
        page.wait_for_timeout(3000)
        check("已创建项目" in page.inner_text("#as-status"), "绑定后创建项目实例")

        # 4. 生成代码
        page.click("#as-detail button:has-text('生成代码草案')")
        page.wait_for_timeout(3000)
        result = page.evaluate("() => document.querySelector('#as-detail').textContent")
        check("已生成 TI 草案" in result, "项目 B 生成 TI 草案")
        data_src = page.evaluate("""() => {
            const d=[...document.querySelectorAll('#as-detail details')].find(x=>x.querySelector('summary')?.textContent.startsWith('data'));
            return d ? d.querySelector('pre').textContent : '';
        }""")
        prolog_src = page.evaluate("""() => {
            const d=[...document.querySelectorAll('#as-detail details')].find(x=>x.querySelector('summary')?.textContent.startsWith('prolog'));
            return d ? d.querySelector('pre').textContent : '';
        }""")
        check("SalesVolume" in prolog_src and "RetailSales.csv" in prolog_src, "代码使用项目 B 的 Cube 与文件")
        check("vProduct = vSKU;" in data_src and "vChannel = vChannelCode;" in data_src, "代码使用项目 B 的字段映射")
        check("VehicleVolume" not in data_src and "VehicleCode" not in data_src, "代码未残留项目 A 的对象名")
        check("CellPutN(vValue, cCubTgt, vScenario, vVersion, vYear, vMonth, vProduct, vChannel, vMeasure);" in data_src,
              "写入参数顺序与项目 B 维度一致")
        page.screenshot(path=OUT + "/50_assets_generated.png", full_page=False)

        # 5. 导出 → 导入
        page.select_option("#as-scope", "private")
        with page.expect_download() as dl:
            page.click("#as-export")
        download = dl.value
        path = os.path.join(OUT, "tm1-insight-assets.zip")
        download.save_as(path)
        check(os.path.getsize(path) > 200, "导出资产包成功（%d 字节）" % os.path.getsize(path))

        page.set_input_files("#as-import", path)
        page.wait_for_timeout(2500)
        check("导入" in page.inner_text("#as-status"), "资产包可再次导入")

        # 6. 刷新后仍在
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1500)
        check("Production Volume Load" in page.inner_text("#as-items"), "刷新后资产仍存在")
        page.locator(".asset-filters button[data-kind='project']").click()
        page.wait_for_timeout(1200)
        check("项目B" in page.inner_text("#as-items"), "刷新后项目实例仍存在")

        # 7. 回沙盘，原有探索不受影响
        page.goto(BASE + "/architecture?view=workbench", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check(page.is_visible("#ew-root"), "架构沙盘仍可打开")
        check(not [e for e in errors], "无页面脚本错误" + ("" if not errors else "：" + str(errors[:2])))
        browser.close()

    print("\n=== 工程资产浏览器验收 ===")
    if failures:
        print("失败 %d 项" % len(failures))
        sys.exit(1)
    print("全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
