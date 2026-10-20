"""浏览器验收：可配置分摊页面。

流程：打开 /allocation → 修改因子 → 执行计算 → 检查结果表 / 对账 / Mermaid 流程图 / 异常。
全部使用默认合成数据（两基地样例），不触碰真实模型。
"""
import os, re
from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8000")
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)

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

    # 校验结果
    rows = page.evaluate("""() => Array.from(document.querySelectorAll('#al-table tbody tr')).map(tr =>
        Array.from(tr.cells).map(c => c.textContent.trim()))""")
    print("[2] 结果表行数:", len(rows))
    for r in rows:
        print("   ", r)
    # A 基地 1,000,000 按 100/200/500 → 125000 / 250000 / 625000
    amounts = {r[1].split("=")[-1]: r[4] for r in rows if "品牌=X" in r[1] or "品牌=Y" in r[1] or "品牌=Z" in r[1]}
    ok = (amounts.get("X") == "125000.00" and amounts.get("Y") == "250000.00" and amounts.get("Z") == "625000.00")
    print(f"[3] 修改因子后结果正确 (125000/250000/625000): {ok}")

    recon = page.inner_text("#al-recon")
    print("[4] 对账摘要:", recon.split("\\n")[0])
    mermaid_svg = page.locator("#al-flow .mm-render svg").count()
    print("[5] 分摊流程 Mermaid SVG:", mermaid_svg)

    # 保存方案 + 重新加载
    page.fill("#al-name", "浏览器验收方案")
    page.click("#al-save")
    page.wait_for_timeout(800)
    page.evaluate("() => { document.getElementById('al-source').value = '[]'; }")
    page.click("#al-load")
    page.wait_for_timeout(800)
    src = page.input_value("#al-source")
    print("[6] 方案保存后重新加载，源数据恢复:", "1000000" in src)

    print()
    print("=== 页面错误 ===")
    for e in errors[:10]:
        print(" ", e)
    if not errors:
        print("  (无)")
    b.close()
