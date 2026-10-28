/* Shared read-only object picker; reuses object catalog + existing input/sr-item styles. */
(function(){
 'use strict';
 const form=document.querySelector('[data-lineage-search]');if(!form)return;
 const input=form.querySelector('input[role=combobox]'),list=document.getElementById('lineage-search-results'),status=document.getElementById('lineage-search-status');
 let sequence=0,timer,controller,active=-1,items=[],snapshot=form.dataset.model||'';
 const historyKey=()=>`tm1-lineage-search:${snapshot}:${form.dataset.lineageSearch}`;
 function history(){try{return snapshot?JSON.parse(sessionStorage.getItem(historyKey())||'[]'):[];}catch(_){return [];}}
 function hide(){list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;}
 function select(name){input.value=name;hide();form.requestSubmit();}
 function draw(names){items=names;active=-1;list.replaceChildren();names.forEach((name,i)=>{const row=document.createElement('div');row.className='sr-item';row.id='lineage-option-'+i;row.setAttribute('role','option');row.setAttribute('aria-selected','false');row.title=name;row.append(window.TM1ObjectBadge(form.dataset.lineageSearch),document.createTextNode(name));row.addEventListener('mousedown',e=>e.preventDefault());row.addEventListener('click',()=>select(name));list.append(row);});list.hidden=!names.length;input.setAttribute('aria-expanded',String(!!names.length));input.removeAttribute('aria-activedescendant');}
 async function search(){controller?.abort();controller=new AbortController();const token=++sequence,q=input.value.trim();status.textContent='正在搜索本地对象…';try{
  const r=await fetch('/api/workbench/objects?'+new URLSearchParams({q,type:form.dataset.lineageSearch,limit:20}),{signal:controller.signal,cache:'no-store'});if(!r.ok)throw new Error('本地对象搜索暂不可用');const d=await r.json();if(token!==sequence)return;
  if(snapshot&&snapshot!==d.snapshot_id)throw new Error('本地模型已变化，请刷新页面；未使用其他模型的历史记录');snapshot=d.snapshot_id;
  const names=q?d.objects.map(o=>o.name):history();draw(names);status.textContent=q?(names.length?`匹配 ${names.length} 项${d.total>names.length?'，输入更多名称可缩小范围':''}；上下键选择，回车分析`:'没有匹配对象，请修改关键词'):(names.length?'最近搜索；不会自动选择首项':'输入名称或关键词开始搜索');
 }catch(e){if(token===sequence&&e.name!=='AbortError'){hide();status.textContent=e.message;}}}
 input.addEventListener('input',()=>{clearTimeout(timer);++sequence;controller?.abort();hide();timer=setTimeout(search,180);});
 input.addEventListener('focus',()=>{if(!list.hidden)return;search();});
 input.addEventListener('keydown',e=>{if(e.key==='Escape'){hide();return;}if(['ArrowDown','ArrowUp'].includes(e.key)&&items.length&&!list.hidden){e.preventDefault();active=e.key==='ArrowDown'?(active+1)%items.length:(active<=0?items.length-1:active-1);Array.from(list.children).forEach((n,i)=>n.setAttribute('aria-selected',String(i===active)));input.setAttribute('aria-activedescendant','lineage-option-'+active);list.children[active].scrollIntoView({block:'nearest'});}else if(e.key==='Enter'&&active>=0&&!list.hidden){e.preventDefault();select(items[active]);}});
 form.addEventListener('submit',()=>{clearTimeout(timer);++sequence;controller?.abort();hide();if(snapshot&&input.value.trim())try{sessionStorage.setItem(historyKey(),JSON.stringify([input.value.trim(),...history().filter(x=>x!==input.value.trim())].slice(0,8)));}catch(_){};});
 document.getElementById('lineage-clear').addEventListener('click',()=>{input.value='';hide();input.focus();search();});
 const outside=e=>{if(!form.contains(e.target))hide();};document.addEventListener('click',outside);
 window.addEventListener('pagehide',()=>{++sequence;clearTimeout(timer);controller?.abort();document.removeEventListener('click',outside);});
})();
