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
  let childMap = new Map();    // element name -> children array (cached; shared across instances)
  let expanded = new Set();    // node PATH keys currently expanded (per tree instance, not per name)

  // A node's path is its identity within the tree: the chain of names from the
  // root down to this node. Two occurrences of the same element (multi-parent)
  // have different paths and thus independent expand/collapse state.
  function nodePath(li) {
    let parts = [li.dataset.name];
    let parent = li.parentElement;
    while (parent && parent.classList && parent.classList.contains('dim-tree-children')) {
      const parentNode = parent.closest('.dim-tree-node');
      if (!parentNode) break;
      parts.unshift(parentNode.dataset.name);
      parent = parentNode.parentElement;
    }
    return parts.join('/');
  }

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
    return '<li class="dim-tree-node" data-name="' + escapeHtml(item.name) + '" data-depth="' + depth + '" role="treeitem" aria-expanded="' + (hasChildren ? isExpanded : 'false') + '">' +
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
      // Expanded state is resolved lazily by path once the node exists in the DOM;
      // here we always render collapsed; the caller re-applies expansion below.
      ul.insertAdjacentHTML('beforeend', nodeTemplate(item, depth, false, false));
    });
  }

  async function loadChildren(name) {
    if (childMap.has(name)) return childMap.get(name);
    const result = await api('/api/dimensions/' + encodeURIComponent(dimName) +
      '/children/' + encodeURIComponent(name) + '?source=' + encodeURIComponent(source));
    childMap.set(name, result.children);
    return result.children;
  }

  // 最大展开深度：防止含循环/自引用边的异常数据在树上无限展开出重复链条。
  const MAX_DEPTH = 64;

  async function toggle(name, li) {
    const childrenUl = li.querySelector(':scope > .dim-tree-children');
    if (!childrenUl) return; // leaf
    const path = nodePath(li);
    const depth = parseInt(li.dataset.depth, 10) || 0;
    if (expanded.has(path)) {
      expanded.delete(path);
      childrenUl.hidden = true;
      const toggleBtn = li.querySelector(':scope > .dim-tree-row .dim-tree-toggle');
      if (toggleBtn) { toggleBtn.textContent = '▸'; toggleBtn.setAttribute('aria-expanded', 'false'); }
      li.setAttribute('aria-expanded', 'false');
      return;
    }
    // Cycle/depth guard: never expand beyond MAX_DEPTH.
    if (depth >= MAX_DEPTH) {
      setStatus('已达到最大展开深度，无法继续展开（可能存在循环引用）。', true);
      return;
    }
    // expand
    expanded.add(path);
    childrenUl.hidden = false;
    const toggleBtn = li.querySelector(':scope > .dim-tree-row .dim-tree-toggle');
    if (toggleBtn) { toggleBtn.textContent = '▾'; toggleBtn.setAttribute('aria-expanded', 'true'); }
    li.setAttribute('aria-expanded', 'true');
    if (childrenUl.dataset.loaded !== '1') {
      childrenUl.innerHTML = '<li class="dim-tree-loading">加载中…</li>';
      try {
        const children = await loadChildren(name);
        renderChildren(childrenUl, children, depth + 1);
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

  // 大型扁平维度：后端已分页返回 roots（默认 200），这里只做有界渲染，
  // 不再一次生成数万个 DOM 节点；剩余成员通过搜索框覆盖完整索引定位。
  const FLAT_PAGE_SIZE = 200;
  let flatItems = [];        // 当前扁平列表的成员（来自 summary.roots，已分页）
  let flatShown = 0;         // 已渲染数量

  function renderFlat(container) {
    // No hierarchy: a searchable flat list (bounded by the server-side page).
    flatItems = summary.roots || [];
    flatShown = 0;
    container.innerHTML = '';
    const note = document.createElement('p');
    note.className = 'muted small';
    const rootTotal = summary.root_total != null ? summary.root_total : flatItems.length;
    const truncated = summary.root_truncated || rootTotal > flatItems.length;
    note.textContent = truncated
      ? '当前数据未包含完整层级关系，以下为扁平成员列表的前 ' + flatItems.length +
        ' 个（共 ' + rootTotal + ' 个）。可用上方搜索框定位任意元素。'
      : '当前数据未包含完整层级关系，以下为扁平成员列表。';
    container.appendChild(note);
    const ul = document.createElement('ul');
    ul.className = 'dim-tree flat';
    ul.setAttribute('role', 'tree');
    container.appendChild(ul);
    renderFlatPage(container);
  }

  function renderFlatPage(container) {
    const ul = container.querySelector('ul.dim-tree.flat');
    const batch = flatItems.slice(flatShown, flatShown + FLAT_PAGE_SIZE);
    batch.forEach(function (item) {
      const html = '<li class="dim-tree-node" data-name="' + escapeHtml(item.name) + '" role="treeitem">' +
        '<div class="dim-tree-row"><span class="dim-tree-toggle leaf" aria-hidden="true"></span>' +
        '<button class="dim-tree-name" type="button" data-name="' + escapeHtml(item.name) + '">' + escapeHtml(item.name) + '</button>' +
        typeBadge(item.type) + '</div></li>';
      ul.insertAdjacentHTML('beforeend', html);
    });
    flatShown += batch.length;
    const more = container.querySelector('.dim-flat-more');
    if (more) {
      const remaining = flatItems.length - flatShown;
      more.hidden = remaining <= 0;
      if (remaining > 0) more.textContent = '加载更多（剩余 ' + remaining + '）';
    }
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
        const hierarchyNote = summary.large_dimension
          ? '规模过大，仅展示部分元素'
          : (summary.has_hierarchy ? '包含层级关系' : '未包含完整层级关系（扁平成员）');
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
        expanded.delete(nodePath(li));
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
        // Prefer full ancestor paths; fall back to direct parents.
        if (match.paths && match.paths.length) {
          parents.textContent = match.paths.map(function (p) {
            return p.join(' › ') + ' › ' + name;
          }).join('；');
        } else if (match.parents.length) {
          parents.textContent = match.parents.join(' › ') + ' › ' + name;
        } else {
          parents.textContent = '（无父项，顶层元素）';
        }
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
            const ancestorText = (m.paths && m.paths.length)
              ? m.paths.map(function (p) { return p.join(' › '); }).join('；')
              : (m.parents && m.parents.length ? m.parents.join(' › ') : '');
            li.innerHTML = '<button class="dim-search-hit" type="button" data-name="' + escapeHtml(m.name) + '">' +
              escapeHtml(m.name) + typeBadge(m.type) + '</button>' +
              (ancestorText ? '<span class="muted small dim-search-ancestors">祖先路径：' + escapeHtml(ancestorText) + '</span>' : '');
            li.querySelector('.dim-search-hit').addEventListener('click', function () {
              showElementDetail(m.name);
            });
            ul.appendChild(li);
          });
          results.innerHTML = '';
          results.appendChild(ul);
          // 真实总数 vs 当前返回数
          const total = data.total != null ? data.total : data.matches.length;
          let note = '共 ' + total + ' 个匹配';
          if (data.truncated) note += '，仅显示前 ' + data.matches.length + ' 个';
          results.insertAdjacentHTML('beforeend',
            '<p class="muted small">' + escapeHtml(note) + '，请细化搜索词定位具体元素。</p>');
        }
      } catch (error) {
        setStatus(error.message, true);
        results.innerHTML = '<p class="chore-warning">' + escapeHtml(error.message) + '</p>';
      }
    });
  }

  init();
})();
