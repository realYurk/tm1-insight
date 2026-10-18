"""GET-only recovery, classified failures, persistence and rollback contracts."""
import json
import http.client
import ssl
from types import SimpleNamespace
import requests
import pytest
from tm1_insight.tm1.metadata_diagnostics import failure,MetadataFailure,diagnose
from tm1_insight.ingest.process_metadata import collect,import_bundle
from tm1_insight.ingest.metadata_persistence import write_json_new,save_snapshot,restore_backup
from tm1_insight.config import Settings
from test_data_row_lineage import con,setup  # noqa: F401


@pytest.mark.parametrize('exc,category',[
    (requests.exceptions.ProxyError('http://name:secret@proxy'),'PROXY_ERROR'),
    (ssl.SSLCertVerificationError(1,'secret cert detail'),'TLS_CERTIFICATE_ERROR'),
    (requests.exceptions.SSLError('secret TLS detail'),'TLS_ERROR'),
    (requests.exceptions.Timeout('secret endpoint'),'TIMEOUT'),
    (http.client.RemoteDisconnected('secret endpoint'),'REMOTE_DISCONNECTED'),
    (ValueError('secret JSON body'),'RESPONSE_OR_CONFIG_INVALID'),
])
def test_safe_failure_categories_never_contain_sensitive_exception_text(exc,category):
    record=failure('PROCESS_METADATA',exc)
    assert record['category']==category and 'secret' not in json.dumps(record)


@pytest.mark.parametrize('code,category',[(401,'AUTHENTICATION_FAILED'),(403,'PERMISSION_DENIED'),(404,'NOT_FOUND'),(400,'REQUEST_OR_API_INCOMPATIBLE'),(407,'PROXY_AUTHENTICATION_REQUIRED')])
def test_http_failure_classification(code,category):
    r=requests.Response();r.status_code=code
    assert failure('PROCESS_METADATA',requests.HTTPError('secret',response=r))['category']==category


def test_readonly_tm1py_session_verifies_tls_preserves_proxy_rules_and_never_logs_out(monkeypatch):
    import tm1_insight.tm1.client as module
    recorded=[]
    def service(**kwargs):
        recorded.append(kwargs)
        return SimpleNamespace(_rest=SimpleNamespace(_s=SimpleNamespace(close=lambda:recorded.append('LOCAL_CLOSE'))))
    monkeypatch.setattr(module,'TM1Service',service)
    s=Settings(tm1_address='synthetic',tm1_port=12345,tm1_ssl=True,tm1_user='user',tm1_password='secret')
    with module.TM1Client(s,timeout=7).connect_metadata():pass
    options=recorded[0]
    assert options['verify'] is True and options['timeout']==7 and options['async_requests_mode'] is False
    assert options['cancel_at_timeout'] is False and options['remote_disconnect_max_retries']==0
    assert options['re_connect_on_remote_disconnect'] is False and 'proxies' not in options
    assert recorded[-1]=='LOCAL_CLOSE'


class Client:
    def __init__(self,read,fail=None):self.read=read;self.fail=fail;self.closed=False
    def connect(self):return self
    def __enter__(self):
        if self.fail:raise self.fail
        return SimpleNamespace(_rest=SimpleNamespace(GET=self.read))
    def __exit__(self,*args):self.closed=True


def process_response(p):
    return dict(Name=p['name'],Variables=p['variables'],DataSource=dict(Type='TM1CubeView',dataSourceNameForServer='Cube_A',view='Input',password='secret'),
        Parameters=[],PrologProcedure=p['prolog'],MetadataProcedure=p['metadata'],DataProcedure=p['data'],EpilogProcedure=p['epilog'])


def read_client(p,requested):
    def read(url):
        requested.append(('GET',url))
        if url.startswith('/Processes'):d=process_response(p)
        elif '/Views(' in url:d={'Name':'Input','@odata.type':'#ibm.tm1.api.v1.NativeView'}
        else:d={'Name':'Cube_A','Dimensions':[{'Name':'Scenario'},{'Name':'Product'}]}
        return SimpleNamespace(json=lambda:d)
    return Client(read)


