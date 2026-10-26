/* Human summaries use the same existing Flow/Rule/write contracts as exports. */
(function(){
  'use strict';
  const n=(tag,text,p)=>{const x=document.createElement(tag);x.textContent=text??'';if(p)p.append(x);return x;};
  const button=(p,label,fn)=>{const b=n('button',label,p);b.type='button';b.className='btn ghost';b.addEventListener('click',async()=>{b.disabled=true;try{await fn();}catch(e){n('p',e.message,p);}finally{b.disabled=false;}});return b;};
  function table(parent,headers,label){const wrap=n('div','',parent);wrap.className='table-wrap human-table-wrap';const t=n('table','',wrap);t.className='table human-table';t.setAttribute('aria-label',label);const head=n('tr','',n('thead','',t));headers.forEach(h=>n('th',h,head));return n('tbody','',t);}
  function coordinates(parent,values){values.forEach(c=>{
    const fixed=c.fixed||c.kind==='FIXED_MEMBER',expr=String(c.expression??''),variable=/^[A-Za-z_]\w*$/.test(expr);
    const value=c.value??(fixed?expr:variable?'变量 · '+expr:'待确认');
    const p=n('span',c.dimension+' = '+value,parent);p.className='human-slice '+(fixed?'slice-fixed':variable||String(value).startsWith('变量')?'slice-variable':'slice-unconfirmed');
  });}

  function paged(parent,items,render,size=20){const body=n('div','',parent),controls=n('div','',parent);controls.className='workflow-pager';let page=0;const prev=button(controls,'上一页',()=>{page--;draw();}),label=n('span','',controls),next=button(controls,'下一页',()=>{page++;draw();});function draw(){body.replaceChildren();render(body,items.slice(page*size,(page+1)*size));controls.hidden=items.length<=size;label.textContent=`${page*size+1}–${Math.min((page+1)*size,items.length)} / ${items.length}`;prev.disabled=page===0;next.disabled=(page+1)*size>=items.length;}draw();}
  function flowTables(parent,flow,api){
    n('h2','B · 对象与作用',parent);
    paged(parent,flow.nodes,(p,items)=>{const body=table(p,['对象','角色','维度数','作用摘要','详情'],'对象与作用');items.forEach(item=>{const row=n('tr','',body);n('td',item.title,row);n('td',item.role,row);n('td',item.dimension_count??'—',row);n('td',item.summary,row);button(n('td','',row),'查看对象',()=>api.selectNode(item));});});
    n('h2','C · 动作与关键切面',parent);const nodes=new Map(flow.nodes.map(x=>[x.id,x]));
    paged(parent,flow.edges,(p,items)=>{const body=table(p,['来源 / 发起对象','动作','目标对象','关键切面摘录','详情'],'动作与关键切面');items.forEach(e=>{const row=n('tr','',body);n('td',nodes.get(e.source).title,row);n('td',e.label,row);n('td',nodes.get(e.target).title,row);const cell=n('td','',row);if(e.slices.length){coordinates(cell,e.slices[0].coordinates);n('small',e.slices.length+' 组切面，详情可展开各写入点',cell);}else n('span','—',cell);button(n('td','',row),'查看动作',()=>api.selectEdge(e));});});
  }
  async function ruleTable(parent,api,offset=0,q=''){
    const data=await api.request(api.url('rule-table',{offset,limit:25,q}));if(!api.current())return;
    n('h2','Rule 计算与切面摘要',parent);n('p','Rule 是声明式计算；以下每行对应一条原始 Rule，计算引用与 TI 写入分开阅读。',parent).className='flow-note';
    const body=table(parent,['所属 Cube / 行号','计算目标区域','来源 Cube / DB 引用','IF','字面固定区域','计算摘要','源码与详情'],'Rule 计算与切面摘要');
    data.items.forEach(r=>{const row=n('tr','',body);n('td',r.cube+' · L'+r.line+(r.line_end!==r.line?'–'+r.line_end:''),row);n('td',r.target_area||'区域待确认',row);n('td',r.sources.join('、')||'无已确认的跨 Cube 引用',row);n('td',r.has_if?'有':'—',row);coordinates(n('td','',row),r.fixed_slices.map(c=>({...c,fixed:true,value:Array.isArray(c.value)?c.value.join('、'):c.value})));const expr=n('td','',row);n('code',r.expression.slice(0,180)+(r.expression.length>180?'…':''),expr);const cell=n('td','',row);
      const details=n('details','',cell);n('summary','查看源码 / 计算上下文',details);let loaded=false;details.addEventListener('toggle',async()=>{if(!details.open||loaded)return;loaded=true;try{const c=await api.request(api.url('relation-context',{ref:r.context_ref}));if(!details.isConnected)return;const pre=n('pre',c.raw,details);pre.className='code';window.tm1Source.mount(pre,{mode:'rules',start:c.line_start});const expert=n('details','',details);n('summary','表达式 IR、证据与未确认项',expert);n('pre',JSON.stringify(c,null,2),expert).className='code technical-json';}catch(e){loaded=false;n('p',e.message,details);}});
    });
    if(!data.items.length)n('p','当前范围没有已保存的 Rule 语句。',parent);
    const pager=n('div','',parent);pager.className='workflow-pager';button(pager,'上一页',()=>api.rules(Math.max(0,offset-25))).disabled=offset===0;n('span',`${data.total?offset+1:0}–${Math.min(offset+25,data.total)} / ${data.total}`,pager);button(pager,'下一页',()=>api.rules(offset+25)).disabled=offset+25>=data.total;
  }
  function processing(parent,items,api){
    n('p','只列已确认的访问与写入方式；同一 TI 的输入输出不等于已证明的值传输。',parent).className='flow-note';
    const body=table(parent,['主要输入','加工程序','目标','写入方式','固定切面','变量 / 待确认切面','详情'],'加工链路摘要');
    items.forEach(s=>{const tr=n('tr','',body);n('td',(s.primary_inputs||[]).join('、')||'来源待确认',tr);n('td',s.process,tr);n('td',s.outputs.join('、')||'当前无目标写入',tr);n('td',Object.entries(s.modes).map(([k,v])=>(k==='INCREMENT'?'累加':'覆盖')+' '+v+' 处').join('、')||'调用 / 读取',tr);coordinates(n('td','',tr),s.common_target_coordinates.filter(c=>c.kind==='FIXED_MEMBER'));coordinates(n('td','',tr),s.common_target_coordinates.filter(c=>c.kind!=='FIXED_MEMBER'));
      const cell=n('td','',tr),d=n('details','',cell);n('summary','源码与处理详情',d);button(d,'查看 TI 源码',()=>api.code(d,s.process,'data',1));n('p',(s.helper_calls||0)+' 个技术调用已折叠；'+(s.row_binding_gaps.length?'Data 行值来源仍需元数据。':'具体值依赖以原计算证据为准。'),d);const raw=n('details','',d);n('summary','技术参数与未确认项',raw);n('pre',JSON.stringify(s,null,2),raw).className='code technical-json';});
  }
  function writes(parent,items,api){
    n('p','源列表示 VIEW 绑定或写入表达式内的读取事实，不表示 vValue 的来源已确认。',parent).className='flow-note';
    const body=table(parent,['来源观察','加工程序','目标','方式 / 位置','固定切面','变量 / 待确认切面','详情'],'数据形成摘要');
    items.filter(w=>w.cube).forEach(w=>{const tr=n('tr','',body);n('td',w.source_view_binding?.cube||[...new Set(w.source_reads.map(r=>r.cube).filter(Boolean))].join('、')||'待确认',tr);n('td',w.process,tr);n('td',w.cube,tr);n('td',(w.mode==='INCREMENT'?'累加':'覆盖')+' · '+w.location.section+':'+w.location.line,tr);const coords=w.target_coordinates.filter(c=>c.dimension);coordinates(n('td','',tr),coords.filter(c=>c.kind==='FIXED_MEMBER').slice(0,6));coordinates(n('td','',tr),coords.filter(c=>c.kind!=='FIXED_MEMBER').slice(0,4));const d=n('details','',n('td','',tr));n('summary','写入与值来源证据',d);let loaded=false;d.addEventListener('toggle',()=>{if(d.open&&!loaded){loaded=true;api.write(d,w);}});});
  }
  window.TM1Workbench={flowTables,ruleTable,processing,writes};
})();
