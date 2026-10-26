/* Switch existing read-only routes; never carry a Cube name into a TI query. */
(function(){
 'use strict';
 document.querySelectorAll('.lineage-mode').forEach(select=>select.addEventListener('change',()=>{
  const model=document.getElementById('cl-root')?.dataset.model||document.getElementById('tr-root')?.dataset.model||'';
  const params=new URLSearchParams();if(select.value==='ti')params.set('ti','');if(model)params.set('model',model);
  window.location.assign('/graph'+(params.size?'?'+params:''));
 }));
})();
