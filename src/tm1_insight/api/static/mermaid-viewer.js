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

   关键设计（多实例 + 稳定 ID 映射 + 异步竞态防护）：
   - 每个 mount 返回独立实例，互不干扰；不再使用全局单例强占。
   - 渲染节点 ID → 业务节点 ID 的稳定映射：调用方通过 opts.idMap
     提供 { mermaidNodeId: businessId }，或 opts.onNodeClick(nodeId, label)
     收到 mermaid 节点 id 后自行反查。节点 id 在 toMermaid 时由调用方
     用稳定、可反查的标识（如 'n0'）命名，mermaid 生成的 SVG 节点
     id 形如 'flowchart-n0-0'，可从该 id 反查出 'n0'。
   - 每次渲染/切换方向都递增 generation；异步 render() 完成后检查
     generation，旧结果不再覆盖新图（防止竞态）。
   - 所有 window/document 级监听器在 unmount 时统一移除，不泄漏。

   用法：
     const inst = TM1Mermaid.mount(container, {
       code: 'flowchart LR\n  n0["Foo"]-->n1["Bar"]',
       idMap: { n0: businessId0, n1: businessId1 },   // 可选：稳定 id → 业务 id
       onNodeClick: function(businessId, nodeId, label) { ... },
       title: '数据形成'
     });
     // 销毁：inst.destroy()

   全局：window.TM1Mermaid = { mount, unmountAll, isAvailable }。
