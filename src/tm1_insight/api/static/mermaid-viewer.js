/* Shared offline Mermaid viewer — TM1 Insight.

   把一段 Mermaid 文本（flowchart / graph）离线渲染成可交互图表。
   不依赖任何在线资源：mermaid.min.js 由后端作为静态资源提供
   （/static/vendor/mermaid.min.js），渲染完全在浏览器本地完成。

   能力：
   - 直接渲染（securityLevel: 'strict'，阻止不可信文本脚本注入）
   - 缩放 / 拖动（Pan & Zoom）
   - 适应画布 / 1:1
   - 全屏
   - 横向 / 纵向布局切换
   - 复制 Mermaid 源码
   - 导出 Mermaid (.mmd)
   - 导出 SVG
   - 导出 PNG（优先画布位图，回退提示）
   - 点击节点回调（用于打开对象详情）
   - Mermaid 出错时回退为源码 <pre>

   用法：
     TM1Mermaid.mount(container, {
       code: 'flowchart LR\n  A["Foo"]-->B["Bar"]',
       onNodeClick: function(nodeId, label) { ... },
       title: '数据形成'
     })

   全局单例挂载：window.TM1Mermaid = { mount, unmount, isAvailable }。
*/
(function () {
  'use strict';

  var ZOOM_MIN = 0.15, ZOOM_MAX = 4, ZOOM_STEP = 1.2;
  var current = null; // { container, destroy }

  function isAvailable() {
    return typeof window.mermaid !== 'undefined';
  }

  function ensureMermaid() {
    if (isAvailable()) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = '/static/vendor/mermaid.min.js';
      s.onload = function () {
        // 读取主题 CSS 变量的实际值（mermaid 不支持 CSS 变量字符串）。
        var cssVar = function (name, fallback) {
          var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
          return v || fallback;
        };
        // 安全配置：阻止不可信文本中的 HTML/脚本注入。
        window.mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: 'base',
          fontFamily: cssVar('--font-ui', 'inherit'),
          flowchart: { htmlLabels: true, curve: 'basis', padding: 12, nodeSpacing: 42, rankSpacing: 52 },
          themeVariables: {
            primaryColor: cssVar('--card', '#ffffff'),
            primaryTextColor: cssVar('--text', '#1a1d29'),
            primaryBorderColor: cssVar('--border-strong', '#d7dae3'),
            lineColor: cssVar('--muted', '#626b80'),
            fontFamily: cssVar('--font-ui', 'inherit'),
          },
        });
        resolve();
      };
      s.onerror = function () { reject(new Error('离线 Mermaid 组件加载失败')); };
      document.head.appendChild(s);
    });
  }

  function download(filename, content, mime) {
    var blob = content instanceof Blob ? content : new Blob([content], { type: mime });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  function buildToolbar(state, container, opts) {
    var bar = document.createElement('div');
    bar.className = 'mm-toolbar';

    function btn(label, fn, cls) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn ghost' + (cls ? ' ' + cls : '');
      b.textContent = label;
      b.addEventListener('click', fn);
      return b;
    }

    var zoomIn = btn('＋', function () { setZoom(state, state.zoom * ZOOM_STEP); });
    zoomIn.title = '放大';
    var zoomOut = btn('－', function () { setZoom(state, state.zoom / ZOOM_STEP); });
    zoomOut.title = '缩小';
    var fit = btn('适应画布', function () { fitView(state); });
    var one = btn('1:1', function () { state.pan = { x: 0, y: 0 }; setZoom(state, 1); });
    var dir = btn(state.vertical ? '纵向' : '横向', function () {
      state.vertical = !state.vertical; reflow(state, container, opts);
    });
    dir.title = '切换布局方向';
    var full = btn('全屏', function () { toggleFullscreen(state.wrapper); });
    var copy = btn('复制', function () {
      navigator.clipboard.writeText(state.code).then(function () { flash(copy, '已复制'); }, function () { flash(copy, '复制失败'); });
    });
    copy.title = '复制 Mermaid 源码';
    var expMmd = btn('导出 Mermaid', function () { download((opts.title || 'flow') + '.mmd', state.code, 'text/plain'); });
    var expSvg = btn('导出 SVG', function () { exportSvg(state, opts); });
    var expPng = btn('导出 PNG', function () { exportPng(state, opts); });

    [zoomOut, zoomIn, fit, one, dir, full, copy, expMmd, expSvg, expPng].forEach(function (b) { bar.appendChild(b); });
    return bar;
  }

  function flash(btn, text) {
    var old = btn.textContent;
    btn.textContent = text;
    setTimeout(function () { btn.textContent = old; }, 1200);
  }

  function setZoom(state, z) {
    state.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
    applyTransform(state);
  }

  function applyTransform(state) {
    if (!state.inner) return;
    state.inner.style.transform = 'translate(' + state.pan.x + 'px,' + state.pan.y + 'px) scale(' + state.zoom + ')';
  }

  function fitView(state) {
    var vp = state.viewport, inner = state.inner;
    if (!vp || !inner) return;
    var vr = vp.getBoundingClientRect();
    var ir = inner.getBoundingClientRect();
    var scale = Math.min((vr.width - 24) / Math.max(ir.width, 1), (vr.height - 24) / Math.max(ir.height, 1), 1.5);
    state.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, scale));
    state.pan = { x: (vr.width - ir.width * state.zoom) / 2, y: (vr.height - ir.height * state.zoom) / 2 };
    applyTransform(state);
  }

  function reflow(state, container, opts) {
    var code = state.vertical
      ? state.code.replace(/^\s*flowchart\s+LR/m, 'flowchart TB').replace(/^\s*graph\s+LR/m, 'graph TB')
      : state.code.replace(/^\s*flowchart\s+TB/m, 'flowchart LR').replace(/^\s*graph\s+TB/m, 'graph LR');
    renderDiagram(state, container, opts, code);
  }

  function renderDiagram(state, container, opts, code) {
    state.code = code;
    state.inner.replaceChildren();
    var p = document.createElement('pre');
    p.className = 'mm-rendering';
    p.textContent = '正在离线渲染…';
    state.inner.appendChild(p);
    // 使用唯一的临时容器：mermaid 10 要求 id 元素存在时由它自己写入，
    // 我们直接读返回值再注入，避免手动创建同 id 元素造成冲突。
    var renderId = 'mm-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
    window.mermaid.render(renderId, code).then(function (res) {
      if (state.disposed) return;
      var el = document.createElement('div');
      el.className = 'mm-render';
      el.innerHTML = res.svg;
      state.inner.replaceChildren(el);
      state.svg = res.svg;
      bindNodes(state, opts);
      requestAnimationFrame(function () { fitView(state); });
    }).catch(function (err) {
      if (state.disposed) return;
      showFallback(state, code, err);
    });
  }

  function showFallback(state, code, err) {
    var box = document.createElement('div');
    box.className = 'mm-fallback';
    var msg = document.createElement('p');
    msg.textContent = 'Mermaid 渲染失败，已回退为源码：' + (err && err.message ? err.message : '语法错误');
    box.appendChild(msg);
    var pre = document.createElement('pre');
    pre.className = 'code';
    pre.textContent = code;
    box.appendChild(pre);
    state.inner.replaceChildren(box);
  }

  function bindNodes(state, opts) {
    if (!opts.onNodeClick) return;
    var svg = state.inner.querySelector('svg');
    if (!svg) return;
    svg.querySelectorAll('.node').forEach(function (node) {
      var id = node.id;
      node.style.cursor = 'pointer';
      node.addEventListener('click', function () {
        var labels = node.querySelectorAll('.nodeLabel, text');
        var label = '';
        labels.forEach(function (t) { label += t.textContent; });
        opts.onNodeClick(id, label);
      });
    });
  }

  function toggleFullscreen(wrapper) {
    if (!document.fullscreenElement) {
      if (wrapper.requestFullscreen) wrapper.requestFullscreen();
    } else if (document.exitFullscreen) {
      document.exitFullscreen();
    }
  }

  function exportSvg(state, opts) {
    if (!state.svg) return;
    var svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + state.svg;
    download((opts.title || 'flow') + '.svg', svg, 'image/svg+xml');
  }

  function exportPng(state, opts) {
    var svg = state.inner.querySelector('svg');
    if (!svg) return;
    var xml = new XMLSerializer().serializeToString(svg);
    var img = new Image();
    var blob = new Blob([xml], { type: 'image/svg+xml' });
    var url = URL.createObjectURL(blob);
    img.onload = function () {
      var canvas = document.createElement('canvas');
      var scale = 2;
      canvas.width = (svg.getBoundingClientRect().width || 800) * scale;
      canvas.height = (svg.getBoundingClientRect().height || 600) * scale;
      var ctx = canvas.getContext('2d');
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob(function (b) {
        if (b) download((opts.title || 'flow') + '.png', b, 'image/png');
      });
    };
    img.onerror = function () { URL.revokeObjectURL(url); };
    img.src = url;
  }

  function mount(container, opts) {
    if (!container) throw new Error('缺少容器');
    unmount();
    opts = opts || {};
    var state = {
      container: container, code: opts.code || '', vertical: !!opts.vertical,
      zoom: 1, pan: { x: 0, y: 0 }, disposed: false, svg: null,
    };
    var wrapper = document.createElement('div');
    wrapper.className = 'mm-wrapper';
    var viewport = document.createElement('div');
    viewport.className = 'mm-viewport';
    viewport.tabIndex = 0;
    state.viewport = viewport;
    var inner = document.createElement('div');
    inner.className = 'mm-inner';
    state.inner = inner;
    viewport.appendChild(inner);
    wrapper.appendChild(viewport);
    state.wrapper = wrapper;

    // 拖动平移
    var dragging = false, startX = 0, startY = 0, origX = 0, origY = 0;
    viewport.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      dragging = true; startX = e.clientX; startY = e.clientY; origX = state.pan.x; origY = state.pan.y;
      viewport.style.cursor = 'grabbing';
      e.preventDefault();
    });
    window.addEventListener('mousemove', function (e) {
      if (!dragging || state.disposed) return;
      state.pan = { x: origX + (e.clientX - startX), y: origY + (e.clientY - startY) };
      applyTransform(state);
    });
    window.addEventListener('mouseup', function () { dragging = false; viewport.style.cursor = 'grab'; });
    viewport.addEventListener('wheel', function (e) {
      e.preventDefault();
      setZoom(state, state.zoom * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP));
    }, { passive: false });

    var toolbar = buildToolbar(state, container, opts);
    wrapper.insertBefore(toolbar, viewport);
    container.appendChild(wrapper);

    current = { container: container, destroy: unmount };

    ensureMermaid().then(function () { renderDiagram(state, container, opts, state.code); }).catch(function (err) {
      if (state.disposed) return;
      showFallback(state, state.code, err);
    });
    return { destroy: unmount };
  }

  function unmount() {
    if (current) {
      current.destroy = null;
      if (current.container) current.container.replaceChildren();
      current = null;
    }
  }

  window.TM1Mermaid = { mount: mount, unmount: unmount, isAvailable: isAvailable };
})();
