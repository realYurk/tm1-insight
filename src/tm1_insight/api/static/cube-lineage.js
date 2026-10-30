/* Read-only presentation of Workbench index + existing Calculation / Rule IR.
 * No parsing, inferred member ownership, or co-read/write value-flow promotion.
 * Rescue 1.0: relations summarize what analysis already knows; opening a detail
 * auto-runs the existing bounded local analysis (budget + cancel preserved). */
(function(){
  'use strict';
  const labels={TI_CANDIDATE:'TI 共同读写候选',RULE_REFERENCE:'Rule 声明式计算',FEEDER_REFERENCE:'Feeder 计算支持（非数值来源）'};
  const operations={CellPutN:'覆盖数值',CellPutS:'覆盖文本',CellIncrementN:'累加数值'};
  function slices(mapping){return (mapping?.items||[]).map(c=>{
    const b=c.binding||{}, fixed=b.kind==='FIXED_MEMBER', dynamic=['PARAMETER','DATA_ROW_VARIABLE','LOOKUP_COORDINATE'].includes(b.kind);
    return {position:c.position,dimension:c.dimension||`第 ${c.position} 个坐标（维度待确认）`,kind:fixed?'固定':dynamic?'动态':'待确认',value:fixed?b.value:b.expression||'待确认',reason:b.reason||'',evidence:b.evidence||[]};
  });}
  function writeRows(data,source,target){return (data.writes||[]).filter(w=>w.cube===target).map(w=>({
    ...w,target_slices:slices(w.coordinate_mapping),
    // Only read_nodes belonging to this value expression may supply source slices.
    // All other process reads remain observations, not this write's source.
    source_reads:(data.reads||[]).filter(r=>r.cube===source&&r.resolution==='resolved'&&(w.confirmed_source_read_ids||((['STATIC','PARTIAL'].includes(w.trace_status))?(w.read_nodes||[]):[])).includes(r.id)),
    source_data_rows:(w.confirmed_data_row_dependencies||((['STATIC','PARTIAL'].includes(w.trace_status)&&w.data_row_binding_status==='STATIC_CELL_VALUE_DEPENDENCY')?(w.data_row_value_dependencies||[]):[])).filter(d=>d.source_cube===source&&d.source_field?.kind==='CELL_VALUE'),
    source_row_slices:data.data_row_lineage?.source_view_binding?.cube===source?(data.data_row_lineage.source_coordinate_mapping||[]).map(c=>({dimension:c.dimension,kind:'动态',value:c.variable})):[],
    source_observations:(data.reads||[]).filter(r=>r.cube===source&&!(w.read_nodes||[]).includes(r.id))
  }));}
  function relations(data){const names=new Map((data.nodes||[]).filter(n=>n.type==='cube').map(n=>[n.id,n.name]));
    return (data.edges||[]).filter(e=>labels[e.kind]&&names.has(e.source)&&names.has(e.target)).map(e=>({...e,source_name:names.get(e.source),target_name:names.get(e.target),label:labels[e.kind]}));}
  function loc(e){return e?`${e.section||'Rule'}:${e.line||e.line_start||'?'}:${e.column||1}`:'位置待确认';}
  function coverage(rows,records){
    let reviewed=0,partial=0,checks=0,total=0;
    rows.forEach(r=>{const items=records.filter(x=>x.relation===r.id),expected=r.kind==='TI_CANDIDATE'?[...new Set(r.process_names||[])]:['Rule'];
      const done=expected.filter(p=>items.some(x=>p==='Rule'?Array.isArray(x.rules):x.process===p)).length;
      total+=Math.max(1,expected.length);checks+=done;if(expected.length&&done===expected.length)reviewed++;else if(done)partial++;
    });return {relations_total:rows.length,reviewed,partial,unreviewed:rows.length-reviewed-partial,checks_completed:checks,checks_total:total};
  }
  function markdownReport(result,name,rows,inspections,snapshot){
    const text=value=>String(value??'待确认').replace(/[\r\n]/g,' ').replace(/[\\`*_[\]<>|#]/g,'\\$&');
    const excerpt=value=>{const s=String(value??'待确认');return text(s.length>240?s.slice(0,240)+'…（摘录）':s);};
    const coordinates=items=>items.length?items.slice(0,6).map(c=>`${excerpt(c.dimension)} = ${excerpt(c.value)}（${text(c.kind)}）`).join('；')+(items.length>6?`；另 ${items.length-6} 个坐标见附录`:''):'未取得可确认的坐标';
    const order=(a,b)=>{const x=String(a.relation)+'\0'+String(a.process||''),y=String(b.relation)+'\0'+String(b.process||'');return x<y?-1:x>y?1:0;};
    const records=[...inspections].sort(order),byId=new Map(rows.map(r=>[r.id,r]));
    const covered=coverage(rows,records);
    const lines=[result.summary_only?'# Cube 血缘摘要':'# Cube 血缘研究',`入口：${text(name)}`,'',`范围：${result.query?.depth||1} 层，最多 40 Cube / 100 关系；仅含本次分析过的切面。静态关联不证明值流。`,`截断：${result.limits.truncated?'是':'否'}；Rule 范围完整：${result.rule_scope?.complete?'是':'否'}`,'','## 通俗摘要：Cube 关系','',
      '| 来源 | 目标 | 机制 | TI |','|---|---|---|---|',...rows.map(r=>`| ${text(r.source_name)} | ${text(r.target_name)} | ${text(r.label)} | ${text((r.process_names||[]).join('、'))} |`),'','## 已分析的切面与计算','',
      '固定成员、动态表达式与待确认坐标分别标记。切面最多摘录 6 项；源码位置按 Section:行:列记录。源切面按本写入保留读取节点及已确认的 VIEW 值列依赖分别投影；其他来源证据保留在附录。未分析的关系不补造切面。',''];
    lines.push(`分析覆盖：关系总数 ${covered.relations_total}，已分析 ${covered.reviewed}，部分分析 ${covered.partial}，未分析 ${covered.unreviewed}；TI / Rule 分析 ${covered.checks_completed} / ${covered.checks_total}。`,'');
    if(result.report_run)lines.push(`有限范围研究：预算 ${result.report_run.budget} 项，已尝试 ${result.report_run.attempted} 项；取消：${result.report_run.cancelled?'是':'否'}；失败 ${result.report_run.failures.length} 项；预算截断：${result.report_run.budget_truncated?'是':'否'}。`,'');
    if(result.summary_only)lines.push('本文件为索引级摘要，不包含逐写入点分析明细；可下载或生成有限范围研究报告。','');
    else if(!records.length)lines.push('尚未分析 TI 写入点或 Rule；以上仅为索引 / 引用关系。','');
    (result.summary_only?[]:records).forEach(item=>{
      const row=byId.get(item.relation);if(!row)return;
      lines.push(`### ${text(row.source_name)} → ${text(row.target_name)}`,'');
      if(item.process){
        lines.push(`TI：${text(item.process)}`,'','| 写入点 | 写入方式 | 值表达式 | 该源 Cube 的切面 | 目标切面摘录 | 证据边界 |','|---|---|---|---|---|---|');
        (item.writes||[]).forEach(w=>{
          const reads=w.source_reads||[],rowValues=w.source_data_rows||[],readText=reads.length?reads.slice(0,4).map(r=>`${text(r.cube)} · ${text(loc(r.evidence))}：${coordinates(slices(r.coordinate_mapping))}`).join('；')+(reads.length>4?`；另 ${reads.length-4} 处读取见附录`:''):'',rowText=rowValues.length?rowValues.map(d=>`VIEW 行 ${text(d.source_cube)} / ${text(d.source_view)} / ${text(d.variable)}（值列）：${coordinates(w.source_row_slices||[])}`).join('；'):'',source=[readText,rowText].filter(Boolean).join('；')||'本表未确认该源切面；数据行及其他来源证据见附录';
          lines.push(`| ${text(loc(w.evidence))} | ${text(operations[w.operation]||w.operation)} | ${excerpt(w.value_expression)} | ${source} | ${coordinates(w.target_slices||[])} | ${reads.length||rowValues.length?'静态读取依赖；非运行结果证明':'本表的源切面未确认'} |`);
        });
        (item.writes||[]).forEach(w=>(w.control_context||[]).forEach(c=>lines.push('',`${text(loc(w.evidence))} 的条件（未求值）：${excerpt(c.condition||c.kind)} · ${text(loc(c))}`,'')));
        if(!(item.writes||[]).length)lines.push('本次源码分析未取得该目标写入点；保留索引候选关系。');
        if(item.total>(item.writes||[]).length||item.read_total>160)lines.push('','本 TI 写入 / 保留读取超过本次展示或筛选范围，结果不完整；完整范围见技术证据。');
      }else{
        lines.push('Rule 为声明式计算，不是 TI 覆盖或累加操作。','',
          '| Rule 位置 | 目标区域 | 已确认 DB 源 Cube | 条件 | 计算表达式摘录 | 解析边界 |','|---|---|---|---|---|---|');
        (item.rules||[]).forEach(r=>lines.push(`| ${text(loc(r))} | ${excerpt(r.lhs?.raw)} | ${text([...new Set((r.db_references||[]).filter(d=>d.cube_resolved).map(d=>d.cube))].join('、')||'未确认')} | ${(r.conditions||[]).length?'已记录（未求值）':'未记录；不推断不存在'} | ${excerpt(r.rhs?.expression)} | ${r.status==='PARSED'?'当前契约结构已解析；非运行验证':r.status==='PARTIAL'?'部分解析；未确认项见附录':'关键结构待确认；见附录'} |`));
        lines.push('','源 Cube 引用不证明完整计算语义。裸成员的维度归属与动态坐标以证据附录为准，不按维度顺序猜测。');
      }
      lines.push('');
    });
    lines.push('## 技术证据附录','','<details>','<summary>展开完整已分析证据与未确认原因</summary>','','```json',JSON.stringify({schema:'cube-lineage-review-1',snapshot_id:snapshot,query:result.query,limits:result.limits,relations:rows,inspected:result.summary_only?[]:records,export_mode:result.summary_only?'INDEX_SUMMARY':'SCOPED_RESEARCH',review_coverage:covered,report_run:result.report_run},null,2),'```','','</details>');
    return lines.join('\n');
  }
  window.TM1CubeLineage={slices,writeRows,relations,coverage,markdownReport,operationLabel:operation=>operations[operation]||operation};
  const $=id=>document.getElementById(id),root=$('cl-root');if(!root)return;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
  const link=(text,url)=>{const a=el('a',text);a.href=url;return a;};
  let snapshot='',resultName='',generation=0,abort=null,result=null,rows=[],viewer=null,inspected=new Map(),searchTimer,externalInputs=[],indexedWriters=[];
  let reviewAbort=null,reviewRun=0,detailAbort=null;const writeCache=new Map(),ruleCache=new Map();
  async function get(url,opts={}){let r;try{r=await fetch(url,{...opts,signal:opts.signal||abort?.signal});}catch(e){if(e.name==='AbortError')throw e;throw new Error('本地服务不可达或连接已中断，请检查启动窗口后重新分析。');}if(!r.ok){const e=new Error(r.status===409?'本地模型已变化，停止分析；未按名称重新绑定。':`本地分析请求失败 (${r.status})`);e.status=r.status;throw e;}return r.json();}
  function cached(cache,key,url,signal){
    if(signal?.aborted){const e=new Error('已取消');e.name='AbortError';return Promise.reject(e);}
    if(!cache.has(key)){
      let pending;const discard=()=>{if(cache.get(key)===pending)cache.delete(key);};
      pending=get(url,{signal}).then(value=>{signal?.removeEventListener('abort',discard);return value;},error=>{signal?.removeEventListener('abort',discard);discard();throw error;});
      cache.set(key,pending);signal?.addEventListener('abort',discard,{once:true});
    }
    return cache.get(key);
  }
  function analyzedCount(row){const records=[...inspected.values()].filter(x=>x.relation===row.id);
    return row.kind==='TI_CANDIDATE'?new Set(records.map(x=>x.process)).size:records.length;}
  function updateRow(row){const records=[...inspected.values()].filter(x=>x.relation===row.id);let cell=null;try{cell=document.querySelector('tr[data-relation="'+CSS.escape(row.id)+'"]')?.children[3]||null;}catch(_){return;}if(!cell)return;cell.replaceChildren();
    if(!records.length){cell.append(el('span','选中后自动分析','cl-hint'));return;}
    const writes=records.flatMap(x=>(x.writes||[]).map(w=>({...w,process:x.process})));
    if(row.kind==='TI_CANDIDATE'){
      const totalTI=(row.process_names||[]).length,done=new Set(records.map(x=>x.process)).size;
      cell.append(el('p',totalTI>1?`${done} / ${totalTI} 个 TI 已分析`:'已分析'));
      if(writes.length){
        const ops=[...new Set(writes.map(w=>operations[w.operation]||w.operation))].join('、');
        const fixed=writes.reduce((n,w)=>n+w.target_slices.filter(c=>c.kind==='固定').length,0);
        const sourced=writes.filter(w=>w.source_reads.length||w.source_data_rows.length).length;
        cell.append(el('p',`${writes.length} 个写入点 · ${ops}${fixed?` · ${fixed} 个固定坐标`:''}`,'small'));
        cell.append(el('p',window.TM1LineageView?.edgeSummary(row,[...inspected.values()]).label||(sourced?`${sourced} 个写入点已定位源读取`:'仅共同读写候选'),'small'));
      }else cell.append(el('p','本目标未取得写入点','small'));
    }else{
      const rules=records.flatMap(x=>x.rules||[]);
      cell.append(el('p',rules.length?`已分析 · ${rules.length} 条 Rule 引用此源`:'已分析 · 未保留此源引用'));
      if(rules.length){const dbs=[...new Set(rules.flatMap(r=>(r.db_references||[]).filter(d=>d.cube_resolved).map(d=>d.cube)))];
        if(dbs.length)cell.append(el('p','DB 引用：'+dbs.slice(0,2).join('、')+(dbs.length>2?'…':''),'small'));}
    }
    if(records.some(x=>x.truncated))cell.append(el('span','单 TI 预算截断','cl-pill cl-unknown'));}
  function evidence(parent,title,data){const d=el('details');d.append(el('summary',title));d.ontoggle=()=>{if(d.open&&!d.dataset.loaded){d.dataset.loaded='1';d.append(el('pre',JSON.stringify(data,null,2)));}};parent.append(d);}
  function sliceBox(parent,title,items){const visible=items.filter(c=>c.kind!=='待确认'&&c.dimension&&!String(c.dimension).includes('待确认')&&c.value&&c.value!=='待确认');if(!visible.length)return;
    const box=el('section');box.append(el('h3',title));visible.forEach(c=>{const p=el('p');p.append(el('span',c.kind,'cl-pill'),document.createTextNode(` ${c.dimension} = ${c.value}`));box.append(p);});parent.append(box);}
  function button(text,fn){const b=el('button',text,'btn');b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){if(e.name!=='AbortError')b.after(el('p',e.message,'err'));}finally{b.disabled=false;}};return b;}
  function writeDetail(host,w){
    const target=(w.target_slices||[]).filter(c=>c.kind==='固定'||c.kind==='动态').filter(c=>c.dimension&&!c.dimension.includes('待确认')&&c.value&&c.value!=='待确认');
    const card=window.TM1WritePointCard.writePoint({operation:operations[w.operation]||w.operation,summary:target.slice(0,3).map(c=>`${c.dimension} = ${c.value}`).join('；'),valueExpression:w.value_expression,conditions:(w.control_context||[]).map(c=>c.condition).filter(Boolean),coordinates:target.map(c=>({position:c.position,dimension:c.dimension,value:c.value,expression:c.kind==='动态'?c.value:'',kind:c.kind==='固定'?'FIXED':'DYNAMIC'}))});
    const coord=el('div',undefined,'cl-slices');
    w.source_reads.forEach(r=>sliceBox(coord,`来源：${r.cube}`,slices(r.coordinate_mapping)));
    w.source_data_rows.forEach(d=>sliceBox(coord,`来源：${d.source_cube} / ${d.source_view}`,w.source_row_slices));
    if(coord.childNodes.length)card.append(coord);
    host.append(card);
  }
  async function loadTI(row,process,token,signal){
    const data=await cached(writeCache,process,'/api/workbench/writes?'+new URLSearchParams({snapshot_id:snapshot,process}),signal);if(token!==generation||signal?.aborted)return;
    const writes=writeRows(data,row.source_name,row.target_name);
    inspected.set(row.id+'::'+process,{relation:row.id,process,writes,limitations:data.limitations||[],total:data.total,read_total:data.read_total,truncated:data.total>data.writes.length||data.read_total>data.reads.length});
    updateRow(row);updateCoverage();draw();return {data,writes};
  }
  /* 自动分析：复用同一缓存与 409 保护；单 TI 失败不阻断其余分析。 */
  async function analyzeTI(host,row,process,token,signal){
    host.replaceChildren(el('p','正在读取本地写入分析…','cl-loading'));
    try{
      const loaded=await loadTI(row,process,token,signal);
      if(!loaded||token!==generation||signal?.aborted)return;const {data,writes}=loaded;
      host.className='cl-process-card';host.replaceChildren(el('span','处理程序','cl-card-kicker'),el('h3',process),el('p',`${row.source_declared?'数据源声明：':''}${row.source_name ? row.source_name+' → ' : ''}${row.target_name}`,'cl-card-path'));
      host.append(link('查看 TI 源码','/explorer/process/'+encodeURIComponent(process)+'?'+new URLSearchParams({model:snapshot})));
      if(!writes.length)host.append(el('p','暂无可展示的写入切面。','muted'));
      writes.forEach(w=>writeDetail(host,w));
      if(data.total>data.writes.length||data.read_total>data.reads.length)host.append(el('p','已达到单 TI 80 个写入 / 160 个读取展示预算，结果不完整。','muted'));
    }catch(e){
      if(token!==generation||e.name==='AbortError')return;
      host.replaceChildren(el('p',e.status===413?'该 TI 超过局部源码预算，未自动分析；可进入 TI 页面按需研究。':'自动分析未完成：'+e.message,'cl-hint'));
    }
  }
  async function loadRule(row,token,signal){
    const data=await cached(ruleCache,row.target_name,'/api/workbench/rules?'+new URLSearchParams({snapshot_id:snapshot,cube:row.target_name}),signal);if(token!==generation||signal?.aborted)return;
    if(!data.available||data.error){ruleCache.delete(row.target_name);throw new Error('Rule 语义结果不可用');}
    const rules=(data.rules||[]).filter(r=>(r.db_references||[]).some(d=>d.cube_resolved&&d.cube===row.source_name));
    inspected.set(row.id,{relation:row.id,rules});updateRow(row);updateCoverage();draw();return {data,rules};
  }
  async function analyzeRule(host,row,token,signal){
    host.replaceChildren(el('p','正在读取本地 Rule 分析…','cl-loading'));
    try{
      const loaded=await loadRule(row,token,signal);
      if(!loaded||token!==generation||signal?.aborted)return;const {rules}=loaded;
      host.replaceChildren();
      if(!rules.length)host.append(el('p','当前 Rule 分析未保留此源 Cube 的引用；不能补造计算关系。'));
      rules.forEach(r=>host.append(window.TM1RuleSlice.render({target:r.lhs?.raw,href:'/explorer/cube/'+encodeURIComponent(row.target_name)+'?'+new URLSearchParams({model:snapshot})+'#rules'})));
    }catch(e){
      if(token!==generation||e.name==='AbortError')return;
      host.replaceChildren(el('p','自动分析未完成：'+e.message,'cl-hint'));
    }
  }
  function updateCoverage(){if(!result)return;const c=coverage(rows,[...inspected.values()]);
    $('cl-coverage').textContent=`分析覆盖：关系 ${c.relations_total} 条，已分析 ${c.reviewed+c.partial}，未分析 ${c.unreviewed}（未分析不代表无法确认，仅是尚未读取本地分析）。图截断：${result.limits.truncated?'是':'否'}；Rule 覆盖：${result.rule_scope?.complete?'当前预算完整':'不完整或未分析'}。`;}
  function render(){
    const panels=$('cl-details');panels.replaceChildren();let active=null;
    const table=el('table'),head=el('tr');['来源 Cube','目标 Cube','处理机制','关系摘要','操作'].forEach(x=>head.append(el('th',x)));table.append(head);
    rows.forEach((row,index)=>{
      const tr=el('tr');tr.dataset.relation=row.id;
      tr.append(el('td',row.source_name),el('td',row.target_name));
      const mech=el('td',row.label);
      if(row.kind==='TI_CANDIDATE'&&row.process_names?.length)mech.append(el('p',row.process_names.slice(0,3).join('、')+(row.process_names.length>3?` 等 ${row.process_names.length} 个`:''),'muted small'));
      if(row.kind==='RULE_REFERENCE')mech.append(el('p','声明式计算 · 引用此源 Cube','muted small'));
      tr.append(mech);
      const summary=el('td');summary.append(el('span','选中后自动分析','cl-hint'));tr.append(summary);
      const body=el('section',undefined,'cl-relation-detail');body.hidden=true;body.id='cl-relation-'+index;panels.append(body);
      let loaded=false;
      const close=()=>{body.hidden=true;trigger.setAttribute('aria-expanded','false');tr.classList.remove('cl-selected');if(active===close)active=null;detailAbort?.abort();detailAbort=null;if(focusRow===row){focusRow=null;draw();}};
      const trigger=button('查看详情',()=>{
        if($('cl-node-detail'))$('cl-node-detail').hidden=true;
        if(!body.hidden){close();return;}
        $('cl-inspector').hidden=false;viewer?.resize?.();
        active?.();active=close;body.hidden=false;trigger.setAttribute('aria-expanded','true');tr.classList.add('cl-selected');
        focusRow=row;draw();
        body.replaceChildren();loaded=true;const token=generation;
        detailAbort=new AbortController();const signal=detailAbort.signal;
        const heading=el('div',undefined,'cl-detail-heading');heading.append(el('h2',`${row.source_name} → ${row.target_name}`),button('关闭关系详情',()=>{close();trigger.focus();}));body.append(heading,el('p',row.label,'muted'));
        /* 自动分析：读取本地已有结果（缓存命中即刻显示），失败逐项降级，不阻断其他项。 */
        if(row.kind==='TI_CANDIDATE'){(async()=>{for(const process of (row.process_names||[])){if(signal.aborted)break;const panel=el('div');body.append(panel);await analyzeTI(panel,row,process,token,signal);}})();}
        else {const panel=el('div');body.append(panel);analyzeRule(panel,row,token,signal);}
        if(!window.matchMedia||!window.matchMedia('(min-width:1101px)').matches)body.scrollIntoView({block:'start'});
      });
      trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-controls',body.id);
      const cell=el('td');cell.append(trigger);tr.append(cell);table.append(tr);
    });
    if(!rows.length)$('cl-table').replaceChildren(el('p','当前方向与预算内没有可展示的 Cube 关联；这不证明模型没有其他依赖。'));else $('cl-table').replaceChildren(table);
    const names=new Set(rows.flatMap(r=>[r.source_name,r.target_name]));$('cl-summary').replaceChildren(el('h2',`${resultName} · ${rows.length} 条关系 / ${names.size} 个相关 Cube`),link('查看入口 Cube 结构与全部写入 TI','/explorer/cube/'+encodeURIComponent(resultName)));
  }
  let focusRow=null, showMore=false;
  const graphOptions=()=>({maxNodes:showMore?24:(window.innerWidth<1000?14:18),maxEdges:showMore?45:30});
  function draw(){if(!result||!$('cl-diagram').open)return;
    const view=window.TM1LineageView.flowModel(result,rows,resultName,externalInputs,indexedWriters,graphOptions());
    const key=JSON.stringify([view.nodes.map(n=>n.id),view.edges.map(e=>[e.source,e.target,e.label])]);
    const previous=viewer?.getPositions?.(),positions=viewer?._lineageKey===key?previous:undefined,manual=viewer?.isUserView?.()===true,saved=manual?viewer?.getView?.():undefined;
    function selectProcess(name,target,relation){$('cl-inspector').hidden=false;viewer?.resize?.();const host=$('cl-node-detail');Array.from($('cl-details').children).forEach(p=>{p.hidden=true;});host.hidden=false;host.replaceChildren();detailAbort?.abort();detailAbort=new AbortController();
      const input=externalInputs.find(x=>x.process===name&&(!target||x.target===target));
      const row=rows.find(r=>r.id===relation)||rows.find(r=>(r.process_names||[]).includes(name)&&(!target||r.target_name===target))||{id:'input:'+name,source_name:input?.name||'',source_declared:!!input,target_name:target||input?.target||resultName};
      analyzeTI(host,row,name,generation,detailAbort.signal);}
    const onEdgeClick=id=>{viewer.select([],id);const edge=view.edges[Number(id.slice(5))];if(edge?.process){selectProcess(edge.process,edge.target_name||externalInputs.find(x=>x.process===edge.process)?.target,edge.relation);return;}const r=rows.find(r=>r.id===edge?.relation);if(r)document.querySelector('tr[data-relation="'+CSS.escape(r.id)+'"] button')?.click();};
    const onNodeClick=id=>{const n=view.nodes.find(x=>x.id===id);if(!n)return;viewer.select([id]);if(n.type==='process'){selectProcess(n.process,n.target,n.relation);return;}detailAbort?.abort();detailAbort=new AbortController();const signal=detailAbort.signal;$('cl-inspector').hidden=false;viewer?.resize?.();const host=$('cl-node-detail');if(!host)return;Array.from($('cl-details').children).forEach(p=>{p.hidden=true;});host.hidden=false;host.replaceChildren(el('h2',n.name),el('p',n.role));if(n.type==='cube')host.append(link('查看 Cube 结构','/explorer/cube/'+encodeURIComponent(n.name)+'?'+new URLSearchParams({model:snapshot})),button('以此 Cube 查看上下游',()=>{$('cl-name').value=n.name;return load();}));
      const input=n.input, definition=input?.evidence?.definition;
      if(n.type==='file' && input){host.append(el('p','处理程序：'+input.process));
        if(definition){const detail=el('p','正在读取路径源码…','muted');host.append(detail);
          get('/api/workbench/detail?'+new URLSearchParams({snapshot_id:snapshot,type:'process',name:input.process}),{signal}).then(data=>{
            if(signal.aborted)return;const lines=String(data.object?.prolog||'').split(/\r?\n/);detail.replaceWith(el('p',`路径表达式 · Prolog 第 ${definition.line} 行`),el('pre',lines.slice(definition.line-1,definition.end_line).join('\n')),el('p','花括号内是运行时变量，实际文件名取决于执行参数。','muted'));
          }).catch(e=>{if(e.name!=='AbortError')detail.textContent='路径源码暂时无法读取。';});
        }
      }
    };
    const first=!viewer;if(first)viewer=window.TM1Canvas.mount($('cl-diagram-host'),{lineage:true,onNodeClick:id=>viewer._onNodeClick(id),onEdgeClick:id=>viewer._onEdgeClick(id)});
    viewer._onNodeClick=onNodeClick;viewer._onEdgeClick=onEdgeClick;
    viewer.setGraph({nodes:view.nodes.map(n=>({...n,type:n.type==='file'?'source':n.type})),edges:view.edges.map((e,i)=>({...e,id:'flow-'+i,kind:e.state==='RULE_REFERENCE'?'RULE_REFERENCE':e.label==='写入'?'TI_WRITE':'TI_READ',status:e.state==='CANDIDATE'?'CANDIDATE':''})),layout:'layered',positions,view:saved,fit:!manual});
    viewer._lineageKey=key;
    const rootNode=view.nodes.find(n=>n.current);if(rootNode)viewer.select([rootNode.id]);
    if(!positions&&saved&&rootNode&&previous?.[rootNode.id]){const after=viewer.getPositions()[rootNode.id],before=previous[rootNode.id];if(after)viewer.applyView({...saved,x:saved.x+(before.x-after.x)*saved.zoom,y:saved.y+(before.y-after.y)*saved.zoom});}
    $('cl-more').hidden=!view.display_truncated&&!showMore;$('cl-more').textContent=showMore?'精简画布':'显示更多';
    $('cl-canvas-limit').textContent=view.display_truncated?`图内折叠 ${view.display_limits.nodes_hidden} 个对象 / ${view.display_limits.edges_hidden} 条连接；可点击“显示更多”或查看关系列表。`:'';
  }
  function stopReview(){++reviewRun;reviewAbort?.abort();if(result?.report_run?.status==='RUNNING'){result.report_run.cancelled=true;result.report_run.status='CANCELLED';}$('cl-review-cancel').disabled=true;$('cl-review').disabled=!result;$('cl-report').disabled=!result?.report_run&&!inspected.size;}
  async function batch(){if(!result)return;stopReview();const run=reviewRun,token=generation;reviewAbort=new AbortController();const signal=reviewAbort.signal,budget=Math.max(1,Math.min(20,Math.floor(Number($('cl-review-budget').value)||8))),groups=new Map();
    rows.forEach(r=>{const names=r.kind==='TI_CANDIDATE'?[...new Set(r.process_names||[])]:[r.target_name];names.forEach(name=>{const isTI=r.kind==='TI_CANDIDATE',key=(isTI?'TI:':'Rule:')+name;if(inspected.has(isTI?r.id+'::'+name:r.id))return;if(!groups.has(key))groups.set(key,{isTI,name,rows:[]});groups.get(key).rows.push(r);});});
    const all=[...groups.values()],selected=all.slice(0,budget),state={budget,planned:selected.length,status:'RUNNING',attempted:0,cancelled:false,budget_truncated:all.length>budget,failures:[]};result.report_run=state;
    $('cl-review').disabled=true;$('cl-review-cancel').disabled=false;$('cl-report').disabled=true;const progress=$('cl-review-progress');progress.hidden=false;progress.max=Math.max(1,selected.length);progress.value=0;
    for(const group of selected){if(signal.aborted||token!==generation||run!==reviewRun)break;state.attempted++;$('cl-review-status').textContent=`正在分析 ${state.attempted} / ${selected.length}：${group.name}`;
      try{for(const r of group.rows){if(signal.aborted)break;if(group.isTI)await loadTI(r,group.name,token,signal);else await loadRule(r,token,signal);}}
      catch(e){if(e.name!=='AbortError')state.failures.push({object:group.name,kind:group.isTI?'TI':'Rule',reason:e.message});if(e.status===409){state.model_changed=true;reviewAbort.abort();}}
      if(token!==generation||run!==reviewRun)return;progress.value=state.attempted;
    }
    if(token!==generation)return;state.cancelled=signal.aborted;state.status=state.cancelled?'CANCELLED':state.failures.length?'PARTIAL_FAILURE':'FINISHED';if(run!==reviewRun)return;$('cl-review').disabled=false;$('cl-review-cancel').disabled=true;$('cl-report').disabled=false;
    $('cl-review-status').textContent=`分析结束；尝试 ${state.attempted} 项，失败 ${state.failures.length} 项${state.budget_truncated?'，预算截断':''}。可下载已分析范围的研究报告。`;updateCoverage();
  }
  async function load(){showMore=false;const name=$('cl-name').value.trim();if(!name)return;stopReview();const token=++generation;abort?.abort();detailAbort?.abort();detailAbort=null;abort=new AbortController();viewer?.destroy();viewer=null;result=null;externalInputs=[];indexedWriters=[];$('cl-relations').hidden=true;$('cl-inspector').hidden=true;$('cl-node-detail').hidden=true;$('cl-node-detail').replaceChildren();inspected.clear();writeCache.clear();ruleCache.clear();$('cl-review').disabled=true;$('cl-report').disabled=true;$('cl-coverage').textContent='';$('cl-review-status').textContent='';$('cl-review-progress').hidden=true;$('cl-export').disabled=true;$('cl-table').replaceChildren();$('cl-details').replaceChildren();$('cl-summary').replaceChildren();$('cl-diagram-host').replaceChildren();$('cl-status').textContent='正在查找数据来源和处理路径…';
    try{const data=await get('/api/workbench/graph',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({snapshot_id:root.dataset.model||'',objects:[{type:'cube',name}],direction:$('cl-direction').value,view:'cubes',depth:Number($('cl-depth')?.value)||1,node_budget:40,edge_budget:100,relation_types:['TI_CANDIDATE','RULE_REFERENCE']})});if(token!==generation)return;snapshot=data.snapshot_id;root.dataset.model=snapshot;result=data;resultName=name;rows=relations(data);$('cl-relations').hidden=!!data.limits.missing?.length;render();draw();$('cl-export').disabled=false;
      $('cl-status').textContent=data.limits.missing?.length?'入口 Cube 不在当前本地模型中。':`展示 ${data.query?.depth||1} 层已索引关系；虚线表示读取或数据源声明，不能单独证明值传输。外部来源检查前 4 个 Cube、各最多 12 个写入程序。${data.limits.truncated?' 本次范围已截断。':''}`;
      const moduleLink=$('cl-module');if(moduleLink){const selected=[...result.nodes.filter(n=>n.type==='cube').map(n=>({type:'cube',name:n.name})),...[...new Set(rows.flatMap(r=>r.process_names||[]))].map(name=>({type:'process',name}))], selection=JSON.stringify(selected);
        const url='/module-reconstruction?'+new URLSearchParams({kind:'cube',name,model:snapshot,selection});
        const tooLarge=selected.length>60||selection.length>20000||url.length>8000;
        moduleLink.href=tooLarge?'#cl-module':url;
        moduleLink.setAttribute('aria-disabled',String(tooLarge));moduleLink.onclick=tooLarge?e=>{e.preventDefault();$('cl-status').textContent=`当前范围有 ${selected.length} 个对象，超过模块规格移交上限（最多 60 个对象，链接长度最多 8000 字符）；请缩小范围后重试。当前关系仍保留在本页。`;}:null;
        moduleLink.textContent=tooLarge?`范围超出模块规格上限（${selected.length} 个对象）`:`选取此局部范围生成模块规格（${selected.length} 个对象）`;}
      $('cl-review').disabled=false;updateCoverage();history.replaceState(null,'','/graph?'+new URLSearchParams({cube:name,model:snapshot}));
      const candidates=[name,...data.nodes.filter(n=>n.type==='cube'&&n.name!==name).map(n=>n.name)].slice(0,4);
      for(const cube of candidates){if(token!==generation||abort.signal.aborted)break;try{const sources=await get('/api/workbench/lineage-inputs?'+new URLSearchParams({snapshot_id:snapshot,cube}));if(token!==generation)break;externalInputs.push(...sources.items);indexedWriters.push(...(sources.writers||[]).map(process=>({process,target:cube})));if(sources.truncated)$('cl-status').textContent+=' 部分写入程序超出本次预算。';draw();}catch(e){if(e.name==='AbortError')break;if(token===generation)$('cl-status').textContent+=e.status===409?' 模型已变化，请重新分析。':' 部分外部来源未能读取。';if(e.status===409)break;}}
    }catch(e){if(token===generation&&e.name!=='AbortError')$('cl-status').textContent=e.message;}}
  $('cl-search').onsubmit=e=>{e.preventDefault();$('lineage-search-status').textContent='';load();};$('cl-direction').onchange=load;if($('cl-depth'))$('cl-depth').onchange=load;
  $('cl-zoom-in').onclick=()=>viewer?.zoomBy(1.25);$('cl-zoom-out').onclick=()=>viewer?.zoomBy(.8);$('cl-fit').onclick=()=>{viewer?.markUserView();viewer?.fit();};
  $('cl-more').onclick=()=>{showMore=!showMore;viewer?.resetUserView();draw();};
  $('cl-close-inspector').onclick=()=>{$('cl-inspector').hidden=true;detailAbort?.abort();viewer?.resize?.();};
  $('cl-mermaid').onclick=()=>{if(!result)return;const code=window.TM1LineageView.mermaid(window.TM1LineageView.flowModel(result,rows,resultName,externalInputs,indexedWriters,graphOptions())).code;const a=el('a');a.href=URL.createObjectURL(new Blob([code],{type:'text/plain;charset=utf-8'}));a.download='Cube-Lineage.mmd';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
  $('lineage-clear').addEventListener('click',()=>{++generation;abort?.abort();detailAbort?.abort();stopReview();$('fa-cancel')?.click();viewer?.destroy();viewer=null;result=null;externalInputs=[];$('cl-relations').hidden=true;$('cl-status').textContent='';history.replaceState(null,'','/graph'+(snapshot?'?'+new URLSearchParams({model:snapshot}):''));});
  $('cl-cancel').onclick=()=>{++generation;abort?.abort();detailAbort?.abort();$('cl-status').textContent='已取消本次请求；未保存任何研究或设计资产。';};
  if(!$('cl-search').dataset.lineageSearch)$('cl-name').oninput=()=>{clearTimeout(searchTimer);const q=$('cl-name').value.trim();if(!q){$('cl-options').replaceChildren();return;}searchTimer=setTimeout(async()=>{try{const r=await fetch('/api/workbench/objects?'+new URLSearchParams({q,type:'cube',limit:20}));if(!r.ok)return;const data=await r.json();if($('cl-name').value.trim()===q)$('cl-options').replaceChildren(...data.objects.map(n=>new Option(n.name,n.name)));}catch(_){}},200);};
  $('cl-diagram').ontoggle=draw;
  $('cl-review').onclick=batch;$('cl-review-cancel').onclick=()=>{stopReview();$('cl-review-status').textContent='已停止；已取得的证据保留，可下载部分研究报告。';updateCoverage();};
  function download(summaryOnly){if(!result)return;const a=el('a');a.href=URL.createObjectURL(new Blob([markdownReport({...result,summary_only:summaryOnly},resultName,rows,[...inspected.values()],snapshot)],{type:'text/markdown;charset=utf-8'}));a.download=summaryOnly?'Cube-Lineage-Summary.md':'Cube-Research.md';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
  if($('cl-json'))$('cl-json').onclick=()=>{if(!result)return;const a=el('a');a.href=URL.createObjectURL(new Blob([JSON.stringify({schema:'cube-lineage-review-1',snapshot_id:snapshot,target:resultName,scope:result,presentation:window.TM1LineageView.cubeModel(result,rows,resultName,[...inspected.values()]),inspected:[...inspected.values()],runtime_verified:false},null,2)],{type:'application/json'}));a.download='Cube-Lineage-Technical.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
  $('cl-export').onclick=()=>download(true);$('cl-report').onclick=()=>download(false);
  window.addEventListener('pagehide',()=>{stopReview();++generation;abort?.abort();clearTimeout(searchTimer);viewer?.destroy();});
  if($('cl-relations'))$('cl-relations').ontoggle=()=>{if($('cl-relations').open&&!result)load();};
  if(root.dataset.cube)load();
})();
