"""Bounded, offline analysis package over the existing scoped artifact and Store.

No new analysis, cells, server configuration or server requests. Original source
is hash-checked before inclusion; credential-bearing source is explicitly redacted.
"""
from contextlib import closing
import hashlib
import json
import re
import tempfile
import zipfile

from tm1_insight.learning.syntax import TOKEN, SECTIONS

VERSION='tm1-analysis-package-1'
MAX_BYTES=64*1024*1024
SENSITIVE=re.compile(r'password|passwd|pwd|secret|token|credential|authorization|cookie|connectionstring|username|odbcname',re.I)


def redact_source(code, private_values=()):
    tokens=list(TOKEN.finditer(code))
    spans=[]; pending=[]
    def flush():
        sensitive=any(t.lastgroup=='id' and SENSITIVE.search(t.group()) for t in pending)
        sensitive |= any(t.lastgroup=='id' and t.group().casefold() in {'odbcopen','httprequest','executecommand'} for t in pending)
        for t in pending:
            if t.lastgroup=='comment':
                if SENSITIVE.search(t.group()) or any(v and v in t.group() for v in private_values):spans.append((t.start(),t.end()))
            elif t.lastgroup=='string' and (sensitive or any(v and v in t.group() for v in private_values) or re.search(r'(?:password|pwd|uid|dsn|token)\s*=|://[^/\s]+:[^/\s]+@',t.group(),re.I)):
                spans.append((t.start()+1,t.end()-1))
        pending.clear()
    for t in tokens:
        pending.append(t)
        if t.lastgroup=='symbol' and t.group()==';':flush()
    flush()
    for start,end in reversed(spans):code=code[:start]+''.join(c if c in '\r\n' else '*' for c in code[start:end])+code[end:]
    return code,len(spans)


def sanitize(value, private_values=()):
    if isinstance(value,dict):
        sensitive_name=any(isinstance(value.get(k),str) and SENSITIVE.search(value[k]) for k in ('name','Name','parameter','variable'))
        return {k:('[REDACTED]' if SENSITIVE.search(k) or (sensitive_name and k.casefold() in {'value','default','expression'}) else sanitize(v,private_values)) for k,v in value.items()}
    if isinstance(value,list):return [sanitize(v,private_values) for v in value]
    if isinstance(value,str):
        if value and value in private_values:return '[REDACTED]'
        return redact_source(value,private_values)[0]
    return value


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')


