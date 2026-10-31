/* Stage 0/1 — TI 语法高亮的「计算成本」测量（Node，无浏览器）。

只测量 syntax.js 的纯计算部分：highlightLine + 拼接 HTML 字符串。
不含浏览器解析、布局、绘制、字体渲染 —— 这些在没有浏览器轨迹时记为「未测」。

用法：
  node scripts/measure_highlight.js < sample.txt
  node scripts/measure_highlight.js --file sample.txt --mode ti --repeat 5
输出 JSON。
*/
"use strict";

var fs = require("fs");
var path = require("path");

function arg(name, fallback) {
  var i = process.argv.indexOf("--" + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

function readStdin() {
  try {
    return fs.readFileSync(0, "utf8");
  } catch (e) {
    return "";
  }
}

// 最小 DOM 桩：syntax.js 只在 mount()/initialize() 里用 DOM，
// 而 tm1Highlight.ti/rules 是纯函数，可独立调用。
global.window = {};
global.document = {
  readyState: "loading",
  addEventListener: function () {},
  body: { nodeType: 1, matches: function () { return false; }, querySelectorAll: function () { return []; } },
};
global.MutationObserver = function () { this.observe = function () {}; this.disconnect = function () {}; };

var src = fs.readFileSync(path.join(__dirname, "..", "src", "tm1_insight", "api", "static", "syntax.js"), "utf8");
new Function("window", "document", "MutationObserver", src)(
  global.window, global.document, global.MutationObserver
);

var code = arg("file", null) ? fs.readFileSync(arg("file"), "utf8") : readStdin();
var mode = arg("mode", "ti");
var repeat = Number(arg("repeat", "3"));
var fn = mode === "rules" ? window.tm1Highlight.rules : window.tm1Highlight.ti;

// warmup
fn(code);

var times = [];
var html = "";
for (var i = 0; i < repeat; i++) {
  var t0 = process.hrtime.bigint();
  html = fn(code);
  var t1 = process.hrtime.bigint();
  times.push(Number(t1 - t0) / 1e6);
}

times.sort(function (a, b) { return a - b; });
var lines = code.replace(/\r\n/g, "\n").split("\n").length;
var lineNodes = (html.match(/<div class="code-line">/g) || []).length;
var tokenSpans = (html.match(/<span class="tok-/g) || []).length;

process.stdout.write(JSON.stringify({
  mode: mode,
  chars: code.length,
  lines: lines,
  html_bytes: Buffer.byteLength(html, "utf8"),
  line_nodes: lineNodes,
  token_spans: tokenSpans,
  // 每个 code-line 固定 1 div + 2 span（lineno / line-code）
  projected_elements: lineNodes === 0 ? 1 : lineNodes * 3 + tokenSpans,
  ms_p50: Math.round(times[Math.floor(times.length / 2)] * 100) / 100,
  ms_max: Math.round(times[times.length - 1] * 100) / 100,
  repeat: repeat,
  note: "compute only; no layout/paint measured"
}, null, 2) + "\n");
