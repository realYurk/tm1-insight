(function(){
 'use strict';
 window.TM1RuleSlice={render:function(options){
  const card=document.createElement('article');card.className='rule-slice-card';
  const label=document.createElement('span');label.className='rule-slice-label';label.textContent='Rule · 目标切面';card.append(label);
  if(options.target){const target=document.createElement('p');target.className='rule-slice-target';target.textContent=options.target;card.append(target);}
  if(options.href){const a=document.createElement('a');a.textContent='查看 Cube Rule 源码';a.href=options.href;card.append(a);}
  return card;
 }};
})();
