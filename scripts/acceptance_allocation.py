"""浏览器验收：可配置分摊页面（断言式，失败退出码 1）。

流程：打开 /allocation → 修改因子 → 执行计算 → 检查结果表 / 对账 / Mermaid 流程图 / 异常。
全部使用默认合成数据（两基地样例），不触碰真实模型。
"""
import os
import sys
from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8000")
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("  ✗", msg)
    else:
        print("  ✓", msg)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          headless=True, args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append("PAGEERROR: " + str(e)))

    page.goto(f"{BASE}/allocation", wait_until="networkidle")
    page.screenshot(path=f"{OUT}/10_allocation_page.png")
    print("[1] 分摊页面打开 OK")

    # 修改 Z 的驱动因子 700 → 500（验证配置真实影响计算）
    page.evaluate("""() => {
        const t = document.getElementById('al-target');
        t.value = t.value.replace('"700"', '"500"');
    }""")
    page.click("#al-run")
    page.wait_for_selector("#al-results:not([hidden])", timeout=15000)
    page.wait_for_timeout(3000)
    page.screenshot(path=f"{OUT}/11_allocation_result.png", full_page=True)

    rows = page.evaluate("""() => Array.from(document.querySelectorAll('#al-table tbody tr')).map(tr =>
        Array.from(tr.cells).map(c => c.textContent.trim()))""")
    print("[2] 结果表行数:", len(rows))
    for r in rows:
        print("   ", r)
    check(len(rows) == 5, "结果表应有 5 行（A 组 3 + B 组 2）")

    # 用品牌标识（X/Y/Z/W）匹配金额，避免依赖具体文本格式
    def amount_by_brand(brand):
        for r in rows:
            if f"品牌={brand}" in r[1]:
                return r[4]
        return None

    x = amount_by_brand("X")
    y = amount_by_brand("Y")
    z = amount_by_brand("Z")
    # 注意：X 在 A 组（1000000*100/800=125000）和 B 组（500000*50/100=250000）都有
    # 用完整坐标区分：A 组 X 应为 125000.00，B 组 X 应为 250000.00
    def amount_by_group_brand(group, brand):
        for r in rows:
            if f"基地={group}" in r[1] and f"品牌={brand}" in r[1]:
                return r[4]
        return None

    check(amount_by_group_brand("A", "X") == "125000.00", "A 组 X = 125000.00")
    check(amount_by_group_brand("A", "Y") == "250000.00", "A 组 Y = 250000.00")
    check(amount_by_group_brand("A", "Z") == "625000.00", "A 组 Z = 625000.00（驱动 700→500 后）")
    check(amount_by_group_brand("B", "X") == "250000.00", "B 组 X = 250000.00")
    check(amount_by_group_brand("B", "W") == "250000.00", "B 组 W = 250000.00")
    print("[3] 修改因子后结果校验完成")

    recon = page.inner_text("#al-recon")
    print("[4] 对账摘要:", recon.split("\n")[0])
    check("守恒" in recon, "对账应显示守恒")
    check("1500000.00" in recon, "对账应含总源金额 1500000.00")

    mermaid_svg = page.locator("#al-flow .mm-render svg").count()
    print("[5] 分摊流程 Mermaid SVG:", mermaid_svg)
    check(mermaid_svg > 0, "分摊流程应渲染 Mermaid SVG")

    # 保存方案 + 重新加载
    page.fill("#al-name", "浏览器验收方案")
    page.click("#al-save")
    page.wait_for_timeout(800)
    page.evaluate("() => { document.getElementById('al-source').value = '[]'; }")
    page.click("#al-load")
    page.wait_for_timeout(800)
    src = page.input_value("#al-source")
    print("[6] 方案保存后重新加载，源数据恢复:", "1000000" in src)
    check("1000000" in src, "方案保存后重新加载应恢复源数据")

    print()
    print("=== 页面错误 ===")
    for e in errors[:10]:
        print(" ", e)
    if not errors:
        print("  (无)")
    check(not errors, "不应有 pageerror")
    b.close()

print("\n=== 分摊浏览器验收结果 ===")
if failures:
    print("失败 %d 项" % len(failures))
    sys.exit(1)
else:
    print("全部通过 ✓")
    sys.exit(0)
