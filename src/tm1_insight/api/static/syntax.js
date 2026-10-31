/* TI / Rules 语法高亮 —— 对齐 Notepad++ TM1 UDL 配色方案，纯前端无依赖。
   分类对应 Notepad++ 的 4 级关键字 + 操作符 + 字符串 + 注释 + 数字，
   变量保持默认色不着色，从而与函数/关键字形成鲜明区分。 */
(function () {
  "use strict";

  // 颜色仅作为 fallback（实际由 CSS 的 --tok-* 变量覆盖）
  var COLORS = {
    comment: "#8080C0",   // 注释（Notepad++ COMMENTS）
    kw1: "#0000FF",       // KEYWORDS1 函数（蓝）
    kw2: "#800080",       // KEYWORDS2 控制流（紫）
    kw3: "#008080",       // KEYWORDS3 DATASOURCE（青）
    kw4: "#F00000",       // KEYWORDS4 FEEDERS/SKIPCHECK（红）
    operator: "#FF0000",  // 操作符（红）
    string: "#408080",    // 字符串（青灰）
    number: "#804000",    // 数字（褐）
  };

  var CONDITION = ["IF", "ENDIF", "ELSEIF", "ELSE", "WHILE", "DO", "END", "FOR", "NEXT", "BREAK", "RETURN"];

  var TM1_KEYWORDS = [
    "EXECUTEPROCESS", "NOW", "TIME", "CONTINUE", "CHOREQUIT",
    "ITEMSKIP", "ITEMREJECT", "PROCESSBREAK", "PROCESSERROR", "PROCESSQUIT",
    "DELETEALLPERSISTENTFEEDERS", "SECURITYREFRESH", "ISLEAF", "UNDEF",
    "UNDEFVALS", "STET", "SYNCHRONIZED", "SAVEDATAALL", "ENCRYPT", "DECRYPT",
    "SETCHOREVERBOSEMESSAGES",
  ];

  var DATASOURCE_KEYWORDS = [
    "DATASOURCENAMEFORSERVER", "DATASOURCENAMEFORCLIENT", "DATASOURCEQUERY",
    "DATASOURCEUSERNAME", "DATASOURCETYPE", "DATASOURCEODBCNAME",
    "DATASOURCEASCIIDELIMITER", "DATASOURCEASCIIDEDECIMALSEP", "DATASOURCEASCIITHOUSANDSSEP",
    "DATASOURCEVIEW", "DATASOURCEROWS", "DATASOURCECOLUMNS",
    "DATASOURCEASCIIQUOTECHARACTER", "DATASOURCEASCIIHEADERROWS", "DATASOURCEPASSWORD",
    "DATASOURCECUBEVIEW", "DATASOURCETYPE", "DATASOURCENAMEFORSERVER",
    "SUBSETDATASOURCETYPE", "DATASOURCEDIMENSIONSUBSET", "DATASOURCEASCIIDELIMITER",
    "DATASOURCEASCIIQUOTECHARACTER", "DATASOURCEASCIIQUOTECHARACTER", "DATASOURCEASCIIDECIMALSEPARATOR",
    "DATASOURCEASCIIQUOTECHARACTER", "DATASOURCEUSERNAME", "DATASOURCEPASSWORD",
    "DATASOURCEQUERY",
  ];

  var FUNCTIONS = [
    "CellGetN", "CellGetS", "CellPutN", "CellPutS", "CellIncrementN",
    "CellPutProportionalSpread", "CellIsUpdateable",
    "AttrPutN", "AttrPutS", "AttrDelete", "AttrInsert", "AttrToAlias",
    "ElementAttrPutN", "ElementAttrPutS", "ElementAttrInsert", "ElementAttrDelete",
    "DimensionCreate", "DimensionDestroy", "DimensionExists", "DimensionDeleteAllElements",
    "DimensionElementInsert", "DimensionElementDelete", "DimensionElementComponentAdd",
    "DimensionElementComponentDelete", "DimensionSortOrder", "DimensionUpdateDirect",
    "ElementInsert", "ElementDelete", "ElementComponentAdd", "ElementComponentDelete",
    "ElementSecurityPut", "ElementSecurityGet",
    "CubeCreate", "CubeDestroy", "CubeExists", "CubeClearData",
    "CubeSetLogChanges", "CubeRuleAppend", "CubeRuleDelete",
    "CubeRuleInsert", "CubeRuleReplace", "CubeUnload",
    "SubsetCreate", "SubsetDestroy", "SubsetExists", "SubsetDeleteAllElements",
    "SubsetElementInsert", "SubsetElementDelete", "SubsetAliasSet",
    "SubsetCreateByMDX", "SubsetMDXSet", "SubsetMDXGet",
    "ViewCreate", "ViewDestroy", "ViewExists", "ViewSubsetAssign",
    "ViewTitleDimensionSet", "ViewExtractSkipCalcsSet", "ViewExtractSkipRuleValuesSet",
    "ViewExtractSkipZeroesSet", "ViewColumnDimensionSet", "ViewRowDimensionSet",
    "NumberToString", "StringToNumber", "NumberToStringEx",
    "Subst", "Scan", "Trim", "Long", "Lower", "Upper", "Char", "Code",
    "Abs", "Exp", "Int", "Log", "Max", "Min", "Mod", "Rand", "Round", "RoundP",
    "Sign", "Sqrt",
    "AsciiOutput", "TextOutput", "AsciiOpen", "AsciiClose",
    "OdbcOpen", "OdbcClose", "OdbcOutput", "OdbcGet",
    "LogOutput", "SetInputCharacterSet", "SetOutputCharacterSet",
    "Day", "Month", "Year", "Date", "Time", "Now", "TimSt",
    "DimIx", "DimNm", "DimSiz", "ElComp", "ElCompN", "ElLev",
    "ElPar", "ElParN", "ElWeight", "CubeDimNm", "CubeDimIx",
    "ServerName", "TM1User",
    "ExecuteProcess", "Sleep", "GetProcessName",
    "HierarchyCreate", "HierarchyDestroy", "HierarchyExists", "HierarchyDeleteAllElements",
    "HierarchyElementInsert", "HierarchyElementDelete", "HierarchyElementComponentAdd",
    "HierarchySubsetCreate", "HierarchySubsetDestroy", "HierarchySubsetElementInsert",
  ];

  var RULES_BLOCK = ["FEEDERS", "ENDFEEDERS", "SKIPCHECK", "ENDSKIP"];
  var RULES_KEYWORDS = ["DIMENSION", "ELEMENT", "UNIQUE", "UNIQUEDEFN", "AGGREGATE", "TIMES"];
  var RULES_FUNCS = [
    "DB", "ATTRS", "ATTRN", "DIMIX", "DIMNM", "ELCOMP", "ELCOMPN", "ELISCOMP",
    "ELPAR", "ELPARN", "ELISPAR", "ELLEV", "ELWEIGHT", "TYPELEAF",
    "CONSOLIDATECHILDREN", "TABDIM", "STET", "CONTINUE", "NUMBR", "STR", "ABS",
    "ROUND", "ROUNDP", "MAX", "MIN", "INT", "MOD", "SIGN", "SQRT", "EXP", "LOG",
    "DAY", "MONTH", "YEAR", "TIMST", "NOW", "DATE", "SUBST", "SCAN", "TRIM",
    "LONG", "LOWER", "UPPER",
  ];

  function lowerSet(arr) {
    var s = {};
    for (var i = 0; i < arr.length; i++) s[arr[i].toLowerCase()] = true;
    return s;
  }
  var CONDITION_S = lowerSet(CONDITION);
  var TM1_S = lowerSet(TM1_KEYWORDS);
  var DS_S = lowerSet(DATASOURCE_KEYWORDS);
  var FUNC_S = lowerSet(FUNCTIONS);
  var RULES_BLOCK_S = lowerSet(RULES_BLOCK);
  var RULES_KW_S = lowerSet(RULES_KEYWORDS);
  var RULES_FUNC_S = lowerSet(RULES_FUNCS);

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function wrap(cls, text) {
    return '<span class="tok-' + cls + '">' + esc(text) + "</span>";
  }
  function isWordChar(c) { return /[A-Za-z0-9_]/.test(c); }

  function highlightLine(line, mode) {
    var out = "";
    var i = 0, n = line.length;
    var isTi = mode === "ti";
    while (i < n) {
      var ch = line[i];
      if (ch === "#") {
        out += wrap("comment", line.slice(i));
        break;
      }
      if (ch === '"' || ch === "'") {
        var q = ch, j = i + 1;
        while (j < n && line[j] !== q) j++;
        var end = (j < n) ? j + 1 : n;
        out += wrap("string", line.slice(i, end));
        i = end;
        continue;
      }
      // 操作符（先多字符）
      var op = null;
      if (line.substr(i, 3) === "@<>") op = 3;
      else if (line.substr(i, 2) === "@=" || line.substr(i, 2) === "<>" ||
               line.substr(i, 2) === "<=" || line.substr(i, 2) === ">=") op = 2;
      else if ("=<>+-*/\\&%|^".indexOf(ch) >= 0 || (isTi === false && ch === "|")) op = 1;
      if (op) {
        out += wrap("operator", line.substr(i, op));
        i += op;
        continue;
      }
      // 单词（标识符 / 关键字 / 函数 / 数字）
      if (isWordChar(ch)) {
        var k = i + 1;
        while (k < n && isWordChar(line[k])) k++;
        var word = line.slice(i, k);
        var low = word.toLowerCase();
        var cls = null;
        if (/^\d+\.?\d*$/.test(word)) cls = "number";
        else if (isTi) {
          // TI 段：控制流→kw2，DATASOURCE→kw3，函数→kw1
          if (CONDITION_S[low]) cls = "kw2";
          else if (DS_S[low]) cls = "kw3";
          else if (FUNC_S[low]) cls = "kw1";
          else if (TM1_S[low]) cls = "kw2";
        } else {
          // Rules 段：FEEDERS/SKIPCHECK→kw4，控制流/维度关键字→kw2，函数→kw1
          if (RULES_BLOCK_S[low]) cls = "kw4";
          else if (CONDITION_S[low] || RULES_KW_S[low]) cls = "kw2";
          else if (RULES_FUNC_S[low]) cls = "kw1";
        }
        if(!cls && /^\s*\(/.test(line.slice(k)))cls='kw1';
        out += cls ? wrap(cls, word) : esc(word);
        i = k;
        continue;
      }
      out += esc(ch);
      i++;
    }
    return out;
  }

  function lineHtml(text, mode, lineno) {
    return '<div class="code-line">'
         + '<span class="lineno" aria-hidden="true">' + lineno + "</span>"
         + '<span class="line-code">' + highlightLine(text, mode) + "</span>"
         + "</div>";
  }

  function render(code, mode) {
    var text = String(code == null ? "" : code).replace(/\r\n/g, "\n");
    var lines = text.split("\n");
    var html = "";
    for (var idx = 0; idx < lines.length; idx++) {
      html += lineHtml(lines[idx], mode, idx + 1);
    }
    return html;
  }

  window.tm1Highlight = {
    ti: function (code) { return render(code, "ti"); },
    rules: function (code) { return render(code, "rules"); },
  };

  // Shared, idempotent source viewer for static pages and asynchronous evidence.
  var sources = new WeakMap();

  // 大段源码的保护阈值：超过字符上限走纯文本（无法高亮但可读、可定位行）。
  var PLAIN_LIMIT = 1000000;
  // 超过行数阈值时分批渲染：首屏只渲染一块，滚动接近底部再追加，
  // 避免一次生成上万个 DOM 节点。行号连续，定位逻辑不依赖渲染总量。
  var CHUNK_THRESHOLD = 1500;
  var CHUNK_SIZE = 800;

  function rawText(pre) {
    var lines = pre.querySelectorAll('.line-code');
    return lines.length ? Array.from(lines, function(x){return x.textContent;}).join('\n') : pre.textContent;
  }

  function appendChunk(pre) {
    var st = sources.get(pre);
    if (!st || st.plain) return false;
    if (st.rendered >= st.lines.length) return false;
    var end = st.chunk ? Math.min(st.lines.length, st.rendered + st.chunk) : st.lines.length;
    var parts = [];
    for (var i = st.rendered; i < end; i++) parts.push(lineHtml(st.lines[i], st.mode, st.start + i));
    pre.insertAdjacentHTML("beforeend", parts.join(""));
    st.rendered = end;
    return true;
  }

  function revealLine(pre, line) {
    var st = sources.get(pre);
    if (!st) return false;
    var n = Number(line);
    if (!isFinite(n) || n < st.start) return false;
    var target = n - st.start + 1;
    if (st.plain) {
      // 纯文本没有行节点：按行高换算滚动位置，行号锚点仍然可用。
      var lh = parseFloat(window.getComputedStyle(pre).lineHeight) || 20;
      pre.scrollTop = Math.max(0, (target - 1) * lh - pre.clientHeight / 2 + lh / 2);
      return true;
    }
    var guard = 0;
    while (st.rendered < target && guard++ < 200) { if (!appendChunk(pre)) break; }
    var row = pre.children[target - 1];
    if (!row) return false;
    var pr = pre.getBoundingClientRect(), rr = row.getBoundingClientRect();
    pre.scrollTop += (rr.top - pr.top) - (pr.height - rr.height) / 2;
    return true;
  }

  function mount(pre, options) {
    options = options || {};
    var previous = sources.get(pre);
    // 已经按自身文本挂载过就不再重建：避免分批渲染后丢失已追加的行与滚动位置。
    if (previous && options.code == null) return pre;
    var code = options.code == null ? rawText(pre) : String(options.code);
    var mode = options.mode || pre.dataset.highlight || 'ti';
    var first = pre.querySelector('.lineno');
    var start = options.start || Number(pre.dataset.sourceStart || (first && first.textContent) || 1);
    var display = code.replace(/\r\n/g, "\n");
    var lines = display.split("\n");
    var plain = options.plain === true || code.length > PLAIN_LIMIT;
    var chunk = options.chunk != null ? options.chunk
              : (lines.length > CHUNK_THRESHOLD ? CHUNK_SIZE : 0);
    var state = {raw: code, display: display, mode: mode, start: start, plain: plain,
                 chunk: chunk, rendered: 0, lines: lines};
    sources.set(pre, state);
    var wrapper = pre.parentElement;
    if (!wrapper || !wrapper.classList.contains('source-viewer')) {
      wrapper = document.createElement('div'); wrapper.className='source-viewer';
      pre.before(wrapper); wrapper.append(pre);
      var tools = document.createElement('div');tools.className='source-tools';wrapper.prepend(tools);
      var label = document.createElement('span'); label.textContent='源码';tools.append(label);
      var copy = document.createElement('button');copy.type='button';copy.className='btn ghost source-copy';copy.textContent='复制源码';tools.append(copy);
      copy.addEventListener('click',async function(){
        try { await navigator.clipboard.writeText(sources.get(pre).raw);copy.textContent='已复制'; }
        catch(e){copy.textContent='复制失败，请选择源码复制';}
        setTimeout(function(){if(copy.isConnected)copy.textContent='复制源码';},1800);
      });
    }
    pre.classList.add('source-code');pre.dataset.sourceMode=mode;
    var labelEl = wrapper.querySelector('.source-tools span');
    if (plain) {
      // Preserve all content. Very large sources use a bounded plain-text fallback.
      pre.textContent = code;
      state.rendered = lines.length;
      if (labelEl) labelEl.textContent = '源码 · 大文件纯文本';
    } else {
      pre.replaceChildren();
      appendChunk(pre);
      if (labelEl) labelEl.textContent = chunk ? '源码 · 分批渲染，滚动继续加载' : '源码';
      if (chunk && !pre.dataset.chunkBound) {
        pre.dataset.chunkBound = '1';
        pre.addEventListener('scroll', function () {
          var st = sources.get(pre);
          if (!st || st.plain || !st.chunk || st.rendered >= st.lines.length) return;
          if (pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 240) appendChunk(pre);
        }, {passive: true});
      }
    }
    pre.dataset.sourceReady = '1';
    return pre;
  }
  window.tm1Source = {
    mount: mount,
    text: function(pre){return sources.get(pre)?.raw ?? rawText(pre);},
    revealLine: revealLine,
    isReady: function(pre){return pre.dataset.sourceReady === '1';}
  };
  function scan(root) {
    var pres=[];
    if(root.nodeType!==1)return;
    if(root.matches('pre.code,pre[data-highlight]'))pres.push(root);
    root.querySelectorAll('pre.code,pre[data-highlight]').forEach(function(p){pres.push(p);});
    pres.forEach(function(pre){
      if(pre.classList.contains('dimension-expression') || pre.dataset.sourceMode==='json')return;
      // 惰性代码段：等页面在自己的时机挂载（首屏只渲染激活的段）。
      if(pre.dataset.lazySource && pre.dataset.sourceReady!=='1')return;
      var text=rawText(pre).trim();
      if(text[0]==='{' || text[0]==='['){try{JSON.parse(text);return;}catch(e){}}
      mount(pre);
    });
  }
  function initialize(){
    scan(document.body);
    var pending=new Set(),scheduled=false;
    var observer=new MutationObserver(function(records){
      records.forEach(function(r){
        var pre=r.target.nodeType===1?r.target.closest('pre.code,pre[data-highlight]'):r.target.parentElement?.closest('pre.code,pre[data-highlight]');
        if(pre)pending.add(pre);
        r.addedNodes.forEach(function(x){if(x.nodeType===1)pending.add(x);});
      });
      if(scheduled || !pending.size)return;scheduled=true;
      queueMicrotask(function(){scheduled=false;var nodes=Array.from(pending);pending.clear();nodes.forEach(function(x){if(x.isConnected)scan(x);});});
    });
    observer.observe(document.body,{childList:true,subtree:true,characterData:true});
    window.addEventListener('pagehide',function(){observer.disconnect();});
    window.addEventListener('pageshow',function(e){if(e.persisted){scan(document.body);observer.observe(document.body,{childList:true,subtree:true,characterData:true});}});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize);else initialize();
})();