def verify_package(path, *, include_summary=False):
    """Verify an analysis ZIP without extracting it or trusting its manifest."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos=archive.infolist()
            if len(infos)>1000 or sum(i.file_size for i in infos)>MAX_BYTES+1024*1024:
                raise ValueError('包超过校验预算')
            names=[i.filename for i in infos]
            if len(names)!=len(set(names)):
                raise ValueError('包中存在重复文件名')
            for name in names:
                if not name or name.startswith('/') or '\\' in name or ':' in name or any(p in {'.','..'} for p in name.split('/')):
                    raise ValueError('包含不安全路径')
            info=archive.getinfo('Manifest.json')
            if info.file_size>1024*1024:
                raise ValueError('清单超过大小限制')
            manifest=json.loads(archive.read(info))
            if not isinstance(manifest,dict) or manifest.get('schema')!=VERSION:
                raise ValueError('不支持的分析包版本')
            entries=manifest.get('files')
            if not isinstance(entries,list):raise ValueError('文件清单无效')
            listed=set()
            for entry in entries:
                if not isinstance(entry,dict) or not isinstance(entry.get('path'),str):raise ValueError('文件清单条目无效')
                name=entry['path']
                if name in listed or name=='Manifest.json':raise ValueError('文件清单重复')
                listed.add(name)
                item=archive.getinfo(name)
                if type(entry.get('bytes')) is not int or item.file_size!=entry['bytes']:raise ValueError('文件长度不匹配')
                digest=hashlib.sha256()
                with archive.open(item) as source:
                    while chunk:=source.read(65536):digest.update(chunk)
                if digest.hexdigest()!=entry.get('sha256'):raise ValueError('文件校验和不匹配')
            if listed != set(names)-{'Manifest.json'}:raise ValueError('文件与清单不一致')
            omissions=manifest.get('omissions',[])
            if not isinstance(omissions,list):raise ValueError('遗漏清单无效')
            result={'schema':VERSION,'files_checked':len(listed),'omissions':len(omissions)}
            if include_summary:
                # Only read the exact, checksummed report; do not extract or render HTML.
                if 'BusinessFlow.md' in listed:
                    info=archive.getinfo('BusinessFlow.md')
                    if info.file_size>512*1024:raise ValueError('功能说明超过预览大小限制')
                    result['summary']=archive.read(info).decode('utf-8')
                else:
                    result['summary']=None
            return result
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        raise ValueError('分析包损坏或清单无效') from exc


def package(path, con, guard=lambda:None, settings=None):
    """Build and validate fully before returning a stream; failures publish no ZIP."""
    from tm1_insight import workflow
    from tm1_insight.store import dimensions
    from tm1_insight.human_workbench import flow
    from tm1_insight.functional_flow import markdown,mermaid
    if path.stat().st_size>MAX_BYTES:raise ValueError('当前范围超过分析包预算，请缩小入口。')
    private_values=tuple(str(v) for v in (getattr(settings,'tm1_password',None),getattr(settings,'tm1_address',None)) if v)
    file=tempfile.TemporaryFile();entries=[];written=0
    try:
        guard()
        with zipfile.ZipFile(file,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            def write(name,data,**meta):
                nonlocal written
                written+=len(data)
                if written>MAX_BYTES:raise ValueError('当前范围超过分析包 64 MiB 预算，请缩小入口。')
                info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(info,data)
                entries.append(dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),**meta))
            with path.open(encoding='utf-8') as src:report=json.load(src)
            header={k:report.get(k) for k in ('version','module','boundary','source_fingerprint','scope','limits','runtime_verified')}
            # One canonical resource owns all IR, writes, relationships and evidence.
            # Sources are not repeated on individual relations.
            write('Architecture.json',canonical(sanitize(report,private_values)),kind='analysis',schema=report['version'])
            presentation=flow(path)
            write('FunctionalFlow.json',canonical(sanitize(presentation,private_values)),kind='human_projection',schema=presentation['schema'])
            write('BusinessFlow.md',''.join(markdown(sanitize(presentation,private_values),include_evidence=False)).encode('utf-8'),kind='human_reading')
            write('Diagram.mmd',mermaid(sanitize(presentation,private_values)).encode('utf-8'),kind='diagram')
            omissions=[];sources=[];redactions=0
            with closing(workflow.connection(path)) as index:
                selected=index.execute("SELECT name,json_extract(payload,'$.source_hash') FROM processes ORDER BY name LIMIT 501").fetchall()
            if len(selected)>500:raise ValueError('源码范围超过 500 个 TI，请缩小入口。')
            metadata_present=bool(con.execute("SELECT 1 FROM information_schema.tables WHERE table_name='process_source_metadata'").fetchone())
            for i,(name,digest) in enumerate(selected):
                guard()
                if not digest:
                    omissions.append(dict(kind='process_source',name=name,reason='原分析未核对源码，未补写为已确认。'));continue
                row=con.execute('SELECT prolog,metadata,data,epilog FROM processes WHERE name=?',[name]).fetchone()
                if row is None:raise ValueError('本地源码已变化，请重新解析后导出。')
                parts=dict(zip(SECTIONS,(v or '' for v in row)))
                if hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest()!=digest:raise ValueError('本地源码与分析证据不匹配，请重新解析。')
                sections={}
                for section,code in parts.items():
                    sections[section],count=redact_source(code,private_values);redactions+=count
                metadata=None
                if metadata_present:
                    record=con.execute('SELECT payload FROM process_source_metadata WHERE process_name=?',[name]).fetchone()
                    if record:
                        metadata=json.loads(record[0])
                        metadata={'recorded':True,'matches_source':metadata.get('source_hash')==digest,'payload':sanitize(metadata,private_values)}
                if metadata is None:metadata={'recorded':False,'reason':'旧快照没有该 Process 的 Variables / DataSource 元数据。'}
                name_path=f'sources/ti-{i:04d}.json'
                write(name_path,canonical(dict(name=name,original_source_hash=digest,sections=sections,recorded_metadata=metadata,credential_redaction=True)),kind='process_source')
                sources.append(dict(type='process',name=name,path=name_path,original_source_hash=digest))
            for i,r in enumerate(report.get('rules', [])):
                guard()
                row=con.execute('SELECT rules FROM cubes WHERE name=?',[r['cube']]).fetchone()
                if row is None:raise ValueError('本地 Rule 已变化，请重新解析。')
                code=row[0] or ''
                if hashlib.sha256(code.encode()).hexdigest()!=r['source_hash']:raise ValueError('Rule 源码与分析证据不匹配，请重新解析。')
                code,count=redact_source(code,private_values);redactions+=count
                name_path=f'sources/rule-{i:04d}.json'
                write(name_path,canonical(dict(cube=r['cube'],original_source_hash=r['source_hash'],source=code,credential_redaction=True)),kind='rule_source')
                sources.append(dict(type='rule',name=r['cube'],path=name_path,original_source_hash=r['source_hash']))
            dim_names=sorted({d['name'] for d in report.get('dimensions', [])})
            if len(dim_names)>200:raise ValueError('维度摘要范围超过 200 个，请缩小入口。')
            for i,name in enumerate(dim_names):
                guard();meta=dimensions.metadata(con,name)
                if meta is None:
                    omissions.append(dict(kind='dimension',name=name,reason='缺少已保存定义。'));continue
                summary={}
                for field in dimensions.FIELDS:
                    page=dimensions.records(con,name,field,page=1)
                    recorded=meta['fields'][field]['status']=='recorded'
                    count_consistent=field!='elements' or meta['element_count'] is None or meta['element_count']==page['total']
                    summary[field]=dict(total=page['total'],sample=page['items'][:25],sample_limit=25,
                        complete=recorded and page['total']<=25 and count_consistent, recorded=recorded)
                write(f'dimensions/dimension-{i:04d}.json',canonical(sanitize(dict(metadata=meta,summary=summary),private_values)),kind='dimension_summary')
            guard()
            readme='''# 本地分析包阅读说明\n\n先阅读 BusinessFlow.md；Diagram.mmd 可用于查看流程图。\nArchitecture.json 和 sources/ 保留当前分析范围的结构、证据和已核对源码。\n\n维度文件是摘要，每类最多 25 条；未采集字段不等于空结构。\n请查看 Manifest.json 和维度文件中的遗漏、记录状态与采样情况。\n可在安装了 TM1 Insight 命令行的环境中运行 tm1-insight verify-analysis-package <文件路径> 校验包内一致性。该校验不证明来源可信。\n本包不是完整服务器备份，也不证明运行结果或重建等价。\n源码和结构可能包含敏感信息，请自行决定分享范围。\n'''
            write('README.md',readme.encode('utf-8'),kind='package_guide')
            manifest=dict(schema=VERSION,model=header,files=entries,sources=sources,omissions=omissions,
                sections={k:'Architecture.json#/'+k for k in ('cubes','dimensions','processes','rules','chores','execution_relationships','formation_relationships','write_explanations','unified_relations','relation_evidence','evidence','diagnostics','unresolved_dependencies','details')},
                source_policy='仅当前已核对范围，源码有凭据脱敏；原哈希指向本地原件，文件校验指向实际导出。',
                dimension_policy='已保存定义的计数及每类前 25 项摘要；未记录/未采集/未确认权重不补齐。',
                budgets=dict(max_uncompressed_bytes=MAX_BYTES,max_process_sources=500,max_dimensions=200,dimension_sample=25),
                credential_redactions=redactions,runtime_verified=False,
                warning='业务源码及结构可能敏感，请自行决定共享范围。静态分析不是运行证明；缺失字段不代表不存在。')
            # Manifest intentionally excludes itself; every listed payload has a checksum.
            archive.writestr(zipfile.ZipInfo('Manifest.json',date_time=(1980,1,1,0,0,0)),canonical(manifest))
        file.seek(0)
        return file
    except BaseException:
        file.close();raise


def stream(file):
    try:
        while chunk:=file.read(65536):yield chunk
    finally:file.close()
