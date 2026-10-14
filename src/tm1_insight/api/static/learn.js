(function () {
  'use strict';
  const el = id => document.getElementById(id);
  const patternNames = {pipeline:'分步骤编排',proportion:'乘除计算线索',configuration:'配置读取线索',mapping:'维度映射',rebuild:'清理后重建',accumulate:'增量累加',validation:'输入校验',temporary:'临时视图',dimension:'维度维护',parallel:'并行启动',output:'结果输出'};
  let task = null, section = 'processes', offset = 0, total = 0, pattern = '', serial = 0, timer;
  function error(message) { el('study-error').textContent = message || ''; el('study-error').hidden = !message; }
  async function request(url, body) {
    const response = await fetch(url, body === undefined ? {cache:'no-store'} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!response.ok) { let value = {}; try { value = await response.json(); } catch (_) {} throw new Error(value.error || '请求失败，请重试'); }
    return response;
  }
  function node(tag, text, parent) { const item = document.createElement(tag); item.textContent = text || ''; if (parent) parent.appendChild(item); return item; }
  function link(parent, text, href) { const item = node('a', text, parent); item.href = href; return item; }
  function process(parent, name) { return link(parent, name, '/explorer/process/' + encodeURIComponent(name)); }
  function list(parent, values) { const ul = node('ul','',parent); values.forEach(value => node('li',value,ul)); }
  function references(parent, label, values, kind) {
    const p = node('p',label + '：',parent);
    if (!values.length) node('span','本范围未观察到',p);
    values.slice(0,10).forEach((value,index) => { if(index) node('span',' · ',p); kind === 'process' ? process(p,value) : link(p,value,'/explorer/cube/' + encodeURIComponent(value)); });
    if (values.length > 10) node('span',`（共 ${values.length} 项，完整清单见教材）`,p);
  }
  function position(parent, events) { node('p',events.slice(0,6).map(e => `${e.section}:${e.line} ${e.operation || ''}`).join(' · '),parent).className='muted small'; }
  function busy(value) { el('study-start').disabled=value; el('study-query').disabled=value; el('study-start').textContent=value?'正在分析…':'分析这块功能'; el('study-cancel').hidden=!value; }
  async function results() {
    const id = ++serial;
    error(''); el('study-results').setAttribute('aria-busy','true');
    try {
      const params = new URLSearchParams({section,offset:String(offset),limit:'20',pattern,q:el('study-filter').value.trim()});
      const report = await (await request(`/api/learning/tasks/${task}/result?${params}`)).json();
      if (id !== serial) return;
      total=report.total; el('study-output').hidden=false;
      const s=report.summary; el('study-summary').textContent=`范围 ${report.query} · ${s.processes} 个 TI · ${s.cubes} 个 Cube · ${s.dimensions} 个维度 · ${s.chapters_with_evidence} 类设计信号 · ${s.review_items} 项待复查`;
      const coverage=report.coverage;el('study-coverage').replaceChildren();node('p',coverage.meaning,el('study-coverage'));node('p',`本范围分析 ${coverage.analyzed_processes} 个 TI；未解释的 Rule/Feeder ${coverage.rules_uninterpreted} 个；仅盘点的维度 ${coverage.dimensions_inventory_only} 个；运行结果验证 0 个。`,el('study-coverage'));const statusNames={resolved:'已绑定目录对象',parameter:'依赖运行参数',unresolved:'动态或未知表达式',missing_object:'常量不在目录',structure_unknown:'控制结构无法确认'};node('p',Object.entries(coverage.object_reference_counts).map(([key,value])=>`${statusNames[key] || key} ${value}`).join(' · '),el('study-coverage'));
      (coverage.source_gaps || []).forEach(text=>node('p',text,el('study-coverage')).className='err');
      el('study-sop').replaceChildren(); report.sop.forEach(value => node('li',value,el('study-sop')));
      el('study-limits').replaceChildren(); report.limitations.forEach(value => node('li',value,el('study-limits')));
      document.querySelectorAll('[data-study]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.study===section)));
      el('study-pattern').textContent=pattern?`正在查看 ${patternNames[pattern] || pattern} 的匹配 TI。清除筛选可返回全部。`:'';
      const container=el('study-results'); container.replaceChildren();
      report.items.forEach(item => {
        const card=node('article','',container); card.className='study-item';
        if (section==='chapters') {
          node('h3',item.title,card); node('p',item.meaning,card); node('p','什么时候适用：'+item.when,card); node('p','代价与边界：'+item.tradeoff,card); list(card,item.checks); node('p','迁移成 Java 时：'+item.java,card);
          node('p',`本范围观察到 ${item.match_count} 个代码信号候选；业务含义仍需复查。`,card);
          item.examples.slice(0,3).forEach(example => { process(card,example.process); position(card,example.evidence); });
          const view=node('button','查看匹配 TI',card); view.className='btn ghost'; view.disabled=!item.match_count;
          view.addEventListener('click',()=>{pattern=item.id;section='processes';offset=0;el('study-filter').value='';results();});
          link(card,' 打开教材模板','/codegen?pattern='+encodeURIComponent(item.id));
        } else if (section==='processes') {
          const title=node('h3','',card); process(title,item.process); node('p',item.explanation,card);
          references(card,'读取来源',item.reads,'cube'); references(card,'写入目标',item.writes,'cube'); if(item.calls.length) references(card,'调用步骤',item.calls,'process'); if(item.called_by.length) references(card,'谁调用它',item.called_by,'process');
          item.formulas.forEach(formula => node('pre',`${formula.section}:${formula.line} ${formula.variable} = ${formula.expression}`,card).className='code study-formula');
          Object.entries(item.patterns).forEach(([kind,events])=>{node('strong',patternNames[kind] || kind,card);position(card,events);});
          const ir=item.understanding;const evidence=node('details','',card);node('summary','查看已解析引用与边界',evidence);node('p',`结构解释：${ir.statements} 条语句 · ${ir.reference_total} 个对象引用。条件未求值，完整记录可下载。`,evidence);
          ir.references.forEach(ref=>node('p',`${ref.section}:${ref.line} ${ref.operation} → ${ref.target || ref.expression || '未知'}（${statusNames[ref.status] || ref.status}）`,evidence).className='muted small');
          const actions=node('div','',card);actions.className='study-actions';
          link(actions,'核对计算定义','/calculation?name='+encodeURIComponent(item.process)+'&source='+encodeURIComponent(report.inspection_source)).className='btn primary';
          const save=node('button','记到我的经验',actions);save.className='btn ghost';save.addEventListener('click',async()=>{save.disabled=true;save.textContent='正在保存…';try{const value=await(await request('/api/experience/cards',{task_id:task,process:item.process})).json();save.textContent='线索已保存';link(actions,'填写业务含义与验证记录','/experience?card='+encodeURIComponent(value.id));}catch(e){error(e.message);save.disabled=false;save.textContent='记到我的经验';}});
          const contract=node('button','下载迁移准备说明',actions);contract.className='btn ghost';contract.addEventListener('click',async()=>{contract.disabled=true;try{const response=await request(`/api/learning/tasks/${task}/contract?process=${encodeURIComponent(item.process)}`);const url=URL.createObjectURL(await response.blob());const a=node('a','');a.href=url;a.download='migration-contract.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){error(e.message);}finally{contract.disabled=false;}});

        } else if (section==='cubes') {
          const title=node('h3','',card); link(title,item.cube,'/explorer/cube/'+encodeURIComponent(item.cube)); node('p','观察位置：'+item.position,card); node('p','维度：'+item.dimensions.join(' → '),card); references(card,'读取它的 TI',item.readers,'process');references(card,'写入它的 TI',item.writers,'process');
        } else if(section==='findings') {
          node('h3',item.title+' · 待验证',card);process(card,item.process);node('p',item.detail,card);position(card,item.evidence);
        } else if(section==='dimensions') {
          node('h3',item.dimension,card);node('p',`目录声明元素 ${item.declared_elements ?? '未知'} 个；仅完成字段盘点。`,card);node('p',item.note,card);
        } else if(section==='rules') {
          link(card,item.cube,'/explorer/cube/'+encodeURIComponent(item.cube));node('p',`规则文本 ${item.characters} 字符。${item.note}`,card);
        } else if(section==='chores') {
          link(card,item.chore,'/explorer/chore/'+encodeURIComponent(item.chore));references(card,'调度成员',item.processes,'process');node('p',item.note,card);
        } else if(section==='coupling') {
          node('h3',item.kind==='call_cycle'?'调用关系形成闭环':'多个 TI 写同一 Cube',card);if(item.cube)link(card,item.cube,'/explorer/cube/'+encodeURIComponent(item.cube));references(card,'相关 TI',item.processes,'process');node('p',item.reason,card);
        } else {
          node('h3',`${item.processes.length} 个 TI 具有相同的去常量词法结构`,card);node('p',item.reason,card);item.processes.slice(0,10).forEach(name=>{process(card,name);node('br','',card);});
        }
      });
      if(!report.items.length) node('p','当前范围没有匹配项。可以清除筛选或换一个功能关键词。',container);
      el('study-page').textContent=total?`${offset+1}–${Math.min(offset+20,total)} / ${total}`:'0 / 0';
      el('study-previous').disabled=offset===0;el('study-next').disabled=offset+20>=total;
    } catch(e) {if(id===serial)error(e.message);} finally {if(id===serial)el('study-results').removeAttribute('aria-busy');}
  }
  async function poll() {
    clearTimeout(timer);
    try {
      const state=await(await request(`/api/learning/tasks/${task}`)).json();
      el('study-task').hidden=false;el('study-status').textContent=`${state.stage_index}/6 ${({Completed:"已完成",Queued:"等待开始",Cancelled:"已取消","Checking local cache":"检查本地缓存","Saving local result":"保存本地结果"})[state.stage] || state.stage} · 已用 ${state.elapsed_seconds.toFixed(1)} 秒${state.cached?' · 复用本地缓存':''}`;
      const progress=el('study-progress'); if(state.total>0){progress.max=state.total;progress.value=state.current;}else progress.removeAttribute('value');
      if(state.status==='completed'){busy(false);el('study-task').hidden=true;results();}
      else if(['failed','cancelled'].includes(state.status)){busy(false);error(state.error||state.message);sessionStorage.removeItem('tm1-study');}
      else timer=setTimeout(poll,500);
    }catch(e){busy(false);error(e.message);sessionStorage.removeItem('tm1-study');}
  }
  el('study-form').addEventListener('submit',async event=>{
    event.preventDefault();error('');busy(true);++serial;el('study-output').hidden=true;el('study-task').hidden=false;el('study-status').textContent='正在提交本地分析…';el('study-progress').removeAttribute('value');
    try{const query=el('study-query').value.trim();const state=await(await request('/api/learning/tasks',{query})).json();task=state.task_id;section='processes';pattern='';offset=0;el('study-filter').value='';sessionStorage.setItem('tm1-study',JSON.stringify({task,query}));poll();}catch(e){busy(false);error(e.message);}
  });
  document.querySelectorAll('[data-study]').forEach(button=>button.addEventListener('click',()=>{section=button.dataset.study;pattern='';offset=0;el('study-filter').value='';results();}));
  el('study-filter-form').addEventListener('submit',event=>{event.preventDefault();offset=0;results();});
  el('study-clear').addEventListener('click',()=>{pattern='';offset=0;el('study-filter').value='';results();});
  el('study-previous').addEventListener('click',()=>{offset=Math.max(0,offset-20);results();});el('study-next').addEventListener('click',()=>{offset+=20;results();});
  el('study-cancel').addEventListener('click',async()=>{try{await request(`/api/learning/tasks/${task}/cancel`,{});poll();}catch(e){error(e.message);}});
  el('study-export').addEventListener('click',async()=>{const button=el('study-export');button.disabled=true;try{const response=await request(`/api/learning/tasks/${task}/export`,{});const url=URL.createObjectURL(await response.blob());const a=node('a','');a.href=url;a.download='TM1_Study.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){error(e.message);}finally{button.disabled=false;}});
  window.addEventListener('pagehide',()=>{clearTimeout(timer);++serial;});
  try{const saved=JSON.parse(sessionStorage.getItem('tm1-study'));if(saved){task=saved.task;el('study-query').value=saved.query;busy(true);poll();}}catch(_){}
})();
