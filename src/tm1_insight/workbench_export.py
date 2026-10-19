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
                    summary[field]=dict(total=page['total'],sample=page['items'][:25],sample_limit=25,complete=page['total']<=25,
                        recorded=meta['fields'][field]['status']=='recorded')
                write(f'dimensions/dimension-{i:04d}.json',canonical(sanitize(dict(metadata=meta,summary=summary),private_values)),kind='dimension_summary')
            guard()
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
