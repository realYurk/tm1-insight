/* TM1 Insight · 画布工作台外壳（canvas-shell）
 *
 * 只负责「外壳」交互：应用栏溢出菜单、资源栏折叠、底部 Dock、
 * 键盘快捷键、缩放 HUD、保存状态指示。不接触任何业务数据与图谱语义。
 * 业务逻辑仍全部在 architecture-workbench.js。
 */
(function () {
  'use strict';

  var root = document.getElementById('ew-root');
  if (!root) return;
  var $ = function (id) { return document.getElementById(id); };

  var RAIL_KEY = 'tm1-canvas-rail';
  var DOCK_KEY = 'tm1-canvas-dock';

  /* ------------------------------------------------ 资源栏折叠（记忆宽度开关） */
  try {
    if (localStorage.getItem(RAIL_KEY) === '0') root.classList.add('rail-collapsed');
  } catch (e) { /* 隐私模式：不记忆 */ }

  var railBtn = $('ew-toggle-rail');
  if (railBtn) railBtn.addEventListener('click', function () {
    var collapsed = root.classList.toggle('rail-collapsed');
    try { localStorage.setItem(RAIL_KEY, collapsed ? '0' : '1'); } catch (e) {}
    window.dispatchEvent(new CustomEvent('tm1-canvas-resize'));
  });

  /* ------------------------------------------------ 应用栏溢出菜单 */
  var moreBtn = $('ew-more');
  var moreMenu = $('ew-more-menu');
  function closeMenu() {
    if (moreMenu) { moreMenu.hidden = true; moreBtn && moreBtn.setAttribute('aria-expanded', 'false'); }
  }
  if (moreBtn && moreMenu) {
    moreBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = moreMenu.hidden;
      moreMenu.hidden = !open;
      moreBtn.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', function (e) {
      if (!moreMenu.hidden && !moreMenu.contains(e.target) && e.target !== moreBtn) closeMenu();
    });
    // 点菜单里的任何条目后自动收起（导入 label 内的文件选择除外）
    moreMenu.addEventListener('click', function (e) {
      if (e.target.closest('label')) return;
      closeMenu();
    });
  }

  /* ------------------------------------------------ 底部 Dock：页签 + 折叠 */
  var dock = $('ew-dock');
  if (dock) {
    var tabs = dock.querySelectorAll('.cx-dock-tab');
    var panes = dock.querySelectorAll('.cx-dock-pane');
    function setDock(open, persist) {
      dock.dataset.open = open ? '1' : '0';
      dock.setAttribute('aria-expanded', String(open));
      var collapse = $('ew-dock-collapse');
      if (collapse) {
        collapse.textContent = open ? '▾ 收起' : '▸ 展开';
        collapse.setAttribute('aria-label', open ? '收起底部面板' : '展开底部面板');
      }
      if (open) {
        window.dispatchEvent(new CustomEvent('tm1-canvas-resize'));
      }
      if (persist) { try { localStorage.setItem(DOCK_KEY, open ? '1' : '0'); } catch (e) {} }
    }
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        tabs.forEach(function (t) { t.setAttribute('aria-selected', String(t === tab)); });
        panes.forEach(function (p) { p.hidden = p.dataset.dockpane !== tab.dataset.docktab; });
        setDock(true, false);
      });
    });
    var collapseBtn = $('ew-dock-collapse');
    if (collapseBtn) collapseBtn.addEventListener('click', function () {
      setDock(dock.dataset.open !== '1', true);
    });
    var restored = null;
    try { restored = localStorage.getItem(DOCK_KEY); } catch (e) {}
    setDock(restored === '1', false);
  }

  /* ------------------------------------------------ 键盘快捷键 */
  document.addEventListener('keydown', function (e) {
    var inField = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || '')) || e.target.isContentEditable;
    // Ctrl+S：保存工作区（阻止浏览器另存）
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 's' || e.key === 'S')) {
      var save = $('ew-save');
      if (save) { e.preventDefault(); save.click(); }
      return;
    }
    if (inField) return;
    if (e.key === 'Escape') {
      if (moreMenu && !moreMenu.hidden) { closeMenu(); return; }
      var ctx = document.querySelector('.ew-ctx');
      if (ctx) { ctx.remove(); return; }
      // 交给画布取消拖线；否则关闭详情
      if (window.__ewCanvas && window.__ewCanvas.cancelConnect && window.__ewCanvas.cancelConnect()) return;
      window.dispatchEvent(new CustomEvent('tm1-canvas-escape'));
    }
  });

  /* ------------------------------------------------ 缩放 HUD */
  var hudZoom = $('ew-hud-zoom');
  function refreshHud() {
    var cy = window.__ewCanvas && window.__ewCanvas.cy && window.__ewCanvas.cy();
    if (cy && hudZoom) hudZoom.textContent = Math.round(cy.zoom() * 100) + '%';
  }
  var zoomOut = $('hud-zoom-out'), zoomIn = $('hud-zoom-in');
  if (zoomOut) zoomOut.addEventListener('click', function () { window.dispatchEvent(new CustomEvent('tm1-canvas-zoom', { detail: 1 / 1.25 })); });
  if (zoomIn) zoomIn.addEventListener('click', function () { window.dispatchEvent(new CustomEvent('tm1-canvas-zoom', { detail: 1.25 })); });
  setInterval(refreshHud, 400);

  /* ------------------------------------------------ 画布 resize 事件桥 */
  window.addEventListener('tm1-canvas-resize', function () {
    if (window.__ewCanvas && window.__ewCanvas.resize) window.__ewCanvas.resize();
  });

  /* ------------------------------------------------ 外壳 API（供业务脚本调用） */
  window.TM1Shell = {
    setSaveState: function (state, text) {
      var el = $('ew-save-state');
      if (!el) return;
      el.dataset.state = state;
      el.textContent = text || { dirty: '未保存', saving: '保存中…', saved: '已保存', error: '保存失败', idle: '' }[state] || '';
    },
    setSelectionCount: function (n) {
      var el = $('ew-selection-count');
      if (el) el.textContent = n > 1 ? '已选 ' + n + ' 个对象' : '';
    },
    openDock: function (tab) {
      if (!dock) return;
      var target = dock.querySelector('.cx-dock-tab[data-docktab="' + tab + '"]');
      if (target) target.click();
    },
    closeMenu: closeMenu,
  };
})();
