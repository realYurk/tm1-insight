/* Presentation of existing indexed relations / Workflow observations, never a parser. */
(function(){
 'use strict';
 function bounded(model){
  const allNodes=model.nodes,allEdges=model.edges;
  model.nodes=[...allNodes].sort((a,b)=>Number(b.current)-Number(a.current)||Number(a.role==='间接关系')-Number(b.role==='间接关系')).slice(0,24);
  const ids=new Set(model.nodes.map(n=>n.id));model.edges=allEdges.filter(e=>ids.has(e.source)&&ids.has(e.target)).slice(0,30);
  model.display_limits={nodes_total:allNodes.length,edges_total:allEdges.length,nodes_hidden:allNodes.length-model.nodes.length,edges_hidden:allEdges.length-model.edges.length};
  model.display_truncated=!!(model.display_limits.nodes_hidden||model.display_limits.edges_hidden);return model;
 }
 function edgeSummary(row,records){
  if(row.kind==='RULE_REFERENCE')return {state:'RULE_REFERENCE',label:'Rule 引用',note:'已确认表达式中的 Cube 引用；完整计算与坐标见详情。'};
  const selected=records.filter(r=>r.relation===row.id),writes=selected.flatMap(r=>r.writes||[]);
  const confirmed=writes.filter(w=>(w.source_reads||[]).length||(w.source_data_rows||[]).length).length;
  const done=new Set(selected.map(r=>r.process)).size,expected=new Set(row.process_names||[]).size;
  const complete=done===expected&&confirmed===writes.length&&selected.every(r=>(r.writes||[]).length&&!r.truncated);
  return {state:confirmed?(complete?'STATIC_VALUE_DEPENDENCY':'PARTIAL_STATIC_VALUE_DEPENDENCY'):'CANDIDATE',
   label:confirmed?`${confirmed} 处静态值依赖${confirmed<writes.length||done<expected?' · 含候选':''}`:`经 ${expected} TI · 候选`,
   note:confirmed?'仅这些写入点包含所选来源的静态值依赖；其他写入不随之升级。':'仅同一 TI 共同读写，不代表已确认值传输。'};
 }
 function cubeModel(result,rows,entry,records=[]){
  const root=(result.nodes||[]).find(n=>n.type==='cube'&&n.name===entry)?.id;
  const edges=rows.map(r=>({...r,...edgeSummary(r,records),direct:r.source===root||r.target===root}));
  return bounded({schema:'lineage-presentation-2',mode:'cube',snapshot_id:result.snapshot_id,entry,
   nodes:(result.nodes||[]).filter(n=>n.type==='cube').map(n=>{const up=edges.some(e=>e.source===n.id&&e.target===root),down=edges.some(e=>e.target===n.id&&e.source===root);
    return {...n,title:n.name,role:n.id===root?'当前 Cube':up&&down?'直接上下游':up?'直接上游':down?'直接下游':'间接关系',current:n.id===root};}),
   edges,truncated:!!result.limits?.truncated,runtime_verified:false});
 }
 function callModel(report){
  const source=(report.calls||[]).concat(report.downstream_calls||[]),pairs=new Set(source.filter(c=>c.target).map(c=>JSON.stringify([c.process,c.target])));
  const indexed=(report.callers||[]).filter(c=>!pairs.has(JSON.stringify([c.process,c.target]))).map(c=>({...c,index_only:true}));
  const calls=source.concat(indexed),seen=new Set(),edges=[];
  calls.filter(c=>c.target).forEach(c=>{const identity=JSON.stringify([c.process,c.target,c.index_only||false,c.section,c.line,c.column,c.bindings,c.control_context]);if(seen.has(identity))return;seen.add(identity);
   edges.push({id:'call-'+edges.length,source:c.process,target:c.target,
    label:c.index_only?'索引调用入口':c.control_context?.length?'条件调用':'源码调用',state:c.index_only?'INDEX_CALL':c.control_context?.length?'CONDITIONAL_CALL':'SOURCE_CALL',evidence:c});});
  const names=[...new Set([report.process,...edges.flatMap(e=>[e.source,e.target])])].sort();
  return bounded({schema:'lineage-presentation-2',mode:'process',snapshot_id:report.snapshot_id,entry:report.process,
   nodes:names.map(name=>({id:name,name,title:name,current:name===report.process,role:name===report.process?'当前 TI':(report.analyzed_process_names||[]).includes(name)?'已分析 TI':'范围外 TI'})),
   edges,dynamic_calls:source.filter(c=>!c.target),schedules:report.schedules||[],runtime_verified:false});
 }
 function escape(value){return String(value??'').replace(/&/g,'&amp;').replace(/"/g,'#quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/`/g,"'").replace(/[\r\n]/g,' ');}
 function mermaid(model){
  const ids=new Map(model.nodes.map((n,i)=>[n.id,'n'+i])),short=s=>s.length>62?s.slice(0,28)+' … '+s.slice(-26):s;
  const lines=['flowchart LR'];model.nodes.forEach(n=>{const text=escape((model.mode==='cube'?'▣ ':'TI · ')+short(n.title)+' · '+n.role),id=ids.get(n.id);lines.push(model.mode==='cube'?`${id}["${text}"]`:`${id}("${text}")`);if(n.current)lines.push(`style ${id} fill:#e7efff,stroke:#3564cd,stroke-width:2px`);});
  model.edges.forEach(e=>{if(!ids.has(e.source)||!ids.has(e.target))return;const uncertain=['CANDIDATE','PARTIAL_STATIC_VALUE_DEPENDENCY','INDEX_CALL','CONDITIONAL_CALL'].includes(e.state);lines.push(`${ids.get(e.source)} ${uncertain?'-.->':'-->'}|"${escape(e.label+(e.direct===false?' · 间接':''))}"| ${ids.get(e.target)}`);});
  return {code:lines.join('\n'),idMap:Object.fromEntries(model.nodes.map(n=>[ids.get(n.id),n]))};
 }
 window.TM1LineageView={edgeSummary,cubeModel,callModel,mermaid,escape};
})();
