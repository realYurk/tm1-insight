/* Dimension element hierarchy TreeGrid: table layout with lazy child loading,
   search with ancestor paths, optional attribute-value columns.

   Read-only browser of the recorded element/parent-child metadata; no MDX eval.
   Layout: a semantic <table> with a fixed header (名称 / 类型 / 父子权重), where
   the name column carries the hierarchy indent + expand toggle. Multi-parent
   nodes have independent expand/collapse state keyed by their DOM path. */
(function () {
  'use strict';
  const root = document.getElementById('dimension-tree');
  if (!root) return;
  const dimName = root.dataset.name;
  const source = root.dataset.source;
  const status = document.getElementById('dimension-tree-status');

  let summary = null;          // tree_summary payload
  let childMap = new Map();    // element name -> children array (cached)
  let expanded = new Set();    // node PATH keys currently expanded (per instance)
  let attributeColumns = [];   // selected attribute names for value columns

  // 属性列选择偏好：按维度名隔离持久化（不同 Dimension 各自保存列配置）。
  // 仅保存已采集值的属性名列表，读取时校验，避免过期属性污染当前渲染。
  function loadAttributeColumns() {
    if (!window.WorkbenchContext) return;
    var saved = window.WorkbenchContext.preference('dim-attr-cols:' + dimName);
    if (!saved) return;
    try {
      var names = JSON.parse(saved);
      if (Array.isArray(names)) attributeColumns = names.filter(function (x) { return typeof x === 'string'; });
    } catch (e) { /* 过期偏好丢弃 */ }
  }
  function saveAttributeColumns() {
    if (!window.WorkbenchContext) return;
    window.WorkbenchContext.setPreference('dim-attr-cols:' + dimName, JSON.stringify(attributeColumns));
  }

  // A node's path is its identity: the chain of names from root down to this node.
  function nodePath(tr) {
    let parts = [tr.dataset.name];
    let parent = tr.parentElement;
    while (parent && parent.classList && parent.classList.contains('dim-grid-children')) {
      const parentRow = parent.closest('tr.dim-grid-row');
      if (!parentRow) break;
      parts.unshift(parentRow.dataset.name);
      parent = parentRow.parentElement;
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

  // 类型列：简洁 C/N/S 协调标签（不堆砌彩色徽章）
  function typeLabel(type) {
    if (!type) return '<span class="dim-type dim-type-unknown" title="类型未采集">?</span>';
    const t = String(type).toLowerCase();
    if (t === 'consolidated') return '<span class="dim-type dim-type-c" title="Consolidated 汇总">C</span>';
    if (t === 'numeric') return '<span class="dim-type dim-type-n" title="Numeric 数值">N</span>';
    if (t === 'string') return '<span class="dim-type dim-type-s" title="String 文本">S</span>';
    return '<span class="dim-type dim-type-unknown" title="' + escapeHtml(type) + '">' + escapeHtml(type) + '</span>';
  }

  function weightCell(item) {
    if (!item.weight_known) return '<td class="dim-grid-weight dim-grid-unknown">—</td>';
    return '<td class="dim-grid-weight">' + item.weight + '</td>';
  }

  function attributeValueCell(name) {
    const av = (summary.attribute_values || {}).attributes || {};
    const attr = av[name];
    if (!attr) return '<td class="dim-grid-attr dim-grid-unknown" title="未采集">—</td>';
    // 元素名 -> 值；未命中时表示未采集该元素的值（区别于真实空值）
    return '<td class="dim-grid-attr"></td>'; // 值由 fillAttributeCells 按行填充
  }

  // 展开箭头 + 缩进 + 名称（元素名称列）
  function nameCell(item, depth, isExpanded) {
    const hasChildren = item.has_children;
    const indent = '&nbsp;'.repeat(depth * 3);
    const arrow = hasChildren
      ? '<button class="dim-tree-toggle" type="button" aria-label="' + (isExpanded ? '收起' : '展开') + ' ' + escapeHtml(item.name) + '" aria-expanded="' + isExpanded + '">' + (isExpanded ? '▾' : '▸') + '</button>'
      : '<span class="dim-tree-toggle leaf" aria-hidden="true"></span>';
    const title = item.weight_known || !hasChildren ? '' : ' title="查看 ' + escapeHtml(item.name) + ' 详情"';
    return '<td class="dim-grid-name"><span class="dim-grid-indent">' + indent + '</span>' + arrow +
      '<button class="dim-tree-name" type="button" data-name="' + escapeHtml(item.name) + '"' + title + '>' +
      escapeHtml(item.name) + '</button>' +
      (hasChildren ? '<span class="dim-child-count">' + item.child_count + '</span>' : '') + '</td>';
  }

  function rowTemplate(item, depth, isExpanded) {
    const attrTds = attributeColumns.map(function (a) { return attributeValueCell(a); }).join('');
    return '<tr class="dim-grid-row" data-name="' + escapeHtml(item.name) + '" data-depth="' + depth + '" role="treeitem" aria-expanded="' + (item.has_children ? isExpanded : 'false') + '">' +
      nameCell(item, depth, isExpanded) +
      '<td class="dim-grid-type">' + typeLabel(item.type) + '</td>' +
      weightCell(item) + attrTds +
      '</tr>';
  }

  function fillAttributeCells(row, name) {
    const av = (summary.attribute_values || {}).attributes || {};
    row.querySelectorAll('.dim-grid-attr').forEach(function (td, idx) {
      const attrName = attributeColumns[idx];
      const attr = av[attrName];
      if (!attr) return;
      const val = attr.values && Object.prototype.hasOwnProperty.call(attr.values, name)
        ? attr.values[name] : null;
      if (val === null || val === undefined) {
        td.textContent = '—';
        td.classList.add('dim-grid-unknown');
        td.title = '未采集该元素此属性的值';
      } else {
        td.textContent = String(val);
        td.classList.remove('dim-grid-unknown');
        td.title = attrName + ': ' + String(val);
      }
    });
  }

  function renderRows(container, items, depth) {
    const frag = document.createDocumentFragment();
    items.forEach(function (item) {
      frag.appendChild(buildRow(item, depth, false));
    });
    container.innerHTML = '';
    container.appendChild(frag);
  }

  async function loadChildren(name) {
    if (childMap.has(name)) return childMap.get(name);
    const result = await api('/api/dimensions/' + encodeURIComponent(dimName) +
      '/children/' + encodeURIComponent(name) + '?source=' + encodeURIComponent(source));
    childMap.set(name, result.children);
    return result.children;
  }

  const MAX_DEPTH = 64;

  async function toggle(name, tr) {
    const path = nodePath(tr);
    const depth = parseInt(tr.dataset.depth, 10) || 0;
    // 收起：移除该节点已展开插入的子行组
    if (expanded.has(path)) {
      expanded.delete(path);
      removeChildGroup(tr);
      const btn = tr.querySelector('.dim-tree-toggle');
      if (btn) { btn.textContent = '▸'; btn.setAttribute('aria-expanded', 'false'); }
      tr.setAttribute('aria-expanded', 'false');
      return;
    }
    if (depth >= MAX_DEPTH) {
      setStatus('已达到最大展开深度，无法继续展开（可能存在循环引用）。', true);
      return;
    }
    // 展开：在父行后插入子行组
    expanded.add(path);
    const btn = tr.querySelector('.dim-tree-toggle');
    if (btn) { btn.textContent = '▾'; btn.setAttribute('aria-expanded', 'true'); }
    tr.setAttribute('aria-expanded', 'true');
    if (tr.dataset.loaded !== '1') {
      tr.dataset.loaded = '1';
      try {
        const children = await loadChildren(name);
        insertChildGroup(tr, children, depth + 1);
      } catch (error) {
        tr.dataset.loaded = '';
        expanded.delete(path);
        const errTr = document.createElement('tr');
        errTr.className = 'dim-grid-loading-row';
        errTr.innerHTML = '<td colspan="99" class="dim-tree-error">' + escapeHtml(error.message) +
          ' <button class="dim-tree-retry" type="button" data-name="' + escapeHtml(name) + '">重试</button></td>';
        tr.after(errTr);
      }
    } else {
      // 已加载过，重新插入（缓存的子行组）
      const cached = tr.dataset.children ? JSON.parse(tr.dataset.children) : null;
      if (cached) insertChildGroup(tr, cached, depth + 1);
    }
  }

  // 子行组：父行之后的一组子 tr，用 dataset.parent 标记归属，收起时按标记移除。
  function insertChildGroup(parentTr, children, depth) {
    const frag = document.createDocumentFragment();
    children.forEach(function (item) {
      frag.appendChild(buildRow(item, depth, false));
    });
    // 标记归属（在插入后设置，便于收起时识别子树范围）
    Array.from(frag.childNodes).forEach(function (tr) { tr.dataset.parent = parentTr.dataset.name; });
    parentTr.after(frag);
    // 缓存子数据以便收起后重新插入（不重新请求）
    parentTr.dataset.children = JSON.stringify(children);
  }

  function removeChildGroup(parentTr) {
    // 移除紧随父行之后、归属于该父行的连续子行。子行展开产生的更深层行
    // 都以「下一层父行」为 dataset.parent，需递归移除整段子树。
    const stopAt = parentTr.dataset.name;
    let node = parentTr.nextElementSibling;
    // 先收集需要移除的节点范围：从 parentTr 之后，直到遇到不属于本子树的兄弟。
    // 由于子行用 dataset.parent 链接到各自直接父，直接按「parent == stopAt」或
    // 「parent 指向本子树内任一节点」递归移除整段。
    const toRemove = [];
    let cursor = node;
    // 借助一个栈标记子树内的所有父名
    const subtreeParents = new Set([stopAt]);
    while (cursor && cursor.dataset && cursor.dataset.parent) {
      if (subtreeParents.has(cursor.dataset.parent)) {
        toRemove.push(cursor);
        subtreeParents.add(cursor.dataset.name);
      } else {
        break; // 遇到不属于本子树的兄弟，停止
      }
      cursor = cursor.nextElementSibling;
    }
    toRemove.forEach(function (n) { n.remove(); });
  }

  function rowInner(item, depth, isExpanded) {
    const attrTds = attributeColumns.map(function (a) { return attributeValueCell(a); }).join('');
    return nameCell(item, depth, isExpanded) +
      '<td class="dim-grid-type">' + typeLabel(item.type) + '</td>' +
      weightCell(item) + attrTds;
  }

  // 构建一行：直接在 tr 元素上设置 class/dataset，innerHTML 只放单元格。
  // （不能把 <tr> 字符串塞进 tr.innerHTML——嵌套 tr 会被 HTML 解析器丢弃。）
  function buildRow(item, depth, isExpanded) {
    const tr = document.createElement('tr');
    tr.className = 'dim-grid-row';
    tr.dataset.name = item.name;
    tr.dataset.depth = depth;
    tr.setAttribute('role', 'treeitem');
    tr.setAttribute('aria-expanded', item.has_children ? String(isExpanded) : 'false');
    tr.innerHTML = rowInner(item, depth, isExpanded);
    fillAttributeCells(tr, item.name);
    return tr;
  }

  function renderTree() {
    const container = document.getElementById('dimension-tree-body');
    if (!summary.roots.length) {
      container.innerHTML = '<p class="muted">当前数据没有可展示的元素。</p>';
      return;
    }
    container.innerHTML = '';
    const table = document.createElement('table');
    table.className = 'dim-grid';
    // 表头：名称 / 类型 / 权重 + 属性值列（仅选中时显示）
    let header = '<thead><tr><th class="dim-grid-name">元素名称</th><th class="dim-grid-type">类型</th><th class="dim-grid-weight">父子权重</th>';
    attributeColumns.forEach(function (a) {
      header += '<th class="dim-grid-attr">' + escapeHtml(a) + '</th>';
    });
    header += '</tr></thead>';
    table.innerHTML = header + '<tbody></tbody>';
    container.appendChild(table);
    const tbody = table.querySelector('tbody');
    renderRows(tbody, summary.roots, 0);
  }

  // 大型扁平维度：分页有界渲染
  const FLAT_PAGE_SIZE = 200;
  let flatItems = [];
  let flatShown = 0;
  let flatTbody = null;

  function renderFlat(container) {
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
    const table = document.createElement('table');
    table.className = 'dim-grid';
    let header = '<thead><tr><th class="dim-grid-name">元素名称</th><th class="dim-grid-type">类型</th><th class="dim-grid-weight">父子权重</th>';
    attributeColumns.forEach(function (a) { header += '<th class="dim-grid-attr">' + escapeHtml(a) + '</th>'; });
    header += '</tr></thead><tbody></tbody>';
    table.innerHTML = header;
    container.appendChild(table);
    flatTbody = table.querySelector('tbody');
    renderFlatPage();
  }

  function renderFlatPage() {
    if (!flatTbody) return;
    const batch = flatItems.slice(flatShown, flatShown + FLAT_PAGE_SIZE);
    const frag = document.createDocumentFragment();
    batch.forEach(function (item) {
      const tr = document.createElement('tr');
      tr.className = 'dim-grid-row';
      tr.dataset.name = item.name;
      tr.innerHTML = '<td class="dim-grid-name"><span class="dim-grid-indent">&nbsp;</span><span class="dim-tree-toggle leaf" aria-hidden="true"></span><button class="dim-tree-name" type="button" data-name="' + escapeHtml(item.name) + '">' + escapeHtml(item.name) + '</button></td>' +
        '<td class="dim-grid-type">' + typeLabel(item.type) + '</td>' +
        '<td class="dim-grid-weight dim-grid-unknown">—</td>' +
        attributeColumns.map(function () { return '<td class="dim-grid-attr dim-grid-unknown">—</td>'; }).join('');
      fillAttributeCells(tr, item.name);
      frag.appendChild(tr);
    });
    flatTbody.appendChild(frag);
    flatShown += batch.length;
    const more = document.getElementById('dim-flat-more');
    if (more) {
      const remaining = flatItems.length - flatShown;
      more.hidden = remaining <= 0;
      if (remaining > 0) more.textContent = '加载更多（剩余 ' + remaining + '）';
    }
  }

  async function init() {
    loadAttributeColumns();
    setStatus('正在加载维度结构…');
    try {
      summary = await api('/api/dimensions/' + encodeURIComponent(dimName) +
        '/tree?source=' + encodeURIComponent(source));
      setStatus('');
      renderMeta();
      renderSideInfo(summary);
      const container = document.getElementById('dimension-tree-body');
      if (summary.has_hierarchy) {
        renderTree();
      } else {
        renderFlat(container);
      }
    } catch (error) {
      setStatus(error.message, true);
      const container = document.getElementById('dimension-tree-body');
      if (container) container.innerHTML = '<p class="chore-warning">' + escapeHtml(error.message) + '</p>';
    }
  }

  function renderMeta() {
    const metaEl = document.getElementById('dimension-meta');
    if (metaEl) {
      const total = summary.element_count != null ? summary.element_count : summary.recorded_elements;
      const hierarchyNote = summary.large_dimension
        ? '规模过大，仅展示部分元素'
        : (summary.has_hierarchy ? '包含层级关系' : '未包含完整层级关系（扁平成员）');
      const hcount = summary.hierarchy_names && summary.hierarchy_names.length
        ? ' · 层级 ' + summary.hierarchy_names.length : '';
      metaEl.textContent = '元素总数 ' + total + ' · ' + hierarchyNote +
        ' · 属性 ' + summary.attributes.length + ' · 子集 ' + summary.subsets.length + hcount;
    }
  }

  function renderSideInfo(s) {
    // 顶部工作区：属性定义 / 层级计数 + 显示列选择 + 子集面板
    const attrEl = document.getElementById('dimension-attributes');
    if (attrEl) {
      attrEl.innerHTML = s.attributes.length
        ? s.attributes.map(function (a) {
          return '<span class="dim-attr" title="属性定义（' + escapeHtml(a.type || '') + '）">' + escapeHtml(a.name || 'UNKNOWN') + '</span>';
        }).join('')
        : '<span class="muted">无属性定义</span>';
    }
    const subCountEl = document.getElementById('dim-subset-tab-count');
    if (subCountEl) subCountEl.textContent = s.subsets.length;
    renderAttributeColumnPicker(s);
    renderSubsetPanel(s);
  }

  // 「显示列」：选择要展示属性值的属性（只有已采集值的属性可被选中）
  function renderAttributeColumnPicker(s) {
    const picker = document.getElementById('dimension-attr-columns');
    if (!picker) return;
    const collectedAttrs = Object.keys((s.attribute_values || {}).attributes || {});
    if (!s.attributes.length) {
      picker.innerHTML = '<span class="muted small">无属性定义</span>';
      return;
    }
    const opts = s.attributes.map(function (a) {
      const hasValues = collectedAttrs.indexOf(a.name) >= 0;
      const checked = attributeColumns.indexOf(a.name) >= 0 ? ' checked' : '';
      const disabled = hasValues ? '' : ' disabled';
      const title = hasValues ? '显示 ' + escapeHtml(a.name) + ' 列' : '未采集 ' + escapeHtml(a.name) + ' 的属性值，无法显示';
      return '<label class="dim-attr-col" title="' + title + '"><input type="checkbox" data-attr="' + escapeHtml(a.name) + '"' + checked + disabled + '> ' + escapeHtml(a.name || 'UNKNOWN') + (hasValues ? '' : ' <em class="muted">未采集</em>') + '</label>';
    }).join('');
    picker.innerHTML = opts;
    if (!collectedAttrs.length) {
      picker.insertAdjacentHTML('beforeend', '<span class="muted small">（当前未采集任何属性值，无法显示列）</span>');
    }
    picker.querySelectorAll('input[type=checkbox]').forEach(function (cb) {
      cb.addEventListener('change', function () {
        const name = cb.dataset.attr;
        if (cb.checked) {
          if (attributeColumns.indexOf(name) < 0) attributeColumns.push(name);
        } else {
          attributeColumns = attributeColumns.filter(function (x) { return x !== name; });
        }
        saveAttributeColumns();
        // 重新渲染树（保留展开状态）
        rerenderTree();
      });
    });
  }

  function rerenderTree() {
    if (!summary) return;
    const container = document.getElementById('dimension-tree-body');
    if (summary.has_hierarchy) {
      renderTree();
      // 恢复已展开节点
      const toExpand = Array.from(expanded);
      expanded.clear();
      toExpand.forEach(function (path) {
        const name = path.split('/').pop();
        const tr = container.querySelector('tr.dim-grid-row[data-name="' + CSS.escape(name) + '"]');
        if (tr && tr.querySelector('.dim-tree-toggle:not(.leaf)')) {
          toggle(name, tr);
        }
      });
    } else {
      flatShown = 0;
      container.innerHTML = '';
      renderFlat(container);
    }
  }

  // Subset 面板：列表 + 搜索 + 静态/动态类型 + MDX 原文 + 采集状态
  function renderSubsetPanel(s) {
    const panel = document.getElementById('dimension-subset-panel');
    if (!panel) return;
    const defs = s.subset_definitions || [];
    if (!defs.length) {
      panel.innerHTML = '<p class="muted small">未采集子集定义（可通过增量补采获取）。</p>';
      return;
    }
    const search = document.getElementById('dimension-subset-search');
    const listEl = document.getElementById('dimension-subset-list');
    const detailEl = document.getElementById('dimension-subset-detail');
    function filterList() {
      const kw = search ? search.value.trim().toLowerCase() : '';
      const filtered = defs.filter(function (d) { return !kw || (d.name || '').toLowerCase().indexOf(kw) >= 0; });
      listEl.innerHTML = filtered.map(function (d) {
        const typeTag = d.type === 'dynamic' ? '<span class="dim-subset-type dynamic">动态</span>'
          : d.type === 'static' ? '<span class="dim-subset-type static">静态</span>'
          : '<span class="dim-subset-type unknown">未知</span>';
        const statusTag = d.status === 'collected' ? '' : ' <span class="dim-subset-status ' + escapeHtml(d.status) + '">' + escapeHtml(d.status) + '</span>';
        return '<li><button class="dim-subset-item" type="button" data-name="' + escapeHtml(d.name) + '">' + escapeHtml(d.name) + typeTag + statusTag + '</button></li>';
      }).join('') || '<li class="muted">没有匹配的子集。</li>';
      listEl.querySelectorAll('.dim-subset-item').forEach(function (btn) {
        btn.addEventListener('click', function () { showSubsetDetail(btn.dataset.name); });
      });
    }
    if (search) search.addEventListener('input', filterList);
    filterList();

    function showSubsetDetail(name) {
      const d = defs.find(function (x) { return x.name === name; });
      if (!d) return;
      let html = '<h4>' + escapeHtml(d.name) + '</h4>';
      html += '<p class="muted small">所属层级：' + escapeHtml(d.hierarchy || '—') + ' · 类型：' +
        (d.type === 'dynamic' ? '动态 MDX' : d.type === 'static' ? '静态' : '未知') +
        ' · 状态：' + escapeHtml(d.status || '—') + '</p>';
      if (d.type === 'dynamic' && d.expression) {
        html += '<p class="muted small">MDX 表达式（未求值）：</p><pre class="code dimension-expression">' + escapeHtml(d.expression) + '</pre>';
      } else if (d.type === 'static' && d.elements && d.elements.length) {
        html += '<p class="muted small">静态成员（' + d.elements.length + ' 个，按序）：</p>';
        html += '<div class="dim-subset-elements">' + d.elements.map(function (e) { return '<span class="dim-subset-element">' + escapeHtml(e) + '</span>'; }).join('') + '</div>';
      } else if (d.status === 'unavailable') {
        html += '<p class="chore-warning">该子集定义采集失败（可能权限受限或已删除），未保存成员或表达式。</p>';
      } else {
        html += '<p class="muted small">未采集成员或表达式。</p>';
      }
      detailEl.innerHTML = html;
    }
    // 默认选中第一个
    if (defs.length) showSubsetDetail(defs[0].name);
  }

  // 点击事件委托：展开/收起 + 元素名查看详情
  const body = document.getElementById('dimension-tree-body');
  body.addEventListener('click', async function (event) {
    const arrow = event.target.closest('.dim-tree-toggle');
    if (arrow && !arrow.classList.contains('leaf')) {
      const tr = arrow.closest('tr.dim-grid-row');
      const name = tr.dataset.name;
      await toggle(name, tr);
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
      const tr = body.querySelector('tr.dim-grid-row[data-name="' + CSS.escape(name) + '"]');
      if (tr) {
        expanded.delete(nodePath(tr));
        await toggle(name, tr);
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
        if (match.paths && match.paths.length) {
          parents.textContent = match.paths.map(function (p) { return p.join(' › ') + ' › ' + name; }).join('；');
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

  // 搜索：覆盖整个维度
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
              escapeHtml(m.name) + typeLabel(m.type) + '</button>' +
              (ancestorText ? '<span class="muted small dim-search-ancestors">祖先路径：' + escapeHtml(ancestorText) + '</span>' : '');
            li.querySelector('.dim-search-hit').addEventListener('click', function () {
              showElementDetail(m.name);
            });
            ul.appendChild(li);
          });
          results.innerHTML = '';
          results.appendChild(ul);
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

  // 扁平列表「加载更多」
  const flatMore = document.getElementById('dim-flat-more');
  if (flatMore) {
    flatMore.addEventListener('click', function () { renderFlatPage(); });
  }

  init();
})();
