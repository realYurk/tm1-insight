"""BP Management Report PnL 数据形成视图浏览器验收。

验证：
1. 打开 PnL Cube 详情页
2. 数据形成视图渲染 Mermaid 图（含 Rule/TI/引用节点）
3. 紧凑规则表展示（含 PL01010、Per Car、SC00300 等）
4. 点击 Rule 行打开源码下钻
5. MDX 切面输入 → 动态匹配
6. 中文无乱码

关键行为不成立时断言失败（退出码非 0）。
只读操作，不访问真实 TM1 Server，只用本地 demo DuckDB。
"""
import sys, time, os, re
from urllib.parse import quote
from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8000")
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)

CUBE = "BP Management Report PnL"


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True, args=["--no-sandbox", "--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None)

        try:
            # 1. 打开 PnL Cube 详情页
            page.goto(f"{BASE}/explorer/cube/{quote(CUBE)}", wait_until="networkidle", timeout=45000)
            assert_true("BP Management Report PnL" in page.title() or "BP Management Report PnL" in page.inner_text("body")[:200],
                        "应打开 PnL Cube 详情页")
            print("[1] PnL Cube 详情页加载 OK")

            # 2. 等待数据形成视图渲染
            page.wait_for_selector("#cube-formation .cf-chart .mm-render svg, #cube-formation .cf-chart .cf-fallback", timeout=45000)
            time.sleep(3)
            print("[2] 数据形成视图出现")

            # 3. Mermaid 图渲染检查
            svg_count = page.locator("#cube-formation .cf-chart .mm-render svg").count()
            fb_count = page.locator("#cube-formation .cf-chart .cf-fallback").count()
            print(f"[3] 数据形成图: SVG={svg_count}, 回退={fb_count}")
            assert_true(svg_count > 0, "数据形成图必须渲染 Mermaid SVG（不得回退）")
            assert_true(fb_count == 0, "数据形成图不得回退为源码")

            # 4. 节点数（Rule + TI + 引用）应 > 10
            node_count = page.locator("#cube-formation .cf-chart .mm-render svg .node").count()
            print(f"[4] 数据形成图节点数: {node_count}")
            assert_true(node_count > 10, f"数据形成图节点数应 > 10（Rule+TI+引用），实际 {node_count}")

            # 5. 中文无乱码
            svg_text = page.evaluate("() => { const s = document.querySelector('#cube-formation .cf-chart .mm-render svg'); return s ? s.textContent : ''; }")
            garbled = re.findall(r"#\d{4,};", svg_text or "")
            assert_true(len(garbled) == 0, f"Mermaid 图不应含数字实体乱码，发现 {len(garbled)}")
            assert_true("Rule" in svg_text or "TI" in svg_text, "数据形成图应区分 Rule/TI 节点")
            print(f"[5] 中文无乱码，节点类型标注正常")

            # 6. 紧凑规则表：应含 PL01010 / Per Car / SC00300 / CM09001 / BP09000
            rule_text = page.inner_text("#cube-formation .cf-rule-table")
            assert_true("PL01010" in rule_text, "规则表应含 PL01010 目标区域（消费税）")
            assert_true("Per Car" in rule_text or "SC00300" in rule_text, "规则表应含 Per Car / SC00300 计算关系")
            # 关键审计点：CM09001（销售公司费用扣除）与 BP09000（官方 STD）均真实存在，不可互相替代
            assert_true("CM09001" in rule_text, "规则表应含 CM09001（销售公司费用扣除），不得误报为不存在")
            assert_true("BP09000" in rule_text, "规则表应含 BP09000（官方 STD）引用")
            print("[6] 规则表含 PL01010 / Per Car / SC00300 / CM09001 / BP09000")

            page.screenshot(path=f"{OUT}/20_pnl_formation.png")

            # 7. 点击第一条规则行 → 源码下钻
            rule_rows = page.locator("#cube-formation .cf-rule-row")
            assert_true(rule_rows.count() > 0, "应有规则行可点击")
            rule_rows.first.click()
            time.sleep(1)
            src_panel = page.locator("#cube-formation .cf-source-panel")
            assert_true(src_panel.count() > 0, "点击规则行应打开源码下钻面板")
            src_text = src_panel.first.inner_text()
            print(f"[7] 源码下钻面板打开，内容长度 {len(src_text)}")

            # 8. MDX 切面
            mdx_input = page.locator("#cube-formation .cf-mdx-input")
            mdx_input.fill("SELECT {[Account PnL].[PL01010]} ON 0 FROM [BP Management Report PnL] WHERE ([Scenario].[SP75],[Version].[WIP])")
            page.locator("#cube-formation .cf-toolbar button", has_text="应用切面").click()
            time.sleep(3)
            slice_text = page.inner_text("#cube-formation .cf-slice")
            print(f"[8] 切面匹配结果: {slice_text[:120]}")
            assert_true("SP75" in slice_text, "切面应反解出 Scenario=SP75")

            page.screenshot(path=f"{OUT}/21_pnl_mdx_slice.png")

        except AssertionError as e:
            failures.append(f"断言失败: {e}")
            page.screenshot(path=f"{OUT}/99_pnl_failure.png")
        except Exception as e:
            failures.append(f"异常: {e}")
            page.screenshot(path=f"{OUT}/99_pnl_error.png")

        print("\n=== 页面错误 ===")
        real_errors = [e for e in errors if "favicon" not in e and "404" not in e]
        for e in real_errors[:10]:
            print(" ", e)
        if not real_errors:
            print("  (无 pageerror / console.error)")

        browser.close()

    print("\n=== PnL 数据形成验收结果 ===")
    if failures:
        for f in failures:
            print("  ✗", f)
        sys.exit(1)
    else:
        print("  全部通过 ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()
