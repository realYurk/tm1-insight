/* Cube 数据形成专项视图：默认优先展示 Rule 计算关系，整合 TI 写入与切面匹配。
 *
 * 拉取 /api/cube/{cube}/formation，客户端渲染：
 *   1. Mermaid 数据形成图（Rule 计算 / TI 写入 / 维度汇总 三类节点，可点击下钻）
 *   2. 紧凑规则表（目标区域 | 表达式 | 引用指标 | 条件 | 固定成员）
 *   3. MDX 切面输入 + 动态匹配结果
 *   4. 源码行号下钻
 *
 * 复用全局 window.TM1Mermaid 统一组件（离线渲染）。纯只读，不连接 TM1 Server。
 */
(function () {
  'use strict';
  function el(tag, cls, text, parent) {
    var x = document.createElement(tag);
    if (cls) x.className = cls;
    if (text != null) x.textContent = text;
    if (parent) parent.append(x);
    return x;
  }

  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function mmLabel(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/"/g, '#quot;')
      .replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/`/g, "'").replace(/\n/g, ' ');
  }

  function mount() {
    var root = document.getElementById('cube-formation');
    if (!root) return;
    var cubeName = root.dataset.cube;
    if (!cubeName) return;

    // 顶部工具栏
    var head = el('div', 'cf-head', null, root);
    el('h2', null, '数据形成 · Rule 计算优先', head);
    el('p', 'cf-sub muted', '先看这个 Cube 的值由哪些 Rule 声明式计算、哪些 TI 写入、哪些可能由维度汇总形成；再沿切面核对源码。', head);

    var toolbar = el('div', 'cf-toolbar', null, head);
    var mdxInput = el('input', 'cf-mdx-input', null, toolbar);
    mdxInput.type = 'text';
    mdxInput.placeholder = '输入 MDX 或切面，如 Scenario=SP75、Version=WIP、Year=All Years…';
    var mdxBtn = el('button', 'btn primary', '应用切面', toolbar);
    var mdxClear = el('button', 'btn ghost', '清除', toolbar);

    var status = el('div', 'cf-status muted', '加载中…', head);

    // 图表容器
    var chartCard = el('div', 'card', null, root);
    el('h3', 'cf-section-title', '数据形成图', chartCard);
    var chartMount = el('div', 'cf-chart', null, chartCard);

    // 规则表容器
    var ruleCard = el('div', 'card', null, root);
    el('h3', 'cf-section-title', 'Rule 计算关系', ruleCard);
    var ruleTable = el('div', 'cf-rule-table', null, ruleCard);

    // TI 写入容器
    var tiCard = el('div', 'card', null, root);
    el('h3', 'cf-section-title', 'TI 写入点', tiCard);
    var tiTable = el('div', 'cf-ti-table', null, tiCard);

    // 切面匹配容器
    var sliceCard = el('div', 'card', null, root);
    el('h3', 'cf-section-title', '切面匹配', sliceCard);
    var sliceBody = el('div', 'cf-slice', null, sliceCard);

    // 边界声明
    var limCard = el('details', 'card cf-limits', null, root);
    el('summary', null, '分析边界与限制', limCard);
    var limBody = el('div', null, null, limCard);

    var currentMdx = '';
    var mermaidInstance = null;

    function load(mdx) {
      status.textContent = '加载中…';
      var url = '/api/cube/' + encodeURIComponent(cubeName) + '/formation';
      if (mdx) url += '?mdx=' + encodeURIComponent(mdx);
      fetch(url).then(function (r) { return r.json(); }).then(function (data) {
        render(data);
      }).catch(function (e) {
        status.textContent = '加载失败：' + e.message;
      });
    }

    function render(data) {
      status.textContent = data.rule_count + ' 条 Rule · ' + data.feeder_count + ' 条 Feeder · ' +
        data.ti_writes.length + ' 个写入 TI · ' + data.unknown_count + ' 处 UNKNOWN';
      renderChart(data);
      renderRules(data);
      renderTi(data);
      renderSlice(data);
      renderLimits(data);
    }

    // ---- Mermaid 数据形成图 ----
    // 大图降噪：引用 Cube 去重聚合；Rule/TI 超限时截断并标注总数。
    var MAX_RULE_NODES = 25;
    var MAX_TI_NODES = 12;
    var MAX_REF_NODES = 15;

    function renderChart(data) {
      // 旧实例必须销毁，否则重渲染会叠加多个图表（多实例组件不自动清理）
      if (mermaidInstance && mermaidInstance.destroy) {
        try { mermaidInstance.destroy(); } catch (e) { /* 忽略 */ }
      }
      mermaidInstance = null;
      chartMount.replaceChildren();

      // 扇入结构（多 Rule/TI 汇入本 Cube）纵向布局更可读
      var lines = ['flowchart TB'];
      var idMap = {};
      var nodeIdx = 0;
      var refIds = {}; // 引用 Cube 去重
      var refCount = 0;
      var idToInfo = {}; // 稳定 id → {kind, rule}

      function addNode(key, label, cls, info) {
        var id = 'n' + (nodeIdx++);
        lines.push('  ' + id + '["' + mmLabel(label) + '"]');
        idMap[id] = key;
        if (info) idToInfo[id] = info;
        return id;
      }
      function refNode(cubeName) {
        if (refIds[cubeName]) return refIds[cubeName];
        if (refCount >= MAX_REF_NODES) return null;
        refCount++;
        var id = addNode('ref:' + cubeName, '引用: ' + cubeName, null, { kind: 'ref', cube: cubeName });
        refIds[cubeName] = id;
        return id;
      }

      // 根节点
      var rootId = addNode('root', data.cube + ' · 本 Cube', null, { kind: 'root' });

      // Rule 计算节点（限量 + 引用去重）
      var ruleShown = Math.min(data.rules.length, MAX_RULE_NODES);
      for (var i = 0; i < ruleShown; i++) {
        var r = data.rules[i];
        var target = r.target || ('Rule L' + (r.line_start || i));
        var shortTarget = target.length > 36 ? target.slice(0, 36) + '…' : target;
        var rid = addNode('rule:' + r.line_start, 'Rule L' + r.line_start + ': ' + shortTarget, null, { kind: 'rule', rule: r });
        lines.push('  ' + rid + ' -->|"计算"| ' + rootId);
        var seenRefs = {};
        r.db_references.forEach(function (ref) {
          var cubeName = ref.cube || (ref.raw || '').slice(0, 30) || '?';
          if (seenRefs[cubeName]) return;
          seenRefs[cubeName] = true;
          var refId = refNode(cubeName);
          if (refId) lines.push('  ' + refId + ' -.->|"引用"| ' + rid);
        });
      }
      if (data.rules.length > ruleShown) {
        var moreId = addNode('rule-more', '… 其余 ' + (data.rules.length - ruleShown) + ' 条 Rule 见下方表格', null, { kind: 'more' });
        lines.push('  ' + moreId + ' -->|"计算"| ' + rootId);
      }

      // TI 写入节点（限量；来源 Cube 去重聚合）
      var tiShown = Math.min(data.ti_writes.length, MAX_TI_NODES);
      for (var j = 0; j < tiShown; j++) {
        var w = data.ti_writes[j];
        var shortName = w.process.length > 40 ? w.process.slice(0, 40) + '…' : w.process;
        var wid = addNode('ti:' + w.process, 'TI: ' + shortName, null, { kind: 'ti', process: w.process });
        lines.push('  ' + wid + ' ==>|"写入"| ' + rootId);
        var seenSrc = {};
        w.writes.forEach(function (wp) {
          wp.source_cubes.forEach(function (s) {
            if (seenSrc[s]) return;
            seenSrc[s] = true;
            var sid = refNode(s);
            if (sid) lines.push('  ' + sid + ' -.->|"读取"| ' + wid);
          });
        });
      }
      if (data.ti_writes.length > tiShown) {
        var moreTi = addNode('ti-more', '… 其余 ' + (data.ti_writes.length - tiShown) + ' 个写入 TI 见下方列表', null, { kind: 'more' });
        lines.push('  ' + moreTi + ' ==>|"写入"| ' + rootId);
      }

      var code = lines.join('\n') + '\n';
      if (window.TM1Mermaid) {
        mermaidInstance = window.TM1Mermaid.mount(chartMount, {
          code: code,
          title: data.cube + ' · 数据形成',
          idMap: idMap,
          onNodeClick: function (id) {
            var info = idToInfo[id];
            if (!info) return;
            if (info.kind === 'rule') scrollToRule(info.rule.line_start);
            else if (info.kind === 'ti') location.href = '/explorer/process/' + encodeURIComponent(info.process);
            else if (info.kind === 'ref') location.href = '/explorer/cube/' + encodeURIComponent(info.cube);
          },
        });
      } else {
        el('pre', 'cf-fallback', code, chartMount);
      }
    }

    function scrollToRule(lineStart) {
      if (lineStart == null) return;
      var rows = ruleTable.querySelectorAll('.cf-rule-row');
      rows.forEach(function (row) {
        if (row.dataset.line == String(lineStart)) {
          row.scrollIntoView({ block: 'center' });
          row.classList.add('cf-flash');
          setTimeout(function () { row.classList.remove('cf-flash'); }, 2000);
        }
      });
    }

    // ---- 紧凑规则表 ----
    function renderRules(data) {
      ruleTable.replaceChildren();
      if (!data.rules.length) {
        el('p', 'muted', '（无 Rule）', ruleTable);
        return;
      }
      var table = el('table', 'table cf-table', null, ruleTable);
      var thead = el('thead', null, null, table);
      var tr = el('tr', null, null, thead);
      ['行号', '目标区域', '计算表达式', '引用指标', '条件', '固定成员'].forEach(function (h) {
        el('th', null, h, tr);
      });
      var tbody = el('tbody', null, null, table);
      data.rules.forEach(function (r) {
        var row = el('tr', 'cf-rule-row', null, tbody);
        row.dataset.line = String(r.line_start || '');
        row.title = '点击查看源码行';
        row.style.cursor = 'pointer';
        row.addEventListener('click', function () { showRuleSource(r); });

        var line = r.line_end && r.line_end !== r.line_start
          ? (r.line_start + '–' + r.line_end) : String(r.line_start || '');
        el('td', 'cf-line mono', line, row);

        var tdTarget = el('td', null, null, row);
        el('code', 'var-inline', esc(r.target || ''), tdTarget);
        if (r.status && r.status !== 'PARSED') {
          el('span', 'tag warn', r.status, tdTarget);
        }

        var tdExpr = el('td', null, null, row);
        el('code', 'var-inline', esc(r.expression || ''), tdExpr);

        var tdRef = el('td', null, null, row);
        r.db_references.forEach(function (ref) {
          var a = el('a', 'cube-chip flow-source', ref.cube || '?', tdRef);
          a.href = '/explorer/cube/' + encodeURIComponent(ref.cube || '');
          a.addEventListener('click', function (e) { e.stopPropagation(); });
        });
        if (!r.db_references.length) el('span', 'muted', '—', tdRef);

        var tdCond = el('td', null, null, row);
        if (r.conditions.length) {
          el('span', 'tag', r.conditions.length + ' 条件', tdCond);
        } else {
          el('span', 'muted', '—', tdCond);
        }

        var tdFixed = el('td', null, null, row);
        r.fixed_members.slice(0, 3).forEach(function (m) {
          el('span', 'tag dim-mini', m, tdFixed);
        });
        if (r.fixed_members.length > 3) el('span', 'muted', '…', tdFixed);
        if (r.dynamic_members.length) el('span', 'muted', '含动态', tdFixed);
        if (!r.fixed_members.length && !r.dynamic_members.length) el('span', 'muted', '—', tdFixed);
      });
    }

    function showRuleSource(r) {
      // 在规则表下方弹出源码下钻
      var existing = ruleTable.querySelector('.cf-source-panel');
      if (existing) existing.remove();
      var panel = el('div', 'cf-source-panel', null, ruleTable);
      var head = el('div', 'cf-source-head', null, panel);
      el('strong', null, 'Rule 原始源码（L' + r.line_start + (r.line_end && r.line_end !== r.line_start ? '–' + r.line_end : '') + '）', head);
      var close = el('button', 'btn ghost btn-sm', '关闭', head);
      close.addEventListener('click', function () { panel.remove(); });
      el('pre', 'code', r.raw, panel);
      // 引用指标链接
      if (r.db_references.length) {
        var refs = el('div', 'cf-source-refs', null, panel);
        el('span', 'muted', '引用 Cube：', refs);
        r.db_references.forEach(function (ref) {
          var a = el('a', 'cube-chip flow-source', ref.cube || '?', refs);
          a.href = '/explorer/cube/' + encodeURIComponent(ref.cube || '');
        });
      }
    }

    // ---- TI 写入表 ----
    function renderTi(data) {
      tiTable.replaceChildren();
      if (!data.ti_writes.length) {
        el('p', 'muted', '（无 TI 写入点，可能仅由 Rule 计算或维度汇总形成）', tiTable);
        return;
      }
      data.ti_writes.forEach(function (w) {
        var det = el('details', 'cf-ti', null, tiTable);
        var sum = el('summary', null, null, det);
        el('strong', null, w.process, sum);
        el('span', 'tag op', w.writes.length + ' 写入点', sum);
        var a = el('a', 'btn ghost btn-sm', 'TI 源码', sum);
        a.href = '/explorer/process/' + encodeURIComponent(w.process);
        a.addEventListener('click', function (e) { e.stopPropagation(); });

        var body = el('div', 'cf-ti-body', null, det);
        w.writes.forEach(function (wp) {
          var row = el('div', 'cf-ti-wp', null, body);
          el('span', 'tag op', wp.operation || '写入', row);
          wp.fixed_members.forEach(function (m) { el('span', 'tag dim-mini', m, row); });
          wp.dynamic_members.forEach(function (m) { el('span', 'tag', m, row); });
          wp.conditions.forEach(function (c) { el('span', 'cond-text', c, row); });
          wp.source_cubes.forEach(function (s) {
            var src = el('a', 'cube-chip flow-source', s, row);
            src.href = '/explorer/cube/' + encodeURIComponent(s);
          });
        });
      });
    }

    // ---- 切面匹配 ----
    function renderSlice(data) {
      sliceBody.replaceChildren();
      if (!data.mdx_slice) {
        el('p', 'muted', '输入 MDX 或切面后，这里展示哪些 Rule/TI 写入点命中该切面。仅做本地静态匹配，不连接服务器。', sliceBody);
        return;
      }
      var s = data.mdx_slice;
      if (s.members && Object.keys(s.members).length) {
        var dims = el('div', 'cf-slice-dims', null, sliceBody);
        el('span', 'muted', '反解切面：', dims);
        Object.keys(s.members).forEach(function (d) {
          el('span', 'tag dim-mini', d + '=' + s.members[d].join('/'), dims);
        });
      } else {
        el('p', 'muted', '无法从该 MDX 反解出维度切面；不伪造匹配结果。', sliceBody);
      }
      el('p', 'cf-slice-count', '命中 ' + s.matched_count + ' 个写入候选' + (s.relaxed ? '（宽松匹配）' : ''), sliceBody);
      if (s.candidates && s.candidates.length) {
        var list = el('div', 'cf-slice-list', null, sliceBody);
        s.candidates.slice(0, 20).forEach(function (c) {
          var item = el('div', 'cf-slice-item', null, list);
          var a = el('a', 'cube-chip flow-target', c.process, item);
          a.href = '/explorer/process/' + encodeURIComponent(c.process);
          el('span', 'tag op', c.operation_human || '', item);
          el('span', 'muted', (c.match_mode || '') + (c.score != null ? ' · ' + c.score + '%' : ''), item);
        });
      }
    }

    function renderLimits(data) {
      limBody.replaceChildren();
      data.limitations.forEach(function (l) {
        el('p', 'muted small', '· ' + l, limBody);
      });
    }

    mdxBtn.addEventListener('click', function () {
      currentMdx = mdxInput.value.trim();
      load(currentMdx);
    });
    mdxClear.addEventListener('click', function () {
      mdxInput.value = '';
      currentMdx = '';
      load('');
    });
    mdxInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { currentMdx = mdxInput.value.trim(); load(currentMdx); }
    });

    // 初始加载（不带切面）
    load('');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
