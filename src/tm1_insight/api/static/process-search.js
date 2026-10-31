/* Read-only TI navigation. Bounded results, source-isolated context and native history. */
(function () {
  'use strict';
  const context = JSON.parse(document.getElementById('process-search-context').textContent);
  const storageKey = 'tm1-process-search';
  const defaults = {q: '', scope: 'name', page: 1, source: context.source};
  function readContext() {
    try {
      const last = JSON.parse(sessionStorage.getItem(storageKey));
      if (last && last.source === context.source && ['name', 'code', 'all'].includes(last.scope)) {
        return {...defaults, ...last};
      }
    } catch (error) { /* Storage is optional; native navigation remains usable. */ }
    return {...defaults};
  }
  function save(value) {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(value));
      // Retain the existing Chore back-link contract.
      sessionStorage.setItem('processes-last', JSON.stringify(value));
    } catch (error) { /* No persistent model data is written. */ }
  }
  function listUrl(value) {
    return '/processes?' + new URLSearchParams({q: value.q, scope: value.scope, page: value.page});
  }
  if (context.is_list) { save({...defaults, ...context}); return; }
  const back = document.getElementById('back-to-list');
  function restoreBack() { back.href = listUrl(readContext()); }
  restoreBack();
  window.addEventListener('pageshow', restoreBack);

  // 源码锚点：页面若自行管理惰性代码段（TM1ProcessView），定位由页面负责，
  // 因为行节点要在切 Tab 之后才会被渲染出来，此处无法提前建立 id。
  document.addEventListener('DOMContentLoaded', function () {
    const view = window.TM1ProcessView;
    if (!view) {
      document.querySelectorAll('.proc-main .tab-pane').forEach(pane => {
        pane.querySelectorAll('.code-line').forEach((line, index) => {
          line.id = pane.dataset.pane + '-L' + (index + 1);
        });
      });
    }
    function focusSource() {
      if (view) return;
      const match = /^#(prolog|metadata|data|epilog)-L([1-9][0-9]*)$/.exec(location.hash);
      if (!match) return;
      const line = document.getElementById(match[1] + '-L' + match[2]);
      if (!line) return;
      document.querySelectorAll('.source-location-current').forEach(el => el.classList.remove('source-location-current'));
      document.querySelector('.tab[data-tab="' + match[1] + '"]').click();
      line.classList.add('source-location-current');
      line.scrollIntoView({block: 'center'});
    }
    const main = document.querySelector('.proc-main');
    const tabbar = main.querySelector('.tabbar');
    function fitCode() {
      const bottom = tabbar.getBoundingClientRect().bottom;
      const gap = parseFloat(getComputedStyle(tabbar).marginBottom) || 0;
      main.style.setProperty('--process-code-height', Math.max(240, window.innerHeight - bottom - gap - 16) + 'px');
    }
    fitCode();
    focusSource();
    window.addEventListener('hashchange', focusSource);
    window.addEventListener('resize', fitCode);
    window.addEventListener('pageshow', fitCode);
    if ('ResizeObserver' in window) {
      const observer = new ResizeObserver(fitCode);
      document.querySelectorAll('.process-page-head, .breadcrumb, .proc-main .tabbar').forEach(el => observer.observe(el));
    }
  });

  const dialog = document.getElementById('process-switcher');
  const open = document.getElementById('open-process-switcher');
  const input = document.getElementById('process-switcher-query');
  const scope = document.getElementById('process-switcher-scope');
  const results = document.getElementById('process-switcher-results');
  const status = document.getElementById('process-switcher-status');
  const prev = document.getElementById('process-switcher-prev');
  const next = document.getElementById('process-switcher-next');
  const fullList = document.getElementById('process-switcher-list');
  let sequence = 0, controller, timer, offset = 0;
  const limit = 25;
  function invalidate() {
    sequence++;
    clearTimeout(timer);
    if (controller) controller.abort();
    results.replaceChildren();
    prev.disabled = next.disabled = true;
    fullList.hidden = true;
  }
  async function search(start = 0) {
    invalidate();
    const request = sequence;
    controller = new AbortController();
    status.textContent = '正在搜索…';
    results.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch('/api/processes/search?' + new URLSearchParams({
        q: input.value.trim(), scope: scope.value, offset: start, limit
      }), {signal: controller.signal, cache: 'no-store'});
      const data = await response.json();
      if (request !== sequence || !dialog.open) return;
      if (!response.ok) throw new Error(data.error || '搜索失败，请重试。');
      if (data.source !== context.source) throw new Error('数据源已变化，请刷新页面后重新搜索。');
      offset = data.offset;
      const last = {q: data.q, scope: data.scope, page: Math.floor(offset / 100) + 1, source: context.source};
      data.items.forEach(item => {
        const row = document.createElement('li');
        row.className = 'process-search-item';
        const link = document.createElement('a');
        link.textContent = item.name;
        link.href = '/explorer/process/' + encodeURIComponent(item.name);
        const badge = document.createElement('span');
        badge.className = 'tag';
        badge.textContent = '名称匹配';
        if (item.match.kind === 'code') {
          link.search = new URLSearchParams({source: data.source});
          link.hash = item.match.section + '-L' + item.match.line;
          badge.textContent = '代码 · ' + item.match.section + ' : ' + item.match.line;
          const excerpt = document.createElement('code');
          excerpt.className = 'process-excerpt';
          excerpt.textContent = item.match.excerpt;
          row.append(link, badge, excerpt);
        } else { row.append(link, badge); }
        link.addEventListener('click', () => { save(last); restoreBack(); dialog.close(); });
        results.append(row);
      });
      status.textContent = data.total ? '共 ' + data.total + ' 个 TI · ' + (offset + 1) + '–' + (offset + data.items.length) : '没有匹配的 TI，试试其他关键词或搜索范围。';
      prev.disabled = offset === 0;
      next.disabled = offset + data.items.length >= data.total;
      fullList.href = listUrl(last);
      fullList.hidden = false;
      fullList.onclick = () => save(last);
    } catch (error) {
      if (request === sequence && error.name !== 'AbortError') status.textContent = error.message;
    } finally {
      if (request === sequence) results.removeAttribute('aria-busy');
    }
  }
  open.addEventListener('click', function () {
    const last = readContext();
    input.value = last.q;
    scope.value = last.scope;
    dialog.showModal();
    input.focus(); input.select();
    search();
  });
  document.getElementById('close-process-switcher').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { invalidate(); open.focus(); });
  document.getElementById('process-switcher-form').addEventListener('submit', event => { event.preventDefault(); search(); });
  input.addEventListener('input', function () {
    invalidate();
    status.textContent = '正在搜索…';
    timer = setTimeout(() => search(), 250);
  });
  scope.addEventListener('change', () => search());
  prev.addEventListener('click', () => search(Math.max(0, offset - limit)));
  next.addEventListener('click', () => search(offset + limit));
})();
