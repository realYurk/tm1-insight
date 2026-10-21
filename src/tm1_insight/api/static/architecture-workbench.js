/* Continuous exploration presenter. No parsing, semantic promotion or server calls. */
(function(){
  'use strict';
  const $=id=>document.getElementById(id), root=$('ew-root'); if(!root)return;
  const files=window.TM1WorkspaceFiles, req=files.request;
  let snapshot='',graph={nodes:[],edges:[]}, selected=new Set(), groups=[], drafts=[], hidden=new Set();
  // 设计模式状态：所有对象都是本地草稿，不参与服务端血缘计算。
  let design={mode:'explore',cubes:[],dimensions:[],schemas:[],relations:[],blueprints:[]};
  let designMeta={dimensions:[],cubes:[],templates:[],template_version:'1'}, schemaDraftFields=[];
  const lastGenerated=new Map();
  let workspaceId='',revision='',viewer=null,query={},layout={},edgeSelection=null,displayEdges=[],nodeMap={},templateRef='';
  let abort=null,generation=0,detailGeneration=0,dirty=false;
  const known=new Map(), name=id=>known.get(id)?.name||drafts.find(d=>d.id===id)?.name
    ||design.cubes.find(c=>c.id===id)?.name||design.schemas.find(s=>s.id===id)?.name
    ||design.relations.find(r=>r.id===id)?.id||id;
  const status=(message,error=false)=>{$('ew-status').textContent=message;$('ew-status').className=error?'err':'muted';};
  const element=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const button=(text,fn)=>{const b=element('button',text,'btn ghost');b.type='button';b.onclick=()=>run(async()=>{b.disabled=true;try{await fn();}finally{b.disabled=false;}});return b;};
  async function run(fn){try{await fn();}catch(e){if(e.name!=='AbortError')status(e.message,true);}}
  function changed(){dirty=true;remember();}
  function currentWorkspace(){
    return {schema_version:'architecture-workspace-2',snapshot_id:snapshot,design:design,name:$('ew-name').value.trim()||'我的架构研究',query:{...query,snapshot_id:snapshot},
      objects:[...known.values()].map(n=>({type:n.type,name:n.name})), selected:[...selected],visible:graph.nodes.map(n=>n.id),edge_ids:graph.edges.map(e=>e.id),hidden:[...hidden],groups,drafts,
      mdx:$('ew-mdx').value,notes:$('ew-notes').value,layout:viewer?.getView()||layout,template_ref:templateRef};
  }
  function remember(){if(snapshot)window.WorkbenchContext?.set('engineering-workspace',{id:workspaceId,revision,workspace:currentWorkspace()});}
  function options(){return {snapshot_id:snapshot,objects:[],source_prefix:'',target_prefix:'',direction:$('ew-direction').value,depth:Number($('ew-depth').value),node_budget:Number($('ew-budget').value),edge_budget:160,view:$('ew-view').value,include_technical:$('ew-technical').checked,relation_types:[]};}
  function restoreOptions(q){for(const [id,key] of [['ew-direction','direction'],['ew-depth','depth'],['ew-budget','node_budget'],['ew-view','view'],['ew-from','source_prefix'],['ew-to','target_prefix']])if(q[key]!==undefined)$(id).value=q[key];$('ew-technical').checked=!!q.include_technical;$('ew-table-kind').value=q.relation_types?.length===1?q.relation_types[0]:'';}
  async function search(){
    const token=$('ew-search').value,kind=$('ew-kind').value;
    const data=await req('/api/workbench/objects?'+new URLSearchParams({q:token,type:kind}));
    if(token!==$('ew-search').value||kind!==$('ew-kind').value)return;
    if(snapshot&&snapshot!==data.snapshot_id)throw new Error('模型已变化，当前画布保留。请刷新并新建工作区。');
    snapshot=data.snapshot_id;$('ew-resources').replaceChildren();
    data.objects.forEach(n=>{
      const b=button(n.name,async()=>{await explore([{type:n.type,name:n.name}],false);select(n.id,false);});
      $('ew-resources').appendChild(b);
    });
    $('ew-resources').appendChild(element('p',`显示前 ${data.objects.length} / ${data.total} 个对象`,'muted small'));
  }
  async function explore(objects,merge=true,pathQuery=false,seedOffset=0){
    const token=++generation;abort?.abort();abort=new AbortController();status('正在查询本地关系索引…');
    let q={...options(),objects};if(pathQuery){q.source_prefix=$('ew-from').value.trim();q.target_prefix=$('ew-to').value.trim();q.seed_offset=seedOffset;q.objects=[];}
    if(objects.some(o=>o.type!=='cube'))q.view='objects';
    const response=await req('/api/workbench/graph',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(q),signal:abort.signal});
    if(token!==generation)return;
    snapshot=response.snapshot_id;query=response.query;restoreOptions(query);
    const future=new Map(known);response.nodes.forEach(n=>future.set(n.id,n));
    if(future.size>120)throw new Error('保存的研究对象将超过 120 个，请另建工作区。原图保留。');
    if(merge){
      const nodes=new Map(graph.nodes.map(n=>[n.id,n])),edges=new Map(graph.edges.map(e=>[e.id,e]));
      response.nodes.forEach(n=>nodes.set(n.id,n));response.edges.forEach(e=>edges.set(e.id,e));
      if(nodes.size>120||edges.size>300)throw new Error('局部展开会超过 120 节点 / 300 关系预算，请先隐藏、清空或缩小查询范围。原图保留。');
      graph={...response,nodes:[...nodes.values()],edges:[...edges.values()]};
    }else{graph=response;selected.clear();hidden.clear();}
    response.nodes.forEach(n=>known.set(n.id,n));
    $('ew-path-next').hidden=!pathQuery||response.limits.next_seed_offset===null||response.limits.next_seed_offset===undefined;
    // 新查询或局部展开都改变了对象集合：沿用旧视口会把新节点留在可视区外，
    // 因此这里重新适应画布；只有「恢复工作区」才使用保存的视口。
    render(false);changed();status(response.nodes.length?`已完成局部查询：${response.nodes.length} 个对象、${response.edges.length} 条关系。${response.limits.truncated?'结果因预算被截断，不能解释为完整模型。':response.limits.boundary?'这是局部视图，边界外仍有对象；可继续展开。':''}${response.rule_scope&&!response.rule_scope.complete?` 部分 Rule 未在本次预算内核对（${response.rule_scope.owners_analyzed}/${response.rule_scope.owners_considered}）。`:''}`:'没有找到入口或路径；没有生成替代关系。');
  }
  function mermaidLabel(value){return String(value).replace(/[&<>"\[\]{}|`\\]/g,c=>'&#'+c.charCodeAt(0)+';').replace(/[\r\n]/g,' ');}
  function nodeLabel(value){const words=String(value).split(' '),lines=[''];words.forEach(word=>{if((lines[lines.length-1]+' '+word).length>24&&lines[lines.length-1])lines.push(word);else lines[lines.length-1]+=(lines[lines.length-1]?' ':'')+word;});return lines.map(mermaidLabel).join('<br/>');}
  function render(preserve=true){
    if(viewer){if(preserve)layout=viewer.getView();viewer.destroy();viewer=null;}
    const designNodes=[...design.cubes.map(c=>({id:c.id,name:c.name,type:'draft',provenance:'DESIGN_DRAFT'})),
                       ...design.schemas.map(s=>({id:s.id,name:s.name,type:'source',provenance:'DESIGN_DRAFT'}))];
    const folded=groups.filter(g=>g.folded), representative=new Map(),
      visible=[...graph.nodes,...drafts.map(d=>({...d,type:'draft'})),...designNodes].filter(n=>!hidden.has(n.id));
    visible.forEach(n=>representative.set(n.id,folded.find(g=>g.members.includes(n.id))?.id||n.id));
    const shown=new Map();visible.forEach(n=>{const id=representative.get(n.id);shown.set(id,id===n.id?n:{id,name:groups.find(g=>g.id===id).name,type:'group'});});
    nodeMap={};let code='flowchart LR\n'; const mapping=new Map();
    [...shown.values()].sort((a,b)=>a.id.localeCompare(b.id)).forEach((n,i)=>{
      const mid='n'+i;mapping.set(n.id,mid);nodeMap[mid]=n.id;
      code+=`  ${mid}["${nodeLabel(n.name)}<br/>${{cube:'Cube',process:'TI',chore:'调度',dimension:'维度',draft:'Cube 草稿 · 未部署',source:'CSV Schema · 未接入',group:'人工模块'}[n.type]||n.type}"]\n`;
      if(n.type==='cube')code+=`  style ${mid} fill:#eef6ff,stroke:#7aa4d7\n`;
      if(n.type==='draft')code+=`  style ${mid} fill:#fff8e6,stroke:#ba8c36,stroke-dasharray:5 5\n`;
      if(n.type==='source')code+=`  style ${mid} fill:#f3f0ff,stroke:#8b7bd8,stroke-dasharray:3 3\n`;
    });
    displayEdges=[];
    graph.edges.forEach(e=>{
      if($('ew-table-kind').value && e.kind!==$('ew-table-kind').value)return;
      const s=representative.get(e.source),t=representative.get(e.target);if(!mapping.has(s)||!mapping.has(t))return;
      if(s===t && e.source!==e.target)return;
      const label=e.kind==='TI_CANDIDATE'?`共同读写 · ${e.process_ids.length} TI`:e.label;
      code+=`  ${mapping.get(s)} ${e.kind==='TI_CANDIDATE'?'-.':'--'} "${mermaidLabel(label)}" ${e.kind==='TI_CANDIDATE'?'.->':'-->'} ${mapping.get(t)}\n`;
      displayEdges.push(e);
    });
    // 设计关系是本地规划边，与服务端静态关系分开绘制，永远标注未部署。
    const kindFilter=$('ew-table-kind').value;
    (design.relations||[]).forEach(r=>{
      if(kindFilter&&kindFilter!=='DESIGN_RELATION')return;
      const s=representative.get(r.source.ref),t2=representative.get(r.target.ref);
      if(!mapping.has(s)||!mapping.has(t2))return;
      const e={id:r.id,kind:'DESIGN_RELATION',label:'设计关系 · 未部署',source:r.source.ref,target:r.target.ref,
               provenance:'DESIGN_RELATION',mapping:r.mapping,write_policy:r.write_policy,template:r.template};
      code+=`  ${mapping.get(s)} -. "设计关系 · 未部署" .-> ${mapping.get(t2)}\n`;
      displayEdges.push(e);
    });
    $('ew-graph').replaceChildren();
    if(shown.size)viewer=window.TM1Mermaid.mount($('ew-graph'),{code,idMap:nodeMap,title:'架构工作区',view:preserve&&Object.keys(layout).length?layout:null,
      onNodeClick:(id,_mid,_label,event)=>{if(groups.some(g=>g.id===id)){showGroup(id);return;}select(id,!!(event?.ctrlKey||event?.metaKey));},
      onEdgeClick:i=>showEdge(displayEdges[i]),onBoxSelect:ids=>{selected=new Set(ids.filter(id=>known.has(id)||drafts.some(d=>d.id===id)||design.cubes.some(c=>c.id===id)||design.schemas.some(s=>s.id===id)));updateSelection();changed();},onRendered:updateSelection});
    $('ew-summary').textContent=`${shown.size} 个可见对象 · ${displayEdges.length} 条可见关系 · ${hidden.size} 个局部隐藏对象。虚线是候选共同读写，不是已证明的值流。`;
    renderTable();renderGroups();updateSelection();
  }
  function updateSelection(){
    viewer?.select([...selected],edgeSelection?displayEdges.findIndex(e=>e.id===edgeSelection):undefined);
    document.querySelectorAll('#ew-relations tr[data-edge]').forEach(tr=>tr.setAttribute('aria-selected',String(tr.dataset.edge===edgeSelection)));
    // 图 → 表联动：选中边时把对应记录滚入视野，而非只改颜色。
    if(edgeSelection){const row=document.querySelector('#ew-relations tr[data-edge="'+CSS.escape(edgeSelection)+'"]');if(row)row.scrollIntoView({block:'nearest'});}
  }
  function select(id,multiple){if(!id)return;if(!multiple)selected.clear();if(multiple&&selected.has(id))selected.delete(id);else selected.add(id);edgeSelection=null;updateSelection();changed();run(()=>showNode(id));}
  function renderTable(){
    const table=element('table'),head=element('tr');['来源','动作','目标'].forEach(t=>head.appendChild(element('th',t)));table.appendChild(head);
    const kind=$('ew-table-kind').value;
    displayEdges.filter(e=>!kind||e.kind===kind).forEach(e=>{const tr=element('tr');tr.dataset.edge=e.id;tr.tabIndex=0;
      [name(e.source),e.label,name(e.target)].forEach(t=>tr.appendChild(element('td',t)));tr.onclick=()=>showEdge(e);tr.onkeydown=event=>{if(event.key==='Enter')showEdge(e);};table.appendChild(tr);});
    $('ew-relations').replaceChildren(table);updateSelection();
  }
  function panel(title){const p=$('ew-detail');p.replaceChildren(element('h2',title));p.appendChild(button('关闭详情',()=>{++detailGeneration;p.replaceChildren(element('p','画布与选中对象已保留。','muted'));}));return p;}
  function evidence(parent,title,value){
    // 证据体积可能达数 KB × 数十条；按需渲染，避免详情面板被 JSON 拖慢。
    const d=element('details');d.appendChild(element('summary',title));parent.appendChild(d);
    let raw='';
    d.addEventListener('toggle',()=>{if(!d.open||d.dataset.ready)return;d.dataset.ready='1';
      if(!raw){raw=typeof value==='string'?value:JSON.stringify(value,null,2);if(raw.length>6000)raw=raw.slice(0,6000)+'\n…（已截断，完整结构请用导出或源码核对）';}
      d.appendChild(element('pre',raw,'code'));});
    return d;
  }
  const KIND_LABEL={FIXED_MEMBER:'固定',PARAMETER:'运行时变量',DATA_ROW_VARIABLE:'数据行变量',LOOKUP_COORDINATE:'查表坐标',UNRESOLVED:'待确认'};
  function source(parent,title,code,mode){if(!code)return;const d=element('details'),box=element('div');d.append(element('summary',title),box);parent.appendChild(d);d.addEventListener('toggle',()=>{if(d.open&&!box.dataset.ready){box.dataset.ready='1';window.tm1Source.mount(box,{code,mode});}});}
  async function showNode(id){
    const dc=design.cubes.find(c=>c.id===id),ds=design.schemas.find(s=>s.id===id);
    if(dc){renderCubeDraft(dc);return;}
    if(ds){renderSchema(ds);return;}
    const token=++detailGeneration,n=known.get(id)||drafts.find(d=>d.id===id);if(!n)return;
    const p=panel(n.name);p.appendChild(element('p',n.provenance==='DESIGN_DRAFT'?'设计草稿 · 未部署 / 未验证':n.in_snapshot===false?'索引提及，当前快照未取得该对象定义':'本地模型对象 · 静态分析不代表运行验证','muted'));
    if(n.provenance==='DESIGN_DRAFT'){p.appendChild(element('p','维度顺序：'+n.dimensions.join(' → ')));return;}
    p.appendChild(button('在当前图展开此对象',()=>explore([{type:n.type,name:n.name}],true)));
    p.appendChild(button('展开直接 TI / 调用关系',async()=>{$('ew-view').value='objects';await explore([{type:n.type,name:n.name}],true);}));
    const adjacent=graph.edges.filter(e=>e.source===id||e.target===id);
    adjacent.slice(0,30).forEach(e=>p.appendChild(button(e.label+'：'+name(e.source===id?e.target:e.source),()=>showEdge(e))));
    const data=await req('/api/workbench/detail?'+new URLSearchParams({snapshot_id:snapshot,type:n.type,name:n.name}));if(token!==detailGeneration)return;
    const o=data.object;
    if(n.type==='cube'){
      p.appendChild(element('h3','实际维度顺序'));(o.dimensions||[]).forEach((d,i)=>p.appendChild(element('p',`${i+1}. ${d}`)));
      source(p,'Rule / Feeder 源码',o.rules,'rule');
      p.appendChild(button('查看 Rule 计算与 Feeder 边界',async()=>{
        const data=await req('/api/workbench/rules?'+new URLSearchParams({snapshot_id:snapshot,cube:n.name}));if(token!==detailGeneration)return;
        const box=element('div');box.appendChild(element('h3','声明式 Rule 计算'));
        p.querySelector('[data-rule-summary]')?.remove();box.dataset.ruleSummary='1';
        (data.rules||[]).slice(0,40).forEach(rule=>{box.appendChild(element('p',`行 ${rule.line_start} · ${rule.lhs?.raw||'目标区域待核对'} ← ${(rule.db_references||[]).map(r=>r.cube||'动态 Cube').join('、')||'本 Cube / 表达式'}`));source(box,'计算源码',rule.raw,'rule');evidence(box,'表达式与未确认项',rule);});
        box.appendChild(element('p',`${(data.feeders||[]).length} 条 Feeder；稀疏性支持，不作为普通数值流。`,'muted small'));evidence(box,'Feeder 技术关系',data.feeders||[]);p.appendChild(box);
      }));
    }
    if(n.type==='process'){
      p.appendChild(element('p','读取：'+(o.reads_cubes||[]).join('、')));p.appendChild(element('p','写入：'+(o.writes_cubes||[]).join('、')));
      ['prolog','metadata','data','epilog'].forEach(s=>source(p,s+' 源码',o[s],'ti'));
      p.appendChild(button('核对写入切面与值表达式',async()=>{
        const data=await req('/api/workbench/writes?'+new URLSearchParams({snapshot_id:snapshot,process:n.name}));if(token!==detailGeneration)return;
        p.querySelector('[data-write-summary]')?.remove();const box=element('div');box.dataset.writeSummary='1';
        const primary=data.writes.filter(w=>w.cube&&!w.cube.startsWith('}'));
        box.appendChild(element('h3',`已解析目标写入 · ${primary.length} 个位置`));
        // 切面聚合：把同一 TI 内重复出现的固定成员/运行时变量归并，默认即可读懂。
        const slice=(list)=>{const fixed=new Map(),runtime=new Map(),pending=new Map();
          list.forEach(w=>(w.coordinate_mapping?.items||[]).forEach(c=>{const b=c.binding||{},dim=c.dimension||'维度待确认';
            if(b.kind==='FIXED_MEMBER'){if(!fixed.has(dim))fixed.set(dim,new Set());fixed.get(dim).add(String(b.value));}
            else if(b.kind==='PARAMETER'||b.kind==='DATA_ROW_VARIABLE'||b.kind==='LOOKUP_COORDINATE'){if(!runtime.has(dim))runtime.set(dim,new Set());runtime.get(dim).add(`${b.expression||'取值待确认'}（${KIND_LABEL[b.kind]}）`);}
            else {if(!pending.has(dim))pending.set(dim,new Set());pending.get(dim).add(String(b.expression||'待确认'));}}));
          const show=m=>[...m].map(([k,v])=>{const a=[...v];return `${k} = ${a.slice(0,3).join(' / ')}${a.length>3?` …共 ${a.length} 种`:''}`;});
          return {fixed:show(fixed),runtime:show(runtime),pending:show(pending)};};
        if(primary.length){
          const s=slice(primary),block=element('div','','ew-slice');
          if(s.fixed.length)block.appendChild(element('p','固定目标切面：'+s.fixed.join('；'),'small'));
          if(s.runtime.length)block.appendChild(element('p','运行时 / 动态坐标：'+s.runtime.join('；'),'small'));
          if(s.pending.length)block.appendChild(element('p','待确认坐标：'+s.pending.slice(0,6).join('；')+(s.pending.length>6?' …':''),'small muted'));
          box.appendChild(block);
        }
        const auxiliary=element('details');auxiliary.appendChild(element('summary',`系统对象 / 目标未确认的写入（${data.writes.length-primary.length}）`));
        data.writes.forEach(w=>{
          const items=w.coordinate_mapping?.items||[];
          const buckets={fixed:[],runtime:[],pending:[]};
          items.forEach(c=>{const b=c.binding||{};
            if(b.kind==='FIXED_MEMBER')buckets.fixed.push(`${c.dimension||'维度待确认'} = ${b.value}`);
            else if(b.kind==='PARAMETER'||b.kind==='DATA_ROW_VARIABLE'||b.kind==='LOOKUP_COORDINATE')buckets.runtime.push(`${c.dimension||'维度待确认'} = ${b.expression||'取值待确认'}（${KIND_LABEL[b.kind]}）`);
            else buckets.pending.push(`${c.dimension||'维度待确认'} = ${b.expression||'待确认'}`);});
          const counts=`固定 ${buckets.fixed.length} · 运行时 ${buckets.runtime.length} · 待确认 ${buckets.pending.length}`;
          const d=element('details');d.appendChild(element('summary',`${w.cube||'目标待确认'} · ${w.operation} · ${w.evidence?.section}:${w.evidence?.line} · ${counts}`));
          if(buckets.fixed.length)d.appendChild(element('p','固定：'+buckets.fixed.join('；'),'small'));
          if(buckets.runtime.length)d.appendChild(element('p','运行时：'+buckets.runtime.join('；'),'small'));
          if(buckets.pending.length)d.appendChild(element('p','待确认（'+buckets.pending.length+'）：'+buckets.pending.slice(0,6).join('；')+(buckets.pending.length>6?' …':''),'small muted'));
          d.appendChild(element('p','源码值表达式：'+(w.value_expression||'未取得')));
          d.appendChild(element('p',w.data_row_binding_status==='NO_CONFIRMED_ROW_DEPENDENCY'?'Data 行值的来源尚未证明。':'切面和表达式来自静态分析；完整源值绑定、条件与运行结果仍需证据核对。','muted small'));evidence(d,'写入证据与定义链状态',w);(primary.includes(w)?box:auxiliary).appendChild(d);
        });if(auxiliary.children.length>1)box.appendChild(auxiliary);if(data.writes.length<data.total)box.appendChild(element('p',`本次仅展示前 ${data.writes.length} / ${data.total} 个写入点。`,'muted small'));p.appendChild(box);
      }));
      const ds=o.datasource||{};
      const external=element('details');external.append(element('summary','外部数据源声明 / 元数据边界'));
      external.append(element('p','数据源类型：'+(ds.type||ds.Type||'未采集 / 未确认')));
      external.append(element('p','字段结构：未在此查询中取得。没有打开外部文件、执行 SQL 或读取业务行。','muted small'));p.appendChild(external);
      evidence(p,'已采集的数据源定义（可能含本地路径，请谨慎分享）',ds);
    }
    codegenLink(p);
  }
  function showEdge(e){
    if(!e)return;++detailGeneration;edgeSelection=e.id;selected=new Set([e.source,e.target]);updateSelection();changed();
    const p=panel(e.label);p.appendChild(element('p',name(e.source)+' → '+name(e.target)));
    p.appendChild(element('p',e.kind==='TI_CANDIDATE'?'同一个 TI 的对象级共同读写。源值绑定和逐单元格映射尚未证明。':e.kind==='RULE_REFERENCE'?'声明式 Rule 引用，不是 TI 物理写入，也不是 Feeder 值传递。':'索引观察；执行次数、条件和运行顺序未验证。','muted'));
    (e.process_ids||[]).forEach((id,i)=>p.appendChild(button('查看处理 TI：'+e.process_names[i],()=>{
      if(!known.has(id)){if(known.size>=120)throw new Error('研究对象已达到 120 个上限。');known.set(id,{id,name:e.process_names[i],type:'process',provenance:'MODEL_FACT'});}
      return showNode(id);
    })));
    [e.source,e.target].forEach(id=>p.appendChild(button('查看 '+name(id),()=>showNode(id))));
    evidence(p,'索引证据与未确认原因',e);codegenLink(p);
  }
  function codegenLink(p){const cubes=[...selected].map(id=>known.get(id)).filter(n=>n?.type==='cube');if(cubes.length!==2)return;
    p.appendChild(button('将两个 Cube 带入现有代码模板',async()=>{templateRef='cube-data-transfer';await save(false);const params=new URLSearchParams({workspace_id:workspaceId,source:cubes[0].name,target:cubes[1].name,snapshot_id:snapshot});location.href='/codegen?'+params;}));
    p.appendChild(element('p','顺序：'+cubes[0].name+' → '+cubes[1].name+'；进入模板后仍需加载维度和人工核对。','muted small'));
  }
  function renderGroups(){const box=$('ew-groups');box.replaceChildren();groups.forEach(g=>{const div=element('div',undefined,'ew-group');div.append(element('strong',g.name),element('p',`${g.members.length} 个对象 · 人工解释`,'small muted'),button(g.folded?'展开':'折叠',()=>{g.folded=!g.folded;render();changed();}),button('编辑',()=>showGroup(g.id)));box.appendChild(div);});}
  function showGroup(id){const g=groups.find(g=>g.id===id),p=panel(g.name);p.appendChild(element('p','人工解释，不能被提升为模型事实。','muted'));g.members.forEach(id=>p.appendChild(element('p',name(id))));
    const note=element('textarea');note.className='input';note.value=g.note;note.setAttribute('aria-label','模块备注');note.oninput=()=>{g.note=note.value;changed();};p.appendChild(note);
    p.appendChild(button('加入当前选中对象（可跨模块）',()=>{g.members=[...new Set([...g.members,...selected])];renderGroups();showGroup(id);changed();}));
    p.appendChild(button('移除这个人工模块',()=>{groups=groups.filter(x=>x.id!==id);render();panel('模块已移除，模型对象保留');changed();}));
  }
  async function savedList(){const data=await files.list();if(snapshot&&snapshot!==data.snapshot_id)throw new Error('模型已变化，不能混用工作区。');snapshot=data.snapshot_id;$('ew-saved').replaceChildren(new Option('选择已保存工作区',''));data.workspaces.forEach(w=>{const o=new Option(w.name+(w.compatible?'':'（其他模型 / 不兼容）'),w.id);o.disabled=!w.compatible;$('ew-saved').appendChild(o);});}
  async function save(asNew){const w=currentWorkspace();const result=await files.save(w,asNew?'':workspaceId,asNew?'':revision);workspaceId=result.id;revision=result.revision;dirty=false;remember();history.replaceState(null,'','/architecture?view=workbench&workspace_id='+workspaceId);await savedList();status('工作区已保存到独立用户目录；采集模型保持只读。');}
  async function restore(data){
    const w=data.workspace;if(w.snapshot_id!==snapshot)throw new Error('工作区绑定其他模型；没有按名称自动重绑。');
    const restoreQuery={...w.query,snapshot_id:snapshot,objects:w.objects,depth:0,node_budget:120,edge_budget:300,source_prefix:'',target_prefix:'',view:'objects'};
    const r=await req('/api/workbench/graph',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(restoreQuery)});
    if(r.limits.missing.length)throw new Error('保存的对象引用失效，原工作区未覆盖。');
    const cubeResult=await req('/api/workbench/graph',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...restoreQuery,objects:w.objects.filter(o=>o.type==='cube'),view:'cubes'})});
    workspaceId=data.id||'';revision=data.revision||'';templateRef=w.template_ref;known.clear();query=w.query;restoreOptions(query);
    $('ew-search').value=query.objects?.[0]?.name||query.source_prefix||'';if(query.objects?.[0])$('ew-kind').value=query.objects[0].type;
    r.nodes.forEach(n=>known.set(n.id,n));
    const edgeMap=new Map([...r.edges,...cubeResult.edges].map(e=>[e.id,e]));
    graph={...r,nodes:r.nodes.filter(n=>!w.visible?.length||w.visible.includes(n.id)),edges:w.edge_ids?.length?w.edge_ids.map(id=>edgeMap.get(id)).filter(Boolean):r.edges};
    const missingEdges=(w.edge_ids||[]).filter(id=>!edgeMap.has(id)).length;
    groups=w.groups;drafts=w.drafts||[];selected=new Set(w.selected);hidden=new Set(w.hidden);layout=w.layout;
    design=w.design||{mode:'explore',cubes:[],dimensions:[],schemas:[],relations:[],blueprints:[]};
    setMode(design.mode||'explore',false);
    $('ew-name').value=w.name;$('ew-mdx').value=w.mdx;$('ew-notes').value=w.notes;dirty=false;render(true);remember();status(missingEdges?`已恢复对象和备注；${missingEdges} 条关系未在当前预算内复核，原文件保留，不能宣称完整恢复。`:'工作区已恢复；MDX 仅为研究文本，没有执行。',missingEdges>0);
  }
  let timer;['ew-search','ew-kind'].forEach(id=>$(id).addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>run(search),180);}));
  $('ew-requery').onclick=()=>run(()=>explore([...selected].map(id=>known.get(id)).filter(Boolean).slice(0,20).map(n=>({type:n.type,name:n.name})),false));
  $('ew-path').onclick=()=>run(()=>explore([],false,true));$('ew-cancel').onclick=()=>{++generation;abort?.abort();status('查询已取消显示；未修改当前画布。');};
  $('ew-path-next').onclick=()=>run(()=>explore([],false,true,(query.seed_offset||0)+20));
  $('ew-clear').onclick=()=>{selected.clear();edgeSelection=null;updateSelection();changed();};$('ew-hide').onclick=()=>{selected.forEach(id=>hidden.add(id));selected.clear();render();changed();};$('ew-show').onclick=()=>{hidden.clear();render();changed();};
  $('ew-table-kind').onchange=()=>{query.relation_types=$('ew-table-kind').value?[$('ew-table-kind').value]:[];render();changed();};
  $('ew-group-create').onclick=()=>{const groupName=$('ew-group-name').value.trim();if(!groupName||!selected.size)return status('先选择对象并填写模块名称。',true);groups.push({id:'g-'+crypto.randomUUID(),name:groupName,members:[...selected],note:'',folded:false,provenance:'USER_INTERPRETATION'});renderGroups();changed();status('人工模块已建立；同一对象可以加入多个模块。');};
  // ---------------------------------------------------------------- 设计模式
  const uid=p=>p+crypto.randomUUID().replace(/-/g,'').slice(0,12);
  const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  function setMode(mode,mark=true){
    design.mode=mode;
    $('ew-mode-explore').className='btn'+(mode==='explore'?' primary':' ghost');
    $('ew-mode-design').className='btn'+(mode==='design'?' primary':' ghost');
    $('ew-mode-explore').setAttribute('aria-selected',String(mode==='explore'));
    $('ew-mode-design').setAttribute('aria-selected',String(mode==='design'));
    $('ew-design').hidden=mode!=='design';
    $('ew-mode-hint').textContent=mode==='design'
      ?'设计：创建草稿并生成代码草案；不部署、不修改模型，草稿不代表快照事实。'
      :'探索：只读研究已有模型。设计：创建草稿，不部署、不修改模型。';
    renderDesignLists();
    if(mark){changed();render();}
  }

  async function loadDesignMeta(){
    const data=await req('/api/workbench/design/meta?snapshot_id='+encodeURIComponent(snapshot||''));
    if(snapshot&&data.snapshot_id!==snapshot)throw new Error('模型已变化，设计元数据未载入。');
    designMeta=data;
    const opts=designMeta.dimensions.map(d=>'<option value="'+esc(d)+'">').join('');
    let list=document.getElementById('ew-dim-options');
    if(!list){list=element('datalist');list.id='ew-dim-options';document.body.appendChild(list);}
    list.innerHTML=opts;
    $('ew-dc-dims').setAttribute('list','ew-dim-options');
    fillRelationSelects();
  }

  function fillRelationSelects(){
    const src=$('ew-rel-source'),tgt=$('ew-rel-target');
    const sOpts=[...design.schemas.map(s=>[s.id,'CSV: '+s.name]),...design.cubes.map(c=>[c.id,'Cube 草稿: '+c.name])];
    src.replaceChildren(...sOpts.map(([v,l])=>new Option(l,v)));
    tgt.replaceChildren(...design.cubes.map(c=>new Option('Cube 草稿: '+c.name,c.id)));
  }

  function designCubeNode(c){
    return {id:c.id,name:c.name,type:'draft',provenance:'DESIGN_DRAFT'};
  }

  function renderDesignLists(){
    const relBox=$('ew-rel-list');relBox.replaceChildren();
    if(!design.relations.length)relBox.appendChild(element('p','还没有设计关系。先建 Cube 草稿与来源，再选择来源→目标。','muted small'));
    design.relations.forEach(r=>{
      const div=element('div','','ew-design-item');
      div.appendChild(element('strong',name(r.source.ref)+' → '+name(r.target.ref)));
      div.appendChild(element('p',(r.template==='csv-to-cube'?'CSV → Cube':'Cube → Cube')+' · 写入 '+(r.write_policy==='overwrite'?'覆盖':'累加')+' · '+r.mapping.length+' 条映射','small muted'));
      div.appendChild(button('配置映射',()=>{openMapping(r.id);}));
      div.appendChild(button('生成 TI 草案',()=>generateFor(r.id)));
      relBox.appendChild(div);
    });
    const dl=$('ew-design-list');dl.replaceChildren();
    design.cubes.forEach(c=>{const d=element('div','','ew-design-item');d.appendChild(element('strong',c.name+' · Cube 草稿'));d.appendChild(element('p',c.dimensions.map(x=>x.name).join(' → '),'small muted'));d.appendChild(button('查看 / 创建说明',()=>renderCubeDraft(c)));dl.appendChild(d);});
    design.dimensions.forEach(d=>{
      const row=element('div','','ew-design-item');
      row.appendChild(element('p','维度草稿：'+d.name+'（'+d.elements.length+' 元素 · '+d.element_type+'）· '+d.id,'small'));
      row.appendChild(button('引用到 Cube 维度框',()=>{
        const box=$('ew-dc-dims');box.value=(box.value.trim()?box.value.trim()+'\n':'')+d.name+'@'+d.id;
        status('已加入：'+d.name+'@'+d.id+'（顺序即 Cube 维度顺序）');
      }));
      dl.appendChild(row);
    });
    design.schemas.forEach(s=>dl.appendChild(element('p','CSV Schema：'+s.name+'（'+s.fields.length+' 字段）','small')));
    const bp=$('ew-bp-list');bp.replaceChildren();
    design.blueprints.forEach(b=>bp.appendChild(element('p','Blueprint：'+b.name+' v'+b.version+'（'+b.relation_ids.length+' 关系）','small')));
  }

  function renderCubeDraft(c){
    const p=panel(c.name);p.appendChild(element('p','Cube 草稿 · 未部署 / 未验证；不修改任何真实 Cube','muted'));
    p.appendChild(element('h3','维度顺序'));
    c.dimensions.forEach((ref,i)=>p.appendChild(element('p',`${i+1}. ${ref.name}（${ref.kind==='existing'?'快照已有维度':'维度草稿 '+ref.draft_id}）`)));
    const rel=design.relations.filter(r=>r.target.ref===c.id);
    rel.forEach(r=>p.appendChild(button('查看映射：'+name(r.source.ref)+' → '+c.name,()=>openMapping(r.id))));
    p.appendChild(button('查看 Cube 创建说明',()=>showCubeSpec(c.id)));
    p.appendChild(button('删除此草稿',()=>{design.cubes=design.cubes.filter(x=>x.id!==c.id);design.relations=design.relations.filter(r=>r.target.ref!==c.id&&r.source.ref!==c.id);selected.delete(c.id);render();renderDesignLists();fillRelationSelects();changed();panel('草稿已删除，真实模型未受影响');}));
  }

  function renderSchema(s){
    const p=panel(s.name);p.appendChild(element('p','CSV Schema 草稿 · 仅表头结构，未读取任何数据行','muted'));
    p.appendChild(element('h3','字段（'+s.fields.length+'）'));
    s.fields.forEach(f=>p.appendChild(element('p',`${f.name} · ${f.type}${f.required?' · 必填':''}`)));
    p.appendChild(element('p','来源：'+s.origin+'（类型为建议值，需在映射中确认）','muted small'));
    p.appendChild(button('删除此 Schema',()=>{design.schemas=design.schemas.filter(x=>x.id!==s.id);design.relations=design.relations.filter(r=>r.source.ref!==s.id);selected.delete(s.id);render();renderDesignLists();fillRelationSelects();changed();panel('Schema 草稿已删除');}));
  }

  async function showCubeSpec(cubeId){
    const data=await req('/api/workbench/design/cube-spec',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({design:design,snapshot_id:snapshot,cube_id:cubeId})});
    const p=panel(data.spec.name+' · 创建说明');
    p.appendChild(element('p','这是规格与步骤，不是已部署对象。','muted'));
    data.spec.dimensions.forEach(d=>p.appendChild(element('p',`${d.position}. ${d.name} — ${d.source==='DESIGN_DRAFT'?'需先创建维度草稿（'+d.elements+' 元素）':'当前快照已存在'}`)));
    const d=element('details'),pre=element('pre',data.spec.steps.join('\n'),'code');d.append(element('summary','创建步骤'),pre);p.appendChild(d);
  }

  function openMapping(relId){
    const rel=design.relations.find(r=>r.id===relId);if(!rel)return;
    const cube=design.cubes.find(c=>c.id===rel.target.ref);
    const schema=design.schemas.find(s=>s.id===rel.source.ref);
    const dims=cube?cube.dimensions.map(d=>d.name):[];
    const p=panel('映射：'+name(rel.source.ref)+' → '+name(rel.target.ref));
    p.appendChild(element('p','每个目标维度都必须显式映射并勾选确认，否则不会生成代码。','muted small'));
    const table=element('div','','ew-map');
    dims.forEach((dim,idx)=>{
      const entry=rel.mapping.find(m=>m.target_dimension===dim)||{target_dimension:dim,kind:'UNMAPPED',fixed_member:'',source_field:'',expression:'',confirmed:false};
      const row=element('div','','ew-map-row');
      row.appendChild(element('strong',(idx+1)+'. '+dim));
      const kind=element('select','','input');
      [['UNMAPPED','未映射'],['FIXED','固定成员'],['FROM_SOURCE','来源字段'],['EXPRESSION','表达式']].forEach(([v,l])=>kind.appendChild(new Option(l,v)));
      kind.value=entry.kind;
      const val=element('input','','input');val.placeholder=entry.kind==='EXPRESSION'?"如 '2026'":'成员 / 字段名';
      val.value=entry.kind==='FIXED'?entry.fixed_member:(entry.kind==='FROM_SOURCE'?entry.source_field:entry.expression);
      const conf=element('input');conf.type='checkbox';conf.checked=!!entry.confirmed;
      const label=element('label','确认');label.prepend(conf);
      const sync=()=>{
        const k=kind.value;const e={target_dimension:dim,kind:k,fixed_member:'',source_field:'',expression:'',confirmed:conf.checked};
        if(k==='FIXED')e.fixed_member=val.value.trim();
        else if(k==='FROM_SOURCE')e.source_field=val.value.trim();
        else if(k==='EXPRESSION')e.expression=val.value.trim();
        const others=rel.mapping.filter(m=>m.target_dimension!==dim);
        rel.mapping=[...others,e];
        changed();
      };
      kind.onchange=()=>{val.placeholder=kind.value==='EXPRESSION'?"如 '2026'":'成员 / 字段名';sync();};
      val.oninput=sync;conf.onchange=sync;
      row.append(kind,val,label);table.appendChild(row);
    });
    p.appendChild(table);
    if(rel.source.kind==='csv'&&schema){
      const vs=element('select','','input');vs.id='ew-vsource';
      vs.appendChild(new Option('（选择数值列）',''));
      schema.fields.forEach(f=>vs.appendChild(new Option(f.name,f.name)));
      vs.value=rel.value_source||'';vs.onchange=()=>{rel.value_source=vs.value;changed();};
      p.appendChild(element('label','数值来源列（vValue）'));p.appendChild(vs);
    }
    const pol=element('select','','input');pol.id='ew-wpolicy';pol.append(new Option('覆盖（CellPutN）','overwrite'),new Option('累加（CellIncrementN）','accumulate'));
    pol.value=rel.write_policy;pol.onchange=()=>{rel.write_policy=pol.value;changed();};
    p.appendChild(element('label','写入策略'));p.appendChild(pol);
    const confAll=button('全部标记为已确认',()=>{rel.mapping=rel.mapping.map(m=>({...m,confirmed:true}));openMapping(relId);changed();});
    p.appendChild(confAll);
    p.appendChild(button('校验并生成 TI 草案',()=>generateFor(relId)));
  }

  async function generateFor(relId){
    const data=await req('/api/workbench/design/generate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({design:design,snapshot_id:snapshot,relation_id:relId})});
    const p=panel('生成结果 · '+relId);
    if(data.status!=='ok'){
      p.appendChild(element('h3','未生成：需要先补齐配置'));
      (data.blockers||[]).forEach(b=>p.appendChild(element('p','· '+b)));
      p.appendChild(button('返回映射配置',()=>openMapping(relId)));
      status('生成被阻断：请补齐映射后再试。',true);return;
    }
    const rel=design.relations.find(r=>r.id===relId);
    lastGenerated.set(relId,{at:data.artifact.generated_at,template:data.artifact.template,
      summary:data.summary,validated:true});
    changed();
    p.appendChild(element('p','TI 草案 · DESIGN_DRAFT · 未在 TM1 Server 部署或执行','muted'));
    p.appendChild(element('p','模板：'+data.artifact.template+' · 维度：'+data.summary.dimensions));
    p.appendChild(element('p','写入：'+data.summary.operation+'（'+(data.summary.write_policy==='overwrite'?'覆盖':'累加')+'）','small'));
    ['prolog','metadata','data','epilog'].forEach(sec=>{
      const d=element('details');if(sec==='data')d.open=true;
      d.append(element('summary',sec+' 源码'),element('pre',data.code[sec]||'','code'));
      p.appendChild(d);
    });
    const all=['prolog','metadata','data','epilog'].map(s=>'### '+s.toUpperCase()+'\n'+data.code[s]).join('\n\n');
    p.appendChild(button('导出 .ti 文本',()=>files.download((design.cubes.find(c=>c.id===rel.target.ref)?.name||'draft')+'.ti',all)));
    p.appendChild(element('p','已知限制：未做运行验证；字符分隔源全部按字符串读取，数值经 StringToNumberEx 转换；目标坐标必须与维度顺序一致。','muted small'));
    status('已生成 TI 草案（仅本地草稿，未部署）。');
  }

  function createCubeDraft(){
    const nameV=$('ew-dc-name').value.trim(),raw=$('ew-dc-dims').value.split('\n').map(s=>s.trim()).filter(Boolean);
    if(!nameV||!raw.length)return status('Cube 草稿需要名称和按顺序声明的维度。',true);
    const dims=raw.map(line=>{
      const at=line.indexOf('@');
      const nm=(at>0?line.slice(0,at):line).trim();
      const id=at>0?line.slice(at+1).trim():'';
      return id?{kind:'draft',name:nm,draft_id:id}:{kind:'existing',name:nm};
    });
    const seen=new Set();
    for(const d of dims){if(seen.has(d.name.toLowerCase()))return status('维度不能重复：'+d.name,true);seen.add(d.name.toLowerCase());}
    const bad=dims.find(d=>d.kind==='draft'&&!design.dimensions.some(x=>x.id===d.draft_id));
    if(bad)return status('草稿维度不存在：'+bad.draft_id+'（请先创建维度草稿）',true);
    const cube={id:uid('draft-'),name:nameV,note:$('ew-dc-note').value.trim(),
      dimensions:dims,measures:[],provenance:'DESIGN_DRAFT'};
    design.cubes.push(cube);
    $('ew-dc-name').value='';$('ew-dc-dims').value='';$('ew-dc-note').value='';
    fillRelationSelects();render();renderDesignLists();changed();
    status('Cube 草稿已创建（未部署，未修改真实模型）。');
  }

  function createDimensionDraft(){
    const nm=$('ew-dd-name').value.trim(),elems=$('ew-dd-elems').value.split('\n').map(s=>s.trim()).filter(Boolean);
    if(!nm)return status('维度草稿需要名称。',true);
    if(new Set(elems.map(e=>e.toLowerCase())).size!==elems.length)return status('维度元素不能重复。',true);
    design.dimensions.push({id:uid('dimdraft-'),name:nm,elements:elems,element_type:$('ew-dd-type').value,note:'',provenance:'DESIGN_DRAFT'});
    $('ew-dd-name').value='';$('ew-dd-elems').value='';
    renderDesignLists();changed();status('维度草稿已创建：'+nm);
  }

  function parseSchema(){
    const text=$('ew-cs-header').value;
    const line=(text.split('\n').find(s=>s.trim())||'').trim();
    if(!line)return status('请粘贴一行表头。',true);
    const names=line.split(/[,;\t|]/).map(s=>s.trim().replace(/^["']|["']$/g,'')).filter(Boolean);
    const seen=new Set();
    for(const n of names){if(seen.has(n.toLowerCase()))return status('表头字段重复：'+n,true);seen.add(n.toLowerCase());}
    const guess=n=>/[Qty|Quantity|Amount|Cost|Price|Value|Amt]/i.test(n)?'number':/date/i.test(n)?'date':(/^is|flag$/i.test(n)?'boolean':'unknown');
    schemaDraftFields=names.map(n=>({name:n,type:guess(n),required:false,note:''}));
    const box=$('ew-cs-fields');box.replaceChildren();
    schemaDraftFields.forEach((f,i)=>{
      const row=element('div','','ew-map-row');
      row.appendChild(element('strong',f.name));
      const sel=element('select','','input');
      ['unknown','string','number','date','boolean'].forEach(t=>sel.appendChild(new Option(t,t)));
      sel.value=f.type;sel.onchange=()=>{schemaDraftFields[i].type=sel.value;};
      row.appendChild(sel);box.appendChild(row);
    });
    status('已解析 '+names.length+' 个字段（仅表头，未读取数据行）。');
  }

  function createSchema(){
    const nm=$('ew-cs-name').value.trim();
    if(!nm)return status('Schema 需要来源名称。',true);
    if(!schemaDraftFields.length)return status('请先解析表头。',true);
    design.schemas.push({id:uid('csv-'),name:nm,fields:schemaDraftFields.slice(),origin:'USER_INPUT',note:'',provenance:'DESIGN_DRAFT'});
    $('ew-cs-name').value='';$('ew-cs-header').value='';$('ew-cs-fields').replaceChildren();schemaDraftFields=[];
    fillRelationSelects();render();renderDesignLists();changed();status('CSV Schema 草稿已保存。');
  }

  function createRelation(){
    const src=$('ew-rel-source').value,tgt=$('ew-rel-target').value;
    if(!src||!tgt)return status('请选择来源与目标。',true);
    const isCsv=design.schemas.some(s=>s.id===src);
    design.relations.push({id:uid('rel-'),source:{kind:isCsv?'csv':'cube_draft',ref:src},
      target:{kind:'cube_draft',ref:tgt},mapping:[],value_source:'',
      write_policy:'overwrite',template:isCsv?'csv-to-cube':'cube-data-transfer',confirmed:false,note:'',provenance:'DESIGN_RELATION'});
    render();renderDesignLists();changed();status('设计关系已建立，请配置映射。');
  }

  function saveBlueprint(){
    const nm=$('ew-bp-name').value.trim();
    if(!nm)return status('Blueprint 需要名称。',true);
    const now=new Date().toISOString();
    design.blueprints.push({id:uid('bp-'),name:nm,note:$('ew-bp-note').value.trim(),version:1,
      cube_ids:design.cubes.map(c=>c.id),dimension_ids:design.dimensions.map(d=>d.id),
      schema_ids:design.schemas.map(s=>s.id),relation_ids:design.relations.map(r=>r.id),
      artifacts:[...lastGenerated.entries()].map(([rid,g])=>({relation_id:rid,template:g.template,
        template_version:'1',generated_at:g.at,status:'DESIGN_DRAFT',validated:true,blockers:[],summary:g.summary||{}})),
      created_at:now,updated_at:now,provenance:'DESIGN_DRAFT'});
    $('ew-bp-name').value='';$('ew-bp-note').value='';
    renderDesignLists();changed();status('Blueprint 已保存到工作区（仍为草稿，不含企业源码正文）。');
  }

  $('ew-mode-explore').onclick=()=>setMode('explore');
  $('ew-mode-design').onclick=()=>{setMode('design');run(loadDesignMeta);};
  $('ew-cs-parse').onclick=parseSchema;
  $('ew-cs-create').onclick=createSchema;
  $('ew-dc-create').onclick=createCubeDraft;
  $('ew-dd-create').onclick=createDimensionDraft;
  $('ew-rel-create').onclick=createRelation;
  $('ew-bp-save').onclick=saveBlueprint;
  $('ew-save').onclick=()=>run(()=>save(false));$('ew-save-as').onclick=()=>run(()=>save(true));$('ew-open').onclick=()=>run(async()=>{if(!$('ew-saved').value)return;await restore(await files.load($('ew-saved').value));});
  $('ew-export').onclick=()=>files.download('architecture-workspace.json',currentWorkspace());
  $('ew-import').onchange=()=>run(async()=>{const file=$('ew-import').files[0];if(!file)return;if(file.size>1024*1024)throw new Error('工作区文件超过 1MB 上限。');const workspace=JSON.parse(await file.text());const result=await files.save(workspace,'','');await restore(await files.load(result.id));await savedList();});
  ['ew-notes','ew-mdx','ew-name'].forEach(id=>$(id).oninput=changed);
  window.addEventListener('pagehide',remember);
  window.addEventListener('beforeunload',e=>{remember();if(dirty){e.preventDefault();e.returnValue='';}});
  run(async()=>{await savedList();const params=new URLSearchParams(location.search),id=params.get('workspace_id'),session=window.WorkbenchContext?.get('engineering-workspace');
    if(id)await restore(await files.load(id));else if(root.dataset.name){$('ew-kind').value=root.dataset.kind==='process'?'process':'cube';$('ew-search').value=root.dataset.name;await explore([{type:$('ew-kind').value,name:root.dataset.name}],false);}else if(session?.workspace.snapshot_id===snapshot)await restore(session);
    await search();
  });
})();
