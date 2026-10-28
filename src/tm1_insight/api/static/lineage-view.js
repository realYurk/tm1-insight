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
 function cubeModel(result,rows,entry,records=[],limit=true){
  const root=(result.nodes||[]).find(n=>n.type==='cube'&&n.name===entry)?.id;
  const edges=rows.map(r=>({...r,...edgeSummary(r,records),direct:r.source===root||r.target===root}));
  const model={schema:'lineage-presentation-2',mode:'cube',snapshot_id:result.snapshot_id,entry,
   nodes:(result.nodes||[]).filter(n=>n.type==='cube').map(n=>{const up=edges.some(e=>e.source===n.id&&e.target===root),down=edges.some(e=>e.target===n.id&&e.source===root);
    return {...n,title:n.name,role:n.id===root?'当前 Cube':up&&down?'直接上下游':up?'直接上游':down?'直接下游':'间接关系',current:n.id===root};}),
   edges,truncated:!!result.limits?.truncated,runtime_verified:false};
  return limit?bounded(model):model;
 }
 function connectedFlow(model){
  const nodes=model.nodes,edges=model.edges;
  const root=nodes.find(n=>n.current),selected=new Set(root?[root.id]:[]),chosen=new Set();
  const byId=new Map(nodes.map(n=>[n.id,n])),paths=[],incoming=new Map();
  edges.forEach((e,i)=>{if(byId.has(e.source)&&byId.get(e.source).type!=='process'){
   if(!incoming.has(e.target))incoming.set(e.target,[]);incoming.get(e.target).push({x:e,j:i});
  }});
  edges.forEach((e,i)=>{if(!byId.has(e.source)||!byId.has(e.target))return;
   if(byId.get(e.source).type==='process'&&byId.get(e.target).type==='cube'){
    const inbound=incoming.get(e.source)||[];
    if(inbound.length)inbound.forEach(v=>paths.push({indices:[v.j,i],file:['file','database'].includes(byId.get(v.x.source).type)}));
    else paths.push({indices:[i],file:false});
   }else if(e.state==='RULE_REFERENCE')paths.push({indices:[i],file:false});
  });
  paths.sort((a,b)=>Number(b.file)-Number(a.file)||a.indices[0]-b.indices[0]);
  let changed=true;while(changed){changed=false;
   for(const path of paths){const all=new Set(path.indices.flatMap(i=>[edges[i].source,edges[i].target]));
    if(![...all].some(id=>selected.has(id)))continue;
    const newNodes=[...all].filter(id=>!selected.has(id)),newEdges=path.indices.filter(i=>!chosen.has(i));
    if(!newNodes.length&&!newEdges.length)continue;
    if(selected.size+newNodes.length>24||chosen.size+newEdges.length>30)continue;
    newNodes.forEach(id=>selected.add(id));newEdges.forEach(i=>chosen.add(i));changed=true;
   }
  }
  model.nodes=nodes.filter(n=>selected.has(n.id));model.edges=edges.filter((e,i)=>chosen.has(i));
  model.display_limits={nodes_total:nodes.length,edges_total:edges.length,nodes_hidden:nodes.length-model.nodes.length,edges_hidden:edges.length-model.edges.length};
  model.display_truncated=!!(model.display_limits.nodes_hidden||model.display_limits.edges_hidden);return model;
 }
 function fileLabel(input){
  if(input.status==='DYNAMIC_FILE_CANDIDATE')return '分隔文件 · 动态路径';
  const name=String(input.name||''),extension=(name.match(/\.([a-z0-9]+)$/i)||[])[1]?.toLowerCase();
  const type=extension==='csv'?'CSV':extension==='xlsx'||extension==='xlsm'||extension==='xls'?'Excel':'';
  return type?type+' · '+name:name;
 }
 function flowModel(result,rows,entry,inputs=[],writers=[]){
  const base=cubeModel(result,rows,entry,[],false), nodes=[...base.nodes], edges=[], known=new Set(nodes.map(n=>n.id)),edgeKeys=new Set();
  const addNode=n=>{if(!known.has(n.id)){known.add(n.id);nodes.push(n);}};
  const addEdge=e=>{const key=JSON.stringify([e.source,e.target,e.relation]);if(!edgeKeys.has(key)){edgeKeys.add(key);edges.push(e);}};
  for(const row of base.edges){
   if(row.kind==='RULE_REFERENCE'){addEdge({source:row.source,target:row.target,label:'Rule 引用',state:'RULE_REFERENCE',relation:row.id});continue;}
   for(const name of row.process_names||[]){const id='ti:'+JSON.stringify([name,row.target]);addNode({id,name,title:name,type:'process',role:'TI',process:name,relation:row.id});
    addEdge({source:row.source,target:id,label:'读取',state:'CANDIDATE',relation:row.id,process:name});
    addEdge({source:id,target:row.target,label:'写入',state:'SOURCE_CALL',relation:row.id,process:name});}
  }
  for(const input of inputs){const target=nodes.find(n=>n.type==='cube'&&n.name===input.target);if(!target)continue;
   const ti='ti:'+JSON.stringify([input.process,target.id]), external='input:'+JSON.stringify([input.type,input.name,input.process,target.id]);addNode({id:ti,name:input.process,title:input.process,type:'process',role:'TI',process:input.process,target:input.target});
   addNode({id:external,name:input.name,displayName:input.type==='file'?fileLabel(input):input.name,title:input.name,type:input.type,role:input.type==='file'?'文件':'数据库'});
   addEdge({source:external,target:ti,label:input.status==='DYNAMIC_FILE_CANDIDATE'?'可能的数据源':input.status==='STATIC_CODE_ASSIGNMENT'?'源码设置（静态）':'数据源声明',state:'CANDIDATE',process:input.process});
   addEdge({source:ti,target:target.id,label:'写入',state:'SOURCE_CALL',process:input.process,target_name:input.target});
  }
  for(const writer of writers){const target=nodes.find(n=>n.type==='cube'&&n.name===writer.target);if(!target)continue;const ti='ti:'+JSON.stringify([writer.process,target.id]);
   addNode({id:ti,name:writer.process,title:writer.process,type:'process',role:'TI',process:writer.process,target:writer.target});
   if(!edges.some(e=>e.source===ti&&e.target===target.id))addEdge({source:ti,target:target.id,label:'写入',state:'SOURCE_CALL',process:writer.process,target_name:writer.target});
  }
  return connectedFlow({...base,mode:'flow',nodes,edges});
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
  const lines=['flowchart LR'];model.nodes.forEach(n=>{const prefix=model.mode==='flow'?(n.type==='cube'?'▣ Cube · ':n.type==='process'?'⚙ TI · ':n.type==='file'?'▤ 文件 · ':'▥ 数据库 · '):(model.mode==='cube'?'▣ ':'TI · ');const text=escape(prefix+short(n.title)+(model.mode==='flow'?'':' · '+n.role)),id=ids.get(n.id);lines.push(n.type==='process'||model.mode==='process'?`${id}("${text}")`:`${id}["${text}"]`);if(n.current)lines.push(`style ${id} fill:#e7efff,stroke:#3564cd,stroke-width:2px`);});
  model.edges.forEach(e=>{if(!ids.has(e.source)||!ids.has(e.target))return;const uncertain=['CANDIDATE','PARTIAL_STATIC_VALUE_DEPENDENCY','INDEX_CALL','CONDITIONAL_CALL'].includes(e.state);lines.push(`${ids.get(e.source)} ${uncertain?'-.->':'-->'}|"${escape(e.label+(e.direct===false?' · 间接':''))}"| ${ids.get(e.target)}`);});
  return {code:lines.join('\n'),idMap:Object.fromEntries(model.nodes.map(n=>[ids.get(n.id),n]))};
 }
 window.TM1LineageView={edgeSummary,cubeModel,flowModel,callModel,mermaid,escape};
})();
