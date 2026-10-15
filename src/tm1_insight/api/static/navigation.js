/* Native navigation with immediate feedback; no full-page JS cache or speculative analysis. */
(function () {
  'use strict';
  // 导航分组（模型资产 / 高级工具）的手动展开/收起状态持久化。
  // 服务端会按当前路由默认展开所属分组；这里只在用户主动切换后记录偏好，
  // 使跨路由切换时分组状态稳定、不跳动。
  try {
    document.querySelectorAll('.nav-group').forEach(function (group) {
      var summary = group.querySelector('.nav-group-summary');
      var key = 'tm1-nav-group-' + (summary.textContent.trim().replace(/\s+/g, '-') || group.dataset.key);
      var saved = localStorage.getItem(key);
      if (saved !== null) { group.open = saved === 'open'; }
      summary.addEventListener('click', function () {
        try { localStorage.setItem(key, group.open ? 'open' : 'closed'); } catch (e) {}
      });
    });
  } catch (e) {}

  const status = document.getElementById('navigation-status');
  const main = document.getElementById('main-content');
  document.querySelectorAll('.nav-link.active').forEach(link => link.setAttribute('aria-current', 'page'));
  function target(event) {
    if (event.button > 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return null;
    const link = event.target.closest && event.target.closest('a[href]');
    if (!link || link.target || link.hasAttribute('download')) return null;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || (url.pathname === location.pathname && url.search === location.search && url.hash)) return null;
    return link;
  }
  document.addEventListener('pointerdown', function (event) {
    const link = target(event);
    if (link) link.classList.add('navigation-pending');
  }, {passive: true});
  document.addEventListener('pointercancel', function () {
    document.querySelectorAll('.navigation-pending').forEach(link => link.classList.remove('navigation-pending'));
  }, {passive: true});
  document.addEventListener('click', function (event) {
    const link = target(event);
    if (!link || event.defaultPrevented) return;
    link.classList.add('navigation-pending');
    main.setAttribute('aria-busy', 'true');
    status.textContent = '正在打开 ' + link.textContent.trim();
    status.hidden = false;
    // Keep normal link behavior: native history, modifier keys and cancellation work.
  });
  window.addEventListener('pageshow', function () {
    main.removeAttribute('aria-busy');
    status.hidden = true;
    document.querySelectorAll('.navigation-pending').forEach(link => link.classList.remove('navigation-pending'));
  });
  // Diagnostics stay in this browser, contain durations only, and never leave the device.
  if ('PerformanceObserver' in window && PerformanceObserver.supportedEntryTypes.includes('event')) {
    const timings = window.tm1InteractionTimings = [];
    const observer = new PerformanceObserver(list => {
      list.getEntries().forEach(entry => {
        if (entry.interactionId) { timings.push(entry.duration); if (timings.length > 100) timings.shift(); }
      });
    });
    observer.observe({type: 'event', buffered: true, durationThreshold: 16});
    window.addEventListener('pagehide', () => observer.disconnect());
  }
})();
