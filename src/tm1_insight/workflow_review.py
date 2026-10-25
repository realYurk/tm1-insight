"""Human-facing projection of existing Workflow artifacts, never an analyzer."""
from html import escape
import json

from tm1_insight import workflow

SCHEMA = 'ti-reconstruction-review-1'
MAX_ROWS = 200


def source_declaration(con, name):
    """Scoped declaration adapter; reuse the existing resolver, never bind values."""
    from tm1_insight.architecture_extraction import datasource
    from tm1_insight.learning.syntax import statements
    lengths=con.execute("SELECT length(coalesce(prolog,''))+length(coalesce(metadata,''))+length(coalesce(data,''))+length(coalesce(epilog,'')) FROM processes WHERE name=?",[name]).fetchone()
    if not lengths or lengths[0]>workflow.MAX_CODE:
        return dict(status='UNKNOWN',reason='未读取超出单 TI 预算的声明',evidence=[])
    parts=con.execute('SELECT prolog,metadata,data,epilog,datasource FROM processes WHERE name=?',[name]).fetchone()
    code=tuple(x or '' for x in parts[:4])
    cubes={r[0] for r in con.execute('SELECT name FROM cubes').fetchall()}
    binding=datasource(code,cubes)
    if binding:
        return dict(type='VIEW' if binding.get('cube') else binding.get('external_type'),cube=binding.get('cube'),
                    view=binding.get('view'),status=binding['status'],evidence=binding.get('locations',[]),
                    reason='数据源声明不证明数据行值进入目标单元格')
    try:recorded=json.loads(parts[4]) if parts[4] else {}
    except (ValueError,TypeError):recorded={}
    if not isinstance(recorded,dict):recorded={}
    from tm1_insight.store.data_row import source_hash,SECTIONS
    proof=[dict(table='processes',process=name,column='datasource')]
    tables={r[0] for r in con.execute('SHOW TABLES').fetchall()}
    matched=False
    if 'process_source_metadata' in tables:
        row=con.execute('SELECT payload FROM process_source_metadata WHERE process_name=? AND length(payload)<=200000',[name]).fetchone()
        try:meta=json.loads(row[0]) if row else {}
        except (ValueError,TypeError):meta={}
        if isinstance(meta,dict) and meta.get('source_hash')==source_hash(dict(zip(SECTIONS,code))) and isinstance(meta.get('datasource'),dict):
            recorded=meta['datasource'];matched=True
            proof=[dict(table='process_source_metadata',process=name,source_hash=meta['source_hash'])]
    dtype=str(recorded.get('type',recorded.get('Type','UNKNOWN')))
    # The snapshot declaration is only a recorded declaration. Effective VIEW
    # identity still comes from the existing source-hash checked row contract.
    overridden=any(t[0]['value'].casefold() in {'datasourcetype','datasourcenameforserver','datasourcecubeview'} and len(t)>1 and t[1]['value']=='='
                   for t in statements(code,include_logging=True))
    if matched and not overridden and dtype.casefold() in {'view','tm1cubeview'} and recorded.get('cube') in cubes:
        return dict(type=dtype,cube=recorded['cube'],view=recorded.get('view'),status='RECORDED_SOURCE_BINDING',evidence=proof,
                    reason='源码身份匹配的元数据声明；未据此确认行变量或写入值依赖')
    return dict(type=dtype,status='UNKNOWN' if overridden else 'RECORDED_DECLARATION',
                evidence=proof,
                reason='源码存在未确认的数据源覆盖' if overridden else '仅为采集声明；有效 Cube/View 与行值绑定另行核对')


