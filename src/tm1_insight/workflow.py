"""Scoped workflow reconstruction from source facts; never executes TM1."""
from __future__ import annotations

from collections import deque
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from tm1_insight.learning.calculation import MAX_CODE, VERSION as CALC_VERSION
from tm1_insight.learning.understanding import call_components
from tm1_insight.learning.pages import index_path
from tm1_insight.store.calculation import inspect, node_label
from tm1_insight.tasks import ResultArtifact

VERSION = 'workflow-1'
CACHE_REVISION = 4
MAX_CODE_TOTAL = 5_000_000
MAX_NODES_TOTAL = 50_000
MAX_RECORDS = 10_000
SECTIONS = {'processes','execution','data','calculation','unknowns','structure','callers'}
LIMITS = [
    '源码调用观察、目录结构关系、表达式值依赖分别记录；全部未经运行验证。',
    '展开目录内字面或安全赋值链确认的常量 ExecuteProcess / RunProcess 目标，动态/分支不确定目标保留 UNKNOWN；RunProcess 不证明完成顺序。',
    '包含 Bedrock / 系统封装源码，不根据函数名合成拷贝、清空或数值流；不存在的封装源码保持未知。',
    '参数仅作显式绑定检查，不替换跨 TI 公式；缺省值、类型、异常、实际执行次数、Rule/Feeder 和外部数据源未还原。',
    '调用方索引和未绑定语句的目录读写只作 STRUCTURAL_UNVERIFIED，不据此推导值流。',
    '每 TI 最多 250000 字符/5000 节点，全范围最多 5000000 字符/50000 节点，每类事实最多 10000 条。',
    '字符串常量从分析及导出中隐藏，原始代码仅通过本地 Evidence 按需查看；导出含私有对象名称。',
]


class ProcessCache:
    """Reuse unchanged-snapshot TI reports across intersecting scopes, max 64 MiB."""
    def __init__(self, root):
        root=Path(root);root.mkdir(parents=True,exist_ok=True)
        self.con=sqlite3.connect(root/'workflow-processes.sqlite3',timeout=2)
        self.con.execute('PRAGMA max_page_count=32768')
        self.con.execute('CREATE TABLE IF NOT EXISTS entries(key TEXT PRIMARY KEY,payload TEXT,touched INTEGER)')

    def get(self,key):
        row=self.con.execute('SELECT payload FROM entries WHERE key=?',[key]).fetchone()
        return json.loads(row[0]) if row else None

    def put(self,key,value):
        import time
        payload=json.dumps(value,ensure_ascii=False)
        self.con.execute('INSERT OR REPLACE INTO entries VALUES (?,?,?)',[key,payload,time.time_ns()])
        total=self.con.execute('SELECT coalesce(sum(length(CAST(payload AS BLOB))),0) FROM entries').fetchone()[0]
        for old,size in self.con.execute('SELECT key,length(CAST(payload AS BLOB)) FROM entries WHERE key<>? ORDER BY touched',[key]).fetchall():
            if total<=64*1024*1024:break
            self.con.execute('DELETE FROM entries WHERE key=?',[old]);total-=size
        self.con.commit()

    def close(self):
        self.con.close()


def bindings(call, child):
    """Names are confirmed only against a selected child's declared parameters."""
    from tm1_insight.store.invocation import named_bindings
    return [dict(**b,binding_status='EXPLICIT_NAME_BINDING' if b['status']=='EXPLICIT_BINDING' else 'UNKNOWN')
        for b in named_bindings(call,child.get('parameter_names',[]) if child else [])]


