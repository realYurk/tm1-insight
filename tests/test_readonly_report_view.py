"""Shared reader behavior: report scroll, bounded viewport and lifecycle."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_datasource_api import client  # noqa: F401


def test_shared_viewport_css_and_readonly_navigation(client):
    for route in ['/graph?cube=Cube_A','/graph?ti=Load','/architecture']:
        page=client.get(route)
        assert page.status_code==200 and '/static/mermaid-viewer.css' in page.text
        assert 'href="/architecture"' in page.text
    assert client.get('/architecture?view=workbench').status_code==200


def test_wheel_fit_resize_manual_zoom_and_disposal():
    node=shutil.which('node')
    if not node:pytest.skip('Node needed for shared viewer behavior checks')
    source=Path('src/tm1_insight/api/static/mermaid-viewer.js').read_text(encoding='utf-8')
    harness=r'''
const vm=require('vm');
let width=400,observers=[],windowListeners=[];
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.style={};this.events={};this.classList={toggle(){}};this.textContent='';this.viewBox={baseVal:{width:8000,height:100}};}
  appendChild(n){this.children.push(n);return n;}
  insertBefore(n,b){this.children.splice(this.children.indexOf(b),0,n);}
  replaceChildren(...nodes){this.children=nodes;}
  set innerHTML(v){this.children=[new Element('svg')];}
  setAttribute(){} addEventListener(k,f){this.events[k]=f;}
  removeEventListener(k){delete this.events[k];}
  querySelector(k){for(const n of this.children){if(n.tag===k)return n;const found=n.querySelector(k);if(found)return found;}return null;}
  querySelectorAll(){return [];}
  getBoundingClientRect(){return {width,height:300};}
}
class Observer {constructor(fn){this.fn=fn;observers.push(this);}observe(){}disconnect(){this.disconnected=true;}}
const host=new Element('host');
const window={mermaid:{render:async()=>({svg:'<svg></svg>'})},addEventListener:(k,f)=>windowListeners.push([k,f]),removeEventListener:(k,f)=>{windowListeners=windowListeners.filter(x=>x[0]!==k||x[1]!==f);}};
const context={window,document:{createElement:tag=>new Element(tag),getElementById:()=>null},ResizeObserver:Observer,requestAnimationFrame:f=>f(),setTimeout,URL,Blob,console};
vm.runInNewContext(SOURCE,context);
const inst=window.TM1Mermaid.mount(host,{code:'flowchart LR\n a-->b'});
(async()=>{
  await new Promise(r=>setImmediate(r));
  const wrapper=host.children[0],bar=wrapper.children[0],viewport=wrapper.children[1];
  const button=text=>bar.children.find(n=>n.textContent===text);
  const fitted=inst.getView().zoom;
  if(!(fitted<.15))throw Error('Fit cropped a very wide diagram');
  let prevented=0;
  viewport.events.wheel({ctrlKey:false,metaKey:false,deltaY:100,preventDefault(){prevented++;}});
  if(prevented)throw Error('Ordinary report scroll was intercepted');
  viewport.events.wheel({ctrlKey:true,metaKey:false,deltaY:-100,preventDefault(){prevented++;}});
  if(prevented!==1)throw Error('Explicit zoom did not intercept wheel');
  button('1:1').events.click();width=800;observers[0].fn();
  if(inst.getView().zoom!==1)throw Error('Resize overwrote manual zoom');
  button('适应画布').events.click();const before=inst.getView().zoom;width=1000;observers[0].fn();
  if(!(inst.getView().zoom>before))throw Error('Fitted view failed to resize');
  width=0;const hidden=inst.getView().zoom;observers[0].fn();
  if(inst.getView().zoom!==hidden)throw Error('Collapsed diagram corrupted fit');
  inst.destroy();if(!observers[0].disconnected||host.children.length||windowListeners.some(x=>['mousemove','mouseup'].includes(x[0])))throw Error('Viewer leaked listeners or observer');
  console.log(JSON.stringify({ordinaryScroll:true,explicitZoom:true,fit:fitted,resize:true,dispose:true}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    harness=harness.replace('SOURCE',json.dumps(source))
    completed=subprocess.run([node,'-e',harness],capture_output=True,text=True,encoding='utf-8',check=True)
    result=json.loads(completed.stdout)
    assert result['ordinaryScroll'] and result['resize'] and result['dispose']
