/* Local Knowledge workbench. Bounded rendering; background work survives navigation. */
(function () {
  'use strict';
  const byId = id => document.getElementById(id);
  const form = byId('knowledge-form');
  if (!form) return;
  let taskId = null;
  let section = 'processes';
  let offset = 0;
  let total = 0;
  let resultRequest = 0;
  let previewRequest = 0;
  let pollTimer = null;
  const pageSize = 50;

  async function request(url, body) {
    const response = await fetch(url, body === undefined ? {cache: 'no-store'} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    if (!response.ok) {
      let message = '请求失败，请重试。';
      try { message = (await response.json()).error || message; } catch (_) {}
      throw new Error(message);
    }
    return response;
  }

  function error(message) {
    byId('knowledge-error').textContent = message || '';
    byId('knowledge-error').hidden = !message;
  }

  function options() {
    const scope = {};
    ['processes', 'cubes', 'dimensions', 'rules'].forEach(kind => {
      scope[kind] = form.elements[kind].checked;
    });
    return {prefix: byId('knowledge-query').value.trim(), scope,
      match_mode: byId('knowledge-mode').value,
      include_dependencies: byId('knowledge-dependencies').checked,
      include_lineage: byId('knowledge-lineage').checked};
  }

  function busy(value) {
    Array.from(form.elements).forEach(control => { control.disabled = value; });
    byId('knowledge-start').textContent = value ? '分析进行中…' : '开始分析';
    form.setAttribute('aria-busy', String(value));
  }

  async function preview() {
    const id = ++previewRequest;
    error('');
    byId('knowledge-scope').textContent = '正在发现对象与直接关联…';
    try {
      const result = await (await request('/api/knowledge/scope', options())).json();
      if (id !== previewRequest) return;
      byId('knowledge-scope').textContent = Object.entries(result.matched)
        .map(([kind, count]) => `${kind}: ${count}`).join(' · ') + ' · 范围规模：' + result.estimated_analysis;
    } catch (e) { if (id === previewRequest) error(e.message); }
  }

  function renderProgress(state) {
    byId('knowledge-task').hidden = false;
    byId('knowledge-stage').textContent = `${state.stage_index}/${state.stages_total} · ${state.stage}`;
    const progress = byId('knowledge-progress');
    if (state.total > 0) {
      progress.max = state.total;
      progress.value = state.current;
      progress.setAttribute('aria-valuetext', `${state.current} / ${state.total}`);
    } else {
      progress.removeAttribute('value');
      progress.setAttribute('aria-valuetext', '当前阶段无法计算百分比');
    }
    byId('knowledge-timing').textContent = (state.total > 0 ? `${state.current} / ${state.total} · ` : '') +
      `已用 ${state.elapsed_seconds.toFixed(1)} 秒` + (state.cached ? ' · 已复用本地分析缓存' : '');
    byId('knowledge-cancel').hidden = !['running', 'queued'].includes(state.status);
  }

  async function poll() {
    clearTimeout(pollTimer);
    try {
      const state = await (await request(`/api/knowledge/tasks/${taskId}`)).json();
      renderProgress(state);
      if (state.status === 'completed') {
        busy(false);
        await results();
      } else if (state.status === 'failed' || state.status === 'cancelled') {
        busy(false);
        error(state.error || state.message);
        sessionStorage.removeItem('tm1-knowledge-task');
      } else { pollTimer = setTimeout(poll, 500); }
    } catch (e) {
      busy(false); error(e.message);
      sessionStorage.removeItem('tm1-knowledge-task');
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const body = options();
    error(''); busy(true);
    ++previewRequest;
    byId('knowledge-scope').textContent = `分析范围：${body.prefix} · ${body.match_mode === 'keyword' ? '名称包含关键词' : '名称前缀'}`;
    byId('knowledge-output').hidden = true;
    byId('knowledge-task').hidden = false;
    byId('knowledge-stage').textContent = '正在提交本地后台分析…';
    byId('knowledge-progress').removeAttribute('value');
    try {
      const state = await (await request('/api/knowledge/tasks', body)).json();
      taskId = state.task_id; offset = 0; section = 'processes';
      sessionStorage.setItem('tm1-knowledge-task', JSON.stringify({taskId, body}));
      poll();
    } catch (e) { busy(false); error(e.message); }
  });

  function cell(row, value) {
    const td = document.createElement('td');
    td.textContent = value == null ? '—' : String(value);
    row.appendChild(td);
    return td;
  }

  function sequence(values) {
    return values.slice(0, 12).join(' → ') + (values.length > 12 ? ` …（${values.length} 项）` : '');
  }

  function processCell(row, name) {
    const td = cell(row, '');
    const link = document.createElement('a');
    link.href = '/explorer/process/' + encodeURIComponent(name);
    link.textContent = name;
    td.appendChild(link);
  }

  function contextCell(row, kind, name) {
    const td = cell(row, '');
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'btn ghost small'; button.textContent = '导出开发上下文';
    button.addEventListener('click', () => download(button, {context_type: kind, name}));
    td.appendChild(button);
  }

  async function results() {
    const id = ++resultRequest;
    error('');
    byId('knowledge-results').setAttribute('aria-busy', 'true');
    try {
      const result = await (await request(`/api/knowledge/tasks/${taskId}/result?section=${section}&offset=${offset}&limit=${pageSize}`)).json();
      if (id !== resultRequest) return;
      total = result.total;
      byId('knowledge-output').hidden = false;
      byId('knowledge-summary').textContent = Object.entries(result.matched)
        .map(([key, count]) => `${key}: ${count}`).join(' · ') + ` · 关系事实 ${result.fact_count} · 模式候选 ${result.pattern_count}`;
      document.querySelectorAll('[data-section]').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.section === section));
      });
      const table = document.createElement('table'); table.className = 'table';
      const header = document.createElement('thead');
      const heading = document.createElement('tr');
      const headings = section === 'processes' ? ['Process / 原始证据', '观察角色', '源码操作顺序', '开发上下文'] :
        section === 'patterns' ? ['候选标识', '操作签名', '匹配 Process 数', '开发上下文'] :
        section === 'flows' ? ['Process', '读取来源', '写入目标'] : ['Process', '关系', '目标'];
      headings.forEach(label => { const th = document.createElement('th'); th.textContent = label; th.scope = 'col'; heading.appendChild(th); });
      header.appendChild(heading); table.appendChild(header);
      const body = document.createElement('tbody');
      result.items.forEach(item => {
        const row = document.createElement('tr');
        if (section === 'processes') {
          processCell(row, item.process); cell(row, item.observed_role); cell(row, sequence(item.behavior)); contextCell(row, 'process', item.process);
        } else if (section === 'patterns') {
          cell(row, item.id); cell(row, sequence(item.behavior_signature)); cell(row, item.processes.length); contextCell(row, 'pattern', item.id);
        } else if (section === 'flows') {
          processCell(row, item.process); cell(row, item.sources.join(', ')); cell(row, item.targets.join(', '));
        } else { processCell(row, item.process); cell(row, item.operation); cell(row, item.target); }
        body.appendChild(row);
      });
      table.appendChild(body);
      const container = byId('knowledge-results'); container.replaceChildren(table);
      if (!total) { const empty = document.createElement('p'); empty.textContent = '当前范围没有匹配结果。'; container.appendChild(empty); }
      byId('knowledge-page').textContent = total ? `${offset + 1}–${Math.min(offset + pageSize, total)} / ${total}` : '0 / 0';
      byId('knowledge-previous').disabled = offset === 0;
      byId('knowledge-next').disabled = offset + pageSize >= total;
    } catch (e) { error(e.message); }
    finally { if (id === resultRequest) byId('knowledge-results').setAttribute('aria-busy', 'false'); }
  }

  async function download(button, selection = {}) {
    button.disabled = true; error('');
    try {
      const response = await request(`/api/knowledge/tasks/${taskId}/export`, selection);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url;
      link.download = selection.context_type ? 'TM1_Development_Context.zip' : 'TM1_Knowledge.zip';
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { error(e.message); }
    finally { button.disabled = false; }
  }

  byId('knowledge-preview').addEventListener('click', preview);
  form.addEventListener('input', () => {
    ++previewRequest;
    byId('knowledge-scope').textContent = '范围已修改，请重新预览或开始分析。';
  });
  byId('knowledge-cancel').addEventListener('click', async () => {
    try { await request(`/api/knowledge/tasks/${taskId}/cancel`, {}); poll(); }
    catch (e) { error(e.message); }
  });
  byId('knowledge-export').addEventListener('click', event => download(event.currentTarget));
  byId('knowledge-previous').addEventListener('click', () => { offset = Math.max(0, offset - pageSize); results(); });
  byId('knowledge-next').addEventListener('click', () => { offset += pageSize; results(); });
  document.querySelectorAll('[data-section]').forEach(button => button.addEventListener('click', () => {
    section = button.dataset.section; offset = 0; results();
  }));
  window.addEventListener('pagehide', () => { clearTimeout(pollTimer); });
  try {
    const saved = JSON.parse(sessionStorage.getItem('tm1-knowledge-task'));
    if (saved) {
      taskId = saved.taskId;
      byId('knowledge-query').value = saved.body.prefix;
      byId('knowledge-mode').value = saved.body.match_mode || 'prefix';
      ['processes', 'cubes', 'dimensions', 'rules'].forEach(kind => {
        form.elements[kind].checked = !!saved.body.scope[kind];
      });
      byId('knowledge-dependencies').checked = saved.body.include_dependencies;
      byId('knowledge-lineage').checked = saved.body.include_lineage;
      busy(true); poll();
    }
  } catch (_) {}
})();
