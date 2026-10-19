/* Lazy, single-Process Formation projection through existing cancellable tasks. */
(function(){
  'use strict';const timers=new Set();let gone=false;
  const n=(tag,text,p)=>{const x=document.createElement(tag);x.textContent=text??'';if(p)p.append(x);return x;};
  async function request(url,body){const r=await fetch(url,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error('局部切面尚未就绪，请关闭后重试或进入业务架构。');return r.json();}
  function sleep(){return new Promise(resolve=>{const id=setTimeout(()=>{timers.delete(id);resolve();},350);timers.add(id);});}
  async function load(box){
    if(box.dataset.loading==='1'||box.dataset.loaded==='1')return;box.dataset.loading='1';box.replaceChildren();
    const state=n('p','正在核对当前 TI 的 Formation 写入证据…',box),cancel=n('button','取消切面解析',box);cancel.type='button';cancel.className='btn ghost';let cancelled=false,task;
    cancel.addEventListener('click',async()=>{cancelled=true;if(task)await request('/api/architecture/tasks/'+task+'/cancel',{}).catch(()=>{});});
    try{
      const job=await request('/api/architecture/tasks',{process:box.dataset.lineageProcess,max_processes:1,max_depth:0,max_nodes:100});task=job.task_id;const base='/api/architecture/tasks/'+task;const deadline=Date.now()+90000;
      while(!gone&&!cancelled){
        const s=await request(base);if(!box.isConnected)return;
        state.textContent=s.stage_index+'/'+s.stages_total+' · '+s.stage;
        if(s.status==='failed'||s.status==='cancelled')throw Error('局部分析未完成；没有用索引猜测切面。');
        if(s.status==='completed')break;
        if(Date.now()>deadline)throw Error('解析仍在进行，可进入业务架构查看进度。');await sleep();
      }
      if(gone||!box.isConnected)return;if(cancelled)throw Error('已取消切面解析。');
      const data=await request(base+'/result?view=write_explanations&limit=100');box.replaceChildren();
      if(!data.items.length)n('p','当前 TI 没有源码确认的直接写入切面；可选择子 TI 查看。',box);
      else window.TM1Workbench.writes(box,data.items,{write:(parent,w)=>{const a=n('a','查看 TI 源码',parent);a.href='/explorer/process/'+encodeURIComponent(w.process)+'#'+w.location.section+'-L'+w.location.line;n('p',w.location.section+':'+w.location.line+' · '+w.value_expression,parent);}});
      if(data.total>100)n('p','仅展示前 100 个写入点；完整范围见业务架构。',box);
      const a=n('a','进入业务架构查看完整证据',box);a.href='/architecture?'+new URLSearchParams({kind:'process',name:box.dataset.lineageProcess,analyze:1});box.dataset.loaded='1';
    }catch(e){if(box.isConnected&&!gone){box.replaceChildren();n('p',e.message,box);}}
    finally{box.dataset.loading='0';}
  }
  document.querySelectorAll('[data-lineage-process]').forEach(box=>{if(box.dataset.auto==='1')load(box);else box.closest('details').addEventListener('toggle',e=>{if(e.target.open)load(box);});});
  window.addEventListener('pagehide',()=>{gone=true;timers.forEach(clearTimeout);timers.clear();});
})();
