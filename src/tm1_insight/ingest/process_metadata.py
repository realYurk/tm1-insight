"""Small, GET-only process metadata bundles; explicit matching-source import.

No Execute/Preview/Cellset requests and no source pointer changes. Bundles are
immutable new files; analysis never invokes import or modifies a snapshot.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
from contextlib import contextmanager
from urllib.parse import quote

from tm1_insight.store.data_row import source_hash, save_metadata
from tm1_insight.tm1.metadata_diagnostics import MetadataFailure, failure


@contextmanager
def _connection(client):
    manager=getattr(client,'connect_metadata',client.connect)()
    try:tm1=manager.__enter__()
    except Exception as exc:
        record=failure('SESSION_START',exc)
        if record['stage']=='SESSION_START' and hasattr(client,'connect_metadata'):
            record['resource']='Configuration/ProductVersion/$value (TM1py session initialization)'
        raise MetadataFailure('SESSION_START','FAILED',record=record) from None
    try:yield tm1
    finally:manager.__exit__(None,None,None)


def _read(tm1,url,stage,cancel):
    if cancel:cancel()
    try:
        rest=getattr(tm1,'_tm1_rest',None)
        if rest is None:rest=tm1._rest  # legacy/mock adapter compatibility
        response=rest.GET(url)
        content=getattr(response,'content',b'')
        if isinstance(content,bytes) and len(content)>5_000_000:raise ValueError('Response budget')
        data=response.json()
        if not isinstance(data,dict):raise ValueError('Expected JSON object')
    except Exception as exc:raise MetadataFailure(stage,'FAILED',record=failure(stage,exc)) from None
    if cancel:cancel()
    return data


def validate_process(p):
    """Shape validation only; no modification of lineage semantics."""
    if not isinstance(p,dict) or not isinstance(p.get('name'),str) or not p['name']:
        raise MetadataFailure('LOCAL_VALIDATE','INVALID_PROCESS_IDENTITY')
    for s in ('prolog','metadata','data','epilog'):
        if not isinstance(p.get(s),str):raise MetadataFailure('LOCAL_VALIDATE','MISSING_SOURCE_FOR_IDENTITY')
    variables=p.get('variables')
    if variables is not None:
        if not isinstance(variables,list) or len(variables)>512:raise MetadataFailure('LOCAL_VALIDATE','INVALID_VARIABLES')
        for v in variables:
            if not isinstance(v,dict):raise MetadataFailure('LOCAL_VALIDATE','INVALID_VARIABLES')
            for field in ('Position','StartByte','EndByte'):
                value=v.get(field,v.get(field[0].lower()+field[1:]))
                if value is not None and type(value) is not int:raise MetadataFailure('LOCAL_VALIDATE','INVALID_VARIABLE_POSITION_TYPE')
    if p.get('datasource') is not None and not isinstance(p['datasource'],dict):raise MetadataFailure('LOCAL_VALIDATE','INVALID_DATASOURCE')


def collect(client, names, *, progress=None, cancel=None):
    names = list(dict.fromkeys(names))
    if not names or len(names)>20 or any(not isinstance(n,str) or not n or len(n)>1000 for n in names):
        raise ValueError('Select 1..20 process names')
    bundle = dict(schema='process-metadata-1', collected_at=datetime.now(timezone.utc).isoformat(), processes=[])
    if cancel:cancel()
    with _connection(client) as tm1:
        for i,name in enumerate(names):
            if progress: progress(i,len(names))  # cancellation may raise here
            key=quote(name.replace("'","''"),safe='')
            d=_read(tm1,f"/Processes('{key}')?$select=Name,DataSource/Type,DataSource/dataSourceNameForServer,DataSource/view,Variables,Parameters,PrologProcedure,MetadataProcedure,DataProcedure,EpilogProcedure",'PROCESS_METADATA',cancel)
            if d.get('Name')!=name: raise MetadataFailure('PROCESS_METADATA','PROCESS_IDENTITY_MISMATCH')
            ds=d.get('DataSource') or {}
            if not isinstance(ds,dict):raise MetadataFailure('PROCESS_METADATA','INVALID_DATASOURCE_RESPONSE')
            raw=dict(name=name,variables=d.get('Variables'),parameters=d.get('Parameters',[]),
                     datasource=dict(type=ds.get('Type'),cube=ds.get('dataSourceNameForServer'),view=ds.get('view')),
                     **{s:d.get(field) or '' for s,field in [('prolog','PrologProcedure'),('metadata','MetadataProcedure'),('data','DataProcedure'),('epilog','EpilogProcedure')]})
            raw['source_view']=None;raw['metadata_issues']=[];raw['view_metadata_status']='NO_STORED_VIEW_BINDING'
            if 'Variables' not in d or d['Variables'] is None:raw['metadata_issues'].append(dict(stage='PROCESS_METADATA',category='VARIABLES_MISSING'))
            if not ds:raw['metadata_issues'].append(dict(stage='PROCESS_METADATA',category='DATASOURCE_MISSING'))
            if isinstance(raw['variables'],list):
                for v in raw['variables']:
                    if isinstance(v,dict):
                        for field in ('Name','Type','Position'):
                            if v.get(field) is None:raw['metadata_issues'].append(dict(stage='PROCESS_METADATA',category='VARIABLE_FIELD_MISSING',field=field))
            validate_process(raw)
            # Only fetch the selected stored view definition, never its values.
            if ds.get('Type')=='TM1CubeView' and ds.get('dataSourceNameForServer') and ds.get('view'):
                cube,view=ds['dataSourceNameForServer'],ds['view']
                ck,vk=(quote(x.replace("'","''"),safe='') for x in (cube,view))
                try:
                    v=_read(tm1,f"/Cubes('{ck}')/Views('{vk}')?$select=Name",'VIEW_METADATA',cancel)
                    kind=v.get('@odata.type','').split('.')[-1]
                    if v.get('Name')==view:
                        raw['source_view']=dict(cube=cube,name=view,type=kind,
                            evidence=dict(method='GET',resource='Cube/Views',collected_at=bundle['collected_at']))
                        cd=_read(tm1,f"/Cubes('{ck}')?$select=Name&$expand=Dimensions($select=Name)",'CUBE_DIMENSION_ORDER',cancel)
                        if cd.get('Name')==cube and isinstance(cd.get('Dimensions'),list):
                            raw['source_view']['dimension_order']=[d.get('Name') for d in cd['Dimensions']]
                            raw['view_metadata_status']='AVAILABLE' if kind in {'NativeView','MDXView'} else 'TYPE_UNKNOWN'
                        else:raise MetadataFailure('CUBE_DIMENSION_ORDER','CUBE_IDENTITY_OR_DIMENSIONS_MISSING')
                    else:raise MetadataFailure('VIEW_METADATA','VIEW_IDENTITY_MISMATCH')
                except MetadataFailure as exc:
                    raw['view_metadata_status']='UNAVAILABLE'  # no exception URLs/secrets in logs
                    raw['metadata_issues'].append(exc.record)
            bundle['processes'].append(raw)
            if len(json.dumps(bundle,ensure_ascii=False).encode('utf-8'))>5_000_000:
                raise ValueError('Selected metadata exceeds 5 MB bundle budget; select fewer processes')
        if progress: progress(len(names),len(names))
    return bundle


def import_bundle(con,bundle,*,backup=None,cancel=None):
    """Explicit offline metadata import, atomically rejecting stale source code."""
    if bundle.get('schema')!='process-metadata-1' or not isinstance(bundle.get('processes'),list) or not 1<=len(bundle['processes'])<=20:
        raise ValueError('Invalid process metadata bundle')
    selected=[]
    if cancel:cancel()
    for p in bundle['processes']:
        validate_process(p)
        row=con.execute('SELECT prolog,metadata,data,epilog FROM processes WHERE name=?',[p['name']]).fetchone()
        if not row or source_hash(dict(zip(('prolog','metadata','data','epilog'),row)))!=source_hash(p):
            raise ValueError('Collected process source differs from snapshot; import into a matching snapshot')
        selected.append(p)
    con.execute('BEGIN TRANSACTION')
    try:
        table_exists=bool(con.execute("SELECT 1 FROM information_schema.tables WHERE table_name='process_source_metadata'").fetchone())
        prior=[]
        for p in selected:
            current=con.execute('SELECT prolog,metadata,data,epilog FROM processes WHERE name=?',[p['name']]).fetchone()
            if current is None or source_hash(dict(zip(('prolog','metadata','data','epilog'),current)))!=source_hash(p):
                raise MetadataFailure('LOCAL_VALIDATE','SOURCE_CHANGED_DURING_IMPORT')
            row=con.execute('SELECT payload FROM process_source_metadata WHERE process_name=?',[p['name']]).fetchone() if table_exists else None
            old=json.loads(row[0]) if row else {}
            if old.get('variables') and not p.get('variables'):raise MetadataFailure('LOCAL_VALIDATE','VARIABLE_METADATA_DOWNGRADE_BLOCKED')
            if old.get('source_view') and not p.get('source_view'):raise MetadataFailure('LOCAL_VALIDATE','VIEW_METADATA_DOWNGRADE_BLOCKED')
            prior.append(dict(name=p['name'],source_hash=source_hash(p),payload=row[0] if row else None))
        if backup:backup(dict(schema='process-metadata-backup-1',table_existed=table_exists,processes=prior))
        for p in selected:
            if cancel:cancel()
            save_metadata(con,p)
        con.execute('COMMIT')
    except BaseException:
        con.execute('ROLLBACK');raise
    return len(selected)
