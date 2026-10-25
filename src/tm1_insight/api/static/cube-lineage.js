/* Read-only presentation of Workbench index + existing Calculation / Rule IR.
 * No parsing, inferred member ownership, or co-read/write value-flow promotion. */
(function(){
  'use strict';
  const labels={TI_CANDIDATE:'TI 候选处理关联',RULE_REFERENCE:'Rule 声明式引用',FEEDER_REFERENCE:'Feeder 计算支持（非数值来源）'};
  const operations={CellPutN:'覆盖数值',CellPutS:'覆盖文本',CellIncrementN:'累加数值'};
  function slices(mapping){return (mapping?.items||[]).map(c=>{
    const b=c.binding||{}, fixed=b.kind==='FIXED_MEMBER', dynamic=['PARAMETER','DATA_ROW_VARIABLE','LOOKUP_COORDINATE'].includes(b.kind);
    return {dimension:c.dimension||`第 ${c.position} 个坐标（维度待确认）`,kind:fixed?'固定':dynamic?'动态':'待确认',value:fixed?b.value:b.expression||'待确认',reason:b.reason||'',evidence:b.evidence||[]};
  });}
  function writeRows(data,source,target){return (data.writes||[]).filter(w=>w.cube===target).map(w=>({
    ...w,target_slices:slices(w.coordinate_mapping),
    // Only read_nodes belonging to this value expression may supply source slices.
    // All other process reads remain observations, not this write's source.
    source_reads:(data.reads||[]).filter(r=>r.cube===source&&(w.read_nodes||[]).includes(r.id)),
    source_data_rows:(w.data_row_binding_status==='STATIC_CELL_VALUE_DEPENDENCY'?(w.data_row_value_dependencies||[]):[]).filter(d=>d.source_cube===source&&d.source_field?.kind==='CELL_VALUE'),
    source_row_slices:data.data_row_lineage?.source_view_binding?.cube===source?(data.data_row_lineage.source_coordinate_mapping||[]).map(c=>({dimension:c.dimension,kind:'动态',value:c.variable})):[],
    source_observations:(data.reads||[]).filter(r=>r.cube===source&&!(w.read_nodes||[]).includes(r.id))
  }));}
  function relations(data){const names=new Map((data.nodes||[]).filter(n=>n.type==='cube').map(n=>[n.id,n.name]));
    return (data.edges||[]).filter(e=>labels[e.kind]&&names.has(e.source)&&names.has(e.target)).map(e=>({...e,source_name:names.get(e.source),target_name:names.get(e.target),label:labels[e.kind]}));}
  function loc(e){return e?`${e.section||'Rule'}:${e.line||e.line_start||e.start_line||'?'}:${e.column||1}`:'位置待确认';}
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
    const lines=[result.summary_only?'# Cube 血缘摘要':'# Cube 血缘研究',`入口：${text(name)}`,'','范围：直接关系，最多 40 Cube / 100 关系；仅含本次主动核对的切面。静态关联不证明值流。',`截断：${result.limits.truncated?'是':'否'}；Rule 范围完整：${result.rule_scope?.complete?'是':'否'}`,'','## Cube 关系','',
      '| 来源 | 目标 | 机制 | TI |','|---|---|---|---|',...rows.map(r=>`| ${text(r.source_name)} | ${text(r.target_name)} | ${text(r.label)} | ${text((r.process_names||[]).join('、'))} |`),'','## 已核对的切面与计算','',
      '固定成员、动态表达式与待确认坐标分别标记。切面最多摘录 6 项；源码位置按 Section:行:列记录。源切面按本写入保留读取节点及已确认的 VIEW 值列依赖分别投影；其他来源证据保留在附录。未主动核对的关系不补造切面。',''];
    lines.push(`覆盖度：关系总数 ${covered.relations_total}，完整核对 ${covered.reviewed}，部分核对 ${covered.partial}，未核对 ${covered.unreviewed}；TI / Rule 核对 ${covered.checks_completed} / ${covered.checks_total}。`,'');
    if(result.report_run)lines.push(`有限范围研究：预算 ${result.report_run.budget} 项，已尝试 ${result.report_run.attempted} 项；取消：${result.report_run.cancelled?'是':'否'}；失败 ${result.report_run.failures.length} 项；预算截断：${result.report_run.budget_truncated?'是':'否'}。`,'');
    if(result.summary_only)lines.push('本文件为索引级摘要，不包含逐写入点核对明细；可下载或生成有限范围研究报告。','');
    else if(!records.length)lines.push('尚未主动核对 TI 写入点或 Rule；以上仅为索引 / 引用关系。','');
    (result.summary_only?[]:records).forEach(item=>{
      const row=byId.get(item.relation);if(!row)return;
      lines.push(`### ${text(row.source_name)} → ${text(row.target_name)}`,'');
      if(item.process){
        lines.push(`TI：${text(item.process)}`,'','| 写入点 | 写入方式 | 值表达式 | 该源 Cube 的切面 | 目标切面摘录 | 证据边界 |','|---|---|---|---|---|---|');
        (item.writes||[]).forEach(w=>{
          const reads=w.source_reads||[],rowValues=w.source_data_rows||[],readText=reads.length?reads.slice(0,4).map(r=>`${text(r.cube)} · ${text(loc(r.evidence))}：${coordinates(slices(r.coordinate_mapping))}`).join('；')+(reads.length>4?`；另 ${reads.length-4} 处读取见附录`:''):'',rowText=rowValues.length?rowValues.map(d=>`VIEW 行 ${text(d.source_cube)} / ${text(d.source_view)} / ${text(d.variable)}（值列）：${coordinates(w.source_row_slices||[])}`).join('；'):'',source=[readText,rowText].filter(Boolean).join('；')||'本表未确认该源切面；数据行及其他来源证据见附录';
          lines.push(`| ${text(loc(w.evidence))} | ${text(operations[w.operation]||w.operation)} | ${excerpt(w.value_expression)} | ${source} | ${coordinates(w.target_slices||[])} | ${reads.length||rowValues.length?'静态读取依赖；非运行结果证明':'本表的源切面待核对'} |`);
        });
        (item.writes||[]).forEach(w=>(w.control_context||[]).forEach(c=>lines.push('',`${text(loc(w.evidence))} 的条件（未求值）：${excerpt(c.condition||c.kind)} · ${text(loc(c))}`,'')));
        if(!(item.writes||[]).length)lines.push('未核对到此目标写入点，保留索引候选关系。');
        if(item.total>(item.writes||[]).length||item.read_total>160)lines.push('','本 TI 写入 / 保留读取超过本次展示或筛选范围，结果不完整；完整范围见技术证据。');
      }else{
        lines.push('Rule 为声明式计算，不是 TI 覆盖或累加操作。','',
          '| Rule 位置 | 目标区域 | 已确认 DB 源 Cube | 条件 | 计算表达式摘录 | 解析边界 |','|---|---|---|---|---|---|');
        (item.rules||[]).forEach(r=>lines.push(`| ${text(loc(r))} | ${excerpt(r.lhs?.raw)} | ${text([...new Set((r.db_references||[]).filter(d=>d.cube_resolved).map(d=>d.cube))].join('、')||'未确认')} | ${(r.conditions||[]).length?'已记录（未求值）':'未记录；不推断不存在'} | ${excerpt(r.rhs?.expression)} | ${r.status==='PARSED'?'当前契约结构已解析；非运行验证':r.status==='PARTIAL'?'部分解析；未确认项见附录':'关键结构待确认；见附录'} |`));
        lines.push('','源 Cube 引用不证明完整计算语义。裸成员的维度归属与动态坐标以证据附录为准，不按维度顺序猜测。');
      }
      lines.push('');
    });
    lines.push('## 技术证据附录','','<details>','<summary>展开完整已核对证据与未确认原因</summary>','','```json',JSON.stringify({schema:'cube-lineage-review-1',snapshot_id:snapshot,query:result.query,limits:result.limits,relations:rows,inspected:result.summary_only?[]:records,export_mode:result.summary_only?'INDEX_SUMMARY':'SCOPED_RESEARCH',review_coverage:covered,report_run:result.report_run},null,2),'```','','</details>');
    return lines.join('\n');
  }
  window.TM1CubeLineage={slices,writeRows,relations,coverage,markdownReport,operationLabel:operation=>operations[operation]||operation};
  const $=id=>document.getElementById(id),root=$('cl-root');if(!root)return;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
  const link=(text,url)=>{const a=el('a',text);a.href=url;return a;};
  let snapshot='',resultName='',generation=0,abort=null,result=null,rows=[],viewer=null,inspected=new Map(),searchTimer;
  let reviewAbort=null,reviewRun=0;const writeCache=new Map(),ruleCache=new Map();
  async function get(url,opts={}){const r=await fetch(url,{...opts,signal:opts.signal||abort?.signal});if(!r.ok){const e=new Error(r.status===409?'本地模型已变化，停止核对；未按名称重新绑定。':`本地分析请求失败 (${r.status})`);e.status=r.status;throw e;}return r.json();}
  function cached(cache,key,url,signal){if(!cache.has(key)){const pending=get(url,{signal}).catch(e=>{if(cache.get(key)===pending)cache.delete(key);throw e;});cache.set(key,pending);}return cache.get(key);}
  function updateCoverage(){if(!result)return;if(inspected.size)$('cl-report').disabled=false;const c=coverage(rows,[...inspected.values()]);$('cl-coverage').textContent=`关系 ${c.relations_total} 条：完整核对 ${c.reviewed}，部分核对 ${c.partial}，未核对 ${c.unreviewed}；TI / Rule ${c.checks_completed} / ${c.checks_total}。图截断：${result.limits.truncated?'是':'否'}；Rule 覆盖：${result.rule_scope?.complete?'当前预算完整':'不完整或未核对'}。`;}
  function updateRow(row){const records=[...inspected.values()].filter(x=>x.relation===row.id),cell=document.querySelector('tr[data-relation="'+CSS.escape(row.id)+'"]')?.children[3];if(!cell)return;cell.replaceChildren();
    const writes=records.flatMap(x=>(x.writes||[]).map(w=>({...w,process:x.process})));cell.append(el('p',`${records.length} / ${row.kind==='TI_CANDIDATE'?(row.process_names||[]).length:1} 个处理机制已核对`));
    const ops=[...new Set(writes.map(w=>operations[w.operation]||w.operation))];if(ops.length)cell.append(el('p',ops.join('、')+' · '+writes.length+' 个独立写入点'));
    writes.slice(0,3).forEach(w=>cell.append(el('p',`${w.process} · ${loc(w.evidence)}：`+w.target_slices.slice(0,3).map(c=>`${c.dimension}=${c.value}（${c.kind}）`).join('；')+`；源切面${(w.source_reads.length||w.source_data_rows.length)?'有静态读取依赖':'待核对'}`,'small')));
    if(writes.length>3)cell.append(el('p',`另 ${writes.length-3} 个写入点见详情`,'muted small'));
    if(records.some(x=>x.rules))cell.append(el('p','Rule 已核对；区域与动态坐标见详情'));
    if(records.some(x=>x.truncated))cell.append(el('p','存在单 TI 预算截断','muted small'));
  }
  function evidence(parent,title,data){const d=el('details');d.append(el('summary',title));d.ontoggle=()=>{if(d.open&&!d.dataset.loaded){d.dataset.loaded='1';d.append(el('pre',JSON.stringify(data,null,2)));}};parent.append(d);}
  function sliceBox(parent,title,items){const box=el('section');box.append(el('h3',title));if(!items.length)box.append(el('p','未取得可确认的坐标；不按变量名猜测。','muted'));
    items.forEach(c=>{const p=el('p');p.append(el('span',c.kind,'cl-pill'+(c.kind==='待确认'?' cl-unknown':'')),document.createTextNode(` ${c.dimension} = ${c.value}`));box.append(p);if(c.reason)box.append(el('p',c.reason,'muted small'));});parent.append(box);}
  function button(text,fn){const b=el('button',text,'btn');b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){if(e.name!=='AbortError')b.after(el('p',e.message,'err'));}finally{b.disabled=false;}};return b;}
  function writeDetail(host,w){const part=el('article',undefined,'cl-detail');part.append(el('h3',`${operations[w.operation]||w.operation} · ${loc(w.evidence)}`),el('p',`写入值表达式：${w.value_expression}`));
    const coord=el('div',undefined,'cl-slices');
    if(!w.source_reads.length&&!w.source_data_rows.length)sliceBox(coord,'源切面：未确认',[]);
    w.source_reads.forEach(r=>sliceBox(coord,`源读取：${r.cube} · ${loc(r.evidence)}`,slices(r.coordinate_mapping)));
    w.source_data_rows.forEach(d=>sliceBox(coord,`VIEW 值列依赖：${d.source_cube} / ${d.source_view} · ${d.variable}`,w.source_row_slices));
    sliceBox(coord,'目标切面',w.target_slices);part.append(coord);
    part.append(el('p',w.source_reads.length||w.source_data_rows.length?'值表达式包含上述静态读取依赖；条件可达性、运行结果及完整单元格映射仍未验证。':'本表未确认该源 Cube 的值切面；仅有声明或共同读写不能证明值依赖。','muted'));
    if(w.source_observations.length)part.append(el('p',`另有 ${w.source_observations.length} 处源 Cube 读取观察，不能据此当作本写入的源切面。`,'muted'));
    (w.control_context||[]).forEach(c=>part.append(el('p',`条件：${c.condition||c.kind} · ${loc(c)}（未求值）`)));
    if((w.unresolved_binding_reasons||[]).length)part.append(el('p','数据行来源绑定仍有缺失证据。','muted'));
    evidence(part,'源码定位、变量链与缺失证据',w);host.append(part);
  }
  async function loadTI(row,process,token,signal){
    const data=await cached(writeCache,process,'/api/workbench/writes?'+new URLSearchParams({snapshot_id:snapshot,process}),signal);if(token!==generation||signal?.aborted)return;
    const writes=writeRows(data,row.source_name,row.target_name);
    inspected.set(row.id+'::'+process,{relation:row.id,process,writes,limitations:data.limitations||[],total:data.total,read_total:data.read_total,truncated:data.total>data.writes.length||data.read_total>data.reads.length});
    updateRow(row);updateCoverage();return {data,writes};
  }
  async function inspectTI(host,row,process,token){
    const loaded=await loadTI(row,process,token);if(!loaded)return;const {data,writes}=loaded;
    host.replaceChildren(el('h3',`TI：${process}`));
    host.append(link('查看 TI 源码','/explorer/process/'+encodeURIComponent(process)+'?'+new URLSearchParams({model:snapshot})));
    host.append(link('研究此 TI 调用与读写','/graph?'+new URLSearchParams({ti:process,model:snapshot})));
    if(!writes.length)host.append(el('p','本次源码分析未核对到该目标写入点；保留索引候选关系，不虚构切面。'));
    writes.forEach(w=>writeDetail(host,w));

    if(data.total>data.writes.length||data.read_total>data.reads.length)host.append(el('p','已达到单 TI 80 个写入 / 160 个读取展示预算，结果不完整。','muted'));
    evidence(host,'分析范围与技术限制',data.limitations||[]);
  }
  async function loadRule(row,token,signal){
    const data=await cached(ruleCache,row.target_name,'/api/workbench/rules?'+new URLSearchParams({snapshot_id:snapshot,cube:row.target_name}),signal);if(token!==generation||signal?.aborted)return;
    if(!data.available||data.error){ruleCache.delete(row.target_name);throw new Error('Rule 语义结果不可用，未记为已核对');}
    const rules=(data.rules||[]).filter(r=>(r.db_references||[]).some(d=>d.cube_resolved&&d.cube===row.source_name));
    inspected.set(row.id,{relation:row.id,rules});updateRow(row);updateCoverage();return {data,rules};
  }
  async function inspectRule(host,row,token){
    const loaded=await loadRule(row,token);if(!loaded)return;const {rules}=loaded;
    host.replaceChildren();
    if(!rules.length)host.append(el('p','本次核对未保留此源 Cube 的 Rule 引用；不能补造计算关系。'));
    rules.forEach(r=>{const p=el('article',undefined,'cl-detail');p.append(el('h3',`Rule · ${loc(r)}`),el('p',`目标区域：${r.lhs?.raw||'待确认'}`),el('p',`计算表达式：${r.rhs?.expression||'待确认'}`));
      p.append(el('p','声明式计算，不是覆盖 / 累加操作。裸成员的维度归属不按 Cube 顺序猜测。','muted'));
      const coord=el('div',undefined,'cl-slices');
      (r.db_references||[]).filter(d=>d.cube_resolved&&d.cube===row.source_name).forEach(d=>{sliceBox(coord,'DB 源坐标（参数顺序，不冒充维度映射）',(d.coordinates||[]).map((c,i)=>({dimension:`坐标 ${i+1}`,kind:c.kind==='literal'?'固定':c.kind==='region'?'动态':'待确认',value:c.value||c.dimension||c.expression||c.raw||'待确认'})));});
      sliceBox(coord,'目标区域的维度归属',(r.lhs?.coordinates||[]).map(c=>({dimension:c.dimension||'维度待确认',kind:c.dimension?'区域声明':'待确认',value:c.member||c.value||c.raw||JSON.stringify(c.members||[])})));
      p.append(coord);evidence(p,'Rule 原文、条件与未确认项',r);host.append(p);
    });
  }
  function render(){
    const panels=$('cl-details');panels.replaceChildren();let active=null;
    const table=el('table'),head=el('tr');['来源 Cube','目标 Cube','处理机制','源 / 目标切面','证据状态','详情'].forEach(x=>head.append(el('th',x)));table.append(head);
    rows.forEach((row,index)=>{const tr=el('tr');tr.dataset.relation=row.id;tr.append(el('td',row.source_name),el('td',row.target_name),el('td',row.label+(row.process_names?.length?` · ${row.process_names.length} 个 TI`:'')),el('td','逐写入点 / Rule 按需核对'),el('td',row.kind==='TI_CANDIDATE'?'共同读写已记录；值流未证明':'源 Cube 引用已确认；完整计算待核对'));
      tr.children[3].textContent='尚未核对切面 · '+(row.kind==='TI_CANDIDATE'?`${row.process_names?.length||0} 个 TI，可逐项或有限范围核对`:'可核对 Rule 区域与 DB 来源');
      if(row.process_names?.length)tr.children[2].append(el('p',row.process_names.slice(0,3).join('、')+(row.process_names.length>3?'…':''),'muted small'));
      const body=el('section',undefined,'cl-relation-detail');body.hidden=true;body.id='cl-relation-'+index;panels.append(body);
      let loaded=false;
      const close=()=>{body.hidden=true;trigger.setAttribute('aria-expanded','false');tr.classList.remove('cl-selected');if(active===close)active=null;};
      const trigger=button('查看切面与证据',()=>{
        if(!body.hidden){close();return;}
        active?.();active=close;body.hidden=false;trigger.setAttribute('aria-expanded','true');tr.classList.add('cl-selected');
        if(loaded){body.scrollIntoView({block:'start'});return;}loaded=true;const token=generation;
        const heading=el('div',undefined,'cl-detail-heading');heading.append(el('h2',`${row.source_name} → ${row.target_name}`),button('关闭关系详情',()=>{close();trigger.focus();}));body.append(heading,el('p',row.label,'muted'));
        if(row.kind==='TI_CANDIDATE')(row.process_names||[]).forEach(process=>{const panel=el('div');body.append(button('核对 TI：'+process,()=>inspectTI(panel,row,process,token)),panel);});
        else {const panel=el('div');body.append(button('核对 Rule 切面',()=>inspectRule(panel,row,token)),panel);}
        evidence(body,'索引 / 引用证据',row);
        body.scrollIntoView({block:'start'});
      });
      trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-controls',body.id);
      const cell=el('td');cell.append(trigger);tr.append(cell);table.append(tr);
    });
    if(!rows.length)$('cl-table').replaceChildren(el('p','当前方向与预算内没有可展示的 Cube 关联；这不证明模型没有其他依赖。'));else $('cl-table').replaceChildren(table);
    const names=new Set(rows.flatMap(r=>[r.source_name,r.target_name]));$('cl-summary').replaceChildren(el('h2',`${resultName} · ${rows.length} 条关系 / ${names.size} 个相关 Cube`),link('查看入口 Cube 结构与全部写入 TI','/explorer/cube/'+encodeURIComponent(resultName)));
  }
  function draw(){if(!result||!$('cl-diagram').open)return;viewer?.destroy();const nodes=result.nodes.filter(n=>n.type==='cube'),ids=new Map(nodes.map((n,i)=>[n.id,'n'+i]));
    if(nodes.length>24||rows.length>30){$('cl-diagram-host').replaceChildren(el('p','当前图超过 24 个 Cube / 30 条关系的可读预算，请以关系表研究或缩小入口范围。'));return;}
    const safe=s=>String(s).replace(/[^\p{L}\p{N} _().-]/gu,' ');let code='flowchart LR\n'+nodes.map(n=>`${ids.get(n.id)}["${safe(n.name)}"]`).join('\n');
    rows.forEach(r=>code+=`\n${ids.get(r.source)} ${r.kind==='TI_CANDIDATE'?'-.->':'-->'}|"${r.kind==='TI_CANDIDATE'?'TI 候选关联（值流未证明）':'Rule 引用'}"| ${ids.get(r.target)}`);
    viewer=window.TM1Mermaid.mount($('cl-diagram-host'),{code,title:'Cube 关联简图'});
  }
  function stopReview(){++reviewRun;reviewAbort?.abort();if(result?.report_run?.status==='RUNNING'){result.report_run.cancelled=true;result.report_run.status='CANCELLED';}$('cl-review-cancel').disabled=true;$('cl-review').disabled=!result;$('cl-report').disabled=!result?.report_run&&!inspected.size;}
  async function batch(){if(!result)return;stopReview();const run=reviewRun,token=generation;reviewAbort=new AbortController();const signal=reviewAbort.signal,budget=Math.max(1,Math.min(20,Math.floor(Number($('cl-review-budget').value)||8))),groups=new Map();
    rows.forEach(r=>{const names=r.kind==='TI_CANDIDATE'?[...new Set(r.process_names||[])]:[r.target_name];names.forEach(name=>{const isTI=r.kind==='TI_CANDIDATE',key=(isTI?'TI:':'Rule:')+name;if(inspected.has(isTI?r.id+'::'+name:r.id))return;if(!groups.has(key))groups.set(key,{isTI,name,rows:[]});groups.get(key).rows.push(r);});});
    const all=[...groups.values()],selected=all.slice(0,budget),state={budget,planned:selected.length,status:'RUNNING',attempted:0,cancelled:false,budget_truncated:all.length>budget,failures:[]};result.report_run=state;
    $('cl-review').disabled=true;$('cl-review-cancel').disabled=false;$('cl-report').disabled=true;const progress=$('cl-review-progress');progress.hidden=false;progress.max=Math.max(1,selected.length);progress.value=0;
    for(const group of selected){if(signal.aborted||token!==generation||run!==reviewRun)break;state.attempted++;$('cl-review-status').textContent=`正在核对 ${state.attempted} / ${selected.length}：${group.name}`;
      try{for(const r of group.rows){if(signal.aborted)break;if(group.isTI)await loadTI(r,group.name,token,signal);else await loadRule(r,token,signal);}}
      catch(e){if(e.name!=='AbortError')state.failures.push({object:group.name,kind:group.isTI?'TI':'Rule',reason:e.message});if(e.status===409){state.model_changed=true;reviewAbort.abort();}}
      if(token!==generation||run!==reviewRun)return;progress.value=state.attempted;
    }
    if(token!==generation)return;state.cancelled=signal.aborted;state.status=state.cancelled?'CANCELLED':state.failures.length?'PARTIAL_FAILURE':'FINISHED';if(run!==reviewRun)return;$('cl-review').disabled=false;$('cl-review-cancel').disabled=true;$('cl-report').disabled=false;
    $('cl-review-status').textContent=`核对结束；尝试 ${state.attempted} 项，失败 ${state.failures.length} 项${state.budget_truncated?'，预算截断':''}。可下载已核对范围的研究报告。`;updateCoverage();
  }
  async function load(){const name=$('cl-name').value.trim();if(!name)return;stopReview();const token=++generation;abort?.abort();abort=new AbortController();viewer?.destroy();viewer=null;result=null;inspected.clear();writeCache.clear();ruleCache.clear();$('cl-review').disabled=true;$('cl-report').disabled=true;$('cl-coverage').textContent='';$('cl-review-status').textContent='';$('cl-review-progress').hidden=true;$('cl-export').disabled=true;$('cl-table').replaceChildren();$('cl-details').replaceChildren();$('cl-summary').replaceChildren();$('cl-diagram-host').replaceChildren();$('cl-status').textContent='正在查询本地索引并核对 Rule 引用…';
    try{const data=await get('/api/workbench/graph',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({snapshot_id:root.dataset.model||'',objects:[{type:'cube',name}],direction:$('cl-direction').value,view:'cubes',depth:1,node_budget:40,edge_budget:100,relation_types:['TI_CANDIDATE','RULE_REFERENCE']})});if(token!==generation)return;snapshot=data.snapshot_id;result=data;resultName=name;rows=relations(data);render();draw();$('cl-export').disabled=false;
      $('cl-status').textContent=data.limits.missing?.length?'入口 Cube 不在当前本地模型中。':`已完成直接关系查询。${data.limits.truncated?'预算已截断，结果不完整。':''}${data.rule_scope&&!data.rule_scope.complete?'部分 Rule 超出核对预算，结果不完整。':''}`;
      $('cl-review').disabled=false;updateCoverage();history.replaceState(null,'','/graph?'+new URLSearchParams({cube:name,model:snapshot}));
    }catch(e){if(token===generation&&e.name!=='AbortError')$('cl-status').textContent=e.message;}}
  $('cl-search').onsubmit=e=>{e.preventDefault();load();};$('cl-direction').onchange=load;
  $('cl-cancel').onclick=()=>{++generation;abort?.abort();$('cl-status').textContent='已取消本次请求；未保存任何研究或设计资产。';};
  $('cl-name').oninput=()=>{clearTimeout(searchTimer);const q=$('cl-name').value.trim();if(!q){$('cl-options').replaceChildren();return;}searchTimer=setTimeout(async()=>{try{const r=await fetch('/api/workbench/objects?'+new URLSearchParams({q,type:'cube',limit:20}));if(!r.ok)return;const data=await r.json();if($('cl-name').value.trim()===q)$('cl-options').replaceChildren(...data.objects.map(n=>new Option(n.name,n.name)));}catch(_){}},200);};
  $('cl-diagram').ontoggle=draw;
  $('cl-review').onclick=batch;$('cl-review-cancel').onclick=()=>{stopReview();$('cl-review-status').textContent='已取消核对；已取得的证据保留，可下载部分研究报告。';updateCoverage();};
  function download(summaryOnly){if(!result)return;const a=el('a');a.href=URL.createObjectURL(new Blob([markdownReport({...result,summary_only:summaryOnly},resultName,rows,[...inspected.values()],snapshot)],{type:'text/markdown;charset=utf-8'}));a.download=summaryOnly?'Cube-Lineage-Summary.md':'Cube-Research.md';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
  $('cl-export').onclick=()=>download(true);$('cl-report').onclick=()=>download(false);
  window.addEventListener('pagehide',()=>{stopReview();++generation;abort?.abort();clearTimeout(searchTimer);viewer?.destroy();});
  if(root.dataset.cube)load();
})();
