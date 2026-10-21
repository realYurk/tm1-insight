/* Workspace files are user interpretation, never Snapshot facts. */
(function(){
  'use strict';
  async function request(url, options={}) {
    const response=await fetch(url,options), data=await response.json();
    if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'请求或工作区格式不受支持，请核对对象引用和版本。');
    return data;
  }
  function download(name,value) {
    const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
    a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  window.TM1WorkspaceFiles={request,download,
    async save(workspace,id,revision){return request('/api/workbench/workspaces'+(id?'/'+id:''),{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace,revision:id?revision:''})});},
    async load(id){return request('/api/workbench/workspaces/'+encodeURIComponent(id));},
    async list(){return request('/api/workbench/workspaces');}
  };
})();