def build(path, schedules=(), declaration=None, *, process=None):
    header, _, processes = workflow.page(path, 'processes', limit=500)
    root = process or header['root']
    detail = workflow.detail(path, root)
    if detail is None:
        raise KeyError(root)
    limits = []

    def page(section, process=''):
        _, total, items = workflow.page(path, section, limit=MAX_ROWS, process=process)
        if total > len(items):
            limits.append(f'{section} 仅显示前 {len(items)} / {total} 项')
        return items

    execution = page('execution')
    structure = page('structure', root)
    callers = [c for c in page('callers') if c['target'] == root]
    observations = [r for r in detail.get('observations', []) if r.get('kind') == 'cube']
    reads = sorted({r['target'] for r in observations if r.get('target') and r['operation'].casefold() in {'cellgetn','cellgets'}})
    writes = sorted({r['target'] for r in observations if r.get('target') and r['operation'].casefold() in {'cellputn','cellputs','cellincrementn'}})
    sections = next((p.get('sections', []) for p in processes if p['process'] == root), [])
    root_calls = [c for c in execution if c['process'] == root]
    # Calls at other source locations remain independent; never draw them as
    # direct invocations by the selected root or interpret discovery as order.
    indirect = [c for c in execution if c['process'] != root]
    source_reads = [{k:n.get(k) for k in ('id','cube','operation','resolution','coordinate_mapping','evidence')}
                    for n in detail.get('nodes', []) if n['kind'] == 'read']
    all_writes = detail.get('writes', [])
    row_context=detail.get('data_row_lineage') or {}
    view=row_context.get('source_view_binding')
    declaration=declaration or dict(type='VIEW' if view else 'UNKNOWN',status='RECORDED_DATASOURCE' if view else 'UNKNOWN',evidence=[])
    view=view or ({k:declaration.get(k) for k in ('cube','view','status','evidence')} if declaration.get('cube') else None)
    sources=dict(declaration=declaration,view_binding=view,
                 variables=row_context.get('data_source_variable_bindings',[]),
                 coordinates=row_context.get('source_coordinate_mapping',[]),
                 reasons=row_context.get('unresolved_binding_reasons',[]),runtime_verified=False)
    if len(all_writes) > 80:limits.append(f'当前 TI 写入仅显示前 80 / {len(all_writes)} 项')
    retained = all_writes[:80]
    write_fields = ('id','cube','operation','value_expression','formula_expression','evidence','coordinate_mapping',
                    'read_nodes','control_context','trace_status','data_row_binding_status',
                    'unresolved_binding_reasons','value_definition_chain','data_row_value_dependencies')
    scoped = dict(process=root, writes=[{k:w.get(k) for k in write_fields} for w in retained],
                  total=len(all_writes), reads=source_reads[:160], read_total=len(source_reads),
                  read_scope='CALCULATION_RETAINED_NODES_NOT_ALL_PROCESS_READS')
    if len(source_reads)>160:limits.append('值依赖读取仅显示前 160 项')
    missing_values = sum(bool(w.get('unknown_nodes') or w.get('unresolved_binding_reasons')) for w in retained)
    known = {p['process'] for p in processes}
    if any(c.get('expansion') in {'BOUNDARY','MODULE_BOUNDARY'} for c in execution):
        limits.append('存在范围外调用；本报告不代表完整程序或全部执行路径')
    behaviors=[]
    if view and view.get('cube'):behaviors.append(f"使用 {view['cube']} 的 View {view.get('view') or '（名称待确认）'} 作为声明数据源")
    if reads:behaviors.append('通过单元格读取函数访问 '+ '、'.join(reads))
    for operation,label in [('CellPutN','覆盖数值'),('CellPutS','覆盖文本'),('CellIncrementN','累加数值')]:
        targets=sorted({w['cube'] for w in all_writes if w.get('operation')==operation and w.get('cube')})
        if targets:behaviors.append('对 '+ '、'.join(targets)+' 执行'+label+'写入')
    if root_calls:behaviors.append(f'包含 {len(root_calls)} 处直接程序调用观察，条件与动态目标另行核对')
    if not behaviors:behaviors.append('尚无法从当前元数据确认主要数据加工行为')
    return dict(schema=SCHEMA, process=root, snapshot_id=header.get('source_fingerprint'), runtime_verified=False,
                summary=dict(reads=reads, writes=writes, direct_calls=len(root_calls), indexed_callers=len(callers),
                             analyzed_processes=len(known), write_points=len(all_writes), uncertain_writes=missing_values,
                             view_sources=[view['cube']] if view and view.get('cube') else [],behaviors=behaviors),
                sources=sources,
                sections=sections, calls=root_calls, downstream_calls=indirect, callers=callers,
                schedules=list(schedules), structure=structure, writes=scoped,
                parameters=detail.get('parameter_names', []),
                data_row_lineage=detail.get('data_row_lineage'),
                critical_unknowns=[x for x in header.get('unknown_groups', []) if x['process']==root][:10],
                cycles=header.get('cycles', []), budgets=header.get('budgets', {}), limitations=limits,
                evidence_context=dict(source_hash=detail.get('source_hash'), parser_version=header.get('parser_version'),
                                      engine_revision=header.get('engine_revision')),
                scope='selected_process_and_bounded_source_invocations_not_runtime_order')