*/
(function () {
  'use strict';

  var ZOOM_MIN = 0.15, ZOOM_MAX = 4, ZOOM_STEP = 1.2;
  var instances = new Set();

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

  function buildToolbar(state, opts) {
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
      state.vertical = !state.vertical;
      dir.textContent = state.vertical ? '纵向' : '横向';
      reflow(state, opts);
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
    if (opts.onBoxSelect) {
      var boxSelect = btn('框选模式', function () {
        state.boxSelection = !state.boxSelection;
        boxSelect.textContent = state.boxSelection ? '退出框选' : '框选模式';
        boxSelect.setAttribute('aria-pressed', String(state.boxSelection));
      });
      boxSelect.setAttribute('aria-pressed','false'); bar.appendChild(boxSelect);
    }
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
    var svg = inner.querySelector('svg');
    var box = svg && svg.viewBox.baseVal;
    var width = box && box.width + 40 || inner.scrollWidth || 800;
    var height = box && box.height + 40 || inner.scrollHeight || 600;
    var scale = Math.min((vr.width - 24) / Math.max(width, 1), (vr.height - 24) / Math.max(height, 1), 1.5);
    state.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, scale));
    state.pan = { x: (vr.width - width * state.zoom) / 2, y: (vr.height - height * state.zoom) / 2 };
    applyTransform(state);
  }

  function reflow(state, opts) {
    var code = state.vertical
      ? state.code.replace(/^\s*flowchart\s+LR/m, 'flowchart TB').replace(/^\s*graph\s+LR/m, 'graph TB')
      : state.code.replace(/^\s*flowchart\s+TB/m, 'flowchart LR').replace(/^\s*graph\s+TB/m, 'graph LR');
    renderDiagram(state, opts, code);
  }

  // 从 mermaid 渲染出的 SVG 节点 id（'flowchart-n0-0'）反查稳定节点 id（'n0'）。
  // mermaid 的节点 id 形如 'flowchart-<nodeId>-<index>' 或 'flowchart-<nodeId>'。
  function extractNodeId(svgNodeId) {
    if (!svgNodeId) return null;
    // 'flowchart-n0-0' -> 'n0'; 'flowchart-n0' -> 'n0'
    var m = svgNodeId.match(/^flowchart-(.+?)(?:-\d+)?$/);
    return m ? m[1] : null;
  }

  function renderDiagram(state, opts, code) {
    var gen = ++state.generation;
    (state.nodeHandlers || []).forEach(function (p) { p[0].removeEventListener('click', p[1]); });
    state.nodeHandlers = [];
    state.code = code;
    state.inner.replaceChildren();
    var p = document.createElement('pre');
    p.className = 'mm-rendering';
    p.textContent = '正在离线渲染…';
    state.inner.appendChild(p);
    // 使用唯一的临时容器 id：mermaid 10 要求 id 元素存在时由它自己写入，
    // 我们直接读返回值再注入，避免手动创建同 id 元素造成冲突。
    var renderId = 'mm-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
    window.mermaid.render(renderId, code).then(function (res) {
      if (state.disposed || gen !== state.generation) return;  // 竞态：旧结果不覆盖新图
      var el = document.createElement('div');
      el.className = 'mm-render';
      el.innerHTML = res.svg;
      state.inner.replaceChildren(el);
      // Mermaid emits width="100%". Give pan/zoom an intrinsic canvas size;
      // otherwise CSS responsive sizing and our transform scale the SVG twice.
      var renderedSvg = el.querySelector('svg');
      if (renderedSvg && renderedSvg.viewBox.baseVal.width) {
        renderedSvg.style.width = renderedSvg.viewBox.baseVal.width + 'px';
        renderedSvg.style.height = renderedSvg.viewBox.baseVal.height + 'px';
        renderedSvg.style.maxWidth = 'none';
      }
      state.svg = res.svg;
      bindNodes(state, opts);
      requestAnimationFrame(function () {
        if (state.disposed || gen !== state.generation) return;
        if (state.restoreView) {
          state.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, state.restoreView.zoom || 1));
          state.pan = {x: state.restoreView.x || 0, y: state.restoreView.y || 0};
          state.restoreView = null; applyTransform(state);
        } else fitView(state);
        if (opts.onRendered) opts.onRendered();
      });
    }).catch(function (err) {
      if (state.disposed || gen !== state.generation) return;
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
    var svg = state.inner.querySelector('svg');
    if (!svg) return;
    if (opts.onEdgeClick) svg.querySelectorAll('.flowchart-link').forEach(function (edge, i) {
      var handler = function (event) { event.stopPropagation(); opts.onEdgeClick(i, event); };
      edge.style.cursor = 'pointer'; edge.addEventListener('click', handler);
      state.nodeHandlers.push([edge, handler]);
    });
    if (!opts.onNodeClick) return;
    // 记录已绑定的事件监听器，unmount 时移除（防泄漏）。
    state.nodeHandlers = state.nodeHandlers || [];
    svg.querySelectorAll('.node').forEach(function (node) {
      var svgNodeId = node.id;
      var nodeId = extractNodeId(svgNodeId);
      node.style.cursor = 'pointer';
      var handler = function (event) {
        var labels = node.querySelectorAll('.nodeLabel, text');
        var label = '';
        labels.forEach(function (t) { label += t.textContent; });
        // 优先通过 idMap 反查业务 id；否则传 mermaid 稳定节点 id。
        var businessId = (opts.idMap && nodeId != null) ? opts.idMap[nodeId] : null;
        opts.onNodeClick(businessId !== undefined ? businessId : null, nodeId, label, event);
      };
      node.addEventListener('click', handler);
      state.nodeHandlers.push([node, handler]);
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
    opts = opts || {};
    var state = {
      container: container, code: opts.code || '', vertical: !!(opts.view ? opts.view.vertical : opts.vertical), restoreView: opts.view || null,
      zoom: 1, pan: { x: 0, y: 0 }, disposed: false, svg: null,
      generation: 0, nodeHandlers: [],
      listeners: [],  // window/document 级监听器 + 对应事件类型，用于清理
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
    var dragging = false, startX = 0, startY = 0, origX = 0, origY = 0, selectionBox = null;
    var onMouseDown = function (e) {
      if (e.button !== 0) return;
      if ((e.shiftKey || state.boxSelection) && opts.onBoxSelect) {
        startX = e.clientX; startY = e.clientY;
        selectionBox = document.createElement('div'); selectionBox.className = 'ew-box';
        selectionBox.style.position = 'fixed'; wrapper.appendChild(selectionBox);
        e.preventDefault(); return;
      }
      if (e.target.closest('.node,.flowchart-link')) return;
      dragging = true; startX = e.clientX; startY = e.clientY; origX = state.pan.x; origY = state.pan.y;
      viewport.style.cursor = 'grabbing';
      e.preventDefault();
    };
    var onMouseMove = function (e) {
      if (selectionBox) {
        selectionBox.style.left = Math.min(startX,e.clientX)+'px'; selectionBox.style.top = Math.min(startY,e.clientY)+'px';
        selectionBox.style.width = Math.abs(e.clientX-startX)+'px'; selectionBox.style.height = Math.abs(e.clientY-startY)+'px'; return;
      }
      if (!dragging || state.disposed) return;
      state.pan = { x: origX + (e.clientX - startX), y: origY + (e.clientY - startY) };
      applyTransform(state);
    };
    var onMouseUp = function (e) {
      if (selectionBox) {
        selectionBox.remove(); selectionBox = null;
        var ids = []; var left=Math.min(startX,e.clientX), right=Math.max(startX,e.clientX), top=Math.min(startY,e.clientY), bottom=Math.max(startY,e.clientY);
        state.inner.querySelectorAll('.node').forEach(function (node) {
          var b=node.getBoundingClientRect(), id=extractNodeId(node.id);
          if (b.right>=left && b.left<=right && b.bottom>=top && b.top<=bottom && opts.idMap[id]) ids.push(opts.idMap[id]);
        });
        opts.onBoxSelect(ids);
      }
      dragging = false; viewport.style.cursor = 'grab';
    };
    var onWheel = function (e) {
      e.preventDefault();
      setZoom(state, state.zoom * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP));
    };
    viewport.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    viewport.addEventListener('wheel', onWheel, { passive: false });
    // 记录监听器用于清理
    state.listeners.push([viewport, 'mousedown', onMouseDown]);
    state.listeners.push([window, 'mousemove', onMouseMove]);
    state.listeners.push([window, 'mouseup', onMouseUp]);
    state.listeners.push([viewport, 'wheel', onWheel]);

    var toolbar = buildToolbar(state, opts);
    wrapper.insertBefore(toolbar, viewport);
    container.appendChild(wrapper);

    var destroy = function () {
      if (state.disposed) return;
      state.disposed = true;
      state.generation++;  // 使任何在途异步结果失效
      // 移除节点点击监听器
      (state.nodeHandlers || []).forEach(function (p) { p[0].removeEventListener('click', p[1]); });
      state.nodeHandlers = [];
      // 移除 window/document 级监听器
      state.listeners.forEach(function (l) { l[0].removeEventListener(l[1], l[2]); });
      state.listeners = [];
      container.replaceChildren();
      instances.delete(instance);
    };
    var instance = { container: container, destroy: destroy,
      getView: function () { return {zoom:state.zoom,x:state.pan.x,y:state.pan.y,vertical:state.vertical?1:0}; },
      select: function (ids, edgeIndex) {
        state.inner.querySelectorAll('.node').forEach(function(n){n.classList.toggle('ew-selected',ids.indexOf(opts.idMap && opts.idMap[extractNodeId(n.id)])>=0);});
        state.inner.querySelectorAll('.flowchart-link').forEach(function(e,i){e.classList.toggle('ew-edge-selected',i===edgeIndex);});
      }
    };
    instances.add(instance);

    ensureMermaid().then(function () { if (!state.disposed) reflow(state, opts); }).catch(function (err) {
      if (state.disposed) return;
      showFallback(state, state.code, err);
    });
    return instance;
  }

  // 销毁所有实例（页面卸载等场景）。
  function unmountAll() {
    Array.from(instances).forEach(function (inst) { inst.destroy(); });
  }

  window.TM1Mermaid = { mount: mount, unmountAll: unmountAll, isAvailable: isAvailable };
  window.addEventListener('pagehide', unmountAll);
})();