def reconstruct(report, write):
    """Expand supported reaching definitions, not object-level read/write joins."""
    nodes={n['id']:n for n in report['nodes']}
    unresolved=[];visited_count=0
    def signature(index,depth=0):
        if depth>32:return None
        n=nodes[index]
        if n['kind']=='parameter':return ('parameter',n['name'].casefold())
        if n['kind']=='number':return ('number',n['value'])
        if n['kind']=='data_row':return ('data_row',n['name'].casefold())
        if n['kind'] in {'variable','assignment'} and n['children']:return signature(n['children'][0],depth+1)
        if n['kind'] in {'unary','binary'}:
            children=[signature(i,depth+1) for i in n['operands']]
            if all(c is not None for c in children):return (n['operator'],*children)
        return None
    mappings=[write['coordinate_mapping'],*[nodes[i]['coordinate_mapping'] for i in write['read_nodes']]]
    keys=[tuple(signature(c['node']) for c in m['items']) for m in mappings]
    compact=bool(not write.get('data_row_value_dependencies') and keys[0] and all(c is not None for c in keys[0]) and all(m['status']=='recorded_order' for m in mappings)
        and all(k==keys[0] for k in keys) and all([c['dimension'] for c in m['items']]==[c['dimension'] for c in mappings[0]['items']] for m in mappings))
    def coordinate(index):
        n=nodes[index]
        if n['kind'] in {'parameter','number','data_row'}:return n.get('name',n.get('value'))
        if n['kind']=='variable':
            definition=nodes[n['definition']]['evidence']
            return n['name']+'@'+str(definition['section'])+':'+str(definition['line'])+':'+str(definition['column'])
        if n['kind']=='unknown':return 'UNKNOWN('+n.get('name','expression')+')'
        if n['kind']=='redacted_string':
            unresolved.append('坐标字符串已隐藏');return 'UNKNOWN_STRING'
        unresolved.append('坐标表达式未完整还原')
        return 'UNKNOWN_COORD('+node_label(n)+')'
    def cell(cube,mapping):
        if not cube or mapping['status']!='recorded_order':
            unresolved.append('Cube 或完整维度顺序未知')
            return (cube or 'UNKNOWN')+'[UNKNOWN]'
        if any(not c.get('dimension_exists') for c in mapping['items']):unresolved.append('维度目录定义缺失')
        if any(c.get('binding',{}).get('kind') in {'UNRESOLVED','LOOKUP_COORDINATE'} for c in mapping['items']):unresolved.append('坐标固定成员或表达式尚未验证')
        return cube+'['+','.join(c['dimension'] if compact else c['dimension']+'='+(c['binding']['expression'] if c.get('binding',{}).get('kind') in {'FIXED_MEMBER','PARAMETER','NUMBER','DATA_ROW_VARIABLE'} else coordinate(c['node'])) for c in mapping['items'])+']'
    def render(index, depth=0):
        nonlocal visited_count
        visited_count+=1
        if depth>80 or visited_count>1000:
            unresolved.append('表达式展开预算');return 'UNKNOWN'
        n=nodes[index];kind=n['kind']
        if kind=='number':return n['value']
        if kind=='parameter':return n['name']
        if kind=='data_row':
            if n['field_kind']=='CELL_VALUE' and n['source_cube']:
                expected='String' if write['operation'].casefold()=='cellputs' else 'Numeric'
                if n['binding']['type']!=expected:
                    unresolved.append('行值类型与写入函数不匹配；隐式转换语义未确认')
                return n['source_cube']+'['+','.join(c['dimension']+'='+c['variable'] for c in n['source_coordinates'])+']'
            unresolved.append('行变量定义已知，但来源字段未确认或并非单元格值')
            return 'ROW('+n['name']+')'
        if kind in {'assignment','variable'} and n['children']:return render(n['children'][0],depth+1)
        if kind=='read' and n['operation'].casefold()=='cellgetn' and n['resolution']=='resolved':
            return cell(n['cube'],n['coordinate_mapping'])
        if kind=='unary':return '('+n['operator']+render(n['operands'][0],depth+1)+')'
        if kind=='binary':return '('+render(n['operands'][0],depth+1)+' '+n['operator']+' '+render(n['operands'][1],depth+1)+')'
        unresolved.append(n.get('reason','值语义未支持'));return 'UNKNOWN'
    expression=render(write['value_node'])
    target=cell(write['cube'],write['coordinate_mapping'])
    if write['operation'].casefold() not in {'cellputn','cellincrementn','cellputs'}:
        unresolved.append('这里只重建数值写入表达式')
    formula=target+(' += ' if write['operation'].casefold()=='cellincrementn' else ' = ')+expression
    if len(formula)>6000:
        formula='UNKNOWN · 展开表达式超过 6000 字符预算';unresolved.append('显示预算')
    expression_complete=not unresolved and not write['unknown_nodes']
    value_dependencies=[]
    confirmed_reads,confirmed_rows=confirmed_write_sources(write,nodes)
    for read in confirmed_reads:
        value_dependencies.append(dict(kind='value_dependency',status='STATIC_EXPRESSION_DEPENDENCY' if write['cube'] else 'PARTIAL_EXPRESSION_DEPENDENCY',
            source_cube=read['cube'],target_cube=write['cube'],read_evidence=read['evidence'],
            write_evidence=write['evidence'],runtime_verified=False))
    for dep in confirmed_rows:
        value_dependencies.append(dict(kind='value_dependency',status='STATIC_VIEW_ROW_DEPENDENCY',
            source_cube=dep['source_cube'],target_cube=write['cube'],source_kind='VIEW_ROW',
            read_evidence={k:v for k,v in dep['metadata_evidence'].items() if k!='process'},
            row_use_evidence=dep['use_location'],write_evidence=write['evidence'],runtime_verified=False))
    return dict(write_id=write['id'], operation=write['operation'],cube=write['cube'], evidence=write['evidence'],
        expression=write['formula_expression'],reconstructed=formula,control_context=write['control_context'],
        expression_status='STATIC_EXPRESSION' if expression_complete else 'PARTIAL',
        status='PARTIAL' if unresolved or write['unknown_nodes'] or write['control_context'] else 'STATIC_EXPRESSION',
        reasons=list(dict.fromkeys(unresolved)),value_dependencies=value_dependencies,
        definition_nodes=write['definition_nodes'],read_nodes=write['read_nodes'],unknown_nodes=write['unknown_nodes'],
        coordinate_mapping=write['coordinate_mapping'],shared_coordinate_binding=compact,runtime_verified=False)


