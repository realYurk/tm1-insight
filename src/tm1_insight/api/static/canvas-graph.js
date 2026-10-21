/* TM1 Insight — 架构画布
 *
 * 以 Cube 图标为节点、TI / Rule 为连线的最小实现。
 * 底层用 Cytoscape.js（离线 vendored）；本文件只负责「TM1 语义 → 视觉」的映射与交互，
 * 不改变任何事实语义：候选共同读写永远是虚线并带「值流待核对」提示。
 */
(function () {
  'use strict';

  const CUBE_BLUE = { top: '#8fbbe8', left: '#4a86c8', right: '#2f6ba8', stroke: '#2f6ba8' };
  const CUBE_AMBER = { top: '#f7d9a0', left: '#dfa64a', right: '#b8801f', stroke: '#b8801f' };
  const CUBE_GRAY = { top: '#dbe3ec', left: '#b3c0cf', right: '#8d9cae', stroke: '#8d9cae' };

  function cubeSvg(c) {
    return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'>"
      + "<polygon points='24,6 42,16 24,26 6,16' fill='" + c.top + "' stroke='" + c.stroke + "' stroke-width='1.2'/>"
      + "<polygon points='6,16 24,26 24,44 6,34' fill='" + c.left + "' stroke='" + c.stroke + "' stroke-width='1.2'/>"
      + "<polygon points='42,16 24,26 24,44 42,34' fill='" + c.right + "' stroke='" + c.stroke + "' stroke-width='1.2'/>"
      + "</svg>";
  }

  function fileSvg() {
    return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'>"
      + "<path d='M12 5h16l9 9v29a2 2 0 0 1-2 2H12a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z' fill='#efe9ff' stroke='#8b7bd8' stroke-width='1.6'/>"
      + "<path d='M28 5v9h9' fill='none' stroke='#8b7bd8' stroke-width='1.6'/>"
      + "<path d='M16 27h16M16 33h16M16 21h8' stroke='#8b7bd8' stroke-width='1.6'/>"
      + "</svg>";
  }

  function stackSvg() {
    return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'>"
      + "<rect x='6' y='20' width='30' height='20' rx='3' fill='#e2e8f0' stroke='#64748b' stroke-width='1.4'/>"
      + "<rect x='12' y='12' width='30' height='20' rx='3' fill='#f1f5f9' stroke='#64748b' stroke-width='1.4'/>"
      + "<rect x='18' y='4' width='24' height='16' rx='3' fill='#fff' stroke='#64748b' stroke-width='1.4'/>"
      + "</svg>";
  }

  function dataUri(svg) {
    return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
  }

  const ICON = {
    cube: dataUri(cubeSvg(CUBE_BLUE)),
    draft: dataUri(cubeSvg(CUBE_AMBER)),
    group: dataUri(stackSvg()),
    source: dataUri(fileSvg()),
    muted: dataUri(cubeSvg(CUBE_GRAY)),
  };

  const TYPE_LABEL = {
    cube: 'Cube', process: 'TI', chore: '调度', dimension: '维度',
    draft: 'Cube 草稿 · 未部署', source: '数据来源 · 未接入', group: '人工模块',
  };

  const EDGE_STYLE = {
    TI_CANDIDATE: { line: 'dashed', color: '#64748b', arrow: 'vee', cls: 'ei-candidate' },
    RULE_REFERENCE: { line: 'solid', color: '#2563eb', arrow: 'tee', cls: 'ei-rule' },
    FEEDER_REFERENCE: { line: 'dotted', color: '#94a3b8', arrow: 'none', cls: 'ei-feeder' },
    DESIGN_RELATION: { line: 'dashed', color: '#b45309', arrow: 'triangle', cls: 'ei-design' },
    TI_READ: { line: 'solid', color: '#94a3b8', arrow: 'vee', cls: 'ei-raw' },
    TI_WRITE: { line: 'solid', color: '#94a3b8', arrow: 'vee', cls: 'ei-raw' },
    CALL: { line: 'dotted', color: '#cbd5e1', arrow: 'vee', cls: 'ei-raw' },
    SCHEDULE: { line: 'dotted', color: '#cbd5e1', arrow: 'vee', cls: 'ei-raw' },
    STRUCTURE: { line: 'dotted', color: '#e2e8f0', arrow: 'none', cls: 'ei-raw' },
  };

  function styleSheet() {
    const base = [
      {
        selector: 'node',
        style: {
          shape: 'ellipse',
          width: 58,
          height: 58,
          'background-color': '#ffffff',
          'background-opacity': 0.001,
          'background-fit': 'contain',
          'background-clip': 'none',
          'border-width': 0,
          'border-color': '#2563eb',
          label: 'data(short)',
          'font-size': 10.5,
          'font-family': 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
          color: '#334155',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 8,
          'text-wrap': 'wrap',
          'text-max-width': '104px',
          'overlay-opacity': 0,
          'transition-property': 'border-width, border-color',
          'transition-duration': '90ms',
        },
      },
      { selector: 'node[type="cube"]', style: { 'background-image': ICON.cube } },
      { selector: 'node[type="draft"]', style: { 'background-image': ICON.draft, color: '#92400e' } },
      { selector: 'node[type="source"]', style: { 'background-image': ICON.source, color: '#5b21b6' } },
      { selector: 'node[type="group"]', style: { 'background-image': ICON.group, color: '#475569', 'font-weight': 'bold' } },
      { selector: 'node[type="process"]', style: { 'background-image': ICON.muted, color: '#475569' } },
      { selector: 'node[type="chore"], node[type="dimension"]', style: { 'background-image': ICON.muted } },
      { selector: 'node.cn-hover', style: { 'border-width': 2, 'border-color': '#bfdbfe' } },
      { selector: 'node.cn-selected', style: { 'border-width': 2, 'border-color': '#2563eb' } },
      {
        selector: 'edge',
        style: {
          width: 1.8,
          'curve-style': 'unbundled-bezier',
          'control-point-step-size': 34,
          'control-point-weights': 0.5,
          'control-point-distances': 'data(cpd)',
          'loop-direction': '-45deg',
          'loop-sweep': '70deg',
          'target-arrow-shape': 'data(arrow)',
          'target-arrow-color': 'data(color)',
          'arrow-scale': 0.85,
          'line-color': 'data(color)',
          'line-style': 'data(lineStyle)',
          label: 'data(label)',
          'font-size': 10.5,
          'font-weight': 600,
          'font-family': 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
          color: '#475569',
          'text-rotation': 'autorotate',
          'text-background-color': '#ffffff',
          'text-background-opacity': 0.82,
          'text-background-padding': '3px',
          'text-max-width': '140px',
          'text-margin-y': -2,
          'overlay-padding': 9,
          'overlay-opacity': 0,
          'transition-property': 'line-color, width',
          'transition-duration': '90ms',
        },
      },
      { selector: 'edge.cn-hover', style: { width: 2.8 } },
      { selector: 'edge.cn-selected', style: { width: 3, 'line-color': '#1d4ed8', 'target-arrow-color': '#1d4ed8' } },
      { selector: 'edge[status="CANDIDATE"]', style: { 'line-style': 'dashed' } },
      { selector: 'edge.cn-dim', style: { opacity: 0.25 } },
    ];
    return base;
  }

  function shortName(name, max) {
    const text = String(name == null ? '' : name);
    if (text.length <= max) return text;
    return text.slice(0, max - 1) + '…';
  }

  function edgeLabel(edge) {
    const kind = edge.kind;
    if (kind === 'TI_CANDIDATE') {
      const names = edge.processNames || edge.process_names || [];
      // 单条关系不写标签：hub 周围十几个「TI」会糊成一团，
      // 具体 Process 名在悬停提示与右侧详情里。
      return names.length > 1 ? names.length + ' TI' : '';
    }
    if (kind === 'RULE_REFERENCE') return 'Rule';
    if (kind === 'FEEDER_REFERENCE') return 'Feeder（非值流）';
    if (kind === 'DESIGN_RELATION') {
      return edge.generated ? (edge.generated.status === 'STALE' ? 'TI Draft · 已过期' : 'TI Draft ✓') : '设计 · 未部署';
    }
    if (kind === 'TI_READ') return '读';
    if (kind === 'TI_WRITE') return '写';
    return shortName(edge.label || kind, 12);
  }

  function mount(container, options) {
    const opt = options || {};
    let cy = null;
    let elementsIndex = new Map();
    let positionsCache = {};
    let hoverNode = null;
    let lastTapAt = 0;
    let lastTapId = '';

    container.classList.add('cn-canvas');
    container.replaceChildren();

    // 拖线覆盖层（pointer-events: none，只有锚点可点）
    const overlay = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    overlay.setAttribute('class', 'cn-overlay');
    const connectLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    connectLine.setAttribute('class', 'cn-connect-line');
    connectLine.style.display = 'none';
    overlay.appendChild(connectLine);

    const tip = document.createElement('div');
    tip.className = 'cn-tip';
    tip.hidden = true;

    const anchor = document.createElement('button');
    anchor.type = 'button';
    anchor.className = 'cn-anchor';
    anchor.title = '从这里拖到另一个对象，建立设计关系';
    anchor.textContent = '+';
    anchor.hidden = true;

    const marquee = document.createElement('div');
    marquee.className = 'cn-marquee';
    marquee.hidden = true;

    container.appendChild(tip);
    container.appendChild(marquee);
    container.appendChild(overlay);
    container.appendChild(anchor);

    let drag = null;
    let box = null;

    function modelPos(evt) {
      const rect = container.getBoundingClientRect();
      return { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
    }

    function nodeAtPoint(point) {
      let hit = null;
      cy.nodes().forEach(function (n) {
        if (n.hidden() || n.data('type') === 'group') return;
        const b = n.renderedBoundingBox({ includeLabels: false, includeOverlays: false });
        if (point.x >= b.x1 && point.x <= b.x2 && point.y >= b.y1 && point.y <= b.y2) hit = n;
      });
      return hit;
    }

    function showAnchor(node) {
      if (!opt.connectable || !node) { anchor.hidden = true; return; }
      const b = node.renderedBoundingBox({ includeLabels: false });
      anchor.style.left = (b.x2 - 2) + 'px';
      anchor.style.top = ((b.y1 + b.y2) / 2 - 11) + 'px';
      anchor.hidden = false;
      anchor.dataset.source = node.id();
      anchor.style.display = opt.connectable(node.data('type')) ? '' : 'none';
    }

    function startConnect(evt) {
      if (anchor.hidden) return;
      const node = cy.getElementById(anchor.dataset.source);
      if (!node || node.empty()) return;
      evt.preventDefault();
      evt.stopPropagation();
      const b = node.renderedBoundingBox({ includeLabels: false });
      drag = { source: node.id(), from: { x: (b.x1 + b.x2) / 2, y: (b.y1 + b.y2) / 2 } };
      connectLine.style.display = '';
      window.addEventListener('mousemove', moveConnect, true);
      window.addEventListener('mouseup', endConnect, true);
    }

    function moveConnect(evt) {
      if (!drag) return;
      const p = modelPos(evt);
      const mid = { x: (drag.from.x + p.x) / 2, y: Math.min(drag.from.y, p.y) - 40 };
      connectLine.setAttribute('d', 'M' + drag.from.x + ',' + drag.from.y
        + ' Q' + mid.x + ',' + mid.y + ' ' + p.x + ',' + p.y);
    }

    function endConnect(evt) {
      window.removeEventListener('mousemove', moveConnect, true);
      window.removeEventListener('mouseup', endConnect, true);
      connectLine.style.display = 'none';
      const p = modelPos(evt);
      const target = nodeAtPoint(p);
      const source = drag && drag.source;
      drag = null;
      if (!source || !target || target.id() === source) return;
      if (opt.onConnect) opt.onConnect(source, target.id());
    }

    anchor.addEventListener('mousedown', startConnect);

    function initCy() {
      cy = cytoscape({
        container: container,
        elements: [],
        style: styleSheet(),
        layout: { name: 'preset' },
        wheelSensitivity: 0.18,
        minZoom: 0.12,
        maxZoom: 3,
        boxSelectionEnabled: false,
        selectionType: 'additive',
        autounselectify: true,
        pixelRatio: 'auto',
      });

      cy.on('tap', 'node', function (evt) {
        const node = evt.target;
        const now = Date.now();
        const id = node.id();
        const isDouble = now - lastTapAt < 320 && lastTapId === id;
        lastTapAt = now; lastTapId = id;
        const oe = evt.originalEvent || {};
        if (isDouble) { if (opt.onNodeDblClick) opt.onNodeDblClick(id); return; }
        if (opt.onNodeClick) opt.onNodeClick(id, { ctrl: !!(oe.ctrlKey || oe.metaKey) });
      });

      cy.on('tap', 'edge', function (evt) {
        if (opt.onEdgeClick) opt.onEdgeClick(evt.target.id());
      });

      cy.on('tap', function (evt) {
        if (evt.target === cy && opt.onBackgroundClick) opt.onBackgroundClick();
      });

      cy.on('cxttap', 'node', function (evt) {
        const oe = evt.originalEvent || {};
        if (opt.onContextMenu) { oe.preventDefault && oe.preventDefault(); opt.onContextMenu(evt.target.id(), oe.clientX || 0, oe.clientY || 0); }
      });

      cy.on('mouseover', 'node', function (evt) {
        const node = evt.target;
        hoverNode = node.id();
        node.addClass('cn-hover');
        const rect = container.getBoundingClientRect();
        const rp = node.renderedPosition();
        const deg = node.connectedEdges().length;
        tip.textContent = node.data('fullName')
          + (TYPE_LABEL[node.data('type')] ? '  ·  ' + TYPE_LABEL[node.data('type')] : '')
          + (deg ? '  ·  ' + deg + ' 条关系' : '');
        tip.style.left = Math.max(6, Math.min(rp.x - 10, rect.width - 240)) + 'px';
        tip.style.top = Math.max(6, rp.y - 46) + 'px';
        tip.hidden = false;
        if (anchor.dataset.source === hoverNode) showAnchor(node);
      });

      cy.on('mouseout', 'node', function (evt) {
        evt.target.removeClass('cn-hover');
        hoverNode = null;
        tip.hidden = true;
      });

      cy.on('mouseover', 'edge', function (evt) {
        evt.target.addClass('cn-hover');
        const rect = container.getBoundingClientRect();
        const mp = evt.target.midpoint();
        const rp = evt.target.renderedMidpoint ? evt.target.renderedMidpoint() : mp;
        tip.textContent = evt.target.data('hint') || '';
        tip.style.left = Math.max(6, Math.min(rp.x - 10, rect.width - 300)) + 'px';
        tip.style.top = Math.max(6, rp.y - 40) + 'px';
        tip.hidden = !tip.textContent;
      });

      cy.on('mouseout', 'edge', function (evt) { evt.target.removeClass('cn-hover'); tip.hidden = true; });

      cy.on('dragfree', 'node', function (evt) {
        if (evt.target.data('type') === 'group') return;
        positionsCache[evt.target.id()] = evt.target.position();
        if (opt.onNodeMoved) opt.onNodeMoved(evt.target.id(), evt.target.position());
      });

      // 指针移到锚点自身时 Cytoscape 仍会收到 mousemove：此时不能把锚点隐藏，
      // 否则紧接着的 mousedown 落空，拖线就永远起不来。
      cy.on('mousemove', function (evt) {
        if (drag) return;
        if (!opt.connectable) { anchor.hidden = true; return; }
        const node = evt.target && evt.target.isNode && evt.target.isNode() ? evt.target : null;
        if (node) showAnchor(node);
      });

      container.addEventListener('mouseleave', function () { if (!drag) anchor.hidden = true; });

      cy.on('pan zoom', function () { if (!anchor.hidden && hoverNode) showAnchor(cy.getElementById(hoverNode)); });
    }

    function stopBox(evt) {
      box = null;
      marquee.hidden = true;
      window.removeEventListener('mousemove', moveBox, true);
      window.removeEventListener('mouseup', stopBox, true);
      const rect = container.getBoundingClientRect();
      const x1 = evt.clientX - rect.left, y1 = evt.clientY - rect.top;
      const ids = [];
      cy.nodes().forEach(function (n) {
        if (n.hidden() || n.data('type') === 'group') return;
        const p = n.renderedPosition();
        if (p.x >= Math.min(boxStart.x, x1) && p.x <= Math.max(boxStart.x, x1)
          && p.y >= Math.min(boxStart.y, y1) && p.y <= Math.max(boxStart.y, y1)) ids.push(n.id());
      });
      if (opt.onBoxSelect) opt.onBoxSelect(ids);
    }

    let boxStart = { x: 0, y: 0 };

    function moveBox(evt) {
      if (!box) return;
      const p = modelPos(evt);
      marquee.style.left = Math.min(boxStart.x, p.x) + 'px';
      marquee.style.top = Math.min(boxStart.y, p.y) + 'px';
      marquee.style.width = Math.abs(p.x - boxStart.x) + 'px';
      marquee.style.height = Math.abs(p.y - boxStart.y) + 'px';
    }

    container.addEventListener('mousedown', function (evt) {
      if (!cy || evt.button !== 0 || !evt.shiftKey) return;
      const node = evt.target.closest && evt.target.closest('.cn-anchor');
      if (node) return;
      box = true;
      boxStart = modelPos(evt);
      marquee.style.left = boxStart.x + 'px';
      marquee.style.top = boxStart.y + 'px';
      marquee.style.width = '0px';
      marquee.style.height = '0px';
      marquee.hidden = false;
      // 必须阻止事件继续传到 Cytoscape，否则框选的同时画布还会被平移
      evt.preventDefault();
      evt.stopPropagation();
      window.addEventListener('mousemove', moveBox, true);
      window.addEventListener('mouseup', stopBox, true);
    }, true);

    initCy();
    // 容器尺寸会随侧栏 / 详情开合变化；Cytoscape 必须收到 resize，
    // 否则视野与元素坐标会停留在初始化那一刻的尺寸上（节点跑到可视区外）。
    let observer = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(function () { if (cy) cy.resize(); });
      observer.observe(container);
    }
    window.requestAnimationFrame(function () { if (cy) cy.resize(); });

    const api = {
      cy: function () { return cy; },

      setGraph: function (payload) {
        const nodes = (payload.nodes || []).map(function (n) {
          const type = n.type || 'cube';
          return {
            group: 'nodes',
            data: {
              id: n.id,
              name: n.name,
              fullName: n.name,
              short: shortName(n.name, type === 'source' ? 22 : 18),
              type: type,
              provenance: n.provenance || '',
            },
          };
        });
        const nodeIds = new Set(nodes.map(function (n) { return n.data.id; }));
        const edges = (payload.edges || []).filter(function (e) {
          return nodeIds.has(e.source) && nodeIds.has(e.target);
        }).map(function (e) {
          const s = EDGE_STYLE[e.kind] || EDGE_STYLE.TI_READ;
          return {
            group: 'edges',
            data: {
              id: e.id,
              source: e.source,
              target: e.target,
              kind: e.kind,
              status: e.status || '',
              label: edgeLabel(e),
              hint: e.hint || '',
              color: s.color,
              lineStyle: s.line,
              arrow: s.arrow,
            },
            classes: s.cls,
          };
        });
        // 同一对端点之间的多条关系必须分开画，否则重叠到无法点击
        const pairCount = {};
        edges.forEach(function (e) { const k = e.data.source + '|' + e.data.target; (pairCount[k] = pairCount[k] || []).push(e); });
        Object.keys(pairCount).forEach(function (k) {
          const list = pairCount[k];
          const n = list.length;
          list.forEach(function (e, i) { e.data.cpd = n === 1 ? 0 : (i - (n - 1) / 2) * 36; });
        });
        elementsIndex = new Map((payload.edges || []).map(function (e) { return [e.id, e]; }));

        const preset = payload.positions || {};
        const hasPreset = Object.keys(preset).length > 0;
        if (hasPreset) {
          let maxX = -Infinity, maxY = -Infinity, minX = Infinity;
          nodes.forEach(function (n) {
            const p = preset[n.data.id];
            if (!p) return;
            n.position = { x: p.x, y: p.y };
            maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y); minX = Math.min(minX, p.x);
          });
          // 新增节点没有历史坐标：排在已有节点右侧一行，避免全部叠在原点
          let slot = 0;
          const baseX = Number.isFinite(minX) ? minX : 0;
          const baseY = Number.isFinite(maxY) ? maxY + 130 : 0;
          nodes.forEach(function (n) {
            if (n.position) return;
            n.position = { x: (Number.isFinite(maxX) ? maxX + 150 : baseX) + slot * 130, y: baseY };
            slot += 1;
          });
        }

        cy.elements().remove();
        cy.add(nodes.concat(edges));
        cy.style(styleSheet());

        if (hasPreset) {
          cy.layout({ name: 'preset', fit: false, padding: 30 }).run();
          if (payload.view) api.applyView(payload.view);
          if (payload.fit) api.fit();
        } else if (nodes.length) {
          api.layout(payload.layout || 'breadthfirst');
        }
        positionsCache = api.getPositions();
      },

      layout: function (name) {
        if (!cy || !cy.nodes().length) return;
        const visible = cy.nodes(':visible');
        if (name === 'grid') {
          cy.layout({ name: 'grid', padding: 40, avoidOverlap: true, condense: true }).run();
        } else {
          // breadthfirst：入口（无入边）在左，逐层向右；对 Cube 主干最易读
          const indeg = {};
          cy.edges().forEach(function (e) {
            const t = e.target().id();
            indeg[t] = (indeg[t] || 0) + 1;
          });
          const roots = visible.filter(function (n) { return !indeg[n.id()] && !n.data('type').match(/group|process/); });
          cy.layout({
            name: 'breadthfirst',
            directed: true,
            padding: 40,
            spacingFactor: 1.15,
            avoidOverlap: true,
            grid: true,
            roots: roots.length ? roots : undefined,
          }).run();
        }
        positionsCache = api.getPositions();
        if (opt.onLayout) opt.onLayout(positionsCache);
      },

      applyView: function (view) {
        if (!cy || !view) return;
        if (view.zoom) cy.zoom(view.zoom);
        if (typeof view.x === 'number' && typeof view.y === 'number') {
          cy.pan({ x: view.x, y: view.y });
        } else if (view.pan && typeof view.pan === 'object') {
          cy.pan(view.pan);  // 兼容旧工作区
        }
      },

      getView: function () {
        if (!cy) return {};
        const p = cy.pan(), z = cy.zoom();
        // Workspace.layout 只接受 {zoom,x,y,vertical} 四个数值键
        return { zoom: Number(z.toFixed(3)), x: Math.round(p.x), y: Math.round(p.y) };
      },

      getPositions: function () {
        const out = {};
        if (!cy) return out;
        cy.nodes().forEach(function (n) {
          if (n.data('type') === 'group') return;
          const p = n.position();
          out[n.id()] = { x: Math.round(p.x), y: Math.round(p.y) };
        });
        return out;
      },

      select: function (ids, edgeId) {
        if (!cy) return;
        cy.batch(function () {
          cy.elements().removeClass('cn-selected');
          (ids || []).forEach(function (id) {
            const n = cy.getElementById(id);
            if (n && n.length) n.addClass('cn-selected');
          });
          if (edgeId) {
            const e = cy.getElementById(edgeId);
            if (e && e.length) e.addClass('cn-selected');
          }
        });
      },

      fit: function () {
        if (!cy || !cy.elements().length) return;
        cy.fit(cy.elements(), 46);
        if (cy.zoom() > 1.15) {
          cy.zoom({ level: 1.15, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
          cy.center(cy.elements());
        }
      },

      focus: function (id) {
        if (!cy) return;
        const n = cy.getElementById(id);
        if (n && n.length) cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 0.9) }, { duration: 220 });
      },

      zoomBy: function (factor) {
        if (!cy) return;
        cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
      },

      centerModel: function () {
        if (!cy) return { x: 0, y: 0 };
        const ext = cy.extent();
        return { x: (ext.x1 + ext.x2) / 2, y: (ext.y1 + ext.y2) / 2 };
      },

      placeAtCenter: function (id) {
        if (!cy) return null;
        const ext = cy.extent();
        return { x: (ext.x1 + ext.x2) / 2, y: (ext.y1 + ext.y2) / 2 };
      },

      resize: function () { if (cy) cy.resize(); },
      destroy: function () {
        window.removeEventListener('mousemove', moveConnect, true);
        window.removeEventListener('mouseup', endConnect, true);
        window.removeEventListener('mousemove', moveBox, true);
        window.removeEventListener('mouseup', stopBox, true);
        if (observer) { observer.disconnect(); observer = null; }
        if (cy) { cy.destroy(); cy = null; }
        container.replaceChildren();
      },
    };

    window.addEventListener('resize', api.resize);
    return api;
  }

  window.TM1Canvas = { mount: mount, icons: ICON, TYPE_LABEL: TYPE_LABEL };
})();
