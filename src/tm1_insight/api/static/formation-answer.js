/* Presentation only; value provenance comes from the existing Calculation IR. */
(function(){
 'use strict';
 const $=id=>document.getElementById(id);if(!$('fa-root'))return;
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);return n;};
 const mode={CellPutN:'覆盖数值',CellPutS:'覆盖文本',CellIncrementN:'累加数值',RULE:'声明式计算'};
 const states={CONFIRMED_STATIC:'已确认静态表达式或引用',PARTIAL:'部分已确认',UNRESOLVED:'值来源尚未解析',CANDIDATE:'仅共同读写候选'};
 let run=0,controller=null,plan=null,query=null,results=new Map(),failures=new Map(),task='NOT_STARTED';
 const taskLabels={NOT_STARTED:'尚未开始',RUNNING:'分析中',COMPLETED:'已完成',CANCELLED:'已取消',PARTIAL_FAILURE:'部分失败',FAILED:'失败'};
 function source(g){if(g.value_kind==='CONSTANT')return '常量写入，无需源 Cube';if(g.value_kind==='PARAMETER')return '由已声明参数计算';return g.sources.length?g.sources.map(s=>s.kind==='VIEW_FIELD'?`${s.cube} / ${s.view} · VIEW 成员字段 ${s.variable}`:s.kind==='VIEW_VALUE'?`${s.cube} / ${s.view} · VIEW 值列 ${s.variable}`:s.cube).join('；'):'';}
 function slice(g){if(g.kind==='RULE')return g.area||'';const ordered=g.coordinates.filter(c=>['FIXED','DYNAMIC'].includes(c.kind)&&c.dimension&&c.expression!==null&&c.expression!==undefined&&c.expression!=='').sort((a,b)=>(a.kind!=='FIXED')-(b.kind!=='FIXED'));
  return ordered.slice(0,6).map(c=>`${c.dimension} = ${c.expression}${c.kind==='DYNAMIC'?'（动态表达式）':''}`).join('；')+(ordered.length>6?'；其余坐标见证据':'');}
 function position(g){return `${g.location.section}:${g.location.line}:${g.location.column||1}`;}
 function status(){const count=results.size;$('fa-status').textContent=`${taskLabels[task]} · ${count} / ${plan?.jobs.length||0} 项取得结果${failures.size?'；'+failures.size+' 项失败，可重试':''}`;$('fa-cancel').disabled=task!=='RUNNING';$('fa-retry').disabled=task==='RUNNING';$('fa-export').disabled=!results.size;}
 function proof(host,g){const d=el('details'),s=el('summary','源码定位与原始证据 · '+position(g));d.append(s);const a=el('a','打开对象源码');a.href='/explorer/'+(g.kind==='TI'?'process/':'cube/')+encodeURIComponent(g.owner)+'?'+new URLSearchParams({model:plan.snapshot_id});d.append(a);d.addEventListener('toggle',()=>{if(d.open&&!d.dataset.loaded){d.dataset.loaded='1';const pre=el('pre',JSON.stringify(g.evidence,null,2));pre.className='code';pre.style.maxHeight='320px';pre.style.overflow='auto';d.append(pre);}});host.append(d);}
 function render(){const host=$('fa-answer');host.replaceChildren();const blockers=new Map();let groups=0,truncated=false;
  for(const [job,data] of results){truncated ||= data.truncated;for(const b of data.blockers){const old=blockers.get(b.id);if(old)old.affected.push(...b.affected);else blockers.set(b.id,{...b,affected:[...b.affected]});}
   if(!data.groups.length){const empty=el('p',job+'：本次保留范围内没有匹配的写入/Rule；不证明运行时没有影响。');host.append(empty);continue;}
   groups+=data.groups.length;const box=el('details');box.className='writer-row';const gs=data.groups;
   const heading=el('summary');const name=el('span',gs[0].owner);name.className='writer-name';const count=el('span',gs.length+(gs[0].kind==='TI'?' 写入点':' 条规则'));count.className='tag op';heading.append(name,count,el('span',gs[0].kind==='TI'?'TI 写入':'Rule 计算'));box.append(heading);
   const detail=el('div');detail.className='writer-detail';
   const sourceLink=el('a','查看 '+(gs[0].kind==='TI'?'TI':'Cube')+' 源码');sourceLink.className='btn ghost btn-sm';sourceLink.href='/explorer/'+(gs[0].kind==='TI'?'process/':'cube/')+encodeURIComponent(gs[0].owner)+'?'+new URLSearchParams({model:plan.snapshot_id});detail.append(sourceLink);
   for(const g of gs){
    const coordinates=(g.coordinates||[]).filter(c=>['FIXED','DYNAMIC'].includes(c.kind)&&c.dimension&&c.expression!=null&&c.expression!=='').map(c=>({dimension:c.dimension,position:c.position,value:c.expression,expression:c.kind==='DYNAMIC'?c.expression:'',kind:c.kind}));
    const card=window.TM1WritePointCard.writePoint({operation:mode[g.operation]||g.operation,summary:slice(g),valueExpression:g.expression,valueLabel:g.kind==='RULE'?'计算表达式':'写入值',coordinateLabel:g.kind==='RULE'?'目标维度':'写入维度',coordinates,conditions:(g.conditions||[]).map(c=>c.condition||c.expression||c.raw||c.kind).filter(Boolean),open:gs.length<=3});
    if(source(g))card.append(el('p',source(g)));detail.append(card);
   }
   box.append(detail);host.append(box);
  }
  for(const [name,message] of failures)host.append(el('p',name+'：'+message+'。成功结果已保留，可重试。'));
  const ph=$('fa-problems');ph.replaceChildren();for(const b of blockers.values()){const p=el('section');p.append(el('h3',b.object),el('p',b.reason),el('p',b.action),el('p','影响 '+new Set(b.affected).size+' 个写入 / Rule 记录'));ph.append(p);}
  $('fa-problem-title').textContent=blockers.size?'影响当前值解释的共享证据缺口（'+blockers.size+' 项）':'当前已分析值表达式没有新增共享阻塞';
  $('fa-scope').textContent=(query.dimension?`切面条件：${query.dimension} = ${query.member}；只排除已确认固定坐标不匹配项。`:'区域概览：未指定切面，不代表匹配某个具体单元格。')+' '+(plan?.scope||'')+(plan?.truncated?' TI 预算截断：已选择 '+plan.writers_selected+' / 至少 '+plan.writers_discovered+' 个索引写入者。':'')+(truncated?' 单项分析预算截断，当前答案不完整。':'')+' 所有结果均为静态证据，不代表运行时验证。';
  if(!groups&&task==='COMPLETED')host.append(el('p','当前范围未取得匹配的形成记录。检查切面条件、索引范围与截断信息。'));
  status();
 }
 async function get(path,args,signal){let r;try{r=await fetch(path+'?'+new URLSearchParams(args),{signal});}catch(e){if(e.name==='AbortError')throw e;throw new Error('本地服务不可达或连接已中断，请确认服务仍在运行');}if(!r.ok){const e=new Error(r.status===409?'模型已变化，请重新查询；旧结果已失效':r.status===413?'超过单项源码预算':`本地分析请求失败 (${r.status})`);e.status=r.status;throw e;}return r.json();}
 function input(){return {cube:$('cl-name').value.trim(),dimension:$('fa-dimension').value.trim(),member:$('fa-member').value.trim(),budget:$('fa-budget').value};}
 async function start(resume=false){const next=input();if(!next.cube)return;if(Boolean(next.dimension)!==Boolean(next.member)){$('fa-status').textContent='请同时填写切面维度和固定成员，或同时留空查看区域概览。';return;}
  const same=resume&&query&&JSON.stringify(next)===JSON.stringify(query);controller?.abort();const token=++run;controller=new AbortController();const signal=controller.signal;
  if(!same){plan=null;results.clear();failures.clear();query=next;}$('cl-status').textContent='目标形成答案 · 本地只读分析';failures.delete('分析任务');task='RUNNING';render();
  try{if(!plan)plan=await get('/api/workbench/formation-plan',{snapshot_id:$('cl-root').dataset.model||'',cube:query.cube,budget:query.budget},signal);if(token!==run)return;
   // Sequential jobs cap fan-in concurrency at one; stopping never loses completed items.
   for(const job of plan.jobs){const id=job.kind+':'+job.name;if(results.has(id)&&!failures.has(id))continue;if(signal.aborted)break;
    $('fa-status').textContent=`分析中 · ${results.size} / ${plan.jobs.length} · ${job.name}`;
    try{const data=await get('/api/workbench/formation-item',{snapshot_id:plan.snapshot_id,cube:query.cube,kind:job.kind,name:job.name,dimension:query.dimension,member:query.member},signal);
     if(token!==run)return;if(data.snapshot_id!==plan.snapshot_id)throw Object.assign(new Error('模型身份不一致'),{status:409});results.set(id,data);if(data.incomplete)failures.set(id,'部分语句未完成解析，已取得的结果保留；详见技术证据');else failures.delete(id);
    }catch(e){if(e.name==='AbortError')throw e;if(e.status===409)throw e;failures.set(id,e.message);}render();
   }
   task=signal.aborted?'CANCELLED':failures.size?(results.size?'PARTIAL_FAILURE':'FAILED'):'COMPLETED';
  }catch(e){if(token!==run)return;if(e.status===409){results.clear();failures.clear();plan=null;}task=e.name==='AbortError'?'CANCELLED':results.size?'PARTIAL_FAILURE':'FAILED';if(e.name!=='AbortError')failures.set('分析任务',e.message);}
  if(token===run)render();
 }
 const secondary=document.querySelector?.('.formation-secondary');
 $('cl-search').addEventListener('submit',e=>{e.preventDefault();if(!secondary||secondary.open)start();else{controller?.abort();++run;plan=null;results.clear();failures.clear();query=input();task='NOT_STARTED';status();}});
 if(secondary)secondary.addEventListener('toggle',()=>{if(secondary.open&&(!plan||query?.cube!==input().cube))start();else if(!secondary.open){controller?.abort();task='CANCELLED';status();}});
 $('fa-retry').onclick=()=>start(true);
 $('fa-cancel').addEventListener('click',()=>{controller?.abort();task='CANCELLED';status();});
 $('fa-export').onclick=()=>{if(!plan||!results.size)return;const text=JSON.stringify({schema:'cube-formation-answer-1',snapshot_id:plan.snapshot_id,target:query.cube,filter:query,task_status:task,scope:plan,items:[...results.values()],failures:[...failures],runtime_verified:false},null,2);const a=el('a');a.href=URL.createObjectURL(new Blob([text],{type:'application/json'}));a.download='CubeFormationAnswer.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
 window.addEventListener('pagehide',()=>{++run;controller?.abort();});
 if($('cl-name').value&&(!secondary||secondary.open))start();else status();
})();
