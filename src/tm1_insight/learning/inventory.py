"""Read-only directory ledger and independent reports for local model stores."""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from tm1_insight.learning.engine import build_report,markdown,VERSION
from tm1_insight.store.db import Store


def study_directory(settings,root,output,progress=None):
    root=Path(root).resolve();output=Path(output).resolve()
    if not root.is_dir():raise ValueError("请选择现有数据目录。")
    if output.is_relative_to(root):raise ValueError("报告目录必须在原始数据目录之外，避免修改数据目录。")
    output.mkdir(parents=True,exist_ok=True)
    models=[];formats=Counter();files=0;bytes_total=0
    known={'.json','.duckdb','.parquet','.xlsx','.xlsm','.sql','.zip','.docx','.blob','.view','.process','.dimension','.cube','.chore','.subset','.rux'}
    with (output/'files_manifest.jsonl').open('w',encoding='utf-8') as ledger:
        for parent,dirs,names in os.walk(root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if not (Path(parent)/d).is_symlink())
            for name in sorted(names):
                path=Path(parent)/name
                if path.is_symlink():continue
                try:stat=path.stat()
                except OSError:continue
                suffix=path.suffix.casefold();format=suffix if suffix in known else 'other'
                formats[format]+=1;files+=1;bytes_total+=stat.st_size
                ledger.write(json.dumps({'path':str(path.relative_to(root)),'bytes':stat.st_size,'modified_ns':stat.st_mtime_ns,
                                         'format':format,'content_verified':False},ensure_ascii=False)+'\n')
                if suffix=='.duckdb':models.append(path)
    if len(models)>50:raise ValueError("发现超过 50 个数据库，请缩小扫描目录。")
    results=[]
    for number,path in enumerate(sorted(models),1):
        if progress:progress(number,len(models))
        candidate=settings.model_copy(update={'database_file':path,'data_dir':path.parent.parent if path.parent.name.casefold()=='db' else path.parent})
        con=Store(candidate).connect(read_only=True)
        try:
            tables={row[0] for row in con.execute('SHOW TABLES').fetchall()}
            if not {'processes','cubes','dimensions'}<=tables:continue
            before=(path.stat().st_size,path.stat().st_mtime_ns)
            report=build_report(con,'*')
            if before!=(path.stat().st_size,path.stat().st_mtime_ns):raise ValueError("分析期间模型发生变化，请重试。")
        finally:con.close()
        identity=hashlib.sha256(str(path).encode()).hexdigest()[:20]
        destination=output/identity;destination.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as pending:
            temporary=Path(pending)
            with (temporary/'study.json').open('w',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False)
            (temporary/'READ_ME_FIRST.md').write_text(markdown(report),encoding='utf-8')
            for name in ('study.json','READ_ME_FIRST.md'):os.replace(temporary/name,destination/name)
        results.append({'database':str(path),'report':identity+'/READ_ME_FIRST.md','summary':report['summary'],'coverage':report['coverage']})
    index={'schema':'local-directory-study-1','engine':VERSION,'root':str(root),'created':datetime.now(timezone.utc).isoformat(),
           'files':files,'bytes':bytes_total,'formats':dict(formats),'models':results,'publishing_authorized':False,
           'limits':['文件清单不等于内容已解析；原始文件保留，未读取数值单元格。','不同仓库分别分析，没有合并对象、业务含义或来源时间。','规则结构和对象引用不是完整运行语义或正确性证明。']}
    (output/'inventory.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 本地数据全目录盘点','','私有材料，禁止上传。',f'文件 {files} 个；独立模型仓库 {len(results)} 个。','','文件目录已经列账，不代表全部业务语义已经解释。']
    for item in results:
        c=item['coverage'];lines += ['',f"## 模型 `{item['database']}`",'',f"[阅读本模型教材]({item['report']})",str(item['summary']),
                                   f"需要解释完整语义的 Rule/Feeder {c['rules_uninterpreted']}；运行验证 0。"]+c['source_gaps']
    lines += ['','## 仍然未知','']+['- '+value for value in index['limits']]
    (output/'从这里开始.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return index
