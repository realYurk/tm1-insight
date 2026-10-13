/* Reuses a single server job on navigation; count-based progress, no simulated %. */
(() => {
  const panel = document.getElementById('dimension-index');
  if (!panel) return;
  const status = document.getElementById('dimension-index-status');
  const progress = document.getElementById('dimension-index-progress');
  const cancel = document.getElementById('dimension-index-cancel');
  const retry = document.getElementById('dimension-index-retry');
  let task = null, timer = null, stopped = false, cancelled = false, failures = 0;
  async function request(url, options) {
    const response = await fetch(url, {cache: 'no-store', ...options});
    let value = {}; try { value = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(value.error || value.detail || '索引状态确认失败，请重试。');
    return value;
  }
  function terminal(message) {
    clearTimeout(timer); cancel.disabled = true; retry.hidden = false;
    progress.hidden = true; status.textContent = message;
  }
  function render(state) {
    if (stopped) return;
    if (state.status === 'completed') { window.location.reload(); return; }
    if (state.status === 'cancelled') { terminal('索引已取消，原始模型未改动。'); return; }
    if (state.status === 'failed') { terminal(state.error || '建立索引失败，请检查本地空间或重试。'); return; }
    const stage = state.status === 'queued' ? '等待本地索引任务' : state.stage;
    status.textContent = `${cancelled ? '已请求取消，将在当前索引操作结束后停止。' : ''}第 ${state.stage_index} / ${state.stages_total} 阶段 · ${stage}` +
      (state.total == null ? ' · 正在读取，尚无可计数进度' : ` · ${state.current} / ${state.total} 条`);
    progress.hidden = false;
    if (state.total > 0) { progress.max = state.total; progress.value = state.current; }
    else progress.removeAttribute('value');
    cancel.disabled = cancelled;
    timer = setTimeout(poll, 1000);
  }
  async function poll() {
    if (stopped || !task) return;
    try { const state = await request(`/api/dimensions/index/${task}`); failures = 0; render(state); }
    catch (error) {
      if (++failures < 3 && !stopped) { status.textContent = '暂时无法确认索引状态，正在重试…'; timer = setTimeout(poll, 1500); }
      else terminal(error.message);
    }
  }
  async function start() {
    if (stopped) return;
    clearTimeout(timer); cancelled = false; failures = 0; retry.hidden = true;
    progress.hidden = false; progress.removeAttribute('value'); cancel.disabled = true;
    status.textContent = '正在准备当前维度的本地检索索引…';
    try {
      const state = await request('/api/dimensions/index', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: panel.dataset.name, source: panel.dataset.source})});
      task = state.task_id; render(state);
    } catch (error) { terminal(error.message); }
  }
  cancel.addEventListener('click', async () => {
    if (!task || stopped) return;
    cancelled = true; cancel.disabled = true;
    status.textContent = '正在请求取消；将在当前索引操作结束后停止。';
    try { await request(`/api/dimensions/index/${task}/cancel`, {method: 'POST'}); }
    catch (error) { terminal(error.message); }
  });
  retry.addEventListener('click', start);
  window.addEventListener('tm1-source-change', () => { stopped = true; terminal('数据源已变化，请重新打开维度页。'); retry.hidden = true; });
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
  start();
})();