def test_successful_single_process_snapshot_duckdb_binding_idempotence_and_rollback(con,tmp_path):
    from tm1_insight.store.calculation import inspect
    from tm1_insight.snapshot import SnapshotStore
    p=setup(con);requested=[]
    old=con.execute("SELECT prolog,metadata,data,epilog FROM processes WHERE name='Load'").fetchone()
    bundle=collect(read_client(p,requested),['Load'])
    assert len(requested)==3 and all(method=='GET' and 'Execute' not in url for method,url in requested)
    assert 'secret' not in json.dumps(bundle)
    assert type(bundle['processes'][0]['variables'][0]['Position']) is int
    assert bundle['processes'][0]['view_metadata_status']=='AVAILABLE'
    out=tmp_path/'bundle.json';write_json_new(out,bundle)
    record=save_snapshot(bundle,tmp_path/'snapshots');_,saved=SnapshotStore(tmp_path/'snapshots').load_snapshot(record.snapshot_id)
    assert saved['processes'][0]['variables']==p['variables']
    backup=[];assert import_bundle(con,bundle,backup=backup.append)==1
    first=con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]
    assert import_bundle(con,bundle)==1
    assert con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]==first
    assert con.execute("SELECT prolog,metadata,data,epilog FROM processes WHERE name='Load'").fetchone()==old
    assert inspect(con,'Load')['writes'][0]['data_row_binding_status']=='STATIC_CELL_VALUE_DEPENDENCY'
    restore_backup(con,backup[0])
    assert inspect(con,'Load')['writes'][0]['data_row_binding_status']=='STATIC_CELL_VALUE_DEPENDENCY'


def test_disconnect_at_start_and_process_request_have_distinct_safe_stages():
    def read(url):raise http.client.RemoteDisconnected('secret url')
    for client,stage in [(Client(read,fail=http.client.RemoteDisconnected('secret')),'SESSION_START'),(Client(read),'PROCESS_METADATA')]:
        with pytest.raises(MetadataFailure) as err:collect(client,['Missing'])
        assert err.value.record['stage']==stage and err.value.record['category']=='REMOTE_DISCONNECTED'
        assert 'secret' not in str(err.value)


def test_missing_variables_keeps_explicit_status_and_rejects_local_downgrade(con):
    p=setup(con);d=process_response(p);d.pop('Variables')
    bundle=collect(Client(lambda u:SimpleNamespace(json=lambda:d if u.startswith('/Processes') else {'Name':'Input'})),['Load'])
    assert bundle['processes'][0]['variables'] is None
    assert any(i['category']=='VARIABLES_MISSING' for i in bundle['processes'][0]['metadata_issues'])
    prior=con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]
    with pytest.raises(MetadataFailure,match='DOWNGRADE'):import_bundle(con,bundle)
    assert con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]==prior


def test_view_permission_failure_keeps_process_variables_and_specific_reason(con):
    p=setup(con)
    def read(url):
        if url.startswith('/Processes'):return SimpleNamespace(json=lambda:process_response(p))
        r=requests.Response();r.status_code=403;raise requests.HTTPError('secret',response=r)
    b=collect(Client(read),['Load'])['processes'][0]
    assert b['variables']==p['variables'] and b['source_view'] is None
    assert b['metadata_issues'][0]['category']=='PERMISSION_DENIED' and b['metadata_issues'][0]['stage']=='VIEW_METADATA'


def test_wrong_variable_position_type_and_non_json_response_rejected(con):
    p=setup(con);d=process_response(p);d['Variables'][0]['Position']='1'
    with pytest.raises(MetadataFailure,match='POSITION_TYPE'):collect(Client(lambda u:SimpleNamespace(json=lambda:d)),['Load'])
    def read(url):return SimpleNamespace(json=lambda:(_ for _ in ()).throw(ValueError('secret HTML')))
    with pytest.raises(MetadataFailure) as exc:collect(Client(read),['Load'])
    assert exc.value.record['stage']=='PROCESS_METADATA' and 'secret' not in str(exc.value)


