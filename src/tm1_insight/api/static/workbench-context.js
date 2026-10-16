/* Workbench Context —— 统一的跨页面浏览上下文记忆。

   目标：用户从列表进入详情、再跳到其它对象、最后返回时，能恢复到
   「之前的搜索词 / 页码 / 选中对象 / 列选择 / 展开状态」，无需重新搜索。

   设计原则：
   - 状态按「模型指纹」隔离。不同 TM1 快照 / DuckDB 模型绝不混用同名对象状态。
   - sessionStorage 存会话级浏览状态；localStorage 存长期偏好（列选择、主题等）。
   - 内容版本化，防止旧版本结构污染新代码。
   - 只存 UI 浏览状态，绝不存账号 / Token / 敏感业务数据。

   模型指纹来源：<body data-model-fingerprint="...">（由 base.html 注入，
   对应后端 _process_search_source 的 sha256）。缺失时退化为全局命名空间，
   并明确标注，避免静默串用。

   API：
     WorkbenchContext.get(key)          -> 当前模型下某个 key 的值
     WorkbenchContext.set(key, value)   -> 写入（自动按模型隔离 + 版本号）
     WorkbenchContext.clear(key)
     WorkbenchContext.preference(key)   -> 读长期偏好（localStorage，不按模型）
     WorkbenchContext.setPreference(key, value)
     WorkbenchContext.fingerprint()     -> 当前模型指纹
*/
(function () {
  'use strict';
  var VERSION = 'wb1';
  var SESSION_PREFIX = 'tm1-wb-session-';
  var PREF_PREFIX = 'tm1-wb-pref-';

  function fingerprint() {
    var fp = document.body && document.body.getAttribute('data-model-fingerprint');
    return fp && fp.trim() ? fp.trim() : '';
  }

  function sessionKey(key) {
    var fp = fingerprint();
    return SESSION_PREFIX + (fp || 'global') + ':' + key;
  }

  function prefKey(key) {
    return PREF_PREFIX + key;
  }

  function readJSON(key) {
    try {
      var raw = sessionStorage.getItem(key);
      if (!raw) return undefined;
      var obj = JSON.parse(raw);
      return obj;
    } catch (e) {
      return undefined;
    }
  }

  function get(key) {
    var obj = readJSON(sessionKey(key));
    if (!obj) return undefined;
    // 版本不匹配视为过期状态，丢弃（不污染当前逻辑）
    if (obj._v !== VERSION) return undefined;
    return obj.value;
  }

  function set(key, value) {
    try {
      sessionStorage.setItem(sessionKey(key), JSON.stringify({ _v: VERSION, value: value }));
    } catch (e) {
      // sessionStorage 满 / 禁用：静默降级，不影响导航
    }
  }

  function clear(key) {
    try { sessionStorage.removeItem(sessionKey(key)); } catch (e) {}
  }

  function preference(key) {
    try { return sessionStorage.getItem(prefKey(key)); } catch (e) { return null; }
  }

  function setPreference(key, value) {
    try {
      if (value === null || value === undefined) {
        sessionStorage.removeItem(prefKey(key));
      } else {
        sessionStorage.setItem(prefKey(key), String(value));
      }
    } catch (e) {}
  }

  window.WorkbenchContext = {
    VERSION: VERSION,
    fingerprint: fingerprint,
    get: get,
    set: set,
    clear: clear,
    preference: preference,
    setPreference: setPreference,
    // 便捷方法：列表页「记住当前位置」，详情页「恢复位置」
    rememberList: function (page, state) {
      set('list:' + page, state);
    },
    recallList: function (page) {
      return get('list:' + page);
    },
  };
})();
