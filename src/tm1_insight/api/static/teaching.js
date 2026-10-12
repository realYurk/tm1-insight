(function () {
  const el=id=>document.getElementById(id); if(!el('teaching-pattern'))return;
  let text=''; const status=el('teaching-status'), select=el('teaching-pattern');
  async function json(url){const response=await fetch(url);if(!response.ok)throw new Error('模板读取失败');return response.json();}
  json('/api/learning/templates').then(cards=>{
    cards.forEach(card=>{const option=document.createElement('option');option.value=card.id;option.textContent=card.title;select.appendChild(option);});
    const requested=new URLSearchParams(location.search).get('pattern');if(cards.some(card=>card.id===requested))select.value=requested;
  }).catch(e=>{status.textContent=e.message;el('teaching-generate').disabled=true;});
  el('teaching-generate').addEventListener('click',async()=>{
    const button=el('teaching-generate');button.disabled=true;status.textContent='正在准备教材骨架…';
    try{const result=await json('/api/learning/templates/'+encodeURIComponent(select.value));text=['prolog','metadata','data','epilog'].map(part=>`# === ${part.toUpperCase()} ===\n${result[part]}`).join('\n\n');el('teaching-code').textContent=text;el('teaching-instructions').textContent=result.instructions;el('teaching-checks').replaceChildren();result.checks.forEach(check=>{const li=document.createElement('li');li.textContent=check;el('teaching-checks').appendChild(li);});el('teaching-output').hidden=false;status.textContent='骨架已生成，默认停用；请按检查清单配置与验证。';}catch(e){status.textContent=e.message;}finally{button.disabled=false;}
  });
  el('teaching-copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(text);status.textContent='已复制教材骨架';}catch(_){status.textContent='浏览器不允许复制，请下载文本或手动选择代码。';}});
  el('teaching-download').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='TM1_Teaching_'+select.value+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
})();
