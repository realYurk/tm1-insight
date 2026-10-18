"""Immutable recovery bundles/snapshots and narrowly scoped metadata rollback."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4


def write_json_new(path,data,*,cancel=None):
    """Publish a complete new file, never replace a user's existing file."""
    path=Path(path)
    if path.exists():raise FileExistsError('Output already exists')
    if cancel:cancel()
    fd,temp=tempfile.mkstemp(prefix='.metadata-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        if cancel:cancel()
        try:os.link(temp,path)
        except OSError:
            if os.name!='nt':raise
            # Windows rename does not replace an existing destination; FAT also works.
            os.rename(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def save_snapshot(bundle,root):
    from tm1_insight.collector import _map_process
    from tm1_insight.snapshot import SnapshotStore
    from tm1_insight.snapshot.schema import validate_snapshot_payload
    from tm1_insight.ingest.process_metadata import validate_process
    processes=[]
    for process in bundle['processes']:
        validate_process(process)
        p=dict(process)
        p['parameters']=[dict(name=v.get('name',v.get('Name')),type=v.get('type',v.get('Type')))
                         for v in (p.get('parameters') or []) if isinstance(v,dict) and v.get('name',v.get('Name'))]
        canonical=_map_process(p)
        canonical['metadata_issues']=p.get('metadata_issues',[])
        canonical['view_metadata_status']=p.get('view_metadata_status','NOT_RECORDED')
        processes.append(canonical)
    payload=dict(processes=processes)
    validate_snapshot_payload(payload)
    return SnapshotStore(root).create_snapshot('metadata-'+uuid4().hex,'source-not-runtime-verified',
        'Selected Process metadata',payload=payload,source='read_only_metadata_recovery',
        created_at=bundle.get('collected_at',''),object_counts=dict(processes=len(processes)))


def restore_backup(con,backup):
    """Explicit rollback of selected metadata only; never changes Process code."""
    from tm1_insight.store.data_row import source_hash
    from tm1_insight.store.schema import OBJECT_TABLES
    if backup.get('schema')!='process-metadata-backup-1' or not 1<=len(backup.get('processes',[]))<=20:
        raise ValueError('Invalid metadata backup')
    con.execute('BEGIN TRANSACTION')
    try:
        for p in backup['processes']:
            row=con.execute('SELECT prolog,metadata,data,epilog FROM processes WHERE name=?',[p['name']]).fetchone()
            if row is None or source_hash(dict(zip(('prolog','metadata','data','epilog'),row)))!=p['source_hash']:
                raise ValueError('Process source changed; metadata restore rejected')
        con.execute(OBJECT_TABLES['process_source_metadata'])
        for p in backup['processes']:
            if p['payload'] is None:con.execute('DELETE FROM process_source_metadata WHERE process_name=?',[p['name']])
            else:con.execute('INSERT OR REPLACE INTO process_source_metadata VALUES (?,?)',[p['name'],p['payload']])
        con.execute('COMMIT')
    except BaseException:con.execute('ROLLBACK');raise
