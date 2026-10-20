/* 可配置分摊前端：全部图表基于后端 allocation_engine 的真实计算结果。 */
(function () {
  'use strict';
  const el = (id) => document.getElementById(id);
  const n = (tag, text, parent) => { const x = document.createElement(tag); x.textContent = text ?? ''; if (parent) parent.append(x); return x; };
  const show = (id, text) => { const e = el(id); e.textContent = text; e.hidden = !text; };

  function readConfig() {
    let sourceRows, targetRows;
    try { sourceRows = JSON.parse(el('al-source').value); } catch (e) { throw Error('源数据不是合法 JSON：' + e.message); }
    try { targetRows = JSON.parse(el('al-target').value); } catch (e) { throw Error('目标数据不是合法 JSON：' + e.message); }
    if (!Array.isArray(sourceRows) || !Array.isArray(targetRows)) throw Error('源数据与目标数据都必须是 JSON 数组。');
    const split = (v) => v.split(/[,，]/).map(s => s.trim()).filter(Boolean);
    return {
      group_dimensions: split(el('al-groups').value),
      allocation_dimensions: split(el('al-allocs').value),
      value_field: el('al-value').value.trim(),
      driver_field: el('al-driver').value.trim(),
      write_policy: el('al-policy').value,
      source_rows: sourceRows,
      target_rows: targetRows,
    };
  }

  function flowMermaid(config, result) {
    // 由真实计算结果构造流程图：源分组 → 分摊内核 → 目标
    const groups = {};
    result.results.forEach(r => {
      const g = JSON.stringify(r.group);
      (groups[g] = groups[g] || new Set()).add(Object.entries(r.target)
        .filter(([k]) => config.allocation_dimensions.includes(k)).map(([k, v]) => k + '=' + v).join('·'));
    });
    const lines = ['flowchart LR'];
    const S = 'S["源数据 · 合成输入"]', E = 'E["分摊结果（守恒核对）"]';
    lines.push('  ' + S, '  K["分摊内核 · 按组比例分配 · 策略：' + (result.write_policy === 'increment' ? '累加' : '覆盖') + '"]', '  ' + E);
    Object.entries(groups).forEach(([g, targets], i) => {
      const label = g.replace(/"/g, "'");
      lines.push('  G' + i + '["分组 ' + label + '"]');
      lines.push('  ' + S + ' --> G' + i + ' --> K');
    });
    lines.push('  K --> ' + E);
    return lines.join('\n') + '\n';
  }

  function renderResult(config, payload) {
    const result = payload.result, rec = payload.reconcile;
    el('al-results').hidden = false;
    el('al-policy-note').textContent = '写入策略：' + (result.write_policy === 'increment' ? '累加' : '覆盖') +
      ' · 引擎版本 ' + payload.engine + ' · 配置哈希 ' + result.config_hash;

    // 结果表
    const tbody = el('al-table').querySelector('tbody');
    tbody.replaceChildren();
    result.results.forEach(r => {
      const row = n('tr', '', tbody);
      n('td', Object.entries(r.group).map(([k, v]) => k + '=' + v).join(' · '), row);
      n('td', Object.entries(r.target).map(([k, v]) => k + '=' + v).join(' · '), row);
      n('td', r.driver ?? '（缺失，记 0）', row);
      const pct = (parseFloat(r.ratio) * 100).toFixed(2) + '%';
      n('td', pct, row);
      const amt = n('td', '', row); const code = n('code', r.allocated, amt); code.className = 'var-inline';
      n('td', r.source_total, row);
    });

    // 对账
    const recon = el('al-recon'); recon.replaceChildren();
    const stat = n('div', '', recon); stat.className = 'al-recon-summary';
    const ok = rec && rec.balanced === 'True';
    n('p', (ok ? '总体守恒：源合计 ' + rec.source_total + ' = 分配合计 ' + rec.allocated_total
           : '总体不平衡：源合计 ' + (rec ? rec.source_total : '—') + '，分配合计 ' + (rec ? rec.allocated_total : '—') +
             '，未分摊 ' + (rec ? rec.unallocated : '—')), stat).className = ok ? 'al-ok' : 'al-bad';
    (rec && rec.groups || []).forEach(g => {
      const p = n('p', (g.conserved === 'True' ? '✓ ' : '✗ ') + Object.entries(g.group).map(([k, v]) => k + '=' + v).join(' · ') +
        '：源 ' + g.source + ' → 分摊 ' + g.allocated, recon);
      p.className = g.conserved === 'True' ? 'al-ok small' : 'al-bad small';
    });

    // 异常
    const anomalies = result.anomalies || [];
    el('al-anomaly-card').hidden = !anomalies.length;
    const box = el('al-anomalies'); box.replaceChildren();
    anomalies.forEach(a => n('p', a, box).className = 'al-warn small');

    // Mermaid 流程图（真实结果）
    if (window.TM1Mermaid) {
      try {
        window.TM1Mermaid.mount(el('al-flow'), { code: flowMermaid(config, result), title: '分摊流程' });
      } catch (e) { n('p', '流程图渲染失败：' + e.message, el('al-flow')); }
    }
  }

  async function run() {
    show('al-error', '');
    let config;
    try { config = readConfig(); } catch (e) { show('al-error', e.message); return; }
    const btn = el('al-run'); btn.disabled = true; btn.textContent = '计算中…';
    try {
      const r = await fetch('/api/allocation/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(config) });
      const j = await r.json();
      if (!r.ok) { show('al-error', (j.errors || []).join('；') || '请求失败'); return; }
      renderResult(config, j);
    } catch (e) { show('al-error', e.message); }
    finally { btn.disabled = false; btn.textContent = '执行分摊'; }
  }

  async function save() {
    show('al-error', '');
    const name = el('al-name').value.trim();
    if (!name) { show('al-error', '请先填写方案名再保存。'); return; }
    let config;
    try { config = readConfig(); } catch (e) { show('al-error', e.message); return; }
    const r = await fetch('/api/allocation/schemes/' + encodeURIComponent(name), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config }) });
    const j = await r.json();
    if (!r.ok) { show('al-error', j.detail || '保存失败'); return; }
    btnFlash(el('al-save'), '已保存 ✓');
  }

  async function load() {
    show('al-error', '');
    const name = el('al-name').value.trim();
    if (!name) { show('al-error', '请填写要加载的方案名。'); return; }
    const r = await fetch('/api/allocation/schemes/' + encodeURIComponent(name));
    const j = await r.json();
    if (!r.ok) { show('al-error', j.detail || '加载失败'); return; }
    const c = j.config || {};
    el('al-groups').value = (c.group_dimensions || []).join(', ');
    el('al-allocs').value = (c.allocation_dimensions || []).join(', ');
    el('al-value').value = c.value_field || '';
    el('al-driver').value = c.driver_field || '';
    el('al-policy').value = c.write_policy || 'overwrite';
    el('al-source').value = JSON.stringify(c.source_rows || [], null, 1);
    el('al-target').value = JSON.stringify(c.target_rows || [], null, 1);
    btnFlash(el('al-load'), '已加载 ✓');
  }

  function btnFlash(btn, text) { const old = btn.textContent; btn.textContent = text; setTimeout(() => { btn.textContent = old; }, 1200); }

  function exportJson() {
    let config;
    try { config = readConfig(); } catch (e) { show('al-error', e.message); return; }
    const blob = new Blob([JSON.stringify({ name: el('al-name').value.trim() || 'allocation-scheme', config }, null, 2)], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = (el('al-name').value.trim() || 'allocation-scheme') + '.json';
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 0);
  }

  function importJson(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const doc = JSON.parse(reader.result);
        const c = doc.config || doc;
        if (doc.name) el('al-name').value = doc.name;
        el('al-groups').value = (c.group_dimensions || []).join(', ');
        el('al-allocs').value = (c.allocation_dimensions || []).join(', ');
        el('al-value').value = c.value_field || '';
        el('al-driver').value = c.driver_field || '';
        el('al-policy').value = c.write_policy || 'overwrite';
        el('al-source').value = JSON.stringify(c.source_rows || [], null, 1);
        el('al-target').value = JSON.stringify(c.target_rows || [], null, 1);
        btnFlash(el('al-import-btn'), '已导入 ✓');
      } catch (e) { show('al-error', '导入失败：' + e.message); }
    };
    reader.readAsText(file);
  }

  el('al-form').addEventListener('submit', (e) => { e.preventDefault(); run(); });
  el('al-save').addEventListener('click', () => save().catch(e => show('al-error', e.message)));
  el('al-load').addEventListener('click', () => load().catch(e => show('al-error', e.message)));
  el('al-export').addEventListener('click', exportJson);
  el('al-import-btn').addEventListener('click', () => {
    let input = el('al-import');
    if (!input.parentNode.hidden) input = el('al-import');
    input.click();
  });
  el('al-import').addEventListener('change', (e) => { if (e.target.files[0]) importJson(e.target.files[0]); });
})();
