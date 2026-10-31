/* 调用关系加载器的行为验收（Node + 最小 DOM 桩，无浏览器）。

守住的契约：
1. 首屏可读后自动加载一次；成功才把片段写进容器，成功后不再自动重复请求。
2. 失败只给一句人话，绝不把整页 HTML 当错误信息塞进状态栏
   （这是实际出现过的缺陷：404 页整篇被倒进「调用关系」卡片）。
3. 404 区分「对象不在数据源」与「接口不存在（旧服务进程）」。
4. 409 提示刷新；5xx 带状态码且不把服务端正文当主信息。
5. 任意长错误体去标签并截断。
6. 加载中再点按钮 = 取消，不并发；取消后可重试。

用法：node tests/ui/call_tree_loader.js <call-tree.js 路径>
*/
"use strict";

const vm = require("node:vm");
const fs = require("node:fs");
const assert = require("node:assert");

class El {
  constructor(id) {
    this.id = id;
    this.attrs = {};
    this.events = {};
    this.textContent = "";
    this.innerHTML = "";
    this.hidden = false;
    this.disabled = false;
    this.children = [];
  }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  addEventListener(type, fn) { this.events[type] = fn; }
  replaceChildren() { this.children = []; this.innerHTML = ""; }
  click() { if (this.events.click) this.events.click(); }
}

class StubAbortController {
  constructor() { this.signal = { aborted: false, _listeners: [] }; }
  abort() {
    this.signal.aborted = true;
    this.signal._listeners.forEach((fn) => fn());
  }
}

function boot(scriptPath) {
  const card = new El("call-tree-card");
  card.attrs["data-endpoint"] = "/explorer/process/Hub/call-tree?source=abc";
  const body = new El("call-tree-body");
  const status = new El("call-tree-status");
  const button = new El("call-tree-load");
  const byId = {
    "call-tree-card": card,
    "call-tree-body": body,
    "call-tree-status": status,
    "call-tree-load": button,
  };

  const calls = [];
  const fetch = (url, opts) => new Promise((resolve, reject) => {
    calls.push({ url: url, opts: opts, resolve: resolve });
    const signal = opts && opts.signal;
    if (signal && signal._listeners) {
      signal._listeners.push(() => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      });
    }
  });

  const window = {
    requestIdleCallback: (fn) => fn(),      // 空闲回调立即执行，测试可确定
    addEventListener() {},
  };
  const document = {
    readyState: "complete",
    addEventListener() {},
    getElementById: (id) => (Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : null),
  };
  window.document = document;

  const ctx = {
    window: window,
    document: document,
    fetch: fetch,
    AbortController: StubAbortController,
    setTimeout: (fn) => fn(),
    Promise: Promise,
    Error: Error,
    String: String,
  };
  ctx.globalThis = ctx;

  vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), ctx);
  return { api: window.tm1CallTree, calls: calls, card, body, status, button };
}

function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function respond(record, ok, status, text) {
  record.resolve({ ok: ok, status: status, text: () => Promise.resolve(text) });
}

const NOT_FOUND_PAGE = '<!DOCTYPE html><html lang="zh-CN"><head><title>404 · 页面不存在</title></head>'
  + '<body><h1>404</h1><p>页面不存在</p></body></html>';