def markdown(report):
    """Same projection as the UI, with readable tables before evidence."""
    def text(v):return escape(str(v if v is not None else '待确认')).replace('|','\\|').replace('\r',' ').replace('\n',' ')
    def location(e):return f"{e.get('section','Rule')}:{e.get('line','?')}:{e.get('column',1)}" if e else '索引定义'
    def table(head, rows):
        return ['| '+' | '.join(head)+' |','|'+'|'.join('---' for _ in head)+'|',
                *['| '+' | '.join(text(c) for c in row)+' |' for row in rows], '']
    def coordinates(mapping):
        result=[]
        for c in (mapping or {}).get('items', []):
            b=c.get('binding', {});kind=b.get('kind')
            label='固定' if kind=='FIXED_MEMBER' else '动态' if kind in {'PARAMETER','DATA_ROW_VARIABLE','LOOKUP_COORDINATE'} else '待确认'
            value=b.get('value') if kind=='FIXED_MEMBER' else b.get('expression','待确认')
            result.append(f"{c.get('dimension') or '维度待确认'}={value}（{label}）")
        return '；'.join(result) or '未确认'
    s=report['summary'];lines=['# TI 重构研究', '', '## 一页摘要', '', f"程序：{text(report['process'])}", '',
        '以下为源码与采集元数据的静态描述，未执行 TI，不证明运行顺序、实际值或迁移等价。', '',
        *[text(x)+'。' for x in s.get('behaviors',[])], '',
        'VIEW 声明来源：'+text('、'.join(s.get('view_sources',[])) or '尚无法从当前元数据确认')+'。声明来源不等于写入值来源。','',
        '读取 Cube：'+text('、'.join(s['reads']) or '未确认'), '', '写入 Cube：'+text('、'.join(s['writes']) or '未确认'), '',
        f"直接调用观察 {s['direct_calls']} 处；入口 Caller 索引 {s['indexed_callers']} 项；独立写入 {s['write_points']} 处，其中当前展示的 {s['uncertain_writes']} 处仍有值来源或坐标缺口。", '',
        '## 工程明细', '', '### 入口与调用', '']
    def call_rows(items):return [
        (c['process'],c.get('target') or '动态目标待确认',
         '；'.join(f"{b.get('parameter') or '参数待确认'}={b.get('expression','待确认')}（{'显式绑定' if b.get('binding_status')=='EXPLICIT_NAME_BINDING' else '待确认'}）" for b in c.get('bindings', [])),
         '；'.join(x.get('condition',x['kind']) for x in c.get('control_context', [])) or '未观察到条件（不代表实际执行）', location(c))
        for c in items]
    lines+=['### 直接调用','']+table(['调用方','被调用方','参数','条件','证据'],call_rows(report['calls']))
    lines+=['### 范围内下级调用（非入口直接调用、非运行顺序）','']+table(['调用方','被调用方','参数','条件','证据'],call_rows(report['downstream_calls']))
    lines+=table(['入口索引 Caller','目标','边界'],[(c['process'],c['target'],'索引观察，调用条件与参数未由该调用方源码核对') for c in report['callers']])
    lines+=table(['Chore 直接调度','步骤','状态'],[(c['chore'],c.get('step_order'),'采集调度定义；未证明实际运行') for c in report['schedules']])
    lines+=['### 四个 Section', '']+table(['Section','源码字符数'],[(x['section'],x['characters']) for x in report['sections']])
    sources=report.get('sources',{})
    view=sources.get('view_binding') or {}
    lines+=['### 数据源声明与行变量（独立确认）','',
            '数据源类型：'+text((sources.get('declaration') or {}).get('type','UNKNOWN')), '',
            '有效 VIEW Cube：'+text(view.get('cube'))+'；View：'+text(view.get('view'))+'；行布局：'+text(view.get('row_layout_status','待确认')), '']
    lines+=table(['行变量','源列位置（非维度位置）','类型','来源字段状态'],[(v.get('name'),v.get('position'),v.get('type'),
                  ('单元格值列' if (v.get('source_field') or {}).get('kind')=='CELL_VALUE' else '维度成员') if v.get('source_field_status')=='STATIC_NATIVE_LAYOUT' else '来源字段待确认') for v in sources.get('variables',[])])
    lines+=['### 独立写入点', '']
    read_by_id={r['id']:r for r in report['writes']['reads']}
    for w in report['writes']['writes']:
        lines += [f"#### {text(w['operation'])} → {text(w['cube'])} · {location(w['evidence'])}", '',
                  '值表达式：'+text(w['value_expression']), '', '目标坐标：'+text(coordinates(w['coordinate_mapping'])), '']
        sources=[read_by_id[i] for i in (w.get('read_nodes') or []) if i in read_by_id]
        if not sources and not (w.get('data_row_binding_status')=='STATIC_CELL_VALUE_DEPENDENCY' and w.get('data_row_value_dependencies')):
            lines+=['源值切面：未确认；共同读写不能补足值绑定。', '']
        for r in sources:lines += ['静态表达式读取：'+text(r.get('cube'))+' · '+text(coordinates(r.get('coordinate_mapping')))+' · '+location(r.get('evidence')), '']
        for d in w.get('data_row_value_dependencies') or []:
            field=(d.get('source_field') or {}).get('kind')
            lines+=['数据行值参数依赖：'+text(d.get('variable'))+'；来源 Cube：'+text(d.get('source_cube'))+'；来源字段：'+('单元格值列' if field=='CELL_VALUE' else '维度成员' if field=='DIMENSION_MEMBER' else '待确认')+'；绑定：'+('静态单元格值列依赖' if w.get('data_row_binding_status')=='STATIC_CELL_VALUE_DEPENDENCY' else '仅变量依赖，完整值来源待确认')+'（非运行验证）','']
        for c in w.get('control_context') or []:lines += ['条件（未求值）：'+text(c.get('condition',c['kind'])), '']
    lines+=['### 重构前应验证', '', '- 覆盖 / 累加与重复执行；清空范围及调用先后。', '- 参数缺省值、条件、循环与未确认的行变量来源。', '- Rule / Feeder、汇总权重与运行环境副作用；本报告未验证这些行为。', '', '## 证据与范围附录', '',
            '调用方仅有索引时不推断入口条件；调度记录不证明实际执行。原始源码按本地链接查看，不在每条关系重复复制。', '',
            *['- '+text(x) for x in report['limitations']], '',
            *['- '+text(x['reason']) for x in report['critical_unknowns']], '',
            '模型指纹：'+text(report.get('snapshot_id')), '', '契约：'+SCHEMA, '',
            '来源哈希：'+text(report.get('evidence_context',{}).get('source_hash')), '',
            '解析版本：'+text(report.get('evidence_context',{}).get('parser_version')), '',
            '```json',json.dumps({'source_evidence':report.get('sources',{}),'budgets':report.get('budgets'),
                                 'cycles':report.get('cycles'), 'evidence_context':report.get('evidence_context')},ensure_ascii=False,sort_keys=True,indent=2),'```']
    return '\n'.join(lines)+'\n'
