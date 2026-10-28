/* Shared presentation for the Cube writer card and lineage write points. */
(function () {
  'use strict';
  function element(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (cls) node.className = cls;
    return node;
  }
  function writePoint(options) {
    const card = element('details', undefined, 'wp-item');
    card.open = options.open !== false;
    const summary = element('summary', undefined, 'wp-summary');
    summary.append(element('span', options.operation || '写入', 'tag op'));
    if (options.summary) summary.append(element('span', options.summary, 'wp-diff'));
    if (options.conditions?.length) summary.append(element('span', '有条件', 'tag'));
    card.append(summary);
    if (options.conditions?.length) {
      const conditions = element('div', undefined, 'cond');
      conditions.append(element('strong', '写入前提：'));
      options.conditions.forEach(value => conditions.append(element('span', value, 'cond-text')));
      card.append(conditions);
    }
    if (options.valueExpression) card.append(element('p', (options.valueLabel || '写入值') + '：' + options.valueExpression));
    const coordinates = (options.coordinates || []).filter(c => c.dimension && c.value != null && c.value !== '' && c.kind !== 'UNKNOWN');
    if (coordinates.length) {
      const wrap = element('div', undefined, 'table-wrap');
      const table = element('table', undefined, 'table');
      const head = element('thead'), header = element('tr');
      ['#', options.coordinateLabel || '写入维度', '来源变量', '取值 / 表达式', '坐标类型'].forEach(label => header.append(element('th', label)));
      head.append(header); table.append(head);
      const body = element('tbody');
      coordinates.forEach(coordinate => {
        const row = element('tr');
        row.append(element('td', coordinate.position ?? '—', 'dim-idx'));
        const dimension = element('td'); dimension.append(element('strong', coordinate.dimension)); row.append(dimension);
        const expression = element('td');
        if (coordinate.expression && coordinate.kind !== 'FIXED') expression.append(element('code', coordinate.expression, 'var-inline'));
        row.append(expression);
        const value = element('td'); value.append(element(coordinate.kind === 'FIXED' ? 'span' : 'code', coordinate.value, coordinate.kind === 'FIXED' ? 'const-lit' : 'var-local')); row.append(value);
        row.append(element('td', coordinate.kind === 'FIXED' ? '固定筛选' : '动态表达式', 'muted small'));
        body.append(row);
      });
      table.append(body); wrap.append(table); card.append(wrap);
    }
    return card;
  }
  window.TM1WritePointCard = {writePoint};
})();
