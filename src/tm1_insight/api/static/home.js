
// ============ 导入数据包 ============
async function importDataPackage(input) {
  const statusEl = document.getElementById('import-status');
  const btn = document.getElementById('import-btn');
  const file = input.files && input.files[0];
  if (!file) return;

  btn.disabled = true;
  btn.textContent = '导入中…';
  statusEl.textContent = '正在导入「' + file.name + '」，请稍候…';
  statusEl.className = 'status-inline muted';

  const formData = new FormData();
  formData.append('file', file);

  try {
    const r = await fetch('/api/import', { method: 'POST', body: formData });
    const j = await r.json();
    if (!r.ok) {
      statusEl.textContent = '导入失败：' + (j.error || r.status);
      statusEl.className = 'status-inline err';
      btn.disabled = false;
      btn.textContent = '选择数据包导入';
      return;
    }
    statusEl.textContent = '导入成功，正在刷新…';
    statusEl.className = 'status-inline ok';
    setTimeout(() => location.reload(), 600);
  } catch (e) {
    statusEl.textContent = '导入失败：' + e;
    statusEl.className = 'status-inline err';
    btn.disabled = false;
    btn.textContent = '选择数据包导入';
  }
}

// ============ 全局搜索（Cube + TI 混合联想） ============
let searchTimer = null;
let searchController = null;
let searchRevision = 0;
const searchInput = document.getElementById('global-search');
const searchResults = document.getElementById('search-results');

searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  if (searchController) searchController.abort();
  const revision = ++searchRevision;
  searchResults.replaceChildren();
  searchResults.hidden = true;
  const q = searchInput.value.trim();
  if (!q) { searchResults.hidden = true; return; }
  searchTimer = setTimeout(async () => {
    try {
      searchController = new AbortController();
      const response = await fetch('/api/search-all?q=' + encodeURIComponent(q), {signal: searchController.signal, cache: 'no-store'});
      if (!response.ok) throw new Error('搜索失败');
      const j = await response.json();
      if (revision !== searchRevision) return;
      renderResults(j);
    } catch (e) {
      if (e.name === 'AbortError' || revision !== searchRevision) return;
      searchResults.textContent = '搜索暂不可用，请重试或进入 TI 列表。';
      searchResults.hidden = false;
    }
  }, 200);
});

function renderResults(j) {
  searchResults.replaceChildren();
  for (const [key, label, kind, badgeText, route] of [
    ['cubes','Cube','cube','C','cube'], ['processes','TI 进程','ti','T','process'], ['chores','Chore','chore','H','chore']
  ]) {
    if (searchInput.dataset.workflow === 'true' && key !== 'processes') continue;
    const items = j[key] || [];
    if (!items.length) continue;
    const heading = document.createElement('div'); heading.className = 'sr-group'; heading.textContent = label;
    searchResults.append(heading);
    for (const name of items) {
      const link = document.createElement('a'); link.className = 'sr-item';
      link.href = searchInput.dataset.workflow === 'true' ? (searchInput.dataset.architecture === 'true' ? '/architecture?name=' : '/workflow?name=')+encodeURIComponent(name)+'&analyze=1' : '/explorer/' + route + '/' + encodeURIComponent(name);
      const badge = document.createElement('span'); badge.className = 'sr-badge ' + kind; badge.textContent = badgeText;
      link.append(badge, document.createTextNode(name)); searchResults.append(link);
    }
  }
  if (!searchResults.childNodes.length) searchResults.textContent = '无匹配结果';
  searchResults.hidden = false;
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('.search-hero')) searchResults.hidden = true;
});
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') searchResults.hidden = true;
  if (e.key === 'Enter') {
    if (searchResults.hidden) return;
    const first = searchResults.querySelector('.sr-item');
    if (first) { e.preventDefault(); location.href = first.href; }
  }
});

// ============ MDX 反查 ============
const mdxInput = document.getElementById('mdx-input');
const mdxBtn = document.getElementById('mdx-btn');
const mdxResult = document.getElementById('mdx-result');
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function hashColor(name) {
  let h = 0;
  for (const ch of String(name)) h = (h * 31 + ch.codePointAt(0)) & 0xFFFFFFFF;
  return 'src-c' + (h % 10);
}

