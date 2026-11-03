/* Object page behaviour: only glue. Each view keeps its own script. */
(function () {
  'use strict';
  var copy = document.getElementById('object-copy');
  var pre = document.getElementById('object-handoff-text');
  if (copy && pre) {
    copy.addEventListener('click', function () {
      var text = pre.textContent || '';
      var status = document.getElementById('object-copy-status');
      function done(ok) { if (status) status.textContent = ok ? '已复制' : '复制失败，请手动选择'; }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      } else {
        var range = document.createRange();
        range.selectNodeContents(pre);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        try { done(document.execCommand('copy')); } catch (e) { done(false); }
      }
    });
  }

  // Formation view: the answer is the point of the tab, so ask for it once.
  var form = document.querySelector('[data-formation-autostart="true"]');
  if (form && typeof form.requestSubmit === 'function') {
    setTimeout(function () { form.requestSubmit(); }, 0);
  }

  // Recent objects: the only thing worth remembering across sessions.
  var page = document.querySelector('.object-page');
  if (page && page.dataset.name) {
    try {
      var key = 'tm1-recent-objects';
      var list = JSON.parse(localStorage.getItem(key) || '[]');
      var entry = { kind: page.dataset.kind, name: page.dataset.name };
      list = [entry].concat(list.filter(function (x) { return !(x && x.kind === entry.kind && x.name === entry.name); })).slice(0, 8);
      localStorage.setItem(key, JSON.stringify(list));
    } catch (e) {}
  }
})();
