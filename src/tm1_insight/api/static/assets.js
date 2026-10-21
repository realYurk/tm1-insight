/* 工程资产工作台：列表、详情、绑定、实例化、生成、打包。 */
(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  const el=(t,x,c)=>{const e=document.createElement(t);if(x!==undefined)e.textContent=x;if(c)e.className=c;return e;};
  const status=(m,err)=>{$('as-status').textContent=m;$('as-status').className=err?'err small':'muted small';};
  let kind='blueprint', items={}, current=null, currentRevision='', summary=null;

  async function api(url,opt={}){
    const r=await fetch(url,opt), data=await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(typeof data.detail==='string'?data.detail:('请求失败 '+r.status));
    return data;
  }
  const jsonOpt=(method,body)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

  async function refresh(){
    summary=await api('/api/assets/summary');
    items=summary.items;
    renderList();
  }

  function renderList(){
    const box=$('as-items');box.replaceChildren();
    const rows=items[kind]||[];
    const q=($('as-search').value||'').toLowerCase();
    const shown=rows.filter(r=>!q||(r.name||'').toLowerCase().includes(q));
    if(!shown.length)box.appendChild(el('p','还没有资产。','muted small'));
    shown.forEach(r=>{
      const b=el('button',undefined,'asset-item'+(current&&current.id===r.id?' active':''));
      b.type='button';
      b.appendChild(el('strong',r.name||r.id));
      const meta=[r.broken?'文件损坏':'', r.status||'', r.version?('v'+r.version):''].filter(Boolean).join(' · ');
      if(meta)b.appendChild(el('span',meta,'muted small'));
      b.onclick=()=>openItem(r.id);
      box.appendChild(b);
    });
    $('as-count').textContent=`共 ${rows.length} 项`+(kind==='blueprint'?'（Blueprint 需要绑定角色后才能生成）':'');
  }

  async function openItem(id){
    try{
      const data=await api(`/api/assets/${kind}/${encodeURIComponent(id)}`);
      current=data.item;currentRevision=data.revision;
      renderList();
      renderDetail();
    }catch(e){status(e.message,true);}
  }

  function renderDetail(){
    const p=$('as-detail');p.replaceChildren();
    if(!current){p.appendChild(el('h2','选择一个资产'));return;}
    p.appendChild(el('h2',current.name));
    if(kind==='blueprint')return renderBlueprint(p);
    if(kind==='pattern')return renderPattern(p);
    if(kind==='verification')return renderVerification(p);
    return renderProject(p);
  }

  function kv(parent,label,value){
    if(value===undefined||value===null||value==='')return;
    const row=el('p');row.appendChild(el('strong',label+'：'));row.appendChild(document.createTextNode(String(value)));parent.appendChild(row);
  }

  function renderPattern(p){
    kv(p,'简介',current.summary);kv(p,'问题',current.problem);
    if(current.inputs.length){p.appendChild(el('h3','输入'));current.inputs.forEach(x=>p.appendChild(el('p','· '+x)));}
    if(current.outputs.length){p.appendChild(el('h3','输出'));current.outputs.forEach(x=>p.appendChild(el('p','· '+x)));}
    if(current.not_applicable.length){p.appendChild(el('h3','不适用'));current.not_applicable.forEach(x=>p.appendChild(el('p','· '+x)));}
    kv(p,'状态',current.status);kv(p,'版本','v'+current.version);
    if(current.template)kv(p,'关联模板',current.template.template+' v'+current.template.version);
  }

  function renderVerification(p){
    kv(p,'版本','r'+current.revision);
    p.appendChild(el('h3','验证要求'));
    (current.requirements||[]).forEach(r=>p.appendChild(el('p',`· ${r.label}（${r.kind} · ${r.severity}）`)));
    if(!current.requirements.length)p.appendChild(el('p','尚未定义要求','muted'));
  }

  function renderProject(p){
    kv(p,'Blueprint',current.blueprint_id+' v'+current.blueprint_version);
    kv(p,'状态',current.status);kv(p,'验证状态',current.verification_status||'未验证');
    kv(p,'生成指纹',current.code_fingerprint);
    p.appendChild(el('h3','角色绑定'));
    (current.bindings||[]).forEach(b=>p.appendChild(el('p',`${b.role} = ${b.value}`)));
    const actions=el('div','','asset-actions');
    const gen=el('button','生成代码草案','btn primary');gen.type='button';
    gen.onclick=async()=>{
      gen.disabled=true;
      try{
        const r=await api('/api/assets/generate',jsonOpt('POST',{project_id:current.id}));
        gen.disabled=false;
        await openItem(current.id);
        showGenerateResult(r);
      }catch(e){gen.disabled=false;status(e.message,true);}
    };
    actions.appendChild(gen);
    if(current.workspace_id){
      const a=el('a','在架构沙盘中打开','btn');
      a.href='/architecture?view=workbench&workspace_id='+encodeURIComponent(current.workspace_id);
      actions.appendChild(a);
    }
    p.appendChild(actions);
    p.appendChild(el('p','生成结果为 TI 草案，未部署、未执行；请在沙盘中复核映射后再使用。','muted small'));
  }

  function showGenerateResult(r){
    const p=$('as-detail');
    const box=el('div','','asset-result');
    box.appendChild(el('h3',r.status==='ok'?'已生成 TI 草案':'生成被阻断'));
    if(r.status!=='ok'){(r.blockers||[]).forEach(b=>box.appendChild(el('p','· '+b)));}
    else{
      kv(box,'维度顺序',r.summary.dimensions);
      kv(box,'写入',r.summary.operation);
      kv(box,'清空策略',r.summary.clear_policy==='none'?'不清空':('清空目标范围：'+(r.summary.clear_scope_text||'未限定')));
      kv(box,'代码指纹',r.summary.code_fingerprint);
      if(r.verification){
        kv(box,'验证级别',r.verification.level+' — '+r.verification.label);
        const v=el('details');v.appendChild(el('summary','这次到底验证了什么'));
        v.appendChild(el('p','已检查：'+(r.verification.checked||[]).join('、')));
        v.appendChild(el('p','未验证：'+(r.verification.not_verified||[]).join('、')));
        box.appendChild(v);
      }
      (r.warnings||[]).forEach(w=>box.appendChild(el('p','⚠ '+w)));
      if(r.process_config&&(r.process_config.data_source_variables||[]).length){
        const d=el('details');d.open=true;
        d.appendChild(el('summary','数据源变量（需在 Process 的 Variables 页签按顺序创建）'));
        r.process_config.data_source_variables.forEach(v=>d.appendChild(el('p',`${v.index}. ${v.name} ← 列 ${v.column}`)));
        box.appendChild(d);
      }
      ['prolog','metadata','data','epilog'].forEach(sec=>{
        const d=el('details');if(sec==='data')d.open=true;
        d.append(el('summary',sec+' 源码'),el('pre',r.code[sec]||'','code'));
        box.appendChild(d);
      });
      if(r.dependencies){
        const d=el('details');d.appendChild(el('summary','依赖清单（目标环境需自备）'));
        (r.dependencies.processes||[]).forEach(x=>d.appendChild(el('p',`Process: ${x.name}（${x.kind}）`)));
        (r.dependencies.cubes||[]).forEach(x=>d.appendChild(el('p',`Cube: ${x.name}（${x.kind}）`)));
        (r.dependencies.notes||[]).forEach(x=>d.appendChild(el('p',x,'muted small')));
        box.appendChild(d);
      }
    }
    p.appendChild(box);
  }

  function renderBlueprint(p){
    kv(p,'简介',current.summary);
    kv(p,'模板',current.template.template+' v'+current.template.version);
    kv(p,'版本','v'+current.version);kv(p,'状态',current.status);
    kv(p,'写入策略',current.write_policy==='overwrite'?'覆盖':'累加');
    kv(p,'清空策略',current.clear_policy==='none'?'不清空':'清空目标范围');
    if(current.restricted)p.appendChild(el('p','该定义含项目信息，导出对外包前需人工改为通用。','muted small'));

    p.appendChild(el('h3','角色绑定（当前项目）'));
    p.appendChild(el('p','每个角色都要绑定到本项目的实际对象；同名不代表同语义，请逐项确认。','muted small'));
    const form=el('div','','asset-bindings');
    const inputs={};
    (current.roles||[]).forEach(role=>{
      const row=el('div','','asset-binding-row');
      row.appendChild(el('strong',role.label));
      row.appendChild(el('span',role.id+' · '+role.kind+(role.required?' · 必需':''),'muted small'));
      const inp=el('input');inp.className='input';inp.value=role.default||'';inp.placeholder=role.hint||'绑定值';
      inp.setAttribute('aria-label',role.id);
      inputs[role.id]=inp;
      const chk=el('input');chk.type='checkbox';chk.checked=false;
      const lab=el('label','已确认');lab.prepend(chk);
      row.append(inp,lab);
      form.appendChild(row);
      inputs[role.id+'_confirmed']=chk;
      if(current.mappings&&current.mappings.length){
        const m=current.mappings.find(x=>x.source_role===role.id||x.dim_role===role.id);
        if(m)row.appendChild(el('span',`→ ${m.dim_role} / ${m.kind}`,'muted small'));
      }
    });
    p.appendChild(form);

    const actions=el('div','','asset-actions');
    const instantiate=el('button','在新项目中使用','btn primary');instantiate.type='button';
    instantiate.onclick=async()=>{
      const bindings=Object.keys(inputs).filter(k=>!k.endsWith('_confirmed')).map(role=>({
        role, value:inputs[role].value.trim(), confirmed:!!inputs[role+'_confirmed'].checked}));
      const name=(prompt('新项目名称', 'New Project')||'').trim();
      if(!name)return;
      instantiate.disabled=true;
      try{
        const r=await api('/api/assets/instantiate',jsonOpt('POST',
          {blueprint_id:current.id,bindings,project_name:name,create_workspace:true}));
        instantiate.disabled=false;
        status('已创建项目并生成设计草稿：'+name);
        await refresh();
        kind='project';syncTabs();await refresh();renderList();
        await openItem(r.project.id);
      }catch(e){instantiate.disabled=false;status(e.message,true);}
    };
    actions.appendChild(instantiate);
    const check=el('button','检查导出风险','btn ghost');check.type='button';
    check.onclick=async()=>{
      try{
        const r=await api('/api/assets/export/preflight',jsonOpt('POST',
          {blueprint_ids:[current.id],pattern_ids:[],verification_ids:[],scope:$('as-scope').value}));
        const box=$('as-detail');box.appendChild(el('h3','导出审查'));
        if(!r.findings.length)box.appendChild(el('p','未发现风险项。'));
        r.findings.forEach(f=>box.appendChild(el('p',`· [${f.severity}] ${f.code}：${f.hint}`)));
      }catch(e){status(e.message,true);}
    };
    actions.appendChild(check);
    p.appendChild(actions);
  }

  function syncTabs(){
    document.querySelectorAll('.asset-filters button').forEach(b=>{
      b.className='btn '+(b.dataset.kind===kind?'primary':'ghost');
      b.setAttribute('aria-selected',String(b.dataset.kind===kind));
    });
  }

  async function createPattern(){
    const lines=id=>(($(id).value||'').split('\n').map(s=>s.trim()).filter(Boolean));
    const body={item:{id:'pat-'+crypto.randomUUID().replace(/-/g,'').slice(0,12),
      name:$('ap-name').value.trim(),summary:$('ap-summary').value.trim(),
      problem:$('ap-problem').value.trim(),inputs:lines('ap-inputs'),outputs:lines('ap-outputs'),
      not_applicable:lines('ap-na'),origin:'USER_INPUT'}};
    if(!body.item.name)return status('Pattern 需要名称',true);
    await api('/api/assets/pattern',jsonOpt('POST',body));
    $('as-pattern-form').hidden=true;
    ['ap-name','ap-summary','ap-problem','ap-inputs','ap-outputs','ap-na'].forEach(id=>$(id).value='');
    kind='pattern';syncTabs();await refresh();
    status('Pattern 已保存');
  }

  function bind(){
    document.querySelectorAll('.asset-filters button').forEach(b=>{
      b.onclick=()=>{kind=b.dataset.kind;current=null;syncTabs();renderList();renderDetail();};
    });
    $('as-search').oninput=renderList;
    $('as-new-pattern').onclick=()=>{$('as-pattern-form').hidden=false;};
    $('ap-cancel').onclick=()=>{$('as-pattern-form').hidden=true;};
    $('ap-save').onclick=()=>createPattern().catch(e=>status(e.message,true));
    $('as-export').onclick=async()=>{
      const scope=$('as-scope').value;
      const ids=k=>items[k].map(x=>x.id);
      if(!ids('blueprint').length&&!ids('pattern').length)return status('还没有可导出的资产',true);
      try{
        const pre=await api('/api/assets/export/preflight',jsonOpt('POST',
          {blueprint_ids:ids('blueprint'),pattern_ids:ids('pattern'),verification_ids:ids('verification'),scope}));
        if(!pre.ok)return status(pre.message,true);
        if((pre.findings||[]).length){
          const lines=(pre.findings||[]).map(f=>`[${f.severity}] ${f.code}：${f.hint}`).slice(0,8).join('\n');
          const go=window.confirm('导出前审查发现 '+pre.findings.length+' 项需要人工确认：\n\n'+lines+
            '\n\n这些内容不会被自动脱敏。确认仍要导出吗？');
          if(!go)return status('已取消导出：请先按审查结果调整资产内容。',true);
        }
        const resp=await fetch('/api/assets/export',jsonOpt('POST',
          {blueprint_ids:ids('blueprint'),pattern_ids:ids('pattern'),verification_ids:ids('verification'),scope}));
        if(!resp.ok){const d=await resp.json().catch(()=>({}));throw new Error(d.detail||'导出失败');}
        const blob=await resp.blob(),url=URL.createObjectURL(blob);
        const a=document.createElement('a');a.href=url;a.download='tm1-insight-assets.zip';a.click();
        setTimeout(()=>URL.revokeObjectURL(url),1500);
        status(`已导出（${scope==='public'?'对外':'私有'}）`);
      }catch(e){status(e.message,true);}
    };
    $('as-import').onchange=async()=>{
      const f=$('as-import').files[0];if(!f)return;
      try{
        const fd=new FormData();fd.append('file',f);
        const r=await api('/api/assets/import',{method:'POST',body:fd});
        const msg=`导入 ${r.imported.length} 项`+(r.errors.length?`，${r.errors.length} 项失败`:'');
        status(msg,r.errors.length>0);
        if(r.errors.length)alert(r.errors.join('\n'));
        await refresh();
      }catch(e){status(e.message,true);}
      finally{$('as-import').value='';}
    };
  }

  document.addEventListener('DOMContentLoaded',()=>{
    bind();syncTabs();
    refresh().catch(e=>status(e.message,true));
  });
})();
