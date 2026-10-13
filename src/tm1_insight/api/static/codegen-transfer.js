/* Structure-confirmed transfer workflow. All results remain unexecuted TI drafts. */
const transferWorkflow = (() => {
  const el = id => document.getElementById(id);
  const pair = () => [el('tr-src').value.trim(), el('tr-tgt').value.trim()];
  let loaded = null, revision = 0, busy = false;
  function sync() {
    el('tr-load').disabled = busy || pair().some(value => !value);
    el('tr-generate').disabled = busy || !loaded;
  }
  function invalidate(message = 'Cube 或配置已改变，请重新加载维度结构。') {
    revision++;
    loaded = null;
    genState.tr = null;
    el('tr-filter-card').hidden = true;
    el('tr-output').hidden = true;
    el('tr-step-status').textContent = message;
    sync();
  }
  ['tr-src', 'tr-tgt'].forEach(id => {
    // Suggestions set the input value and emit change rather than input.
    ['input', 'change'].forEach(event => el(id).addEventListener(event, () => invalidate()));
  });
  ['tr-op', 'global-prefix'].forEach(id => el(id).addEventListener('input', () => {
    revision++;
    el('tr-output').hidden = true;
  }));
  el('tr-filter-card').addEventListener('input', () => {
    revision++;
    el('tr-output').hidden = true;
  });
  window.addEventListener('tm1-source-change', () => invalidate('数据源已改变，请重新加载维度结构。'));
  window.addEventListener('pageshow', event => {
    if (event.persisted) invalidate('返回页面后请重新加载维度结构，确认当前数据源。');
  });
  async function load() {
    invalidate('正在读取源与目标 Cube 的维度顺序…');
    const [src, tgt] = pair(), version = revision;
    if (!src || !tgt) throw new Error('请先填写源 Cube 和目标 Cube。');
    busy = true; sync();
    try {
      const results = await Promise.all([src, tgt].map(async cube => {
        const response = await requestCodegen('/api/codegen/cube-dims', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({cube})
        });
        return response.json();
      }));
      if (version !== revision) return;
      const [source, target] = results;
      if (source.source !== target.source) throw new Error('数据源在加载期间已变化，请重试。');
      loaded = {src, tgt, structure: {source: source.source, src_dims: source.dims, tgt_dims: target.dims}};
      renderFilterList('tr-src-filters', source.dims);
      renderFilterList('tr-tgt-filters', target.dims);
      el('tr-filter-card').hidden = false;
      el('tr-structure-evidence').textContent = `${src}（${source.dims.length} 维）→ ${tgt}（${target.dims.length} 维）。依据当前离线模型记录的维度顺序；同名维度只是坐标复用候选，尚未验证元素或业务含义。`;
      el('tr-step-status').textContent = '维度结构已加载。核对两侧顺序与筛选后，可生成 TI 草稿。未勾选筛选时清目标范围可能覆盖整个 Cube。';
    } catch (error) {
      if (version === revision) invalidate(error.message || '维度加载失败，请重试。');
      throw error;
    } finally { busy = false; sync(); }
  }
  async function generate() {
    const [src, tgt] = pair(), version = revision;
    if (!loaded || loaded.src !== src || loaded.tgt !== tgt) {
      invalidate(); throw new Error('请先加载当前 Cube 的维度结构。');
    }
    busy = true; sync();
    try {
      const response = await requestCodegen('/api/codegen/data-transfer', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({src_cube: src, tgt_cube: tgt, structure: loaded.structure,
          prefix: getGlobalPrefix(), operation: el('tr-op').value,
          src_filters: readFilters('tr-src-filters'), tgt_filters: readFilters('tr-tgt-filters'),
          params: deriveParams('tr-src-filters')})
      });
      const result = await response.json();
      if (version !== revision) return;
      genState.tr = {prolog: result.prolog, metadata: result.metadata, data: result.data, epilog: result.epilog};
      el('tr-mapping').innerHTML = '<div class="cg-map-title">按目标维度顺序排列 · 静态坐标候选，未验证业务映射</div>' +
        result.mapping.map(m => `<span class="cg-map-item ${m.auto ? 'auto' : 'todo'}">${escapeCodegenHTML(m.tgt_dim)}${m.auto ? ' · 同名复用' : ' · UNKNOWN，需配置'}</span>`).join('');
      showOutput('tr-output', 'tr');
      bindOutputSegs('tr-output', 'tr-code', 'tr');
      el('tr-step-status').textContent = '草稿已生成，软件未执行 TI。请核对清理范围、缺失映射及框架依赖，再验证结果。';
    } catch (error) {
      if (version === revision) invalidate(error.message || '生成失败，请重新加载结构。');
      throw error;
    } finally { busy = false; sync(); }
  }
  sync();
  return {load, generate, sync};
})();
