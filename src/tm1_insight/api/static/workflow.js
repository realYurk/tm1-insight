(function(){
  'use strict';
  const el=id=>document.getElementById(id), node=(tag,text,parent)=>{const n=document.createElement(tag);n.textContent=text??'';if(parent)parent.append(n);return n;};
  let task=null,header=null,selected='',view='overview',offset=0,listOffset=0,total=0,listTotal=0,pollTimer,searchTimer,searchSerial=0,renderSerial=0,listSerial=0;
  let evidenceSection='data',evidenceStart=1,evidenceLine=0,evidenceAuto=true;
  function error(message){el('wf-error').textContent=message||'';el('wf-error').hidden=!message;}
  async function request(url,body){const r=await fetch(url,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok){let j={};try{j=await r.json();}catch(_){}throw new Error(j.error||j.detail||'本地请求失败，请重试。');}return r.json();}
  function url(action,params={}){return '/api/workflow/tasks/'+encodeURIComponent(task)+'/'+action+'?'+new URLSearchParams(params);}
  function button(parent,label,action){const b=node('button',label,parent);b.className='btn ghost';b.type='button';b.addEventListener('click',action);return b;}
  function link(parent,label,href){const a=node('a',label,parent);a.href=href;return a;}
  function sourceLocation(e){return `${e?.section||'UNKNOWN'}:${e?.line??'?'}:${e?.column??'?'}`;}
  function evidence(parent,process,e){return button(parent,sourceLocation(e),()=>{selected=process;evidenceSection=e.section||'data';evidenceAuto=false;evidenceLine=e.line||1;evidenceStart=Math.max(1,evidenceLine-8);view='evidence';render();});}
  function conditions(parent,items){(items||[]).forEach(c=>node('p',`${c.kind} · ${c.condition||'条件未还原'} · 路径/次数未求值`,parent).className='workflow-unknown');}
  function table(parent,labels){const wrap=node('div','',parent);wrap.className='table-wrap';const t=node('table','',wrap);t.className='table';const row=node('tr','',node('thead','',t));labels.forEach(x=>node('th',x,row));return node('tbody','',t);}
  function choose(name){selected=name;evidenceAuto=true;el('wf-only').checked=true;offset=0;render();processes();}
  function busy(value){el('wf-submit').disabled=value;el('wf-cancel').disabled=!value;el('wf-submit').textContent=value?'正在解析…':'解析工作流';}
  async function start(){
    task=null;error('');busy(true);el('wf-cancel').disabled=true;el('wf-workspace').hidden=true;el('wf-progress').hidden=false;el('wf-state').textContent='正在选择本地入口…';el('wf-bar').removeAttribute('value');++renderSerial;
    try{const result=await request('/api/workflow/tasks',{process:el('wf-name').value.trim(),max_processes:Number(el('wf-max').value),max_depth:Number(el('wf-depth').value),source:el('wf-start').dataset.source});task=result.task_id;el('wf-cancel').disabled=false;const cleanUrl=new URL(window.location.href);cleanUrl.searchParams.delete('analyze');history.replaceState(null,'',cleanUrl);selected=el('wf-name').value.trim();view='overview';offset=listOffset=0;sessionStorage.setItem('tm1-workflow',JSON.stringify({task,process:selected}));poll();}catch(e){busy(false);el('wf-progress').hidden=true;error(e.message);}
  }
  async function poll(){
    clearTimeout(pollTimer);
    try{const s=await request('/api/workflow/tasks/'+encodeURIComponent(task));el('wf-progress').hidden=false;el('wf-state').textContent=`${s.stage_index}/${s.stages_total} · ${{Queued:'等待本地分析',Completed:'已完成','Checking local cache':'检查本地缓存','Saving local result':'保存结果'}[s.stage]||s.stage} · ${s.current}${s.total==null?'':' / '+s.total} · 已用 ${s.elapsed_seconds} 秒${s.cached?' · 复用结果缓存':''}`;
      const bar=el('wf-bar');if(s.total>0){bar.max=s.total;bar.value=s.current;}else bar.removeAttribute('value');
      if(s.status==='completed'){busy(false);el('wf-progress').hidden=true;const data=await request(url('result'));header=data.header;selected=header.root;evidenceAuto=true;el('wf-workspace').hidden=false;el('wf-root').textContent=header.root;const n=header.summary;el('wf-summary').textContent=`解析 ${n.parsed} / ${n.processes} 个 TI · ${n.execution} 条源码调用 · ${n.value_dependencies} 条表达式依赖（${n.confirmed_value_dependencies??0} 条两端 Cube 已确认） · ${n.unknowns} 个未知/边界项 · 全部未运行验证`;await Promise.all([processes(),render()]);}
      else if(['failed','cancelled'].includes(s.status)){busy(false);error(s.error||s.message||'任务已结束');sessionStorage.removeItem('tm1-workflow');}
      else pollTimer=setTimeout(poll,500);
    }catch(e){busy(false);error(e.message);sessionStorage.removeItem('tm1-workflow');}
  }
  async function processes(){const serial=++listSerial;try{const data=await request(url('result',{view:'processes',offset:listOffset,limit:50,q:el('wf-query').value.trim()}));if(serial!==listSerial)return;listTotal=data.total;el('wf-processes').replaceChildren();data.items.forEach(p=>{const li=node('li','',el('wf-processes'));const b=button(li,p.process,()=>choose(p.process));if(p.process===selected)b.setAttribute('aria-current','true');node('small',`层级 ${p.depth} · 读 ${p.reads.length} / 写 ${p.writes.length} · ${p.status}`,li);});el('wf-list-page').textContent=`${listTotal?listOffset+1:0}–${Math.min(listOffset+50,listTotal)} / ${listTotal}`;el('wf-list-prev').disabled=!listOffset;el('wf-list-next').disabled=listOffset+50>=listTotal;}catch(e){error(e.message);}}
  async function render(){
    if(!header)return;const serial=++renderSerial;error('');const parent=el('wf-content');parent.replaceChildren();node('p','正在读取当前视图…',parent);el('wf-selected').textContent='当前 TI：'+selected;
    document.querySelectorAll('[data-wf-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.wfView===view)));
    const paged=['execution','data','calculation','unknowns'].includes(view);el('wf-pager').hidden=!paged;el('wf-only-label').hidden=!paged;
    try{
      if(view==='overview'){
        parent.replaceChildren();node('h3','范围与已观察事实',parent);node('p','按源码调用逐层发现 TI；列表层级是发现距离，不代表执行时间顺序。目录索引与表达式依赖分别保留。',parent);
        node('p',`本次范围上限：${header.budgets.max_processes} 个 TI / ${header.budgets.max_depth} 层；相交范围复用 ${header.summary.cache_hits} 个 TI 的解析结果。`,parent).className='muted small';
        node('h4','观察到读取的 Cube',parent);node('p',header.summary.inputs.join('、')||'未确认',parent);node('h4','观察到写入的 Cube',parent);node('p',header.summary.outputs.join('、')||'未确认',parent);
        if(header.summary.input_count>100||header.summary.output_count>100)node('p','概览名称展示前 100 项，逐 TI 事实及导出保留预算内记录。',parent);
        if(header.cycles.length)node('p','静态调用闭环：'+header.cycles.map(g=>g.join(' → ')).join('；')+'。不证明运行时无限循环。',parent).className='workflow-unknown';
        const detail=await request(url('process',{process:selected}));if(serial!==renderSerial)return;const refs=detail.observations||[];node('h4','当前 TI 的直接读写观察',parent);for(const [label,ops] of [['读取',['cellgetn','cellgets']],['写入',['cellputn','cellputs','cellincrementn']]]){const cubes=[...new Set(refs.filter(r=>r.kind==='cube'&&ops.includes(r.operation.toLowerCase())).map(r=>r.target||'UNKNOWN · 动态目标'))];node('p',label+'：'+(cubes.join('、')||'当前语句解析未确认'),parent);}node('h4','当前 TI 的四个 Section',parent);node('p','Prolog / Metadata / Data / Epilog 均按原位置保留；字段或外部数据源未知时不补造来源。',parent);['prolog','metadata','data','epilog'].forEach(s=>button(parent,s,()=>{view='evidence';evidenceSection=s;evidenceAuto=false;evidenceStart=1;render();}));
        node('p','当前 TI 源码哈希：'+(detail.source_hash||'UNKNOWN · 本 TI 未解析'),parent).className='muted small';
        node('h4',`未知项与范围边界（${header.summary.unknowns} 个位置 / ${header.unknown_group_count} 组）`,parent);(header.unknown_groups||[]).slice(0,15).forEach(x=>{node('p',`${x.process} · ${x.reason} × ${x.count}${x.names.length?' · '+x.names.join('、'):''}`,parent).className='workflow-unknown';if(x.evidence?.section)evidence(parent,x.process,x.evidence);});
        if(header.unknown_group_count>15)node('p','概览展示前 15 组；全部未知位置可分页查看与导出。',parent);
        button(parent,'查看全部未知项',()=>{view='unknowns';offset=0;render();});
        const extra=node('details','',parent);node('summary','目录关系与入口 Caller（未绑定源码，不作执行证明）',extra);
        for(const v of ['callers','structure']){const data=await request(url('result',{view:v,limit:50}));if(serial!==renderSerial)return;node('h4',v==='callers'?`入口调用方索引 ${data.total}`:`未绑定语句的目录关系 ${data.total}`,extra);data.items.forEach(x=>node('p',x.process+' → '+x.target+' · STRUCTURAL_UNVERIFIED',extra));if(data.total>50)node('p','展示前 50 项；完整预算内目录记录见导出。',extra);}
        return;
      }
      if(view==='export'){
        parent.replaceChildren();node('h3','保存当前工作流说明',parent);node('p','JSON 包含调用、读写事实、计算 DAG、参数、坐标、未知项、源码哈希和范围预算。Markdown 为可读说明。原始源码字符串不纳入导出；材料含私有对象名，请本地保管。',parent);
        link(parent,'下载 JSON',url('export',{format:'json'})).className='btn primary';link(parent,'下载 Markdown',url('export',{format:'markdown'})).className='btn ghost';node('h4','分析边界',parent);header.limits.forEach(x=>node('p',x,parent));return;
      }
      if(view==='evidence'){
        if(evidenceAuto){const scope=await request(url('result',{view:'processes',process:selected,limit:1}));if(serial!==renderSerial)return;evidenceSection=scope.items[0]?.sections.find(s=>s.characters>0)?.section||'prolog';evidenceStart=1;evidenceAuto=false;}
        const data=await request(url('evidence',{process:selected,section:evidenceSection,start:evidenceStart,limit:80}));if(serial!==renderSerial)return;parent.replaceChildren();node('h3',selected+' · '+data.section,parent);const tabs=node('div','',parent);tabs.className='study-actions';['prolog','metadata','data','epilog'].forEach(s=>button(tabs,s,()=>{evidenceSection=s;evidenceAuto=false;evidenceStart=1;evidenceLine=0;render();}));
        node('p',`源码哈希 ${data.source_hash} · 共 ${data.total} 行。这里按需查看原始源码，包含原字符串值；导出默认隐藏它们。`,parent).className='muted small';
        const pre=node('pre','',parent);pre.className='code workflow-code';pre.setAttribute('aria-label','原始 TI 源码');
        window.tm1Source.mount(pre,{code:data.lines.map(x=>x.code).join('\n'),start:data.start,mode:'ti'});pre.querySelectorAll('.code-line').forEach((row,i)=>{if(data.lines[i]?.line===evidenceLine)row.classList.add('source-location-current');});

        const pager=node('div','',parent);pager.className='workflow-pager';button(pager,'前 80 行',()=>{evidenceStart=Math.max(1,evidenceStart-80);render();}).disabled=evidenceStart===1;node('span',`${data.total?data.start:0}–${Math.min(data.start+79,data.total)} / ${data.total}`,pager);button(pager,'后 80 行',()=>{evidenceStart+=80;render();}).disabled=data.start+80>data.total;return;
      }
      const data=await request(url('result',{view,offset,limit:50,process:el('wf-only').checked?selected:''}));if(serial!==renderSerial)return;total=data.total;parent.replaceChildren();
      if(view==='execution'){
        node('h3','源码调用，不代表已经执行或完成',parent);node('p','按发现 TI 和源码位置列出；包含框架封装。动态目标、范围外子 TI 和参数问题明确显示。',parent);
        data.items.forEach(x=>{const a=node('article','',parent);a.className='workflow-record';node('h4',`${x.process} → ${x.target||'UNKNOWN'}`,a);node('p',`${x.operation} · ${x.status} · ${x.expansion} · source_invocation`,a);evidence(a,x.process,x);conditions(a,x.control_context);if(x.target_resolution==='reaching_constant_alias')node('p','目标通过当前位置的常量赋值链确认。',a);
          const proof=node('div','',a);button(a,'查看目标与参数的赋值依据',async()=>{try{const report=await request(url('process',{process:x.process}));if(serial!==renderSerial)return;proof.replaceChildren();const nodes=new Map(report.nodes.map(n=>[n.id,n])),ids=new Set(),pending=[x.target_node];while(pending.length&&ids.size<100){const i=pending.pop();if(i==null||ids.has(i))continue;ids.add(i);pending.push(...(nodes.get(i)?.children||[]));}for(const b of x.bindings)for(const i of b.definition_nodes.slice(0,20)){if(ids.size<100)ids.add(i);}for(const i of ids){const n=nodes.get(i);if(n?.kind==='assignment'){node('p',n.variable+' = '+n.expression,proof);evidence(proof,x.process,n.evidence);}}for(const b of x.bindings){b.read_nodes.slice(0,20).forEach(i=>{const n=nodes.get(i);node('p','参数定义链读取：'+(n.cube||'UNKNOWN'),proof);evidence(proof,x.process,n.evidence);});b.unknown_nodes.slice(0,20).forEach(i=>{const n=nodes.get(i);node('p','UNKNOWN · '+(n.reason||'对象/坐标未确认'),proof);evidence(proof,x.process,n.evidence);});}node('p','赋值依据展示有上限，完整预算内 DAG 见 JSON；没有替换子 TI 参数或验证实际值。',proof).className='muted small';}catch(e){if(serial===renderSerial)error(e.message);}});
          const rows=table(a,['子 TI 参数','调用方表达式','绑定状态']);x.bindings.forEach(b=>{const r=node('tr','',rows);node('td',b.parameter||'UNKNOWN',r);node('td',b.expression,r);node('td',b.binding_status+(b.reason?' · '+b.reason:''),r);});});
      }else if(view==='data'){
        node('h3','读写引用与表达式依赖分开标记',parent);node('p','共同读 A、B、写 C 只构成读写事实。只有写入值定义链实际使用的 CellGet 才列为静态表达式依赖，不是运行时贡献。',parent);
        const rows=table(parent,['关系类型','TI','操作 / Cube','状态','源码']);data.items.forEach(x=>{const r=node('tr','',rows),value=x.relation_kind==='static_value_dependency';node('td',value?'表达式值依赖（静态）':'源码引用 / '+x.role,r);node('td',x.process,r);node('td',value?`${x.source_cube} → ${x.target||'UNKNOWN'}`:`${x.operation} → ${x.target||'UNKNOWN'}`,r);node('td',x.status,r);const c=node('td','',r);if(value){evidence(c,x.process,x.read_evidence);evidence(c,x.process,x.write_evidence);}else evidence(c,x.process,x);});
      }else if(view==='calculation'){
        node('h3','从写入值反向展开受支持的定义',parent);node('p','公式中的坐标标签来自完整离线维度顺序，实际成员与运行值仍需核对。这里没有跨 TI 参数替换。',parent);
        const details=new Map();
        for(const x of data.items){if(!details.has(x.process)){details.set(x.process,await request(url('process',{process:x.process})));if(serial!==renderSerial)return;}const report=details.get(x.process),nodes=new Map(report.nodes.map(n=>[n.id,n]));const a=node('article','',parent);a.className='workflow-record';node('h4',x.process+' · '+x.operation,a);node('pre',x.reconstructed,a).className='code calculation-expression';node('p',x.status+' · 未运行验证',a);evidence(a,x.process,x.evidence);conditions(a,x.control_context);x.reasons.forEach(r=>node('p','UNKNOWN · '+r,a).className='workflow-unknown');
          const definitions=table(a,['变量','该位置的定义','源码']);x.definition_nodes.slice(0,30).forEach(i=>{const n=nodes.get(i),row=node('tr','',definitions);node('td',n.variable,row);node('td',n.expression,row);evidence(node('td','',row),x.process,n.evidence);});
          const mappings=[['写入坐标',x.coordinate_mapping],...x.read_nodes.slice(0,20).map(i=>{const n=nodes.get(i);return ['读取 '+(n.cube||'UNKNOWN'),n.coordinate_mapping];})];mappings.forEach(([label,m])=>{const d=node('details','',a);node('summary',label+' · '+m.status,d);const rows=table(d,['位置','维度','坐标表达式']);m.items.slice(0,30).forEach(c=>{const n=nodes.get(c.node),r=node('tr','',rows);node('td',c.position,r);node('td',c.dimension||'UNKNOWN',r);node('td',n.name||n.expression||n.reason||n.value||n.kind,r);});if(m.items.length>30)node('p','PARTIAL · 只展示前 30 个坐标，完整记录见 JSON。',d);});if(x.definition_nodes.length>30||x.read_nodes.length>20)node('p','PARTIAL · 定义/读取展示达到上限，完整记录见 JSON。',a);}
      }else{node('h3','UNKNOWN / PARTIAL 与范围边界',parent);data.items.forEach(x=>{const a=node('article','',parent);a.className='workflow-record';node('p',x.process+' · '+(x.name?'['+x.name+'] ':'')+x.reason,a);if(x.evidence?.section)evidence(a,x.process,x.evidence);});}
      if(!data.items.length)node('p','当前范围没有可展示记录；不能据此证明没有其他执行或数据关系。',parent);
      el('wf-page').textContent=`${total?offset+1:0}–${Math.min(offset+50,total)} / ${total}`;el('wf-prev').disabled=!offset;el('wf-next').disabled=offset+50>=total;
    }catch(e){if(serial===renderSerial){parent.replaceChildren();error(e.message);}}
  }
  el('wf-start').addEventListener('submit',e=>{e.preventDefault();start();});
  el('wf-cancel').addEventListener('click',async()=>{try{await request('/api/workflow/tasks/'+encodeURIComponent(task)+'/cancel',{});poll();}catch(e){error(e.message);}});
  document.querySelectorAll('[data-wf-view]').forEach(b=>b.addEventListener('click',()=>{view=b.dataset.wfView;offset=0;render();}));
  el('wf-only').addEventListener('change',()=>{offset=0;render();});el('wf-prev').addEventListener('click',()=>{offset=Math.max(0,offset-50);render();});el('wf-next').addEventListener('click',()=>{offset+=50;render();});
  el('wf-filter').addEventListener('submit',e=>{e.preventDefault();listOffset=0;processes();});el('wf-list-prev').addEventListener('click',()=>{listOffset=Math.max(0,listOffset-50);processes();});el('wf-list-next').addEventListener('click',()=>{listOffset+=50;processes();});
  el('wf-name').addEventListener('input',()=>{el('wf-start').dataset.source='';clearTimeout(searchTimer);const serial=++searchSerial,q=el('wf-name').value.trim();el('wf-options').hidden=true;if(!q)return;searchTimer=setTimeout(async()=>{try{const r=await request('/api/process-search?'+new URLSearchParams({q,limit:20,scope:'name'}));if(serial!==searchSerial)return;const parent=el('wf-options');parent.replaceChildren();r.items.forEach(x=>button(parent,x.name,()=>{el('wf-name').value=x.name;el('wf-start').dataset.source=r.source||'';parent.hidden=true;++searchSerial;}));if(!r.items.length)node('p','没有匹配 TI；不会生成替代分析。',parent);parent.hidden=false;}catch(e){error(e.message);}},200);});
  document.addEventListener('click',e=>{if(!e.target.closest('#wf-start'))el('wf-options').hidden=true;});
  window.addEventListener('pagehide',()=>{clearTimeout(pollTimer);clearTimeout(searchTimer);++renderSerial;++listSerial;++searchSerial;});
  if(el('wf-start').dataset.auto==='1'){start();}else{try{const saved=JSON.parse(sessionStorage.getItem('tm1-workflow'));if(saved){task=saved.task;selected=saved.process;el('wf-name').value=selected;busy(true);poll();}}catch(_){}}
})();
