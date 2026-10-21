/* Optional context bridge into the existing, unchanged template workflow. */
(async function(){
  'use strict';
  const params=new URLSearchParams(location.search),id=params.get('workspace_id');if(!id)return;
  const status=document.getElementById('cg-action-status');
  try{
    const response=await fetch('/api/workbench/workspaces/'+encodeURIComponent(id)),data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'无法读取工作区');
    const w=data.workspace,src=params.get('source'),tgt=params.get('target');
    if(w.snapshot_id!==params.get('snapshot_id'))throw new Error('工作区模型不匹配，未自动填入对象。');
    if(![src,tgt].every(n=>w.objects.some(o=>o.type==='cube'&&o.name===n)))throw new Error('来源或目标不在工作区事实对象中；草稿不作为真实 Cube。');
    document.querySelector('[data-tab="transfer"]').click();
    document.getElementById('tr-src').value=src;document.getElementById('tr-tgt').value=tgt;
    ['tr-src','tr-tgt'].forEach(id=>document.getElementById(id).dispatchEvent(new Event('input',{bubbles:true})));
    status.textContent='已从工作区带入来源和目标。请核对方向，点击“加载维度结构”后继续使用原有模板。';
    const link=document.createElement('a');link.className='btn';link.textContent='返回原工作区';link.href='/architecture?view=workbench&workspace_id='+encodeURIComponent(id);status.after(link);
  }catch(e){status.textContent=e.message;}
})();
