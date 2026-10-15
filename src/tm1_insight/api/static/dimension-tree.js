/* Dimension element hierarchy tree: lazy-load children, search with ancestor paths.
   Read-only browser of the recorded element/parent-child metadata; no MDX eval. */
(function () {
  'use strict';
  const root = document.getElementById('dimension-tree');
  if (!root) return;
  const dimName = root.dataset.name;
  const source = root.dataset.source;
  const status = document.getElementById('dimension-tree-status');

  let summary = null;          // tree_summary payload
  let loaded = new Set();      // element names whose children are already loaded/known as leaf
  let childMap = new Map();    // element -> children array (cached)
  let expanded = new Set();    // element names currently expanded

  async function api(path) {
    const response = await fetch(path, { cache: 'no-store' });
    const value = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(value.error || value.detail || '请求失败，请重试。');
    return value;
  }

  function setStatus(msg, isError) {
    if (!status) return;
    status.textContent = msg || '';
    status.classList.toggle('error', !!isError);
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function typeBadge(type) {
    if (!type) return '';
    const t = type.toLowerCase();
    if (t === 'consolidated') return '<span class="dim-elem-type consolidated">汇总</span>';
    if (t === 'numeric') return '<span class="dim-elem-type numeric">数值</span>';
    if (t === 'string') return '<span class="dim-elem-type string">文本</span>';
    return '<span class="dim-elem-type">' + escapeHtml(type) + '</span>';
  }

  function weightText(item) {
    if (!item.weight_known) return '';
    const w = item.weight;
    return '<span class="dim-weight" title="父子权重">' + w + '</span>';
  }

  function nodeTemplate(item, depth, isExpanded, isLoading) {
    const hasChildren = item.has_children;
    const expandedCls = isExpanded ? 'open' : '';
    const arrow = hasChildren
      ? '<button class="dim-tree-toggle" type="button" aria-label="' + (isExpanded ? '收起' : '展开') + ' ' + escapeHtml(item.name) + '" aria-expanded="' + isExpanded + '">' + (isExpanded ? '▾' : '▸') + '</button>'
      : '<span class="dim-tree-toggle leaf" aria-hidden="true"></span>';
    return '<li class="dim-tree-node" data-name="' + escapeHtml(item.name) + '" data-depth="' + depth + '">' +
      '<div class="dim-tree-row">' + arrow +
      '<button class="dim-tree-name" type="button" data-name="' + escapeHtml(item.name) + '" title="查看 ' + escapeHtml(item.name) + ' 的详情">' +
      escapeHtml(item.name) + '</button>' + typeBadge(item.type) + weightText(item) +
      (hasChildren ? '<span class="dim-child-count">' + item.child_count + '</span>' : '') +
      '</div>' +
      (hasChildren ? '<ul class="dim-tree-children" hidden></ul>' : '') +
      '</li>';
  }

  function renderChildren(ul, items, depth) {
    ul.innerHTML = '';
    items.forEach(function (item) {
      const html = nodeTemplate(item, depth, expanded.has(item.name), false);
      ul.insertAdjacentHTML('beforeend', html);
    });
  }

  async function loadChildren(name) {
    if (childMap.has(name)) return childMap.get(name);
    const result = await api('/api/dimensions/' + encodeURIComponent(dimName) +
      '/children/' + encodeURIComponent(name) + '?source=' + encodeURIComponent(source));
    childMap.set(name, result.children);
    return result.children;
  }

  async function toggle(name, li) {
    const childrenUl = li.querySelector(':scope > .dim-tree-children');
    if (!childrenUl) return; // leaf
    if (expanded.has(name)) {
      expanded.delete(name);
      childrenUl.hidden = true;
      const toggle = li.querySelector(':scope > .dim-tree-row .dim-tree-toggle');
      if (toggle) { toggle.textContent = '▸'; toggle.setAttribute('aria-expanded', 'false'); }
      return;
    }
    // expand
    expanded.add(name);
    childrenUl.hidden = false;
    const toggle = li.querySelector(':scope > .dim-tree-row .dim-tree-toggle');
    if (toggle) { toggle.textContent = '▾'; toggle.setAttribute('aria-expanded', 'true'); }
    if (childrenUl.dataset.loaded !== '1') {
      childrenUl.innerHTML = '<li class="dim-tree-loading">加载中…</li>';
      try {
        const children = await loadChildren(name);
        renderChildren(childrenUl, children, parseInt(li.dataset.depth, 10) + 1);
        childrenUl.dataset.loaded = '1';
      } catch (error) {
        childrenUl.innerHTML = '<li class="dim-tree-error">' + escapeHtml(error.message) +
          ' <button class="dim-tree-retry" type="button" data-name="' + escapeHtml(name) + '">重试</button></li>';
        childrenUl.dataset.loaded = '';
      }
    }
  }

  function renderTree() {
    const container = document.getElementById('dimension-tree-body');
    if (!summary.roots.length) {
      container.innerHTML = '<p class="muted">当前数据没有可展示的元素。</p>';
      return;
    }
    const ul = document.createElement('ul');
    ul.className = 'dim-tree';
    summary.roots.forEach(function (item) {
      ul.insertAdjacentHTML('beforeend', nodeTemplate(item, 0, false, false));
    });
    container.innerHTML = '';
    container.appendChild(ul);
  }

  function renderFlat(container) {
    // No hierarchy: a searchable flat list (paginated client-side for display).
    const items = summary.roots;
    container.innerHTML = '';
    const note = document.createElement('p');
    note.className = 'muted small';
    note.textContent = '当前数据未包含完整层级关系，以下为扁平成员列表。';
    container.appendChild(note);
    const ul = document.createElement('ul');
    ul.className = 'dim-tree flat';
    items.forEach(function (item) {
      const html = '<li class="dim-tree-node" data-name="' + escapeHtml(item.name) + '">' +
        '<div class="dim-tree-row"><span class="dim-tree-toggle leaf" aria-hidden="true"></span>' +
        '<button class="dim-tree-name" type="button" data-name="' + escapeHtml(item.name) + '">' + escapeHtml(item.name) + '</button>' +
        typeBadge(item.type) + '</div></li>';
      ul.insertAdjacentHTML('beforeend', html);
    });
    container.appendChild(ul);
  }

  async function init() {
    setStatus('正在加载维度结构…');
    try {
      summary = await api('/api/dimensions/' + encodeURIComponent(dimName) +
        '/tree?source=' + encodeURIComponent(source));
      setStatus('');
      // 基础信息区
      const metaEl = document.getElementById('dimension-meta');
      if (metaEl) {
        const total = summary.element_count != null ? summary.element_count : summary.recorded_elements;
        const hierarchyNote = summary.has_hierarchy
          ? '包含层级关系'
          : '未包含完整层级关系（扁平成员）';
        metaEl.textContent = '元素总数 ' + total + ' · ' + hierarchyNote +
          ' · 属性 ' + summary.attributes.length + ' · 子集 ' + summary.subsets.length;
      }
      const container = document.getElementById('dimension-tree-body');
      if (summary.has_hierarchy) {
        renderTree();
      } else {
        renderFlat(container);
      }
      // 属性 / 子集 / cube 汇总区
      renderSideInfo(summary);
    } catch (error) {
      setStatus(error.message, true);
      const container = document.getElementById('dimension-tree-body');
      if (container) container.innerHTML = '<p class="chore-warning">' + escapeHtml(error.message) + '</p>';
    }
  }

  function renderSideInfo(s) {
    const attrEl = document.getElementById('dimension-attributes');
    if (attrEl) {
      if (s.attributes.length) {
        attrEl.innerHTML = s.attributes.map(function (a) {
          return '<span class="dim-attr" title="属性定义（未采集属性值）">' + escapeHtml(a.name || 'UNKNOWN') +
            (a.type ? ' <em>' + escapeHtml(a.type) + '</em>' : '') + '</span>';
        }).join('');
      } else {
        attrEl.innerHTML = '<span class="muted">无属性定义</span>';
      }
    }
    const subEl = document.getElementById('dimension-subsets');
    if (subEl) {
      if (s.subsets.length) {
        const withExpr = s.subsets.filter(function (x) { return x.has_expression; }).length;
        subEl.textContent = s.subsets.length + ' 个子集定义' +
          (withExpr ? '（其中 ' + withExpr + ' 个保存了 MDX 表达式）' : '（未保存子集成员或表达式）');
      } else {
        subEl.textContent = '无子集定义';
      }
    }
  }

  // 点击事件委托：展开/收起 + 元素名查看详情
  const body = document.getElementById('dimension-tree-body');
  body.addEventListener('click', async function (event) {
    const arrow = event.target.closest('.dim-tree-toggle');
    if (arrow && !arrow.classList.contains('leaf')) {
      const li = arrow.closest('.dim-tree-node');
      const name = li.dataset.name;
      await toggle(name, li);
      return;
    }
    const nameBtn = event.target.closest('.dim-tree-name');
    if (nameBtn) {
      const name = nameBtn.dataset.name;
      await showElementDetail(name);
      return;
    }
    const retry = event.target.closest('.dim-tree-retry');
    if (retry) {
      const name = retry.dataset.name;
      const li = body.querySelector('.dim-tree-node[data-name="' + CSS.escape(name) + '"]');
      if (li) {
        expanded.delete(name);
        await toggle(name, li);
      }
    }
  });

  async function showElementDetail(name) {
    const detail = document.getElementById('dimension-element-detail');
    if (!detail) return;
    detail.hidden = false;
    const title = document.getElementById('dimension-element-detail-name');
    const parents = document.getElementById('dimension-element-detail-parents');
    const children = document.getElementById('dimension-element-detail-children');
    const type = document.getElementById('dimension-element-detail-type');
    title.textContent = name;
    type.textContent = '加载中…';
    parents.textContent = '加载中…';
    children.textContent = '加载中…';
    try {
      const search = await api('/api/dimensions/' + encodeURIComponent(dimName) +
        '/search?q=' + encodeURIComponent(name) + '&source=' + encodeURIComponent(source));
      const match = search.matches.find(function (m) { return m.name === name; });
      if (match) {
        type.textContent = match.type || 'UNKNOWN';
        parents.textContent = match.parents.length ? match.parents.join(' › ') : '（无父项，顶层元素）';
      }
      const ch = await api('/api/dimensions/' + encodeURIComponent(dimName) +
        '/children/' + encodeURIComponent(name) + '?source=' + encodeURIComponent(source));
      if (ch.children.length) {
        children.textContent = ch.children.map(function (c) { return c.name + (c.weight_known ? '（权重 ' + c.weight + '）' : ''); }).join('、');
      } else {
        children.textContent = '（无直接子项）';
      }
    } catch (error) {
      type.textContent = '加载失败';
      parents.textContent = '';
      children.textContent = error.message;
    }
  }

  // 搜索：覆盖整个维度，返回匹配项 + 祖先路径
  const searchForm = document.getElementById('dimension-tree-search-form');
  if (searchForm) {
    searchForm.addEventListener('submit', async function (event) {
      event.preventDefault();
      const q = document.getElementById('dimension-tree-search-input').value.trim();
      const results = document.getElementById('dimension-tree-search-results');
      if (!q) { results.hidden = true; results.innerHTML = ''; return; }
      setStatus('正在搜索整个维度…');
      results.hidden = false;
      results.innerHTML = '<p class="muted small">搜索中…</p>';
      try {
        const data = await api('/api/dimensions/' + encodeURIComponent(dimName) +
          '/search?q=' + encodeURIComponent(q) + '&source=' + encodeURIComponent(source));
        setStatus('');
        if (!data.matches.length) {
          results.innerHTML = '<p class="muted">没有匹配的元素。</p>';
        } else {
          const ul = document.createElement('ul');
          ul.className = 'dim-search-results';
          data.matches.slice(0, 200).forEach(function (m) {
            const li = document.createElement('li');
            li.innerHTML = '<button class="dim-search-hit" type="button" data-name="' + escapeHtml(m.name) + '">' +
              escapeHtml(m.name) + typeBadge(m.type) + '</button>' +
              (m.parents.length ? '<span class="muted small dim-search-ancestors">祖先：' + m.parents.map(escapeHtml).join(' › ') + '</span>' : '');
            li.querySelector('.dim-search-hit').addEventListener('click', function () {
              showElementDetail(m.name);
            });
            ul.appendChild(li);
          });
          results.innerHTML = '';
          results.appendChild(ul);
          if (data.matches.length > 200) {
            results.insertAdjacentHTML('beforeend', '<p class="muted small">仅显示前 200 个匹配项，请细化搜索词。</p>');
          }
        }
      } catch (error) {
        setStatus(error.message, true);
        results.innerHTML = '<p class="chore-warning">' + escapeHtml(error.message) + '</p>';
      }
    });
  }

  init();
})();
