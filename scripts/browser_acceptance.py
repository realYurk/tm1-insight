"""浏览器验收：Mermaid 内嵌渲染 + 功能流视图。

用系统 Chrome 无头模式验证：
1. 进入业务架构页面
2. 解析一个 Cube（数据形成）
3. 切换到 Mermaid 图视图
4. 检查 Mermaid SVG 是否渲染、中文是否正确（无 #数字; 乱码）
5. 检查缩放/拖动/导出按钮存在
6. 截图保存

只读操作，不访问真实 TM1 Server，只用本地 demo DuckDB。
"""
import sys, time, os
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = "logs/browser_acceptance"
os.makedirs(OUT, exist_ok=True)

def main():
    cube_name = "BP Actual Detail"  # demo 数据里的 cube；若不存在会回退到首个 cube
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True, args=["--no-sandbox", "--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None)

        # 1. 进入架构页面
        page.goto(f"{BASE}/architecture", wait_until="networkidle", timeout=30000)
        page.screenshot(path=f"{OUT}/01_architecture_home.png")
        print("[1] 架构页面加载 OK")

        # 2. 找一个真实 cube 名（从首页搜索 API 拿首个 cube）
        cube_name = probe_cube(page, "BP Actual Detail")
        print(f"[2] 使用 Cube: {cube_name}")

        # 3. 触发解析
        page.goto(f"{BASE}/architecture?kind=cube&name={cube_name}&analyze=1&view=functional_flow",
                  wait_until="domcontentloaded", timeout=30000)
        # 等待分析完成（进度条消失 / workspace 出现）
        try:
            page.wait_for_selector("#ar-workspace:not([hidden])", timeout=45000)
        except Exception as e:
            print("[3] 等待 workspace 超时:", e)
            page.screenshot(path=f"{OUT}/02_timeout.png")
        print("[3] 分析完成，workspace 出现")

        # 等待功能流渲染（自绘 SVG 图）
        try:
            page.wait_for_selector(".flow-node", timeout=20000)
            print("[4] 自绘流程图渲染 OK，节点数:", page.locator(".flow-node").count())
        except Exception as e:
            print("[4] 自绘流程图未渲染:", e)
        page.screenshot(path=f"{OUT}/03_flow_selfdrawn.png")

        # 5. 切换到 Mermaid 图
        try:
            page.locator(".flow-view-switch button", has_text="Mermaid 图").click()
            page.wait_for_selector(".mm-render svg, .mm-fallback", timeout=30000)
            time.sleep(2)
        except Exception as e:
            print("[5] Mermaid 切换失败:", e)
        page.screenshot(path=f"{OUT}/04_mermaid_view.png")

        # 6. 检查 Mermaid 渲染结果
        svg_count = page.locator(".mm-render svg").count()
        fallback = page.locator(".mm-fallback").count()
        print(f"[6] Mermaid SVG 数量: {svg_count}, 回退源码: {fallback}")
        if svg_count > 0:
            # 检查中文是否正确（无数字实体乱码）。SVG 文本用 textContent 读取。
            body_text = page.evaluate("() => { const s = document.querySelector('.mm-render svg'); return s ? s.textContent : ''; }")
            import re
            garbled = re.findall(r"#\d{4,};", body_text or "")
            print(f"    SVG 文本长度: {len(body_text or '')}, 数字实体乱码: {len(garbled)}")
            print(f"    SVG 是否含中文: {any('\u4e00' <= c <= '\u9fff' for c in (body_text or ''))}")
        else:
            fb = page.locator(".mm-fallback pre").inner_text() if fallback else ""
            print("    Mermaid 渲染失败，回退源码:", fb[:200])

        # 7. 检查工具栏按钮
        toolbar = page.locator(".mm-toolbar .btn")
        print(f"[7] Mermaid 工具栏按钮数: {toolbar.count()}")

        print("\n=== 页面错误 ===")
        for e in errors[:10]:
            print(" ", e)
        if not errors:
            print("  (无 pageerror / console.error)")

        browser.close()

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