async function traceMdx() {
  const mdx = mdxInput.value.trim();
  if (!mdx) { mdxInput.focus(); return; }
  mdxBtn.disabled = true;
  mdxBtn.textContent = '解析中…';
  mdxResult.hidden = false;
  mdxResult.innerHTML = '<div class="muted">正在解析 MDX 并匹配写入点…</div>';
  try {
    const response = await fetch('/api/trace?mdx=' + encodeURIComponent(mdx));
    if (!response.ok) throw new Error('反查暂不可用，请重试');
    const j = await response.json();
    renderTrace(j);
  } catch (e) {
    mdxResult.textContent = '请求失败：' + e.message;
  } finally {
    mdxBtn.disabled = false;
    mdxBtn.textContent = '解析并反查';
  }
}

function fillExample() {
  mdxInput.value = 'SELECT {[Time].[2025]} ON COLUMNS\nFROM [Sales]\nWHERE ([Version].[Actual])';
  mdxInput.focus();
}

function clearMdx() {
  mdxInput.value = '';
  mdxResult.hidden = true;
  mdxResult.innerHTML = '';
  mdxInput.focus();
}

function renderTrace(j) {
  if (!j.cube) {
    mdxResult.innerHTML = '<div class="err">未从 MDX 中解析出 Cube（请确认包含 FROM [Cube]）。</div>';
    return;
  }
  let html = '';

  const dims = j.dimensions || [];
  const members = j.members || {};
  html += '<div class="trace-summary">';
  html += `<div class="trace-cube">目标 Cube：<a class="cube-chip" href="/explorer/cube/${encodeURIComponent(j.cube)}">${escapeHtml(j.cube)}</a></div>`;
  if (dims.length) {
    html += '<div class="trace-dims">';
    html += dims.map(d => {
      const elems = members[d] || [];
      const v = elems.length ? elems.map(escapeHtml).join(', ') : '<span class="muted">（未限定）</span>';
      return `<span class="trace-dim"><b>${escapeHtml(d)}</b> = ${v}</span>`;
    }).join('');
    html += '</div>';
  } else {
    html += '<div class="muted small">未解析出维度筛选条件</div>';
  }
  html += '</div>';

  const cands = j.candidates || [];
  html += `<div class="trace-count">匹配到 <b>${cands.length}</b> 个可能的写入 TI${j.relaxed ? '（宽松匹配）' : ''}</div>`;

  if (!cands.length) {
    html += '<div class="muted">当前解析范围未找到匹配的写入候选；不能据此证明没有其他写入。</div>';
    mdxResult.innerHTML = html;
    return;
  }

  html += '<div class="trace-list">';
  cands.forEach(c => {
    const score = Number.isFinite(c.score) ? c.score : null;
    const pct = score === null ? '' : `<span class="trace-score ${score >= 100 ? 'full' : score >= 60 ? 'high' : 'mid'}">${score}%</span>`;
    const dimBadges = (c.matched_dims || []).map(d => `<span class="dim-badge hit">${escapeHtml(d)} 命中</span>`)
      .concat((c.variable_dims || []).map(d => `<span class="dim-badge var">${escapeHtml(d)} 变量?</span>`)).join('');
    const srcs = (c.source_cubes || []).map(s => `<a class="cube-chip ${hashColor(s)}" href="/explorer/cube/${encodeURIComponent(s)}">${escapeHtml(s)}</a>`).join(' ');
    const wpCount = c.write_point_count > 1 ? `<span class="trace-wp-count">${escapeHtml(c.write_point_count)} 个写入点</span>` : '';
    html += `<div class="trace-item">
      <div class="trace-item-head">
        ${pct}
        <a href="/explorer/process/${encodeURIComponent(c.process)}">${escapeHtml(c.process)}</a>
        ${wpCount}
      </div>
      <div class="trace-item-meta">
        <span class="muted small">${escapeHtml(c.operation_human || c.operation)}</span>
        ${c.conditions_human && c.conditions_human.length ? '<span class="muted small">条件：' + c.conditions_human.map(escapeHtml).join('；') + '</span>' : ''}
      </div>
      <div class="trace-item-dims">${dimBadges || '<span class="muted small">无维度约束</span>'}</div>
      ${srcs ? '<div class="trace-item-src">关联读取 Cube（未证明值流）：' + srcs + '</div>' : ''}
    </div>`;
  });
  html += '</div>';

  mdxResult.innerHTML = html;
}