def confirmed_write_sources(write, reads_by_id):
    """Source-backed value dependencies only; declarations remain separate facts."""
    if write.get('trace_status') not in {'STATIC', 'PARTIAL'}:
        return [], []
    reads = [reads_by_id[i] for i in write.get('read_nodes', []) if i in reads_by_id
             and reads_by_id[i].get('cube') and reads_by_id[i].get('resolution') == 'resolved']
    rows = [d for d in write.get('data_row_value_dependencies', [])
            if d.get('source_cube') and (d.get('source_field') or {}).get('kind') == 'CELL_VALUE'
            and write.get('data_row_binding_status') == 'STATIC_CELL_VALUE_DEPENDENCY']
    return reads, rows


def build(con, root, *, max_processes=200, max_depth=32, progress=None, cache_root=None, cache_source=None, expand_calls=None, roots=None, accept_root=None):
    if not 1<=max_processes<=500 or not 0<=max_depth<=64:raise ValueError('Invalid scope budget')
    def update(stage,index,current=0,total=None):
        if progress:progress(stage=stage,stage_index=index,stages_total=6,current=current,total=total)
    update('读取名称目录与选择入口',1)
    catalogs={kind:{r[0] for r in con.execute(f'SELECT name FROM {table}').fetchall()}
        for kind,table in [('process','processes'),('cube','cubes'),('dimension','dimensions')]}
    root_names=list(dict.fromkeys(roots if roots is not None else [root]))
    if any(n not in catalogs['process'] for n in root_names):raise KeyError(root)
    if len(root_names)>max_processes:raise ValueError('Too many entry processes')
    tables={r[0] for r in con.execute('SHOW TABLES').fetchall()}
    result=dict(version=VERSION,root=root,runtime_verified=False,status='PARTIAL',limits=LIMITS,
        budgets=dict(max_processes=max_processes,max_depth=max_depth),processes=[],execution=[],data=[],calculation=[],unknowns=[],structure=[],callers=[])
    unknown_keys=set()
    def add(section,record):
        if section=='unknowns':
            if len(result[section])>=MAX_RECORDS:truncated.add(section);return
            e=record.get('evidence',{})
            key=(record.get('process'),record.get('reason'),record.get('name'),e.get('section'),e.get('line'),e.get('column'))
            if key in unknown_keys:return
            unknown_keys.add(key)
        if len(result[section])<MAX_RECORDS:result[section].append(record)
        else:truncated.add(section)
    truncated=set();reports={};unparsed={};queue=deque((n,0) for n in root_names);scheduled=set(root_names);accepted=[];rejected=[];code_total=nodes_total=cache_hits=0
    cache=None
    if cache_root and cache_source:
        try:cache=ProcessCache(cache_root)
        except (sqlite3.Error,OSError):add('unknowns',dict(process=root,reason='局部解析缓存不可用，本次直接分析'))
    try:
        while queue:
            name,depth=queue.popleft()
            update('逐层解析 TI · 已解析 / 已发现',2,len(reports),len(reports)+len(queue)+1)
            key=hashlib.sha256((VERSION+CALC_VERSION+'\0'+str(cache_source)+'\0'+name).encode()).hexdigest()
            cached=None
            if cache:
                try:cached=cache.get(key)
                except (sqlite3.Error,ValueError):cache.close();cache=None
            if cached:
                report=cached['report'];sections=cached['sections'];chars=cached['characters'];cache_hits+=1
            else:
                lengths=con.execute("SELECT length(coalesce(prolog,'')),length(coalesce(metadata,'')),length(coalesce(data,'')),length(coalesce(epilog,'')) FROM processes WHERE name=?",[name]).fetchone()
                if lengths is None:continue
                chars=sum(lengths)
                if chars>MAX_CODE or code_total+chars>MAX_CODE_TOTAL:
                    add('unknowns',dict(process=name,reason='源码字符预算，未读取或解析该 TI 的完整代码'))
                    add('processes',dict(process=name,depth=depth,status='UNKNOWN',reads=[],writes=[],sections=[],source_hash=None,cache_reused=False))
                    unparsed[name]=dict(process=name,source_hash=None,status='UNKNOWN',nodes=[],writes=[],calls=[],parameter_names=[])
                    continue
                report=inspect(con,name,catalogs=catalogs)
                # Only selected source is loaded for section counts, never all model code.
                sections=[dict(section=s,characters=n) for s,n in zip(('prolog','metadata','data','epilog'),lengths)]
                update('保存已解析 TI 的局部缓存',3,len(reports)+1,len(reports)+len(queue)+1)
                if cache:
                    try:cache.put(key,dict(report=report,sections=sections,characters=chars))
                    except sqlite3.Error:cache.close();cache=None
            if code_total+chars>MAX_CODE_TOTAL or nodes_total+len(report['nodes'])>MAX_NODES_TOTAL:
                add('unknowns',dict(process=name,reason='全范围字符或节点预算，该 TI 未纳入结果'))
                add('processes',dict(process=name,depth=depth,status='UNKNOWN',reads=[],writes=[],sections=sections,source_hash=None,cache_reused=bool(cached)))
                unparsed[name]=dict(process=name,source_hash=None,status='UNKNOWN',nodes=[],writes=[],calls=[],parameter_names=[])
                continue
            if name in root_names and accept_root is not None and not accept_root(report):
                rejected.append(name);unparsed[name]=report
                code_total+=chars;nodes_total+=len(report['nodes'])
                add('unknowns',dict(process=name,reason='Cube 写入索引候选未绑定到已解析的直接写入；未沿其调用继续扩展'))
                continue
            if name in root_names:accepted.append(name)
            code_total+=chars;nodes_total+=len(report['nodes']);reports[name]=report
            proof=dict(process=name,source_hash=report['source_hash'])
            reads=set();writes=set()
            for observation in report['observations']:
                if observation['kind']=='cube':
                    op=observation['operation'].casefold()
                    role='read' if op in {'cellgetn','cellgets'} else 'write' if op in {'cellputn','cellputs','cellincrementn'} else 'reference'
                    add('data',dict(**proof,**observation,role=role,relation_kind='source_reference',runtime_verified=False))
                    if observation['target'] and role in {'read','write'}:(reads if role=='read' else writes).add(observation['target'])
                if observation['status']!='resolved':add('unknowns',dict(**proof,evidence=observation,reason='对象引用 '+observation['status']))
            for diagnostic in report['diagnostics']:
                add('unknowns',dict(**proof,reason=diagnostic.get('reason',str(diagnostic)) if isinstance(diagnostic,dict) else diagnostic))
            for write in report['writes']:
                calc=reconstruct(report,write);add('calculation',dict(**proof,**calc))
                if write['control_context']:add('unknowns',dict(**proof,evidence=write['evidence'],reason='写入所在条件/循环的可达性与迭代次数未求值'))
                for dependency in calc['value_dependencies']:
                    add('data',dict(**proof,**dependency,relation_kind='static_value_dependency',operation=write['operation'],
                        target=dependency['target_cube'],role='value_dependency',evidence=write['evidence']))
                for index in write['unknown_nodes']:
                    n=next(n for n in report['nodes'] if n['id']==index)
                    add('unknowns',dict(**proof,evidence=n['evidence'],name=n.get('name'),reason=n.get('reason','坐标或对象尚未确认')))
            indexed=set()
            if 'process_calls_process' in tables:
                indexed={r[0] for r in con.execute('SELECT DISTINCT callee FROM process_calls_process WHERE caller=? ORDER BY callee',[name]).fetchall()}
            observed=set()
            for call in report['calls']:
                if not call['target']:add('unknowns',dict(**proof,evidence=call,reason='调用目标未确认：'+call['status']+' · '+call['target_expression']))
                if call['control_context']:add('unknowns',dict(**proof,evidence=call,reason='调用所在条件/循环的可达性与迭代次数未求值'))
                target=call['target'];observed.add(target)
                edge=dict(**proof,**call,relation_kind='source_invocation',runtime_verified=False,index_present=target in indexed,
                    expansion='UNKNOWN' if not target else 'IN_SCOPE')
                if target and expand_calls is not None and not expand_calls(name,target,depth):
                    edge['expansion']='MODULE_BOUNDARY'
                    add('unknowns',dict(**proof,evidence=call,reason='模块边界策略未展开此调用；调用事实保留'))
                elif target and target not in scheduled:
                    if depth>=max_depth or len(scheduled)>=max_processes:
                        edge['expansion']='BOUNDARY';add('unknowns',dict(**proof,evidence=call,reason='调用展开达到深度或 TI 数量边界'))
                    else:scheduled.add(target);queue.append((target,depth+1))
                add('execution',edge)
            for target in sorted(indexed-observed):add('structure',dict(**proof,target=target,status='STRUCTURAL_UNVERIFIED',
                evidence=dict(table='process_calls_process',caller=name,callee=target),reason='目录调用索引未绑定当前已解析源码调用，未据此展开'))
            for table,seen,role in [('process_reads_cube',reads,'read'),('process_writes_cube',writes,'write')]:
                if table in tables:
                    for (cube,) in con.execute(f'SELECT DISTINCT cube_name FROM {table} WHERE process_name=? ORDER BY cube_name',[name]).fetchall():
                        if cube not in seen:add('structure',dict(**proof,target=cube,status='STRUCTURAL_UNVERIFIED',role=role,
                            evidence=dict(table=table,process_name=name,cube_name=cube),reason='目录读写未绑定当前语句；不推导值流'))
            add('processes',dict(**proof,depth=depth,status='PARTIAL',reads=sorted(reads),writes=sorted(writes),sections=sections,
                cache_reused=bool(cached),call_count=len(report['calls'])))
    finally:
        if cache:cache.close()
    update('核对参数、循环与范围边界',4,len(reports),len(reports))
    for edge in result['execution']:
        edge['bindings']=bindings(edge,reports.get(edge['target']))
        if edge['target'] and edge['target'] not in reports:edge['expansion']='BOUNDARY'
    if 'process_calls_process' in tables and accepted:
        slots=','.join('?' for _ in accepted)
        for caller,target in con.execute(f'SELECT DISTINCT caller,callee FROM process_calls_process WHERE callee IN ({slots}) ORDER BY caller,callee LIMIT 201',accepted).fetchall():
            if len(result['callers'])==200:
                add('unknowns',dict(process=root,reason='入口调用方目录仅展示前 200 条'));break
            result['callers'].append(dict(process=caller,target=target,status='STRUCTURAL_UNVERIFIED',evidence=dict(table='process_calls_process',caller=caller,callee=target)))
    result['cycles']=call_components(set(reports),[(e['process'],e['target']) for e in result['execution'] if e['target']])
    for section in sorted(truncated):result['unknowns'].append(dict(process=root,reason=section+' 达到 10000 条事实预算；后续未纳入导出'))
    inputs=sorted({c for p in result['processes'] for c in p['reads']});outputs=sorted({c for p in result['processes'] for c in p['writes']})
    result['summary']=dict(processes=len(result['processes']),parsed=len(reports),execution=len(result['execution']),unknowns=len(result['unknowns']),
        input_count=len(inputs),output_count=len(outputs),inputs=inputs[:100],outputs=outputs[:100],cache_hits=cache_hits,
        value_dependencies=sum(len(c['value_dependencies']) for c in result['calculation']),
        confirmed_value_dependencies=sum(d['status']=='STATIC_EXPRESSION_DEPENDENCY' for c in result['calculation'] for d in c['value_dependencies']),characters=code_total,nodes=nodes_total)
    groups={}
    for item in result['unknowns']:
        key=(item['process'],item['reason']);group=groups.setdefault(key,dict(process=item['process'],reason=item['reason'],count=0,evidence=item.get('evidence'),names=[]))
        group['count']+=1
        if item.get('name') and item['name'] not in group['names'] and len(group['names'])<5:group['names'].append(item['name'])
    result['unknown_group_count']=len(groups)
    result['unknown_groups']=sorted(groups.values(),key=lambda g:(g['process']!=root,-g['count'],g['process'],g['reason']))[:100]
    result['engine_revision']=CACHE_REVISION
    update('建立工作台分页索引与私有导出',5,len(reports),len(reports))
    result['accepted_roots']=accepted
    result['rejected_roots']=rejected
    result['parser_version']=CALC_VERSION
    result['details']={**reports,**unparsed}
    return result


