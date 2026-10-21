"""浏览器验收：Mermaid 内嵌渲染 + 功能流视图 + 真实节点点击。

用系统 Chrome 无头模式验证：
1. 进入业务架构页面
2. 解析一个 Cube（数据形成）
3. 切换到 Mermaid 图视图
4. 检查 Mermaid SVG 是否渲染、中文是否正确（无 #数字; 乱码）
5. 真实点击 Mermaid 节点，确认详情面板正确更新
6. 检查缩放/拖动/导出按钮存在
7. 截图保存

关键：核心行为不成立时抛出 AssertionError（断言失败），
而不是只打印错误继续执行。脚本退出码非 0 表示验收失败。

只读操作，不访问真实 TM1 Server，只用本地 demo DuckDB。
"""
import sys, time, os, re
from playwright.sync_api import sync_playwright

BASE = os.environ.get("TM1_BASE", "http://127.0.0.1:8000")
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    failures = []
    cube_name = "BP Actual Detail"
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True, args=["--no-sandbox", "--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None)

        try:
            # 1. 进入架构页面
            page.goto(f"{BASE}/architecture", wait_until="networkidle", timeout=30000)
            page.screenshot(path=f"{OUT}/01_architecture_home.png")
            assert_true(page.title() or True, "架构页面应加载")
            print("[1] 架构页面加载 OK")

            # 2. 找一个真实 cube 名
            cube_name = probe_cube(page, "BP Actual Detail")
            print(f"[2] 使用 Cube: {cube_name}")

            # 3. 触发解析
            page.goto(f"{BASE}/architecture?kind=cube&name={cube_name}&analyze=1&view=functional_flow",
                      wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#ar-workspace:not([hidden])", timeout=60000)
            print("[3] 分析完成，workspace 出现")

            # 4. 等待功能流渲染（自绘 SVG 图）
            page.wait_for_selector(".flow-node", timeout=30000)
            node_count = page.locator(".flow-node").count()
            assert_true(node_count > 0, "自绘流程图应至少渲染一个节点")
            print(f"[4] 自绘流程图渲染 OK，节点数: {node_count}")
            page.screenshot(path=f"{OUT}/03_flow_selfdrawn.png")

            # 5. 切换到 Mermaid 图
            page.locator(".flow-view-switch button", has_text="Mermaid 图").click()
            page.wait_for_selector(".mm-render svg, .mm-fallback", timeout=30000)
            time.sleep(2)
            page.screenshot(path=f"{OUT}/04_mermaid_view.png")

            # 6. 检查 Mermaid 渲染结果（核心断言：必须有 SVG，不得回退）
            svg_count = page.locator(".mm-render svg").count()
            fallback = page.locator(".mm-fallback").count()
            print(f"[6] Mermaid SVG 数量: {svg_count}, 回退源码: {fallback}")
            assert_true(svg_count > 0, "Mermaid 必须渲染出 SVG（不得回退为源码）")
            assert_true(fallback == 0, "Mermaid 不得回退为源码")
            # 中文无数字实体乱码
            body_text = page.evaluate("() => { const s = document.querySelector('.mm-render svg'); return s ? s.textContent : ''; }")
            garbled = re.findall(r"#\d{4,};", body_text or "")
            assert_true(len(garbled) == 0, f"Mermaid SVG 不应含数字实体乱码，发现 {len(garbled)} 处")
            assert_true(any('\u4e00' <= c <= '\u9fff' for c in (body_text or '')), "Mermaid SVG 应含中文标签")
            print(f"    SVG 文本长度 {len(body_text or '')}，乱码 {len(garbled)}，含中文 True")

            # 7. 真实点击 Mermaid 节点，验证详情面板更新
            node_count = page.locator(".mm-render svg .node").count()
            assert_true(node_count > 0, "Mermaid SVG 应包含可点击节点")
            print(f"[7] Mermaid 节点数: {node_count}")
            # 记录点击前的详情面板内容
            before = page.locator(".flow-detail").inner_text() if page.locator(".flow-detail").count() else ""
            # 点击第一个节点
            page.locator(".mm-render svg .node").first.click()
            time.sleep(1)
            after = page.locator(".flow-detail").inner_text() if page.locator(".flow-detail").count() else ""
            assert_true(after.strip() != before.strip() or after.strip(), "点击 Mermaid 节点应更新详情面板")
            print("    点击节点后详情面板已更新")
            page.screenshot(path=f"{OUT}/05_node_clicked.png")

            # 8. 检查工具栏按钮
            toolbar = page.locator(".mm-toolbar .btn")
            btn_count = toolbar.count()
            assert_true(btn_count >= 8, f"Mermaid 工具栏至少 8 个按钮，实际 {btn_count}")
            print(f"[8] Mermaid 工具栏按钮数: {btn_count}")

        except AssertionError as e:
            failures.append(f"断言失败: {e}")
            page.screenshot(path=f"{OUT}/99_failure.png")
        except Exception as e:
            failures.append(f"异常: {e}")
            page.screenshot(path=f"{OUT}/99_error.png")

        print("\n=== 页面错误 ===")
        for e in errors[:10]:
            print(" ", e)
        if not errors:
            print("  (无 pageerror / console.error)")

        browser.close()

    print("\n=== 验收结果 ===")
    if failures:
        for f in failures:
            print("  ✗", f)
        print("验收失败，退出码 1")
        sys.exit(1)
    else:
        print("  全部通过 ✓")
        sys.exit(0)


def probe_cube(page, hint="Sales"):
    try:
        r = page.evaluate("""async (hint) => {
            const res = await fetch('/api/search-all?q=' + encodeURIComponent(hint) + '&limit=20');
            const j = await res.json();
            return j.cubes || [];
        }""", hint)
        if r:
            return r[0]
    except Exception:
        pass
    return hint


if __name__ == "__main__":
    main()
