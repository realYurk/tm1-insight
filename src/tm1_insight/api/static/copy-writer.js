(function(){
 'use strict';
 document.addEventListener('click', async e=>{
   const button=e.target.closest('.copy-writer');if(!button)return;
   const name=button.dataset.name||'';
   try {await navigator.clipboard.writeText(name);button.textContent='已复制';}
   catch (_) {button.textContent='复制失败，请选择名称复制';}
   setTimeout(()=>{button.textContent='复制 TI 名称';},1800);
 });
})();