def test_cancellation_during_view_collection_and_local_import_preserve_old_data(con):
    p=setup(con);requested=[];checks=[]
    def cancel():
        checks.append(1)
        if len(checks)==5:raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):collect(read_client(p,requested),['Load'],cancel=cancel)
    assert len(requested)<=2
    bundle=collect(read_client(p,[]),['Load']);prior=con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]
    def cancel_import():raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):import_bundle(con,bundle,cancel=cancel_import)
    assert con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]==prior


def test_failed_write_and_transaction_do_not_corrupt_existing_data(con,tmp_path,monkeypatch):
    p=setup(con);b=collect(read_client(p,[]),['Load'])
    target=tmp_path/'out.json';target.write_text('original')
    with pytest.raises(FileExistsError):write_json_new(target,b)
    assert target.read_text()=='original'
    import tm1_insight.ingest.metadata_persistence as persist
    def fail_link(*args):raise OSError('disk error')
    monkeypatch.setattr(persist.os,'link',fail_link)
    if persist.os.name=='nt':monkeypatch.setattr(persist.os,'rename',fail_link)
    with pytest.raises(OSError):write_json_new(tmp_path/'new.json',b)
    assert not (tmp_path/'new.json').exists() and not list(tmp_path.glob('*.tmp'))
    prior=con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]
    def backup_fail(data):raise OSError('disk full')
    with pytest.raises(OSError):import_bundle(con,b,backup=backup_fail)
    assert con.execute('SELECT payload FROM process_source_metadata').fetchone()[0]==prior


def test_diagnostics_preserve_proxy_route_no_auth_redirects_or_certificate_bypass(monkeypatch):
    import tm1_insight.tm1.metadata_diagnostics as module
    events=[]
    class Context:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    class Response(Context):
        status_code=401
    class Session(Context):
        def get(self,url,**options):events.append((options,self.auth));return Response()
    monkeypatch.setattr(module.requests,'Session',Session)
    monkeypatch.setattr(module.socket,'create_connection',lambda *a,**kw:Context())
    s=Settings(tm1_address='synthetic',tm1_port=12345)
    r=diagnose(s,probe_tls=False)
    assert r['stages'][-1]['category']=='AUTHENTICATION_REQUIRED' and not r['credentials_sent']
    options,auth=events[0]
    assert options['verify'] is True and options['allow_redirects'] is False and 'proxies' not in options
    assert isinstance(auth,module.NoAuth)


@pytest.mark.parametrize('status,category',[(404,'NOT_FOUND'),(401,'AUTHENTICATION_FAILED'),(403,'PERMISSION_DENIED')])
def test_process_endpoint_missing_authentication_or_permission_error_is_not_connection_failure(status,category):
    def read(url):
        response=requests.Response();response.status_code=status
        raise requests.HTTPError('secret body',response=response)
    with pytest.raises(MetadataFailure) as exc:collect(Client(read),['Missing'])
    assert exc.value.record['stage']=='PROCESS_METADATA' and exc.value.record['category']==category


def test_failure_after_first_metadata_write_rolls_back_entire_selection(con,monkeypatch):
    import copy
    import tm1_insight.ingest.process_metadata as module
    p=setup(con);bundle=collect(read_client(p,[]),['Load'])
    second=copy.deepcopy(bundle['processes'][0]);second['name']='Other';bundle['processes'].append(second)
    con.execute("INSERT INTO processes SELECT 'Other',prolog,metadata,data,epilog,parameters,datasource,code_length FROM processes WHERE name='Load'")
    before=con.execute('SELECT * FROM process_source_metadata ORDER BY process_name').fetchall()
    original=module.save_metadata;count=[]
    def write(con,p):
        count.append(1)
        if len(count)==2:raise OSError('interrupted disk write')
        return original(con,p)
    monkeypatch.setattr(module,'save_metadata',write)
    with pytest.raises(OSError):import_bundle(con,bundle)
    assert con.execute('SELECT * FROM process_source_metadata ORDER BY process_name').fetchall()==before