def artifact(report, root, *, sections=SECTIONS):
    temporary=tempfile.TemporaryDirectory(dir=root)
    try:
        path=Path(temporary.name)/'workflow.json'
        path.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True),encoding='utf-8')
        with closing(sqlite3.connect(index_path(path))) as con:
            con.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,payload TEXT)')
            con.execute('CREATE TABLE items(section TEXT,position INTEGER,payload TEXT,search TEXT,PRIMARY KEY(section,position))')
            con.execute('CREATE TABLE processes(name TEXT PRIMARY KEY,payload TEXT)')
            header={k:v for k,v in report.items() if k not in set(sections)|{'details'}}
            stat=path.stat()
            con.executemany('INSERT INTO meta VALUES (?,?)',[('header',json.dumps(header,ensure_ascii=False)),('file',json.dumps([stat.st_size,stat.st_mtime_ns]))])
            for section in sections:
                con.executemany('INSERT INTO items VALUES (?,?,?,?)',[(section,i,json.dumps(item,ensure_ascii=False),item.get('process','').casefold()) for i,item in enumerate(report[section])])
            con.executemany('INSERT INTO processes VALUES (?,?)',[(name,json.dumps(data,ensure_ascii=False)) for name,data in report['details'].items()])
            con.commit()
        return ResultArtifact(path,index_path(path),temporary)
    except BaseException:temporary.cleanup();raise


