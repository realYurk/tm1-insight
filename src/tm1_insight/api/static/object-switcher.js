(function(){
 'use strict';
 const dialog=document.getElementById('object-switcher');if(!dialog)return;
 const $=id=>document.getElementById(id),input=$('object-switcher-query'),list=$('object-switcher-results'),status=$('object-switcher-status'),kind=dialog.dataset.kind,model=dialog.dataset.model;
 const key=`tm1-object-switcher:${model}:${kind}`,limit=25;let seq=0,controller,timer,offset=0,opener;
 function stop(){++seq;clearTimeout(timer);controller?.abort();}
 async function search(start=0){stop();const token=seq;controller=new AbortController();status.textContent='正在搜索…';list.replaceChildren();try{
  const r=await fetch('/api/workbench/objects?'+new URLSearchParams({type:kind,q:input.value.trim(),limit,offset:start,include_technical:'true'}),{signal:controller.signal,cache:'no-store'});if(!r.ok)throw Error('搜索失败，请重试');const d=await r.json();if(token!==seq||!dialog.open)return;if(model&&model!==d.snapshot_id)throw Error('本地模型已变化，请刷新页面后重新搜索');offset=d.offset;
  d.objects.forEach(item=>{const li=document.createElement('li'),a=document.createElement('a');li.className='process-search-item';a.textContent=item.name;const params=new URLSearchParams();if(kind==='cube'){if(model)params.set('model',model);a.href='/explorer/cube/'+encodeURIComponent(item.name)+(params.size?'?'+params:'');}else{params.set('name',item.name);if(dialog.dataset.source)params.set('source',dialog.dataset.source);a.href='/dimensions?'+params;}a.addEventListener('click',()=>{try{sessionStorage.setItem(key,input.value.trim());}catch(_){}});li.append(a);list.append(li);});
  status.textContent=d.total?`共 ${d.total} 项 · ${offset+1}–${offset+d.objects.length}`:'没有匹配对象，请尝试其他关键词';$('object-switcher-prev').disabled=offset===0;$('object-switcher-next').disabled=offset+d.objects.length>=d.total;$('object-switcher-list').href=(kind==='cube'?'/cubes?':'/dimensions?')+new URLSearchParams({q:input.value.trim()});
 }catch(e){if(token===seq&&e.name!=='AbortError')status.textContent=e.message;}}
 document.querySelectorAll('[data-open-object-switcher]').forEach(b=>b.addEventListener('click',()=>{opener=b;try{input.value=sessionStorage.getItem(key)||'';}catch(_){}dialog.showModal();input.focus();input.select();search();}));
 $('object-switcher-close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{stop();opener?.focus();});$('object-switcher-form').onsubmit=e=>{e.preventDefault();search();};input.addEventListener('input',()=>{stop();timer=setTimeout(()=>search(),250);});$('object-switcher-prev').onclick=()=>search(Math.max(0,offset-limit));$('object-switcher-next').onclick=()=>search(offset+limit);
})();
