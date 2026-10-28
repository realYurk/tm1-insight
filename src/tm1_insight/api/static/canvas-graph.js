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
    return "<svg xmlns='http://www.w3.org/2000/svg' width='192' height='192' viewBox='0 0 48 48'>"
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
    process: dataUri("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'><rect x='5' y='9' width='38' height='30' rx='7' fill='#eaf1f7' stroke='#64748b' stroke-width='1.5'/><path d='m20 17 12 7-12 7z' fill='#64748b'/></svg>"),
    cube: dataUri(cubeSvg(CUBE_BLUE)),
    draft: dataUri(cubeSvg(CUBE_AMBER)),
    group: dataUri(stackSvg()),
    source: dataUri(fileSvg()),
    muted: dataUri(cubeSvg(CUBE_GRAY)),
    lineageFile: dataUri("<svg xmlns='http://www.w3.org/2000/svg' width='192' height='192' viewBox='0 0 48 48'><path d='M10 4h19l10 10v28a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z' fill='#e8f6ee' stroke='#188555' stroke-width='2'/><path d='M29 4v10h10' fill='none' stroke='#188555' stroke-width='2'/><path d='M15 21h18M15 27h18M15 33h18M21 19v17M28 19v17' stroke='#188555' stroke-width='1.5'/></svg>"),
    lineageGear: dataUri("<svg xmlns='http://www.w3.org/2000/svg' width='192' height='192' viewBox='0 0 48 48'><path d='M20 4h8l1.2 4.8a16 16 0 0 1 3.4 1.4l4.3-2.5 5.5 5.5-2.5 4.3a16 16 0 0 1 1.4 3.4L46 22v7l-4.7 1.1a16 16 0 0 1-1.4 3.4l2.5 4.3-5.5 5.5-4.3-2.5a16 16 0 0 1-3.4 1.4L28 46h-8l-1.2-4.8a16 16 0 0 1-3.4-1.4l-4.3 2.5-5.5-5.5 2.5-4.3a16 16 0 0 1-1.4-3.4L2 29v-7l4.7-1.1a16 16 0 0 1 1.4-3.4l-2.5-4.3 5.5-5.5 4.3 2.5a16 16 0 0 1 3.4-1.4z' fill='#e9efff' stroke='#5272c7' stroke-width='1.6' stroke-linejoin='round'/><circle cx='24' cy='25' r='7' fill='#fff' stroke='#5272c7' stroke-width='2'/></svg>"),
    lineageDatabase: dataUri("<svg xmlns='http://www.w3.org/2000/svg' width='192' height='192' viewBox='0 0 48 48'><ellipse cx='24' cy='10' rx='16' ry='6' fill='#eff0ff' stroke='#6e6abb' stroke-width='2'/><path d='M8 10v25c0 4 7 7 16 7s16-3 16-7V10M8 19c0 4 7 7 16 7s16-3 16-7M8 27c0 4 7 7 16 7s16-3 16-7' fill='none' stroke='#6e6abb' stroke-width='2'/></svg>"),
  };

  const TYPE_LABEL = {
    cube: 'Cube', process: 'TI', chore: '调度', dimension: '维度',
    draft: 'Cube 草稿 · 未部署', source: '数据来源 · 未接入', group: '人工模块',
  };

  const EDGE_STYLE = {
    TI_CANDIDATE: { line: 'dashed', color: '#94a3b8', arrow: 'vee', cls: 'ei-candidate' },
    RULE_REFERENCE: { line: 'solid', color: '#5b7fd6', arrow: 'tee', cls: 'ei-rule' },
    FEEDER_REFERENCE: { line: 'dotted', color: '#b3bdd0', arrow: 'none', cls: 'ei-feeder' },
    DESIGN_RELATION: { line: 'dashed', color: '#c08a3e', arrow: 'triangle', cls: 'ei-design' },
    TI_READ: { line: 'solid', color: '#b3bdd0', arrow: 'vee', cls: 'ei-raw' },
    TI_WRITE: { line: 'solid', color: '#b3bdd0', arrow: 'vee', cls: 'ei-raw' },
    CALL: { line: 'dotted', color: '#cbd5e1', arrow: 'vee', cls: 'ei-raw' },
    SCHEDULE: { line: 'dotted', color: '#cbd5e1', arrow: 'vee', cls: 'ei-raw' },
    STRUCTURE: { line: 'dotted', color: '#e2e8f0', arrow: 'none', cls: 'ei-raw' },
  };

  function styleSheet(opt) {
    const base = [
      {selector:'core',style:{'active-bg-opacity':0,'active-bg-size':0}},
      {
        selector: 'node',
        style: {
          // 轻量横向卡片：左侧小图标 + 右侧完整名称。
          // 宽度由 data(cardW) 按名称长度计算，与 canvas-layout.nodeWidth 同一公式，
          // 保证布局间距与视觉宽度一致；缩放只改变 rendered 尺寸，不改变宽高比。
          shape: 'roundrectangle',
          width: 'data(cardW)',
          height: 42,
          'background-color': '#ffffff',
          'background-opacity': 1,
          'background-fit': 'none',
          'background-width': '18px',
          'background-height': '18px',
          'background-position-x': '12px',
          'background-position-y': '50%',
          'background-image-opacity': 0.92,
          'border-width': 1,
          'border-color': '#e2e8f0',
          label: 'data(name)',
          'font-size': 11,
          'font-family': 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
          color: '#1e293b',
          'text-valign': 'center',
          'text-halign': 'center',
          // 文字中心右移半个图标区（图标占左侧 12+18px），使正文落在图标右侧
          'text-margin-x': 10,
          'text-max-width': 165,
          'text-wrap': 'wrap',
          'overlay-opacity': 0,
          'transition-property': 'border-width, border-color, background-color',
          'transition-duration': window.matchMedia('(prefers-reduced-motion: reduce)').matches?'0ms':'90ms',
        },
      },
      { selector: 'node[type="cube"]', style: { 'background-image': ICON.cube } },
      { selector: 'node[type="draft"]', style: { 'background-image': ICON.draft, color: '#92400e' } },
      { selector: 'node[type="source"]', style: { 'background-image': ICON.source, color: '#5b21b6' } },
      { selector: 'node[type="group"]', style: { 'background-image': ICON.group, color: '#475569', 'font-weight': 'bold' } },
      { selector: 'node[type="process"]', style: { 'background-image': ICON.process, color: '#475569' } },
      { selector: 'node[type="chore"], node[type="dimension"]', style: { 'background-image': ICON.muted } },
      { selector: 'node.cn-hover', style: { 'border-width': 1.5, 'border-color': '#b9cdf3', 'background-color': '#fcfdff' } },
      { selector: 'node.cn-selected', style: { 'border-width': 1.5, 'border-color': '#3556d4', 'background-color': '#f6f9ff' } },
      { selector: 'node.cn-kb-focus', style: { 'border-width': 2, 'border-style': 'dashed', 'border-color': '#3556d4' } },
      {
        selector: 'edge',
        style: {
          width: 1.4,
          'curve-style': 'unbundled-bezier',
          'control-point-step-size': 34,
          'control-point-weights': 0.5,
          'control-point-distances': 'data(cpd)',
          'loop-direction': '-45deg',
          'loop-sweep': '70deg',
          'target-arrow-shape': 'data(arrow)',
          'target-arrow-color': 'data(color)',
          'arrow-scale': 0.8,
          'line-color': 'data(color)',
          'line-style': 'data(lineStyle)',
          label: '',
          'font-size': 9.5,
          'font-weight': 600,
          'font-family': 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
          color: '#7a849c',
          'text-rotation': 'autorotate',
          'text-background-color': '#ffffff',
          'text-background-opacity': 0.75,
          'text-background-padding': '2px',
          'text-max-width': '140px',
          'text-margin-y': -2,
          'overlay-padding': 13,
          'overlay-opacity': 0,
          'transition-property': 'line-color, width, opacity',
          'transition-duration': window.matchMedia('(prefers-reduced-motion: reduce)').matches?'0ms':'90ms',
        },
      },
      // 边标签降噪：默认隐藏，聚焦（hover/选中）时才出现——减少「2 TI / Rule」糊满画布
      { selector: 'edge.cn-hover', style: { width: 2.2, label: 'data(fullLabel)', color: '#334155', 'text-background-opacity': 0.95 } },
      { selector: 'edge.cn-selected', style: { width: 2.4, label: 'data(fullLabel)', 'line-color': '#3556d4', 'target-arrow-color': '#3556d4', color: '#1e293b', 'text-background-opacity': 0.95 } },
      { selector: 'node.cn-connect-target', style: { 'border-width': 3, 'border-color': '#b45309' } },
      { selector: 'edge[status="CANDIDATE"]', style: { 'line-style': 'dashed' } },
      { selector: 'edge.cn-dim', style: { opacity: 0.25 } },
    ];
    if (opt && opt.lineage) base.push(
      {selector:'node',style:{'height':'data(cardH)','label':'data(displayName)','background-width':'28px','background-height':'28px','background-position-x':'24px','text-margin-x':27,'text-max-width':'data(labelW)','text-wrap':'wrap','font-size':16,'border-color':'#d6e2f1','color':'#233955'}},
      {selector:'node[type="cube"]',style:{'background-color':'#edf5ff','border-color':'#8db7e6','color':'#163e70'}},
      {selector:'node[type="process"]',style:{'background-image':ICON.lineageGear,'background-color':'#f3efff','border-color':'#b5a2e3','color':'#493b78','shape':'round-rectangle'}},
      {selector:'node[type="source"]',style:{'background-image':ICON.lineageFile,'background-color':'#f3fbf7','border-color':'#cce9d9','color':'#216245'}},
      {selector:'node[type="database"]',style:{'background-image':ICON.lineageDatabase,'background-color':'#faf8ff','border-color':'#e1daf3','color':'#554f8f'}},
      {selector:'node.cn-selected',style:{'border-width':2,'border-color':'#426acb','background-color':'#eff5ff'}},
      {selector:'edge',style:{'curve-style':'bezier','label':'data(displayLabel)','text-rotation':'none','font-size':10,'color':'#536f8e','text-background-opacity':.96,'width':1.6}},
      {selector:'edge[status="CANDIDATE"]',style:{'line-style':'dashed','line-color':'#8fa6c4','target-arrow-color':'#8fa6c4'}},
      {selector:'edge[kind="TI_WRITE"]',style:{'line-color':'#83a3ca','target-arrow-color':'#83a3ca'}},
      {selector:'edge.cn-hover, edge.cn-selected',style:{'label':'data(fullLabel)','width':2.2,'color':'#334e71'}}
    );
    return base;
  }

  function shortName(name, max) {
    const text = String(name == null ? '' : name);
    if (text.length <= max) return text;
    return text.slice(0, max - 1) + '…';
  }

  function lineageLabel(name) {
    const chars=Array.from(String(name || '')), lines=[];
    for(let i=0;i<chars.length;){
      let end=Math.min(i+16,chars.length);
      if(end<chars.length){
        for(let j=end-1;j>=i+8;j--){if(chars[j]==='.'||chars[j]===' '){end=j+1;break;}}
      }
      lines.push(chars.slice(i,end).join(''));i=end;
    }
    return {text:lines.join('\n'),width:270,height:Math.max(48,lines.length*21+12)};
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
    let direction='LR';

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
    let lastStrategy = '';
    // 视图归属：程序化 fit/缩放不标记 userView；用户滚轮/拖拽平移后不再自动重适配
    let userView = false;
    let programmatic = false;
    let settleUntil = 0;
    function runProgrammatic(fn) {
      programmatic = true;
      try { fn(); } finally { window.setTimeout(function () { programmatic = false; }, 0); }
    }

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
      // 拖动过程中实时高亮合法目标；非法位置（空白）不高亮
      const target = nodeAtPoint(p);
      if (target && target.id() !== drag.source) {
        if (!connectTarget || connectTarget.id() !== target.id()) {
          if (connectTarget) connectTarget.removeClass('cn-connect-target');
          connectTarget = target;
          connectTarget.addClass('cn-connect-target');
        }
      } else if (connectTarget) {
        connectTarget.removeClass('cn-connect-target');
        connectTarget = null;
      }
    }

    function cleanupConnect() {
      window.removeEventListener('mousemove', moveConnect, true);
      window.removeEventListener('mouseup', endConnect, true);
      connectLine.style.display = 'none';
      if (connectTarget) { connectTarget.removeClass('cn-connect-target'); connectTarget = null; }
      drag = null;
    }

    let connectTarget = null;

    function endConnect(evt) {
      const source = drag && drag.source;
      cleanupConnect();
      const p = modelPos(evt);
      const target = nodeAtPoint(p);
      if (!source || !target || target.id() === source) {
        if (source && opt.onConnectCancel) opt.onConnectCancel();
        return;
      }
      if (opt.onConnect) opt.onConnect(source, target.id());
    }

    // Esc 取消拖线（供外壳快捷键调用）；返回是否确实取消了进行中的拖线
    function cancelConnect() {
      if (!drag) return false;
      cleanupConnect();
      if (opt.onConnectCancel) opt.onConnectCancel();
      return true;
    }

    anchor.addEventListener('mousedown', startConnect);

    function initCy() {
      cy = cytoscape({
        container: container,
        elements: [],
        style: styleSheet(opt),
        layout: { name: 'preset' },
        wheelSensitivity: 0.18,
        minZoom: 0.12,
        maxZoom: 3,
        boxSelectionEnabled: false,
        selectionType: 'additive',
        autounselectify: true,
        pixelRatio: Math.min(2, Math.max(1.5, window.devicePixelRatio || 1)),
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

      cy.on('cxttap', function (evt) {
        if (evt.target === cy && opt.onCanvasContext) {
          const oe = evt.originalEvent || {};
          opt.onCanvasContext(oe.clientX || 0, oe.clientY || 0);
        }
      });

      // 语义缩放：低倍率下保持边的轻量（标签本身已只在聚焦时显示，无需额外切换）
      let lowZoom = false;
      cy.on('zoom', function () {
        lowZoom = cy.zoom() < 0.55;
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

      cy.on('pan zoom', function () {
        if (!programmatic) userView = true;
        if (!anchor.hidden && hoverNode) showAnchor(cy.getElementById(hoverNode));
      });
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
    // 键盘节点导航：画布容器可获得焦点（tabindex=0），方向键在可见节点间移动，
    // Enter 触发选择。仅在容器自身获得焦点时响应，避免与输入框/面板滚动冲突。
    let kbFocus = null;
    container.addEventListener('keydown', function (evt) {
      const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Enter'];
      if (!keys.includes(evt.key)) return;
      // 只在画布容器自身获得焦点（Tab 聚焦）时响应；不抢输入框 / 菜单 / 面板的键盘。
      if (document.activeElement !== container) return;
      const visible = cy.nodes(':visible').filter(function (n) { return n.data('type') !== 'group'; });
      if (!visible.length) return;
      evt.preventDefault();
      if (evt.key === 'Enter') {
        if (kbFocus && opt.onNodeClick) { opt.onNodeClick(kbFocus, {}); return; }
        return;
      }
      // 从当前焦点（或首个节点）出发，按模型坐标在该方向找最近邻
      const cur = kbFocus ? cy.getElementById(kbFocus) : null;
      const origin = (cur && cur.length) ? cur.position() : (visible.first() && visible.first().position());
      if (!origin) return;
      let best = null, bestDist = Infinity;
      const wantX = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: 0, ArrowDown: 0 }[evt.key];
      const wantY = { ArrowLeft: 0, ArrowRight: 0, ArrowUp: -1, ArrowDown: 1 }[evt.key];
      visible.forEach(function (n) {
        if (cur && n.id() === kbFocus) return;
        const p = n.position();
        const dx = p.x - origin.x, dy = p.y - origin.y;
        // 方向投影必须为正，否则不在目标方向
        const proj = dx * wantX + dy * wantY;
        if (proj <= 0) return;
        const d = Math.abs(dx) + Math.abs(dy) - proj; // 偏向该方向上的最近邻
        if (d < bestDist) { bestDist = d; best = n; }
      });
      if (!best) return;
      kbFocus = best.id();
      cy.elements().removeClass('cn-kb-focus');
      best.addClass('cn-kb-focus');
      runProgrammatic(function () { best.emit('position'); }); // 触发重绘
      if (opt.onKbFocus) opt.onKbFocus(best.id());
    });
    container.addEventListener('blur', function () {
      kbFocus = null;
      cy && cy.elements().removeClass('cn-kb-focus');
    });
    // 容器尺寸会随侧栏 / 详情开合变化；Cytoscape 必须收到 resize，
    // 否则视野与元素坐标会停留在初始化那一刻的尺寸上（节点跑到可视区外）。
    let observer = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(function () {
        if (!cy) return;
        cy.resize();
        // 安定窗口内容器尺寸变化（详情开合、字体加载）→ 重新适应；
        // 用户一旦手动平移/缩放（userView）或窗口过期，绝不覆盖用户视口。
        if (!userView && cy.elements().length && Date.now() < settleUntil) api.fit();
      });
      observer.observe(container);
    }
    window.requestAnimationFrame(function () { if (cy) cy.resize(); });

    const api = {
      cy: function () { return cy; },

      setGraph: function (payload) {
        const nodes = (payload.nodes || []).map(function (n) {
          const type = n.type || 'cube';
          // 卡片宽度与 canvas-layout.nodeWidth 同一公式：布局间距与视觉宽度一致。
          // 上限收紧到 210：避免长名称卡片右侧大片空白（文字 165px 内换行补齐）。
          const fullName=String(n.displayName || n.name || ''), label=opt.lineage?lineageLabel(fullName):null;
          const cardW = label ? label.width : Math.min(60 + fullName.length * 6.0, 210);
          const cardH = label ? label.height : 42;
          return {
            group: 'nodes',
            data: {
              id: n.id,
              name: n.name,
              fullName: n.name,
              short: shortName(n.name, type === 'source' ? 22 : 18),
              cardW: cardW,
              labelW: Math.max(36, cardW - 70),
              cardH: cardH,
              displayName: label ? label.text : fullName,
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
              fullLabel: opt.lineage ? (e.label || '') : edgeLabel(e),
              displayLabel: opt.lineage && (payload.edges || []).length > 10 ? '' : (e.label || ''),
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
        cy.style(styleSheet(opt));

        if (hasPreset) {
          cy.layout({ name: 'preset', fit: false, padding: 30 }).run();
          if (payload.view) api.applyView(payload.view);
          if (payload.fit) api.fit();
        } else if (nodes.length) {
          // 全新图（无保存坐标、无保存视口）：布局并适应画布；
          // 否则节点默认落在模型原点 (0,0)，会被画布左上角裁掉。
          api.layout(payload.layout || 'auto');
          if (!payload.view) {
            settleUntil = Date.now() + 2500;
            api.fit();
            window.requestAnimationFrame(function () { api.fit(); });
            setTimeout(function () { api.fit(); }, 320);
          }
        }
        positionsCache = api.getPositions();
      },

      layout: function (name) {
        if (!cy || !cy.nodes().length) return;
        const visibleNodes = cy.nodes(':visible').filter(function (n) { return n.data('type') !== 'group'; });
        if (!visibleNodes.length) return;
        if(name==='tb')direction='TB';else if(name==='layered')direction='LR';
        if (name === 'grid') {
          cy.layout({ name: 'grid', padding: 40, avoidOverlap: true, condense: true }).run();
        } else {
          // auto：分层 / 辐射 / 环分解由 TM1CanvasLayout 依据图形态决定
          const nodes = visibleNodes.map(function (n) { return { id: n.id(), type: n.data('type'), name: n.data('name'), width: n.data('cardW'), height: n.data('cardH') }; });
          const nodeIds = new Set(nodes.map(function (n) { return n.id; }));
          const edges = cy.edges().filter(function (e) {
            return e.target().id() !== e.source().id()
              && nodeIds.has(e.source().id()) && nodeIds.has(e.target().id());
          }).map(function (e) { return { source: e.source().id(), target: e.target().id() }; });
          const result = window.TM1CanvasLayout
            ? window.TM1CanvasLayout.compute(nodes, edges,{strategy:'layered',direction:direction,lineage:!!opt.lineage})
            : null;
          if (result) {
            lastStrategy = result.strategy;
            cy.batch(function () {
              nodes.forEach(function (n) {
                const p = result.positions[n.id];
                if (p) cy.getElementById(n.id).position(p);
              });
            });
            if (opt.onStrategy) opt.onStrategy(result.strategy, result);
          } else {
            cy.layout({ name: 'breadthfirst', directed: true, padding: 40, spacingFactor: 1.15, avoidOverlap: true, grid: true }).run();
          }
        }
        positionsCache = api.getPositions();
        if (opt.onLayout) opt.onLayout(positionsCache);
      },

      applyView: function (view) {
        if (!cy || !view) return;
        direction=view.vertical?'TB':'LR';
        runProgrammatic(function () {
          if (view.zoom) cy.zoom(view.zoom);
          if (typeof view.x === 'number' && typeof view.y === 'number') {
            cy.pan({ x: view.x, y: view.y });
          } else if (view.pan && typeof view.pan === 'object') {
            cy.pan(view.pan);  // 兼容旧工作区
          }
        });
      },

      getView: function () {
        if (!cy) return {};
        const p = cy.pan(), z = cy.zoom();
        // Workspace.layout 只接受 {zoom,x,y,vertical} 四个数值键
        return { zoom: Number(z.toFixed(3)), x: Math.round(p.x), y: Math.round(p.y),vertical:direction==='TB'?1:0 };
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
        runProgrammatic(function () {
          cy.fit(cy.elements(), 46);
          if (cy.zoom() > 1.15) {
            cy.zoom({ level: 1.15, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
            cy.center(cy.elements());
          }
        });
      },

      focus: function (id) {
        if (!cy) return;
        const n = cy.getElementById(id);
        if (n && n.length) runProgrammatic(function () {
          if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){cy.center(n);cy.zoom({level:Math.max(cy.zoom(),0.9),position:n.position()});}
          else cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 0.9) }, { duration: 160 });
        });
      },

      zoomBy: function (factor) {
        if (!cy) return;
        runProgrammatic(function () {
          cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } });
        });
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
      cancelConnect: cancelConnect,
      layoutStrategy: function () { return lastStrategy; },
      destroy: function () {
        window.removeEventListener('resize', api.resize);
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

  window.TM1Canvas = { mount: mount, icons: ICON, TYPE_LABEL: TYPE_LABEL, lineageLabel: lineageLabel };
})();
