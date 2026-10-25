/* Deferred fetches exercise the shipped controller, never a duplicate parser. */
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.value='';this.attrs={};this.classList={add(){},remove(){}};}
  append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}
  setAttribute(k,v){this.attrs[k]=v;}scrollIntoView(){}focus(){}click(){}after(){}
}
const ids=new Map(),get=id=>{if(!ids.has(id))ids.set(id,new Element(id));return ids.get(id);};
let requests=[],blob;
get('cl-direction').value='both';get('cl-review-budget').value='2';
const context={window:{addEventListener(){}},document:{getElementById:get,createElement:t=>new Element(t),querySelector:()=>null},CSS:{escape:x=>x},
  fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject})),AbortController,URLSearchParams,Blob,
  URL:{createObjectURL:b=>{blob=b;return 'blob:export';},revokeObjectURL(){}},history:{replaceState(){}},setTimeout:()=>0,clearTimeout(){},console};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
const tick=()=>new Promise(r=>setImmediate(r));
const respond=(request,data,status=200)=>request.resolve({ok:status===200,status,json:async()=>data});
const graph={snapshot_id:'synthetic',limits:{truncated:true},rule_scope:{complete:false},
  nodes:['A','B','C'].map(name=>({id:name,name,type:'cube'})),edges:[
    {id:'ab',source:'A',target:'B',kind:'TI_CANDIDATE',process_names:['One','Two']},
    {id:'ac',source:'A',target:'C',kind:'TI_CANDIDATE',process_names:['One']},
    {id:'bc',source:'B',target:'C',kind:'RULE_REFERENCE'},
    {id:'self',source:'B',target:'B',kind:'TI_CANDIDATE',process_names:['Self']}]};
const write={cube:'B',operation:'CellPutN',value_expression:'42',coordinate_mapping:{items:[]},read_nodes:[]};
const writes={writes:[write,{...write,cube:'C'}],reads:[],total:2,read_total:0};
async function query(){get('cl-name').value='B';get('cl-search').onsubmit({preventDefault(){}});respond(requests.at(-1),graph);await tick();}
async function exported(){get('cl-report').onclick();return JSON.parse((await blob.text()).split('```json\n')[1].split('\n```')[0]);}
(async()=>{
  await query();let task=get('cl-review').onclick();await tick();
  assert.match(requests.at(-1).url,/process=One/);respond(requests.at(-1),writes);await tick();
  assert.match(requests.at(-1).url,/process=Two/);respond(requests.at(-1),writes);await task;
  let data=await exported();assert.equal(data.review_coverage.reviewed,2);assert.equal(data.review_coverage.unreviewed,2);
  get('cl-export').onclick();let summary=JSON.parse((await blob.text()).split('```json\n')[1].split('\n```')[0]);
  assert.equal(summary.export_mode,'INDEX_SUMMARY');assert.equal(summary.inspected.length,0);assert.equal(summary.review_coverage.reviewed,2);
  assert.equal(data.report_run.budget_truncated,true);assert.equal(data.report_run.attempted,2);
  assert.equal(requests.filter(r=>r.url.includes('process=One')).length,1); // Reused across A→B and A→C.
  get('cl-review-budget').value='20';task=get('cl-review').onclick();await tick();
  assert.match(requests.at(-1).url,/rules/);respond(requests.at(-1),{},503);await tick();
  assert.match(requests.at(-1).url,/process=Self/);respond(requests.at(-1),writes);await task;
  data=await exported();assert.equal(data.report_run.failures.length,1);assert.equal(data.review_coverage.reviewed,3);
  assert.equal(data.review_coverage.unreviewed,1); // Failed Rule never counts as reviewed.
  await query();task=get('cl-review').onclick();await tick();respond(requests.at(-1),writes);await tick();
  const pending=requests.at(-1),count=requests.length;assert.match(pending.url,/process=Two/);
  get('cl-review-cancel').onclick();assert.equal(pending.options.signal.aborted,true);
  // Even an abort-ignoring late response cannot add evidence or start another request.
  respond(pending,writes);await task;await tick();assert.equal(requests.length,count);
  data=await exported();assert.equal(data.report_run.cancelled,true);assert.equal(data.review_coverage.partial,1);
  assert.equal(data.review_coverage.reviewed,1);assert.equal(data.review_coverage.unreviewed,2);
  await query();task=get('cl-review').onclick();await tick();const beforeConflict=requests.length;
  respond(requests.at(-1),{},409);await task;assert.equal(requests.length,beforeConflict);
  data=await exported();assert.equal(data.report_run.model_changed,true);assert.equal(data.review_coverage.reviewed,0);
  assert(requests.every(r=>r.url.startsWith('/api/workbench/')));
  console.log(JSON.stringify({budget:true,reused:true,failed:true,cancelled:true}));
})().catch(e=>{console.error(e);process.exitCode=1;});
