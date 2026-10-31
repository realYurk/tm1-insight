/* 调用关系片段的按需加载器（只读，不写任何库）。
 *
 * 契约：
 * 1. 首屏不请求调用树；页面空闲时才取，取不到不影响看源码。
 * 2. 失败只显示一句可读的话：绝不把服务端返回的整页 HTML 塞进状态栏。
 * 3. 可取消（再点一次按钮）、可重试；数据源变化（409）提示刷新，
 *    接口不存在（404）提示服务进程可能是旧版本。
 * 4. 加载成功才把片段写进 DOM；失败清空容器，不残留半截内容。
 */
(function () {
  'use strict';

  var MAX_BRIEF = 180;

  // 服务端返回的是「片段」；一旦拿到整页文档，说明命中的不是本接口
  // （旧版本进程缺路由、被错误页兜底等）。这种情况必须换成人话。
  function looksLikeDocument(text) {
    return /^\s*(?:<!doctype|<\/?html[\s>])/i.test(text || '');
  }

  // 把任意错误体压成一句短文本：去标签、并空白、限长。不做 HTML 注入。
  function brief(text) {
    var plain = String(text == null ? '' : text)
      .replace(/<script[\s\S]*?<\/script>/gi, ' ')
      .replace(/<style[\s\S]*?<\/style>/gi, ' ')
      .replace(/<[^>]*>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    if (plain.length > MAX_BRIEF) plain = plain.slice(0, MAX_BRIEF) + '…';
    return plain;
  }

  function describeError(status, text) {
    if (status === 404) {
      if (looksLikeDocument(text)) {
        return '调用关系接口不存在（404）：服务进程可能仍是更新前的旧版本，重启本地服务后再打开本页。';
      }
      return '该 TI 不在当前数据源中（404），没有可加载的调用关系。';
    }
    if (status === 409) return '数据源或文件已变化（409），请刷新本页后重试。';
    if (status >= 500) {
      return '服务端读取调用关系时出错（HTTP ' + status + '），可重试；源码与其它内容不受影响。';
    }
    var plain = brief(text);
    if (!plain || looksLikeDocument(text)) {
      return '调用关系未加载（HTTP ' + status + '），可重试或直接查看源码。';
    }
    return plain;
  }

  function setup() {
    var card = document.getElementById('call-tree-card');
    if (!card) return null;
    var body = document.getElementById('call-tree-body');
    var statusEl = document.getElementById('call-tree-status');
    var loadBtn = document.getElementById('call-tree-load');
    if (!body || !statusEl || !loadBtn) return null;

    var controller = null;
    var loaded = false;

    function setBusy(busy) {
      loadBtn.disabled = false;            // 加载中按钮即「取消」，不能禁用
      loadBtn.textContent = busy ? '取消加载' : (loaded ? '重新加载' : '加载调用树');
      if (card.setAttribute) card.setAttribute('aria-busy', busy ? 'true' : 'false');
    }

    function render(html) {
      body.innerHTML = html;
      body.hidden = false;
      loaded = true;
      statusEl.textContent = '调用关系为静态识别结果（源码中可直接读到的进程名）；动态构造的调用目标与运行顺序不在其中。';
      setBusy(false);
    }

    function fail(message, retryable) {
      body.replaceChildren();
      body.hidden = true;
      statusEl.textContent = message + (retryable === false ? '' : '');
      setBusy(false);
      if (retryable !== false) loadBtn.textContent = '重试加载';
    }

    function load() {
      if (controller) { controller.abort(); return; }
      controller = new AbortController();
      setBusy(true);
      statusEl.textContent = '正在加载调用关系…';
      body.hidden = true;
      body.replaceChildren();
      fetch(card.getAttribute('data-endpoint'), {
        signal: controller.signal,
        cache: 'no-store',
        headers: { 'Accept': 'text/html' }
      })
        .then(function (response) {
          return response.text().then(function (text) {
            return { ok: response.ok, status: response.status, text: text };
          });
        })
        .then(function (result) {
          if (result.ok) render(result.text);
          else fail('调用关系加载失败：' + describeError(result.status, result.text));
        })
        .catch(function (error) {
          if (error && error.name === 'AbortError') {
            statusEl.textContent = '已取消加载调用关系。源码不受影响。';
            setBusy(false);
          } else {
            fail('调用关系加载失败：' + brief(error && error.message) + '。可重试，或直接查看源码。');
          }
        })
        .finally(function () { controller = null; });
    }

    loadBtn.addEventListener('click', load);

    function scheduleIdle(fn) {
      if (typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(fn, { timeout: 1200 });
      } else {
        setTimeout(fn, 300);
      }
    }

    var api = {
      load: load,
      describeError: describeError,
      brief: brief,
      card: card,
      body: body,
      status: statusEl,
      button: loadBtn,
      isLoaded: function () { return loaded; }
    };
    scheduleIdle(function () { if (!loaded && !controller) load(); });
    return api;
  }

  function boot() {
    var api = setup();
    if (api) window.tm1CallTree = api;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
