/* Workbench Context —— 统一的跨页面浏览上下文记忆（Workbench 1.1）。

   目标：用户从列表进入详情、再跳到其它对象、最后返回时，能恢复到
   「之前的搜索词 / 页码 / 选中对象 / 列选择 / 展开状态」，无需重新搜索。

   设计原则（与存储严格区分）：
   - sessionStorage：会话级浏览状态（搜索词、页码、选中对象、跳转来源、展开状态）。
     关闭浏览器标签后清空，属于「本次会话的浏览轨迹」。
   - localStorage：长期用户偏好（属性列选择、主题、列表密度等）。
     跨会话保留，不随浏览器关闭丢失。
   - 状态按「模型指纹」隔离。不同 TM1 快照 / DuckDB 模型绝不混用同名对象状态。
   - 两类存储都做版本化，旧版本结构一律判过期丢弃，不污染当前逻辑。
   - 只存 UI 浏览状态，绝不存账号 / Token / 敏感业务数据 / 大体积模型内容。

   模型指纹来源：<body data-model-fingerprint="...">（由 base.html 注入，
   对应后端 _process_search_source 的 sha256）。缺失时退化为全局命名空间。

   API：
     WorkbenchContext.fingerprint()              当前模型指纹
     WorkbenchContext.get(key) / set(key, value) / clear(key)        会话状态（按模型隔离 + 版本化）
     WorkbenchContext.preference(key) / setPreference(key, value)    长期偏好（localStorage，不按模型，版本化）
     WorkbenchContext.rememberList(page, state) / recallList(page)   列表位置（含选中对象）
     WorkbenchContext.rememberJump(fromPage, fromState) / recallJump(page)   跨对象跳转来源
*/
(function () {
  'use strict';
  var VERSION = 'wb2';                    // 存储版本升级：旧 wb1 结构自动失效
  var SESSION_PREFIX = 'tm1-wb-session-';
  var PREF_PREFIX = 'tm1-wb-pref-';

  function fingerprint() {
    var fp = document.body && document.body.getAttribute('data-model-fingerprint');
    return fp && fp.trim() ? fp.trim() : '';
  }

  function sessionKey(key) {
    return SESSION_PREFIX + (fingerprint() || 'global') + ':' + key;
  }

  function prefKey(key) {
    return PREF_PREFIX + key;
  }

  // ---- 会话级状态（sessionStorage） ----
  function readSession(key) {
    try {
      var raw = sessionStorage.getItem(key);
      if (!raw) return undefined;
      var obj = JSON.parse(raw);
      if (!obj || obj._v !== VERSION) return undefined;  // 过期版本丢弃
      return obj.value;
    } catch (e) { return undefined; }
  }

  function get(key) { return readSession(sessionKey(key)); }

  function set(key, value) {
    try {
      sessionStorage.setItem(sessionKey(key), JSON.stringify({ _v: VERSION, value: value }));
    } catch (e) { /* 满/禁用：静默降级，不影响导航 */ }
  }

  function clear(key) {
    try { sessionStorage.removeItem(sessionKey(key)); } catch (e) {}
  }

  // ---- 长期偏好（localStorage，跨会话保留） ----
  function preference(key) {
    try {
      var raw = localStorage.getItem(prefKey(key));
      if (raw === null || raw === undefined) return undefined;
      var obj = JSON.parse(raw);
      if (!obj || obj._v !== VERSION) return undefined;  // 过期版本丢弃
      return obj.value;
    } catch (e) { return undefined; }
  }

  function setPreference(key, value) {
    try {
      if (value === null || value === undefined) {
        localStorage.removeItem(prefKey(key));
      } else {
        localStorage.setItem(prefKey(key), JSON.stringify({ _v: VERSION, value: value }));
      }
    } catch (e) {}
  }

  function clearPreference(key) {
    try { localStorage.removeItem(prefKey(key)); } catch (e) {}
  }

  // ---- 列表位置：含选中对象，按模型隔离 ----
  function rememberList(page, state) {
    set('list:' + page, state || {});
  }
  function recallList(page) {
    return get('list:' + page);
  }

  // ---- 跨对象跳转来源：记录「从哪个对象页跳到这里」，供返回恢复 ----
  // 用法：在进入对象 B 之前，来源页 A 调用 rememberJump('B', { page: 'A', state: {...} })
  //       对象 B 页面的「返回」按钮调用 recallJump('B') 拿到来源信息，构造返回链接。
  function rememberJump(targetPage, sourceState) {
    set('jump:' + targetPage, sourceState || {});
  }
  function recallJump(targetPage) {
    return get('jump:' + targetPage);
  }

  window.WorkbenchContext = {
    VERSION: VERSION,
    fingerprint: fingerprint,
    get: get,
    set: set,
    clear: clear,
    preference: preference,
    setPreference: setPreference,
    clearPreference: clearPreference,
    rememberList: rememberList,
    recallList: recallList,
    rememberJump: rememberJump,
    recallJump: recallJump,
  };
})();
