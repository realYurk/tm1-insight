/* Offline presentation only. All actions/evidence come from Architecture facts. */
(function () {
  'use strict';
  let observer, generation = 0, includeContext = false;
  const make = (tag, text, parent) => { const x = document.createElement(tag); x.textContent = text ?? ''; if (parent) parent.append(x); return x; };
  const details = (p, title) => { const d = make('details', '', p); make('summary', title, d); return d; };
  function dispose() { ++generation; if (observer) observer.disconnect(); observer = null; }
  async function render(parent, api) {
    dispose();
    const serial = generation, active = () => api.current() && serial === generation;
    const flow = await api.request(api.url('functional-flow', {include_context:includeContext}));
    if (!active()) return;
    parent.replaceChildren();
    const heading = make('div', '', parent); heading.className = 'flow-heading';
    make('h2', '业务流程图', heading);
    make('p', '先看输入、处理与结果；点击节点或连线查看详情。', heading);
    const toolbar = make('div', '', heading); toolbar.className = 'study-actions';
    [['flow-markdown', '流程文档 Markdown'], ['mermaid', 'Mermaid 图'], ['flow-json', '流程 JSON']].forEach(([format, label]) => {
      const a = make('a', label, toolbar); a.className = 'btn ghost'; a.href = api.url('export', { format, include_context:includeContext });
    });
    const options = make('label', '', toolbar); options.className='flow-context'; const check=make('input','',options); check.type='checkbox'; check.checked=includeContext; options.append(document.createTextNode(' 展开调用入口、消费者与来源规则')); check.addEventListener('change',()=>{includeContext=check.checked;render(parent,api).catch(e=>make('p',e.message,parent));});
    make('p', flow.note, parent).className = 'flow-note';
    if (flow.statistics.truncated) make('p', '已达到展示范围上限，当前图不完整。请缩小入口，完整事实可在架构导出中查看。', parent).className = 'flow-boundary';
    const layout = make('div', '', parent); layout.className = 'flow-layout';
    const viewport = make('div', '', layout); viewport.className = 'flow-viewport'; viewport.tabIndex = 0; viewport.setAttribute('aria-label', '业务流程图，可滚动');
    const canvas = make('div', '', viewport); canvas.className = 'flow-canvas';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); canvas.append(svg); svg.classList.add('flow-lines'); svg.setAttribute('aria-label', '流程动作连线');
    const lanes = ['来源 / 规则输入', '处理 / 规则计算', '结果 / 中间数据'].map(title => { const lane = make('div', '', canvas); lane.className = 'flow-lane'; make('h3', title, lane); return lane; });
    const panel = make('aside', '', layout); panel.className = 'flow-detail'; panel.setAttribute('aria-label', '流程节点详情');
    const byId = new Map(flow.nodes.map(n => [n.id, n])), cards = new Map();
    const smallButton = (p, title, fn) => {
      const b = make('button', title, p); b.type = 'button'; b.className = 'btn ghost';
      b.addEventListener('click', async () => { b.disabled = true; try { await fn(); } catch (e) { make('p', e.message, p); } finally { b.disabled = false; } }); return b;
    };
    function proof(p, edges) {
      const d = details(p, '源码与技术证据（折叠）');
      let loaded = false;
      d.addEventListener('toggle', async () => {
        if (!d.open || loaded) return; loaded = true;
        const refs = [...new Set(edges.flatMap(e => e.context_refs))].filter(ref => /^\/(write_explanations\/\d+|rules\/\d+\/(rule_semantics|feeder_semantics)\/\d+)$/.test(ref));
        for (const ref of refs.slice(0, 20)) smallButton(d, ref.startsWith('/write_') ? '查看写入点、表达式与条件' : '查看 Rule 语句、条件与表达式', async () => {
          if (!/^\/(write_explanations\/\d+|rules\/\d+\/(rule_semantics|feeder_semantics)\/\d+)$/.test(ref)) return;
          const c = await api.request(api.url('relation-context', { ref }));
          const box = make('section', '', d);
          make('p', c.location ? `${c.process} · ${c.location.section}:${c.location.line}:${c.location.column}` : `Rule · ${c.line_start}–${c.line_end}`, box);
          make('pre', c.rhs ? c.raw : (c.value_expression || '') + '\n' + (c.target_coordinates || []).map(x => `${x.dimension || '维度待确认'} = ${x.expression}`).join('\n'), box).className = 'code';
          const raw = details(box, '解析结构与未确认项'); make('pre', JSON.stringify(c, null, 2), raw).className = 'code';
        });
        if (refs.length > 20) make('p', '此处提供前 20 组上下文；其余见完整架构导出。', d);
        const facts = new Set(edges.flatMap(e => e.evidence_refs));
        flow.evidence.filter(f => facts.has(f.id)).slice(0, 30).forEach(f => {
          const where = `${f.process || f.cube || f.chore || ''} · ${f.section || f.table || ''}:${f.line || ''}`;
          if (f.section && f.section !== 'rule') smallButton(d, '源码 · ' + where, () => api.code(d, f.process, f.section, Math.max(1, (f.line || 1) - 3)));
          else make('p', where, d);
        });
        const gaps = details(d, '未确认事项与语义边界');
        [...new Set(edges.flatMap(e => e.unresolved_reasons))].forEach(reason => make('p', reason, gaps));
        flow.limitations.forEach(x => make('p', x, gaps));
        make('p', '完整证据见 Architecture.json；此处按需读取，不代表运行验证。', d);
      });
    }
    function slices(p, values) {
      if (!values.length) return;
      make('h4', '关键写入切面', p);
      values.slice(0, 6).forEach(s => {
        const box = make('div', '', p); box.className = 'flow-slice';
        if (s.target) make('strong', s.target, box);
        make('small', `${s.write_sites} 个写入点${s.conditional ? ' · 含条件' : ''} · 切面摘录`, box);
        s.coordinates.forEach(c => make('p', `${c.dimension} = ${c.value}`, box));
      });
      if (values.length > 6) make('p', '其余切面组合见写入点证据或流程导出。', p);
    }
    function selectNode(n) {
      panel.replaceChildren(); cards.forEach((card, id) => card.setAttribute('aria-pressed', String(id === n.id)));
      make('small', n.kind === 'process' ? 'TI PROCESS' : n.kind === 'rule' ? 'RULE' : n.kind === 'chore' ? 'CHORE' : 'CUBE', panel).className = 'flow-eyebrow';
      make('h3', n.title, panel); make('p', n.role + ' · ' + n.summary, panel);
      if (n.kind === 'cube') { make('h4', '维度结构', panel); make('p', n.dimensions.join(' → ') || '当前范围未保存维度定义', panel); }
      make('h4', '上游对象', panel); make('p', [...new Set(flow.edges.filter(e=>e.target===n.id).map(e=>byId.get(e.source).title))].join('、') || '当前范围未确认', panel);
      make('h4', '下游对象', panel); make('p', [...new Set(flow.edges.filter(e=>e.source===n.id).map(e=>byId.get(e.target).title))].join('、') || '当前范围未确认', panel);
      const related = flow.edges.filter(e => e.source === n.id || e.target === n.id);
      slices(panel, n.slices.length ? n.slices : related.flatMap(e => e.slices.map(s => ({ target: byId.get(e.target).name, ...s }))));
      if (n.kind !== 'chore') { const a = make('a', '打开原始对象', panel); a.className = 'btn ghost'; a.href = '/explorer/' + (n.kind === 'process' ? 'process' : 'cube') + '/' + encodeURIComponent(n.name); }
      if(n.kind==='process'){const focus=make('a','以此 TI 为入口查看流程',panel);focus.className='btn primary';focus.href='/architecture?'+new URLSearchParams({kind:'process',name:n.name,analyze:'1',view:'functional_flow'});}
      proof(panel, related);
    }
    function selectEdge(e) {
      panel.replaceChildren(); cards.forEach(card => card.setAttribute('aria-pressed', 'false'));
      make('small', '关系详情', panel).className = 'flow-eyebrow'; make('h3', e.label, panel);
      make('p', byId.get(e.source).title + ' → ' + byId.get(e.target).title, panel);
      make('p', e.note, panel); slices(panel, e.slices); proof(panel, [e]);
    }
    const rootCube=flow.nodes.find(n=>n.selected_entry&&n.kind==='cube');
    const displayNodes=[...flow.nodes].sort((a,b)=>{const downstream=n=>rootCube&&n.kind==='process'&&flow.edges.some(e=>e.source===rootCube.id&&e.target===n.id&&e.action==='read')?1:0;return downstream(a)-downstream(b)||a.title.localeCompare(b.title);});
    displayNodes.forEach(n => {
      const lane = ['process','rule'].includes(n.kind) ? 1 : n.kind === 'chore' || ['源数据','数据对象'].includes(n.role) ? 0 : 2;
      const card = make('button', '', lanes[lane]); card.type = 'button'; card.className = 'flow-node flow-node-' + n.kind; card.dataset.flowNode = n.id; card.title = n.title; card.setAttribute('aria-pressed', 'false');
      make('small', (n.kind === 'process' ? 'TI' : n.kind === 'cube' ? 'CUBE' : n.kind.toUpperCase()) + ' · ' + n.role, card).className = 'flow-eyebrow';
      make('strong', n.kind==='process'&&n.title.length>48?n.title.slice(0,15)+' … '+n.title.slice(-28):n.title, card); make('span', n.summary, card).className = 'flow-node-summary';
      if (n.slices[0]?.coordinates.length) make('span', '示例切面 · ' + n.slices[0].coordinates.slice(0, 3).map(c => c.dimension + ' = ' + c.value).join('；'), card).className = 'flow-node-slice';
      card.addEventListener('click', () => selectNode(n)); cards.set(n.id, card);
    });
    if (!flow.nodes.length) make('p', '当前范围没有已确认的可展示关系。可以切换到模块概览核对入口与边界。', viewport);
    else selectNode(flow.nodes.find(n => n.selected_entry) || flow.nodes[0]);
    function draw() {
      if (!canvas.isConnected || !active()) return;
      svg.replaceChildren(); const bounds = canvas.getBoundingClientRect();
      svg.setAttribute('width', canvas.scrollWidth); svg.setAttribute('height', canvas.scrollHeight);
      const create = (tag, attrs, p = svg) => { const x = document.createElementNS(svg.namespaceURI, tag); Object.entries(attrs).forEach(([k, v]) => x.setAttribute(k, v)); p.append(x); return x; };
      const defs = create('defs', {}), marker = create('marker', { id: 'flow-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse' }, defs);
      create('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: 'currentColor' }, marker);
      flow.edges.forEach((e, i) => {
        const a = cards.get(e.source).getBoundingClientRect(), b = cards.get(e.target).getBoundingClientRect();
        const forward = a.left < b.left, same = Math.abs(a.left - b.left) < 5;
        const x1 = (forward || same ? a.right : a.left) - bounds.left, x2 = (forward ? b.left : b.right) - bounds.left;
        const y1 = a.top - bounds.top + a.height / 2, y2 = b.top - bounds.top + b.height / 2;
        const bend = same ? 22 + (i % 3) * 7 : Math.max(18, Math.abs(x2 - x1) / 2);
        const dx = forward || same ? bend : -bend;
        const group = create('g', { class: 'flow-edge' + (['PROCESS_CALL','CHORE_SCHEDULE'].includes(e.action) ? ' flow-edge-call' : ''), tabindex: 0, role: 'button', 'aria-label': byId.get(e.source).title + ' ' + e.label + ' ' + byId.get(e.target).title });
        create('path', { d: `M${x1},${y1} C${x1+dx},${y1} ${same ? x2+dx : x2-dx},${y2} ${x2},${y2}`, 'marker-end': 'url(#flow-arrow)' }, group);
        const text = create('text', { x: same ? x1+dx : (x1+x2)/2, y: (y1+y2)/2-5, 'text-anchor': 'middle' }, group); text.textContent = e.label;
        group.addEventListener('click', () => selectEdge(e)); group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectEdge(e); } });
      });
    }
    observer = new ResizeObserver(draw); observer.observe(canvas); requestAnimationFrame(draw);
    const folded = details(parent, '技术执行细节（Bedrock / 框架调用）及辅助关系已折叠');
    make('p', '折叠基于现有引擎的技术角色与源码效果分类；核心读写仍保留在所属处理步骤中。', folded);
    make('p', '技术关系 ' + (flow.statistics.folded.technical || 0) + '；其余辅助、未确认或展示预算外的关系请在“关系与计算”及完整架构中核对。', folded);
    smallButton(folded, '查看技术关系与原始依据', () => api.technical());
    heading.scrollIntoView({block:'start'});
  }
  window.TM1FunctionalFlow = { render, dispose };
  window.addEventListener('pagehide', dispose);
})();
