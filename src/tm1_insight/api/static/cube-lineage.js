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
    source_observations:(data.reads||[]).filter(r=>r.cube===source&&!(w.read_nodes||[]).includes(r.id))
  }));}
  function relations(data){const names=new Map((data.nodes||[]).filter(n=>n.type==='cube').map(n=>[n.id,n.name]));
    return (data.edges||[]).filter(e=>labels[e.kind]&&names.has(e.source)&&names.has(e.target)).map(e=>({...e,source_name:names.get(e.source),target_name:names.get(e.target),label:labels[e.kind]}));}
  function loc(e){return e?`${e.section||'Rule'}:${e.line||e.line_start||e.start_line||'?'}:${e.column||1}`:'位置待确认';}
  function markdownReport(result,name,rows,inspections,snapshot){
    const text=value=>String(value??'待确认').replace(/[\r\n]/g,' ').replace(/[\\`*_[\]<>|#]/g,'\\$&');
    const excerpt=value=>{const s=String(value??'待确认');return text(s.length>240?s.slice(0,240)+'…（摘录）':s);};
    const coordinates=items=>items.length?items.slice(0,6).map(c=>`${excerpt(c.dimension)} = ${excerpt(c.value)}（${text(c.kind)}）`).join('；')+(items.length>6?`；另 ${items.length-6} 个坐标见附录`:''):'未取得可确认的坐标';
    const order=(a,b)=>{const x=String(a.relation)+'\0'+String(a.process||''),y=String(b.relation)+'\0'+String(b.process||'');return x<y?-1:x>y?1:0;};
    const records=[...inspections].sort(order),byId=new Map(rows.map(r=>[r.id,r]));
    const lines=['# Cube 血缘研究',`入口：${text(name)}`,'','范围：直接关系，最多 40 Cube / 100 关系；仅含本次主动核对的切面。静态关联不证明值流。',`截断：${result.limits.truncated?'是':'否'}；Rule 范围完整：${result.rule_scope?.complete?'是':'否'}`,'','## Cube 关系','',
      '| 来源 | 目标 | 机制 | TI |','|---|---|---|---|',...rows.map(r=>`| ${text(r.source_name)} | ${text(r.target_name)} | ${text(r.label)} | ${text((r.process_names||[]).join('、'))} |`),'','## 已核对的切面与计算','',
      '固定成员、动态表达式与待确认坐标分别标记。切面最多摘录 6 项；源码位置按 Section:行:列记录。源切面表仅投影本写入保留读取节点的依赖；数据行变量等其他来源证据保留在附录。未主动核对的关系不补造切面。',''];
    if(!records.length)lines.push('尚未主动核对 TI 写入点或 Rule；以上仅为索引 / 引用关系。','');
    records.forEach(item=>{
      const row=byId.get(item.relation);if(!row)return;
      lines.push(`### ${text(row.source_name)} → ${text(row.target_name)}`,'');
      if(item.process){
        lines.push(`TI：${text(item.process)}`,'','| 写入点 | 写入方式 | 值表达式 | 该源 Cube 的切面 | 目标切面摘录 | 证据边界 |','|---|---|---|---|---|---|');
        (item.writes||[]).forEach(w=>{
          const reads=w.source_reads||[],source=reads.length?reads.slice(0,4).map(r=>`${text(r.cube)} · ${text(loc(r.evidence))}：${coordinates(slices(r.coordinate_mapping))}`).join('；')+(reads.length>4?`；另 ${reads.length-4} 处读取见附录`:''):'本表未确认该源切面；数据行及其他来源证据见附录';
          lines.push(`| ${text(loc(w.evidence))} | ${text(operations[w.operation]||w.operation)} | ${excerpt(w.value_expression)} | ${source} | ${coordinates(w.target_slices||[])} | ${reads.length?'静态读取依赖；非运行结果证明':'本表的源切面待核对'} |`);
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
    lines.push('## 技术证据附录','','<details>','<summary>展开完整已核对证据与未确认原因</summary>','','```json',JSON.stringify({schema:'cube-lineage-review-1',snapshot_id:snapshot,query:result.query,limits:result.limits,relations:rows,inspected:records},null,2),'```','','</details>');
    return lines.join('\n');
  }
  window.TM1CubeLineage={slices,writeRows,relations,markdownReport,operationLabel:operation=>operations[operation]||operation};
  const $=id=>document.getElementById(id),root=$('cl-root');if(!root)return;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
  const link=(text,url)=>{const a=el('a',text);a.href=url;return a;};
  let snapshot='',resultName='',generation=0,abort=null,result=null,rows=[],viewer=null,inspected=new Map(),searchTimer;
  async function get(url,opts={}){const r=await fetch(url,{...opts,signal:abort?.signal});if(!r.ok)throw new Error(`本地分析请求失败 (${r.status})`);return r.json();}
  function evidence(parent,title,data){const d=el('details');d.append(el('summary',title));d.ontoggle=()=>{if(d.open&&!d.dataset.loaded){d.dataset.loaded='1';d.append(el('pre',JSON.stringify(data,null,2)));}};parent.append(d);}
  function sliceBox(parent,title,items){const box=el('section');box.append(el('h3',title));if(!items.length)box.append(el('p','未取得可确认的坐标；不按变量名猜测。','muted'));
    items.forEach(c=>{const p=el('p');p.append(el('span',c.kind,'cl-pill'+(c.kind==='待确认'?' cl-unknown':'')),document.createTextNode(` ${c.dimension} = ${c.value}`));box.append(p);if(c.reason)box.append(el('p',c.reason,'muted small'));});parent.append(box);}
  function button(text,fn){const b=el('button',text,'btn');b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){if(e.name!=='AbortError')b.after(el('p',e.message,'err'));}finally{b.disabled=false;}};return b;}
  function writeDetail(host,w){const part=el('article',undefined,'cl-detail');part.append(el('h3',`${operations[w.operation]||w.operation} · ${loc(w.evidence)}`),el('p',`写入值表达式：${w.value_expression}`));
    const coord=el('div',undefined,'cl-slices');
    if(!w.source_reads.length)sliceBox(coord,'源切面：未确认',[]);
    w.source_reads.forEach(r=>sliceBox(coord,`源读取：${r.cube} · ${loc(r.evidence)}`,slices(r.coordinate_mapping)));
    sliceBox(coord,'目标切面',w.target_slices);part.append(coord);
    part.append(el('p',w.source_reads.length?'值表达式包含上述静态读取依赖；条件可达性、运行结果及完整单元格映射仍未验证。':'未建立该源 Cube 与本写入值的表达式依赖；对象共同读写仅为候选关联。','muted'));
    if(w.source_observations.length)part.append(el('p',`另有 ${w.source_observations.length} 处源 Cube 读取观察，不能据此当作本写入的源切面。`,'muted'));
    (w.control_context||[]).forEach(c=>part.append(el('p',`条件：${c.condition||c.kind} · ${loc(c)}（未求值）`)));
    if((w.unresolved_binding_reasons||[]).length)part.append(el('p','数据行来源绑定仍有缺失证据。','muted'));
    evidence(part,'源码定位、变量链与缺失证据',w);host.append(part);
  }
  async function inspectTI(host,row,process,token){
    const data=await get('/api/workbench/writes?'+new URLSearchParams({snapshot_id:snapshot,process}));if(token!==generation)return;
    host.replaceChildren(el('h3',`TI：${process}`));
    host.append(link('查看 TI 源码','/explorer/process/'+encodeURIComponent(process)));
    const writes=writeRows(data,row.source_name,row.target_name);
    if(!writes.length)host.append(el('p','本次源码分析未核对到该目标写入点；保留索引候选关系，不虚构切面。'));
    writes.forEach(w=>writeDetail(host,w));
    const summary=document.querySelector('tr[data-relation="'+CSS.escape(row.id)+'"]')?.children[3];
    if(summary&&writes.length){const first=writes[0];summary.replaceChildren(el('p',process+' · '+loc(first.evidence)),el('p','源：'+(first.source_reads.length?'静态读取依赖（见详情）':'未确认')),el('p','目标：'+first.target_slices.slice(0,3).map(c=>`${c.dimension}=${c.value}（${c.kind}）`).join('；')),el('p',`${operations[first.operation]||first.operation} · 本 TI 共 ${writes.length} 个已核对写入，其他位置展开查看`,'muted small'));}

    if(data.total>data.writes.length||data.read_total>data.reads.length)host.append(el('p','已达到单 TI 80 个写入 / 160 个读取展示预算，结果不完整。','muted'));
    evidence(host,'分析范围与技术限制',data.limitations||[]);
    inspected.set(row.id+'::'+process,{relation:row.id,process,writes,limitations:data.limitations||[],total:data.total,read_total:data.read_total});
  }
  async function inspectRule(host,row,token){
    const data=await get('/api/workbench/rules?'+new URLSearchParams({snapshot_id:snapshot,cube:row.target_name}));if(token!==generation)return;
    host.replaceChildren();
    if(!data.available||data.error){host.append(el('p','未取得 Rule 语义结果，不能据此认定没有规则。'));return;}
    const rules=(data.rules||[]).filter(r=>(r.db_references||[]).some(d=>d.cube_resolved&&d.cube===row.source_name));
    rules.forEach(r=>{const p=el('article',undefined,'cl-detail');p.append(el('h3',`Rule · ${loc(r)}`),el('p',`目标区域：${r.lhs?.raw||'待确认'}`),el('p',`计算表达式：${r.rhs?.expression||'待确认'}`));
      p.append(el('p','声明式计算，不是覆盖 / 累加操作。裸成员的维度归属不按 Cube 顺序猜测。','muted'));
      const coord=el('div',undefined,'cl-slices');
      (r.db_references||[]).filter(d=>d.cube_resolved&&d.cube===row.source_name).forEach(d=>{sliceBox(coord,'DB 源坐标（参数顺序，不冒充维度映射）',(d.coordinates||[]).map((c,i)=>({dimension:`坐标 ${i+1}`,kind:c.kind==='literal'?'固定':c.kind==='region'?'动态':'待确认',value:c.value||c.dimension||c.expression||c.raw||'待确认'})));});
      sliceBox(coord,'目标区域的维度归属',(r.lhs?.coordinates||[]).map(c=>({dimension:c.dimension||'维度待确认',kind:c.dimension?'区域声明':'待确认',value:c.member||c.value||c.raw||JSON.stringify(c.members||[])})));
      p.append(coord);evidence(p,'Rule 原文、条件与未确认项',r);host.append(p);
    });
    inspected.set(row.id,{relation:row.id,rules});
  }
  function render(){
    const panels=$('cl-details');panels.replaceChildren();let active=null;
    const table=el('table'),head=el('tr');['来源 Cube','目标 Cube','处理机制','源 / 目标切面','证据状态','详情'].forEach(x=>head.append(el('th',x)));table.append(head);
    rows.forEach((row,index)=>{const tr=el('tr');tr.dataset.relation=row.id;tr.append(el('td',row.source_name),el('td',row.target_name),el('td',row.label+(row.process_names?.length?` · ${row.process_names.length} 个 TI`:'')),el('td','逐写入点 / Rule 按需核对'),el('td',row.kind==='TI_CANDIDATE'?'共同读写已记录；值流未证明':'源 Cube 引用已确认；完整计算待核对'));
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
  async function load(){const name=$('cl-name').value.trim();if(!name)return;const token=++generation;abort?.abort();abort=new AbortController();viewer?.destroy();viewer=null;result=null;inspected.clear();$('cl-export').disabled=true;$('cl-table').replaceChildren();$('cl-details').replaceChildren();$('cl-summary').replaceChildren();$('cl-diagram-host').replaceChildren();$('cl-status').textContent='正在查询本地索引并核对 Rule 引用…';
    try{const data=await get('/api/workbench/graph',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({objects:[{type:'cube',name}],direction:$('cl-direction').value,view:'cubes',depth:1,node_budget:40,edge_budget:100,relation_types:['TI_CANDIDATE','RULE_REFERENCE']})});if(token!==generation)return;snapshot=data.snapshot_id;result=data;resultName=name;rows=relations(data);render();draw();$('cl-export').disabled=false;
      $('cl-status').textContent=data.limits.missing?.length?'入口 Cube 不在当前本地模型中。':`已完成直接关系查询。${data.limits.truncated?'预算已截断，结果不完整。':''}${data.rule_scope&&!data.rule_scope.complete?'部分 Rule 超出核对预算，结果不完整。':''}`;
      history.replaceState(null,'','/graph?'+new URLSearchParams({cube:name}));
    }catch(e){if(token===generation&&e.name!=='AbortError')$('cl-status').textContent=e.message;}}
  $('cl-search').onsubmit=e=>{e.preventDefault();load();};$('cl-direction').onchange=load;
  $('cl-cancel').onclick=()=>{++generation;abort?.abort();$('cl-status').textContent='已取消本次请求；未保存任何研究或设计资产。';};
  $('cl-name').oninput=()=>{clearTimeout(searchTimer);const q=$('cl-name').value.trim();if(!q){$('cl-options').replaceChildren();return;}searchTimer=setTimeout(async()=>{try{const r=await fetch('/api/workbench/objects?'+new URLSearchParams({q,type:'cube',limit:20}));if(!r.ok)return;const data=await r.json();if($('cl-name').value.trim()===q)$('cl-options').replaceChildren(...data.objects.map(n=>new Option(n.name,n.name)));}catch(_){}},200);};
  $('cl-diagram').ontoggle=draw;
  $('cl-export').onclick=()=>{if(!result)return;const a=el('a');a.href=URL.createObjectURL(new Blob([markdownReport(result,resultName,rows,[...inspected.values()],snapshot)],{type:'text/markdown;charset=utf-8'}));a.download='Cube-Lineage.md';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
  window.addEventListener('pagehide',()=>{++generation;abort?.abort();clearTimeout(searchTimer);viewer?.destroy();});
  if(root.dataset.cube)load();
})();
