const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.value=''; this.events={}; this.textContent=''; }
  append(x) { this.children.push(x); }
  replaceChildren() { this.children=[]; }
  setAttribute() {}
  addEventListener(k, f) { this.events[k]=f; }
}
global.document={createElement:tag=>new Element(tag)};global.window={};
vm.runInThisContext(fs.readFileSync(process.argv[2],'utf8'));
const parent=new Element('div');
const nodes=[{id:'a',title:'Cube A',role:'来源'},{id:'b',title:'Cube B',role:'结果'}];
const edges=[{source:'a',target:'b',label:'写入',slices:[]}];
window.TM1Workbench.flowTables(parent,{nodes,edges},{selectNode(){},selectEdge(){}});
const search=parent.children[0],count=parent.children[1];
assert.match(count.textContent,/2 个对象 · 1 个动作/);
search.value='cube b';search.events.input();assert.match(count.textContent,/1 个对象 · 1 个动作/);
search.value='missing';search.events.input();assert.match(count.textContent,/0 个对象 · 0 个动作/);
search.value='';search.events.input();assert.match(count.textContent,/2 个对象 · 1 个动作/);