async function main() {
  const scriptPath = process.argv[2];
  const report = {};

  // 1) 空闲自动加载一次；成功才渲染；成功后不重复自动请求
  {
    const view = boot(scriptPath);
    assert(view.api, "必须暴露 window.tm1CallTree");
    assert.strictEqual(view.calls.length, 1, "空闲时应自动请求一次调用树");
    assert(view.calls[0].url.indexOf("/call-tree") > -1, "请求应指向片段接口");
    assert.strictEqual(view.calls[0].opts.cache, "no-store", "片段请求不得使用缓存");
    respond(view.calls[0], true, 200, '<div class="tree-node">Hub</div>');
    await flush();
    assert.strictEqual(view.body.innerHTML, '<div class="tree-node">Hub</div>');
    assert.strictEqual(view.body.hidden, false, "成功后容器应可见");
    assert.strictEqual(view.api.isLoaded(), true);
    assert(view.status.textContent.indexOf("静态识别结果") > -1, "成功后应说明口径");
    assert.strictEqual(view.calls.length, 1, "成功后不应重复自动请求");
    view.button.click();
    assert.strictEqual(view.calls.length, 2, "手动重新加载应发新请求");
    report.success_path = true;
  }

  // 2) 404 整页 HTML：换成人话，绝不回显整页
  {
    const view = boot(scriptPath);
    respond(view.calls[0], false, 404, NOT_FOUND_PAGE);
    await flush();
    const status = view.status.textContent;
    assert(status.indexOf("<!DOCTYPE") === -1, "状态栏不得包含整页 HTML");
    assert(status.indexOf("<html") === -1, "状态栏不得包含 html 标签");
    assert(status.indexOf("404") > -1, "应说明 404");
    assert(status.indexOf("重启本地服务") > -1, "整页 404 应提示服务进程可能过期");
    assert(status.length <= 160, "状态文案应保持一句话，实际长度 " + status.length);
    assert.strictEqual(view.body.hidden, true, "失败时不得显示容器");
    assert.strictEqual(view.button.textContent, "重试加载", "失败后按钮应为重试");
    assert.strictEqual(view.button.disabled, false, "失败后按钮必须可点");
    report.whole_page_404_is_one_sentence = true;
  }

  // 3) 404 片段：对象不在数据源，不提重启
  {
    const view = boot(scriptPath);
    respond(view.calls[0], false, 404,
      '<p class="muted small call-tree-note">该 TI 不在当前数据源中，未加载调用树。</p>');
    await flush();
    const status = view.status.textContent;
    assert(status.indexOf("不在当前数据源") > -1, "片段 404 应给出对象维度说明");
    assert(status.indexOf("重启本地服务") === -1, "片段 404 不应误报为服务进程过期");
    report.missing_object_404 = true;
  }

  // 4) 409 提示刷新
  {
    const view = boot(scriptPath);
    respond(view.calls[0], false, 409, '<p class="muted small">数据源已变化</p>');
    await flush();
    assert(view.status.textContent.indexOf("刷新本页") > -1, "409 应提示刷新");
    report.stale_source_409 = true;
  }

  // 5) 5xx 带状态码
  {
    const view = boot(scriptPath);
    respond(view.calls[0], false, 500, "<p>internal error</p>");
    await flush();
    const status = view.status.textContent;
    assert(status.indexOf("HTTP 500") > -1, "5xx 应带状态码");
    assert(status.indexOf("Traceback") === -1, "不得把堆栈当提示");
    report.server_error_500 = true;
  }

  // 6) 超长错误体：去标签 + 截断
  {
    const view = boot(scriptPath);
    respond(view.calls[0], false, 422, "<span>" + "x".repeat(4000) + "</span>");
    await flush();
    const status = view.status.textContent;
    assert(status.indexOf("<") === -1, "状态栏不得残留标签");
    assert(status.length <= 200, "超长错误体必须截断，实际 " + status.length);
    assert(status.indexOf("…") > -1, "截断应有省略标记");
    report.long_body_truncated = true;
  }

  // 7) 加载中再点 = 取消，不并发；取消后可重试
  {
    const view = boot(scriptPath);
    assert.strictEqual(view.calls.length, 1);
    view.button.click();
    await flush();
    assert.strictEqual(view.calls.length, 1, "取消不应再发新请求");
    assert(view.status.textContent.indexOf("已取消") > -1, "应告知已取消");
    view.button.click();
    assert.strictEqual(view.calls.length, 2, "取消后重试应发出新请求");
    assert.strictEqual(view.button.textContent, "取消加载", "在途时按钮应可取消");
    report.cancel_then_retry = true;
  }

  console.log(JSON.stringify(report));
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
