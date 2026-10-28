(function(){
  'use strict';
  window.TM1ObjectBadge=function(kind){
    const badge=document.createElement('span');
    const cube=kind==='cube', chore=kind==='chore';
    badge.className='sr-badge '+(cube?'cube':chore?'chore':'ti');
    badge.textContent=cube?'C':chore?'H':'T';
    badge.setAttribute('aria-label',cube?'Cube':chore?'Chore':'TI');
    return badge;
  };
})();