def connection(path):
    return sqlite3.connect(index_path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)


def page(path,section='processes',offset=0,limit=50,process='',q='',*,sections=SECTIONS,version=VERSION):
    if section not in sections:raise ValueError('Unknown workflow view')
    with closing(connection(path)) as con:
        header=json.loads(con.execute("SELECT payload FROM meta WHERE key='header'").fetchone()[0])
        if header.get('version')!=version:raise ValueError('Not a compatible report')
        where='section=?';args=[section]
        if process:where+=' AND search=?';args.append(process.casefold())
        if q:where+=' AND instr(search,?)>0';args.append(q.casefold())
        total=con.execute('SELECT count(*) FROM items WHERE '+where,args).fetchone()[0]
        rows=con.execute('SELECT payload FROM items WHERE '+where+' ORDER BY position LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
        return header,total,[json.loads(r[0]) for r in rows]


def detail(path,process):
    with closing(connection(path)) as con:
        row=con.execute('SELECT payload FROM processes WHERE name=?',[process]).fetchone()
        return json.loads(row[0]) if row else None


def markdown(path):
    from html import escape
    def text(value):return escape(str(value)).replace('`','\\`').replace('\n',' ')
    def position(e):return f"{e.get('section','UNKNOWN')}:{e.get('line','?')}:{e.get('column','?')}"
    header,_,_=page(path)
    yield '# Analyze Workflow — 解析工作流\n\n'
    yield f"入口：{text(header['root'])}\n\n模型指纹：{header['source_fingerprint']}\n\n"
    yield '全部为静态分析，未执行 TM1；不将调用或共同读写解释为运行时值流。字符串常量已隐藏。\n\n'
    for section,title in [('processes','范围与逐 TI 读写'),('execution','源码调用与参数'),('structure','目录结构索引（未绑定源码）'),
                          ('callers','入口调用方目录（未验证源码）'),('data','源码读写与引用'),('calculation','受支持计算与表达式依赖'),('unknowns','UNKNOWN / 范围边界')]:
        yield '## '+title+'\n\n'
        offset=0
        while True:
            _,total,items=page(path,section,offset,100)
            for item in items:
                prefix='- '+text(item.get('process',header['root']))+' · '
                if section=='processes':
                    yield prefix+f"读取 {text(', '.join(item['reads']))}；写入 {text(', '.join(item['writes']))}；源码哈希 {item['source_hash'] or 'UNKNOWN'}\n"
                elif section=='execution':
                    yield prefix+f"{text(item['operation'])} → {text(item['target'] or 'UNKNOWN')} · {position(item)} · {item['expansion']}\n"
                    for b in item['bindings']:
                        yield f"  - 参数 {text(b['parameter'] or 'UNKNOWN')} ← {text(b['expression'])} · {b['binding_status']}\n"
                    for c in item['control_context']:yield '  - 条件未求值：'+text(c.get('condition','UNKNOWN'))+'\n'
                elif section=='calculation':
                    yield prefix+f"{text(item['reconstructed'])} · {item['status']} · {position(item['evidence'])}\n"
                    for d in item['value_dependencies']:yield f"  - {d['status']}：{text(d['source_cube'])} → {text(d['target_cube'] or 'UNKNOWN')} · 读取 {position(d['read_evidence'])} / 写入 {position(d['write_evidence'])}\n"
                elif section=='data':yield prefix+f"{text(item['operation'])} → {text(item['target'] or 'UNKNOWN')} · {item['status']} · {position(item)}\n"
                elif section in {'structure','callers'}:yield prefix+text(item['target'])+' · STRUCTURAL_UNVERIFIED · '+text(json.dumps(item['evidence'],ensure_ascii=False))+'\n'
                else:yield prefix+text(item['reason'])+' · '+position(item.get('evidence',{}))+'\n'
            offset+=len(items)
            if offset>=total:break
        yield '\n'
    yield '## 限制\n\n'
    for limit in header['limits']:yield '- '+limit+'\n'
