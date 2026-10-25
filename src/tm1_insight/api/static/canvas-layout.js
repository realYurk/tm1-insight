/* TM1 Insight · 架构图布局引擎（canvas-layout）
 *
 * 目标：不是"输出了坐标"，而是可读性：
 *  - 数据加工链 → 自左向右分层（Source → 中间 → Target）
 *  - 中心辐射（高连接度 hub）→ 中心 + 同心环，按角度均匀分布，标签互不重叠
 *  - 循环（强连通分量）→ 收缩后分层，成员围绕分量中心成小环，不强行 DAG
 *  - 层内排序用重心迭代减少交叉；行距按节点尺寸计算，避免标签碰撞
 *  - 层过高时分栏（wrap），避免一字长蛇阵或超高竖列
 *
 * 纯函数：输入 nodes/edges 数组，输出 {positions, strategy, sccCount}。
 * 不依赖 Cytoscape，可单独测试。
 */
(function () {
  'use strict';

  var ROW_H = 96;        // 行距：节点 58 + 标签 + 呼吸
  var BASE_COL = 170;    // 最小列距
  var MAX_ROWS = 9;      // 单列最大行数，超过则分栏
  var RING_MIN = 235;    // 辐射布局最小半径
  var RING_PER = 124;    // 环上每节点占用的弧长（须容纳最长标签不碰撞）

  function nodeWidth(name) {
    var len = String(name || '').length;
    return Math.min(60 + len * 6.0, 210);
  }

  /* ---------------- Tarjan SCC（迭代版，防深图爆栈） ---------------- */
  function tarjanSCC(nodeIds, adj) {
    var index = {}, low = {}, onStack = {}, stack = [], sccs = [];
    var counter = 0;
    nodeIds.forEach(function (id) { if (index[id] === undefined) strong(id); });
    return sccs;

    function strong(v0) {
      var work = [{ v: v0, pi: 0 }];
      while (work.length) {
        var frame = work[work.length - 1];
        var v = frame.v;
        if (frame.pi === 0) {
          index[v] = low[v] = counter++;
          stack.push(v); onStack[v] = true;
        }
        var advanced = false;
        var neighbors = adj[v] || [];
        while (frame.pi < neighbors.length) {
          var w = neighbors[frame.pi];
          frame.pi += 1;
          if (index[w] === undefined) {
            work.push({ v: w, pi: 0 });
            advanced = true;
            break;
          } else if (onStack[w]) {
            low[v] = Math.min(low[v], index[w]);
          }
        }
        if (advanced) continue;
        if (low[v] === index[v]) {
          var comp = [];
          for (;;) {
            var w2 = stack.pop();
            onStack[w2] = false;
            comp.push(w2);
            if (w2 === v) break;
          }
          sccs.push(comp);
        }
        work.pop();
        if (work.length) {
          var parent = work[work.length - 1].v;
          low[parent] = Math.min(low[parent], low[v]);
        }
      }
    }
  }

  /* ---------------- 主入口 ---------------- */
  function compute(nodes, edges, opts) {
    var opt = opts || {};
    var list = nodes.filter(function (n) { return n.type !== 'group'; }).slice().sort(function(a,b){return String(a.id).localeCompare(String(b.id));});
    var idset = new Set(list.map(function (n) { return n.id; }));
    var links = edges.filter(function (e) {
      return idset.has(e.source) && idset.has(e.target) && e.source !== e.target;
    }).slice().sort(function(a,b){return String(a.source).localeCompare(String(b.source))||String(a.target).localeCompare(String(b.target));});

    if (list.length === 0) return { positions: {}, strategy: 'empty', sccCount: 0 };
    if (list.length === 1) return { positions: (function () { var p = {}; p[list[0].id] = { x: 0, y: 0 }; return p; })(), strategy: 'single', sccCount: 1 };

    var adj = {}, radj = {};
    list.forEach(function (n) { adj[n.id] = []; radj[n.id] = []; });
    var degree = {};
    list.forEach(function (n) { degree[n.id] = 0; });
    links.forEach(function (e) {
      adj[e.source].push(e.target);
      radj[e.target].push(e.source);
      degree[e.source] += 1; degree[e.target] += 1;
    });

    var sccs = tarjanSCC(list.map(function (n) { return n.id; }), adj);
    var compOf = {};
    sccs.forEach(function (comp, i) { comp.forEach(function (id) { compOf[id] = i; }); });

    // ---- hub 检测：一个节点吃掉大部分连接 → 辐射布局
    var hub = null, hubDeg = 0;
    list.forEach(function (n) { if (degree[n.id] > hubDeg) { hubDeg = degree[n.id]; hub = n.id; } });
    var starLike = hubDeg >= 5 && hubDeg >= 0.34 * list.length;
    if (starLike && opt.strategy === 'radial') {
      return radial(hub, list, links, adj, radj, sccs.length);
    }
    var result=layered(list, links, adj, sccs, compOf);
    if(opt.direction==='TB')Object.keys(result.positions).forEach(function(id){var p=result.positions[id];result.positions[id]={x:p.y,y:p.x};});
    return result;
  }

  /* ---------------- 分层布局 ---------------- */
  function layered(list, links, adj, sccs, compOf) {
    var nc = sccs.length;                       // 分量数
    var cadj = [], indeg = [];
    for (var i = 0; i < nc; i++) { cadj.push([]); indeg.push(0); }
    var compLinks = {};
    links.forEach(function (e) {
      var a = compOf[e.source], b = compOf[e.target];
      if (a === b) return;
      var key = a + '>' + b;
      if (compLinks[key]) return;
      compLinks[key] = true;
      cadj[a].push(b); indeg[b] += 1;
    });

    // Kahn 拓扑序 + 最长路径分层
    var layer = new Array(nc).fill(0);
    var queue = [];
    for (var k = 0; k < nc; k++) if (!indeg[k]) queue.push(k);
    var order = [];
    while (queue.length) {
      var c = queue.shift();
      order.push(c);
      cadj[c].forEach(function (d) {
        layer[d] = Math.max(layer[d], layer[c] + 1);
        indeg[d] -= 1;
        if (!indeg[d]) queue.push(d);
      });
    }
    // 剩余（理论上不会：环已收缩）
    for (var k2 = 0; k2 < nc; k2++) if (order.indexOf(k2) < 0) order.push(k2);

    // 分层分组
    var layerMax = 0;
    layer.forEach(function (v) { layerMax = Math.max(layerMax, v); });
    var layers = [];
    for (var L = 0; L <= layerMax; L++) layers.push([]);
    order.forEach(function (c) { layers[layer[c]].push(c); });

    // 层内排序：重心迭代（先按度，再 3 轮相邻层平均位置）
    layers.forEach(function (comp) {
      comp.sort(function (a, b) { return sccs[b].length - sccs[a].length; });
      comp.forEach(function (c, i) { sccs[c]._ord = i; });
    });
    for (var sweep = 0; sweep < 3; sweep++) {
      var forward = sweep % 2 === 0;
      var seq = forward ? layers : layers.slice().reverse();
      seq.forEach(function (comp, li) {
        comp.forEach(function (c) {
          var neigh = [];
          sccs[c].forEach(function (id) {
            (forward ? adj[id] : predecessors(links, id)).forEach(function (other) {
              var oc = compOf[other];
              if (oc !== c && sccs[oc]._ord !== undefined) neigh.push(sccs[oc]._ord);
            });
          });
          if (neigh.length) {
            neigh.sort(function (a, b) { return a - b; });
            sccs[c]._ord = neigh[Math.floor(neigh.length / 2)];
          }
        });
        comp.sort(function (a, b) { return sccs[a]._ord - sccs[b]._ord; });
      });
    }
    function predecessors(links_, id) { // 反向邻居：量小直接遍历，可接受
      var out = [];
      links.forEach(function (e) { if (e.target === id) out.push(e.source); });
      return out;
    }

    // 每层宽度 = 分量内最大节点宽 + 边距；列高超出则分栏
    var positions = {};
    var x = 0;
    var tallest = 0;
    var colWidths = [];
    layers.forEach(function (comp) {
      var maxW = 64;
      comp.forEach(function (c) {
        sccs[c].forEach(function (id) { maxW = Math.max(maxW, nodeWidth(nameOf(id))); });
      });
      var colW = maxW + BASE_COL;
      var packed=[],heights=[0],column=0;
      comp.forEach(function(c){var size=sccs[c].length;if(heights[column]&&heights[column]+size>MAX_ROWS){column++;heights[column]=0;}packed.push({column:column,row:heights[column],size:size});heights[column]+=size;});
      var cols = heights.length;
      // 展开分量成员：单成员直接放；多成员（环）先占格再成环
      comp.forEach(function (c, ci) {
        var members = sccs[c];
        var colIdx = packed[ci].column;
        var rowInCol = packed[ci].row+(packed[ci].size-1)/2;
        var cellX = x + colIdx * colW;
        var columnCount = heights[colIdx];
        var cellY = (rowInCol - (columnCount - 1) / 2) * ROW_H;
        if (members.length === 1) {
          positions[members[0]] = { x: cellX, y: cellY };
        } else {
          // Cyclic members share one layer; local staggering is presentation,
          // never an invented execution order within the strongly connected set.
          members.sort();
          members.forEach(function (id, mi) {
            positions[id] = { x: cellX + (mi%2)*24, y: cellY + (mi-(members.length-1)/2)*ROW_H };
          });
        }
      });
      colWidths.push(colW * cols);
      x += colW * cols;
      tallest = Math.max(tallest, Math.min(comp.length, MAX_ROWS));
    });
    return { positions: positions, strategy: 'layered', sccCount: nc, layerCount: layers.length };

    function nameOf(id) {
      // canvas-graph 传入 nodes 带 name；这里通过闭包 list 查
      for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i].name;
      return '';
    }
  }

  /* ---------------- 辐射布局（hub + 同心环） ---------------- */
  function radial(hub, list, links, adj, radj, sccCount) {
    var positions = {};
    positions[hub] = { x: 0, y: 0 };

    var ring1 = [];
    var seen = new Set([hub]);
    adj[hub].forEach(function (id) { if (!seen.has(id)) { ring1.push(id); seen.add(id); } });
    radj[hub].forEach(function (id) { if (!seen.has(id)) { ring1.push(id); seen.add(id); } });
    ring1.sort(function (a, b) { return String(a).localeCompare(String(b)); }); // 稳定排序，避免每次刷新乱跳

    // 第二环：不与 hub 直连、但与环上节点相连的节点，挂在锚点附近
    var anchors = {}; // id -> 环上邻居
    var ring2 = [];
    links.forEach(function (e) {
      [e.source, e.target].forEach(function (end) {
        var other = end === e.source ? e.target : e.source;
        if (!seen.has(end) && seen.has(other) && end !== hub) {
          if (!anchors[end]) { anchors[end] = other; ring2.push(end); seen.add(end); }
        }
      });
    });

    var n1 = ring1.length;
    var R1 = Math.max(RING_MIN, (n1 * RING_PER) / (2 * Math.PI) + 60);
    ring1.forEach(function (id, i) {
      var ang = (i / Math.max(n1, 1)) * Math.PI * 2 - Math.PI / 2;
      positions[id] = { x: Math.cos(ang) * R1, y: Math.sin(ang) * R1 * 0.86 };
    });
    var R2 = R1 + 205;
    ring2.forEach(function (id) {
      var anchor = positions[anchors[id]];
      var base = Math.atan2(anchor.y, anchor.x);
      positions[id] = { x: Math.cos(base) * R2, y: Math.sin(base) * R2 * 0.86 };
    });

    // 兜底：孤立节点放外环空位
    var placed = Object.keys(positions);
    list.forEach(function (n) {
      if (!positions[n.id]) {
        var idx = placed.length;
        var ang = (idx / Math.max(list.length, 1)) * Math.PI * 2;
        positions[n.id] = { x: Math.cos(ang) * (R2 + 180), y: Math.sin(ang) * (R2 + 180) * 0.86 };
      }
    });
    return { positions: positions, strategy: 'radial', sccCount: sccCount, hub: hub, hubDegree: adj[hub].length + radj[hub].length };
  }

  window.TM1CanvasLayout = { compute: compute, nodeWidth: nodeWidth };
})();
