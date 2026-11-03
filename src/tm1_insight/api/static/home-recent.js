/* Home: recent objects from this browser only. Nothing is sent anywhere. */
(function () {
  'use strict';
  var host = document.getElementById('home-recent');
  var list = document.getElementById('home-recent-list');
  if (!host || !list) return;
  var items = [];
  try { items = JSON.parse(localStorage.getItem('tm1-recent-objects') || '[]'); } catch (e) { items = []; }
  items = (items || []).filter(function (x) { return x && x.kind && x.name; }).slice(0, 8);
  if (!items.length) return;
  items.forEach(function (item) {
    var a = document.createElement('a');
    a.className = 'catalog-item';
    a.href = '/object/' + item.kind + '/' + encodeURIComponent(item.name);
    var name = document.createElement('span');
    name.textContent = item.name;
    var kind = document.createElement('b');
    kind.textContent = item.kind === 'process' ? 'TI' : 'Cube';
    a.append(name, kind);
    list.append(a);
  });
  host.hidden = false;
})();