def test_restore_removes_new_metadata_without_touching_source(con):
    p=setup(con);b=collect(read_client(p,[]),['Load'])
    con.execute('DELETE FROM process_source_metadata')
    before=con.execute('SELECT * FROM processes').fetchall();backup=[]
    import_bundle(con,b,backup=backup.append)
    assert con.execute('SELECT count(*) FROM process_source_metadata').fetchone()[0]==1
    restore_backup(con,backup[0])
    assert con.execute('SELECT count(*) FROM process_source_metadata').fetchone()[0]==0
    assert con.execute('SELECT * FROM processes').fetchall()==before


def test_cli_collect_snapshot_import_backup_and_restore_are_executable(con,tmp_path,monkeypatch):
    from typer.testing import CliRunner
    from tm1_insight.cli import app
    import tm1_insight.tm1.client as client_module
    from tm1_insight.store.schema import ALL_TABLES
    import duckdb
    p=setup(con);requested=[]
    monkeypatch.setattr(client_module,'TM1Client',lambda *args,**kwargs:read_client(p,requested))
    out=tmp_path/'bundle.json';runner=CliRunner()
    assert runner.invoke(app,['collect-process-metadata','--process','Load','--output',str(out)]).exit_code==0
    assert len(list((tmp_path/'metadata-snapshots').iterdir()))==1
    target=tmp_path/'copy.duckdb';c=duckdb.connect(str(target))
    for ddl in ALL_TABLES.values():c.execute(ddl)
    for table in ('processes',):
        rows=con.execute('SELECT * FROM '+table).fetchall()
        c.executemany('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in rows[0])+')',rows)
    c.close()
    result=runner.invoke(app,['import-process-metadata','--bundle',str(out),'--database',str(target)])
    assert result.exit_code==0,result.output
    backup=list(tmp_path.glob('copy.duckdb.metadata-backup-*.json'))
    assert len(backup)==1
    assert runner.invoke(app,['restore-process-metadata','--backup',str(backup[0]),'--database',str(target)]).exit_code==0
    with duckdb.connect(str(target),read_only=True) as c:assert c.execute('SELECT count(*) FROM process_source_metadata').fetchone()[0]==0


def test_actual_tm1py_transport_sends_only_get_including_session_lifecycle(con,monkeypatch):
    from tm1_insight.tm1.client import TM1Client
    p=setup(con);events=[]
    def send(session,request,**kwargs):
        events.append((request.method,kwargs.get('verify')))
        assert request.method=='GET'
        response=requests.Response();response.status_code=200;response.request=request
        if 'ProductVersion' in request.url:response._content=b'11.8.00000.1'
        elif '/Processes(' in request.url:response._content=json.dumps(process_response(p)).encode()
        elif '/Views(' in request.url:response._content=json.dumps({'Name':'Input','@odata.type':'#ibm.tm1.api.v1.NativeView'}).encode()
        else:response._content=json.dumps({'Name':'Cube_A','Dimensions':[{'Name':'Scenario'},{'Name':'Product'}]}).encode()
        return response
    monkeypatch.setattr(requests.Session,'send',send)
    settings=Settings(tm1_address='synthetic.invalid',tm1_port=12345,tm1_ssl=True,tm1_user='synthetic',tm1_password='synthetic')
    b=collect(TM1Client(settings,timeout=2),['Load'])
    assert len(events)==4 and all(method=='GET' and verify is True for method,verify in events)
    assert b['processes'][0]['variables']==p['variables']


def test_ca_bundle_cannot_be_used_to_disable_certificate_verification(monkeypatch):
    from tm1_insight.tm1.metadata_diagnostics import verify_setting
    monkeypatch.setenv('REQUESTS_CA_BUNDLE','False')
    with pytest.raises(MetadataFailure,match='TRUSTED_CA_FILE_REQUIRED'):verify_setting(Settings())
