/* 惰性源码查看器的行为验收（Node + 最小 DOM 桩，无浏览器）。

守住的契约：
1. 大段源码分批渲染：首屏只产生一块行节点。
2. tm1Source.text() 始终返回完整源码（搜索/Ctrl+F/复制不依赖渲染量）。
3. revealLine 会把目标行渲染出来并设置滚动位置（行号锚点仍可用）。
4. 超大源码退化为纯文本，但仍可按行换算滚动位置。
5. HTML 转义不变。

用法：node tests/ui/source_viewer_lazy.js <syntax.js 路径>
*/
"use strict";

const vm = require("node:vm");
const fs = require("node:fs");
const assert = require("node:assert");

class El {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.events = {};
    this.className = "";
    this.dataset = {};
    this.textContent = "";
    this._html = "";
    this.style = {};
    this.clientHeight = 100;
    this.scrollTop = 0;
    this.isConnected = true;
    this.classList = {
      contains: (c) => this.className.split(/\s+/).includes(c),
      add: (c) => { if (!this.className.split(/\s+/).includes(c)) this.className += " " + c; },
      remove: (c) => { this.className = this.className.split(/\s+/).filter((x) => x !== c).join(" "); },
      toggle: (c, on) => { on ? this.classList.add(c) : this.classList.remove(c); },
    };
  }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = v; }
  before(x) { x.parentElement = this.parentElement; }
  append(x) { this.children.push(x); x.parentElement = this; return x; }
  prepend(x) { this.children.unshift(x); x.parentElement = this; return x; }
  appendChild(x) { return this.append(x); }
  replaceChildren() { this.children = []; this._html = ""; }
  insertAdjacentHTML(_position, html) {
    this._html += html;
    const rows = html.match(/<div class="code-line">/g) || [];
    const start = this.children.length;
    for (let i = 0; i < rows.length; i++) {
      const row = new El("div");
      // 模拟固定行高的排版结果，让 revealLine 的滚动换算可以验证。
      row._rectTop = (start + i) * 20;
      row._rectHeight = 20;
      this.children.push(row);
    }
  }
  addEventListener(type, fn) { this.events[type] = fn; }
  setAttribute() {}
  querySelectorAll() { return []; }
  querySelector(sel) {
    if (sel === ".source-tools span") {
      const tools = this.children.find((c) => c.className === "source-tools");
      return tools ? tools.children.find((c) => c.tag === "span") : null;
    }
    return null;
  }
  getBoundingClientRect() { return { top: this._rectTop || 0, height: this._rectHeight || 0 }; }
}

function newSandbox() {
  const window = {
    getComputedStyle: () => ({ lineHeight: "20px" }),
    addEventListener() {},
  };
  const document = {
    readyState: "loading",
    addEventListener() {},
    body: new El("body"),
    createElement: (tag) => new El(tag),
  };
  const ctx = { window, document, navigator: { clipboard: { writeText: async () => {} } }, setTimeout() {}, MutationObserver: function () { this.observe = () => {}; this.disconnect = () => {}; } };
  ctx.globalThis = ctx;
  return ctx;
}

function makePre() {
  const pre = new El("pre");
  pre._rectTop = 0;
  pre._rectHeight = 600;   // 可视高度
  const section = new El("section");
  pre.parentElement = section;
  return pre;
}

function codeOf(lines) {
  const out = [];
  for (let i = 1; i <= lines; i++) {
    out.push(i % 3 === 0 ? "    CellPutN(v" + i + ", 'Target', vYear);" : "v" + i + " = " + i + ";");
  }
  return out.join("\n");
}

const syntaxPath = process.argv[2];
const source = fs.readFileSync(syntaxPath, "utf8");
const ctx = newSandbox();
vm.runInNewContext(source, ctx);
const api = ctx.window.tm1Source;
assert(api && typeof api.mount === "function", "tm1Source.mount 必须存在");

// 1) 大段源码：分批渲染，首屏只渲染一块
const big = codeOf(2000);
const pre = makePre();
api.mount(pre, { code: big, mode: "ti" });
assert.strictEqual(pre.children.length, 800, "首屏应只渲染第一块（800 行）");
assert.ok(pre.dataset.sourceReady === "1", "挂载后必须标记 sourceReady");

// 2) 文本始终完整
assert.strictEqual(api.text(pre), big, "text() 必须返回完整源码（不受分批影响）");

// 3) 按行定位：把目标行渲染出来并滚动
const ok = api.revealLine(pre, 1600);
assert.strictEqual(ok, true, "revealLine 应成功");
assert.ok(pre.children.length >= 1600, "目标行之前的行必须被渲染出来");
assert.ok(pre.scrollTop > 0, "定位后应产生滚动位移");

// 4) 小段源码不分批
const small = codeOf(20);
const pre2 = makePre();
api.mount(pre2, { code: small, mode: "ti" });
assert.strictEqual(pre2.children.length, 20, "小段源码应一次渲染完");
assert.strictEqual(api.text(pre2), small);

// 5) 超大源码：纯文本降级，但仍可定位
const huge = "x".repeat(1000001) + "\nsecond line";
const pre3 = makePre();
api.mount(pre3, { code: huge, mode: "ti" });
assert.strictEqual(pre3.children.length, 0, "超大源码应退化为纯文本");
assert.strictEqual(pre3.textContent, huge, "纯文本模式必须保留全部内容");
assert.strictEqual(api.revealLine(pre3, 2), true, "纯文本模式仍应支持行定位");

// 6) 转义不变
const pre4 = makePre();
api.mount(pre4, { code: "CellPutN(1,'<script>',vYear);", mode: "ti" });
assert.ok(pre4.innerHTML.includes("&lt;script&gt;"), "必须转义尖括号");
assert.ok(!pre4.innerHTML.includes("<script>"), "不得输出原始标签");

// 7) 重复挂载不重建（避免丢失已追加的行与滚动位置）
const before = pre.children.length;
api.mount(pre);
assert.strictEqual(pre.children.length, before, "无新代码时重复 mount 不应重建");

console.log(JSON.stringify({
  chunked_first_block: 800,
  after_reveal: before,
  full_text_preserved: true,
  plain_fallback: true,
  escaping: true,
  idempotent_mount: true,
}));
