/* Human-facing Inspector over the existing API contracts; no semantic parser. */
(function(){
  'use strict';
  const technicalPanels=new WeakMap();
  function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function mount(host,title,close){
    const head=el('header',undefined,'cx-inspector-head'),heading=el('h2',title),button=el('button','×','cx-tbtn');heading.title=title;
    button.type='button';button.setAttribute('aria-label','关闭详情');button.onclick=close;head.append(heading,button);
    const tabs=el('div',undefined,'cx-inspector-tabs'),body=el('div',undefined,'cx-inspector-main'),technical=el('div',undefined,'cx-inspector-technical');technical.hidden=true;
    [['概览',body],['源码与证据',technical]].forEach(([label,pane])=>{const b=el('button',label,'cx-tbtn');b.type='button';b.setAttribute('role','tab');b.setAttribute('aria-selected',String(pane===body));b.onclick=()=>{body.hidden=pane!==body;technical.hidden=pane!==technical;[...tabs.children].forEach(x=>x.setAttribute('aria-selected',String(x===b)));};tabs.appendChild(b);});
    tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','详情深度');host.replaceChildren(head,tabs,body,technical);technicalPanels.set(body,technical);return body;
  }
  function technical(parent){return technicalPanels.get(parent)||parent;}
  function stat(parent,label,value){const row=el('div',undefined,'cx-summary-row');row.append(el('span',label),el('strong',String(value)));parent.appendChild(row);}
  function list(parent,label,values,max=3){const items=[...new Set(values.filter(Boolean))];stat(parent,label,items.length?items.slice(0,max).join('、')+(items.length>max?` 等 ${items.length} 项`:''):'当前范围未确认');}
  function writes(parent,data){
    parent.querySelector('[data-compact-writes]')?.remove();const box=el('section',undefined,'cx-summary-block');box.dataset.compactWrites='1';
    if(!data||data.error){
      box.appendChild(el('p','未取得写入分析结果（接口错误或对象不存在），不能据此认定「没有写入」。','cx-summary-limit'));
      parent.appendChild(box);return;
    }
    const rows=(data.writes||[]).filter(w=>w.cube&&!w.cube.startsWith('}'));
    if(!rows.length){
      // total=0 与 total>0 但无业务 Cube 写入是两种不同状态，都要显式说明，不用空列表伪装成功。
      box.appendChild(el('p',(data.total>0)
        ?'本次分析的写入点均为系统对象或目标未确认，未将其列为业务写入。'
        :'当前范围未解析到写入点；不能据此认定该 TI 无写入。','cx-summary-limit'));
      parent.appendChild(box);return;
    }
    const labels={CellIncrementN:'累加',CellPutN:'覆盖数值',CellPutS:'覆盖文本'};
    list(box,'写入方式',rows.map(w=>labels[w.operation]||w.operation));list(box,'目标 Cube',rows.map(w=>w.cube));
    const fixed=[],runtime=[];
    rows.forEach(w=>(w.coordinate_mapping?.items||[]).forEach(c=>{const b=c.binding||{};if(b.kind==='FIXED_MEMBER')fixed.push(`${c.dimension||'维度待确认'} = ${b.value}`);else if(['PARAMETER','DATA_ROW_VARIABLE','LOOKUP_COORDINATE'].includes(b.kind))runtime.push(`${c.dimension||'维度待确认'} = ${b.expression||'变量'}`);}));
    list(box,'观察到的固定切面',fixed,4);list(box,'运行时坐标',runtime,2);
    box.appendChild(el('p','切面为各写入点的观察汇总，未证明所有写入使用同一组成员。源切面及逐值映射未在此摘要中确认。','cx-summary-limit'));
    if(rows.some(w=>(w.unresolved_binding_reasons||[]).length))box.appendChild(el('p','部分源值绑定缺少证据，不能由共同读写推导值传输。','cx-summary-limit'));
    stat(box,'已解析目标写入',`${rows.length} / ${data.total} 个位置`);
    (data.limitations||[]).slice(0,2).forEach(lim=>box.appendChild(el('p','限制：'+lim,'cx-summary-limit')));
    parent.appendChild(box);
  }
  function rules(parent,data,scope){
    parent.querySelector('[data-compact-rules]')?.remove();const box=el('section',undefined,'cx-summary-block');box.dataset.compactRules='1';
    if(data.available===false||data.error){box.appendChild(el('p','当前范围未取得可用规则结果，不能据此认定没有规则。','cx-summary-limit'));parent.appendChild(box);return;}
    const all=data.rules||[],rows=scope?all.filter(scope):all;
    stat(box,'相关 Rule',rows.length+' 条');
    list(box,'计算目标区域',rows.map(r=>r.lhs?.raw),3);
    list(box,'已确认引用 Cube',rows.flatMap(r=>(r.db_references||[]).filter(db=>db.cube_resolved).map(db=>db.cube)),3);
    stat(box,'条件分支',rows.some(r=>(r.conditions||[]).length)?'存在条件，实际分支未运行验证':'当前解析范围未观察到 IF');
    box.appendChild(el('p','Rule 为声明式计算引用；区域成员归属、动态坐标和完整公式仍以证据层状态为准。Feeder 不表示数值贡献。','cx-summary-limit'));parent.appendChild(box);
  }
  window.TM1Inspector={mount,technical,stat,list,writes,rules};
})();
