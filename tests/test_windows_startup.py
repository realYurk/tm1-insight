"""Execute the real CMD launcher; mocked probe results never install another Python."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows CMD launcher')
ROOT = Path(__file__).resolve().parents[1]

# Isolated child-process shim: simulates probe return codes, not a Python 3.9 runtime.
SHIM = '''
import sys, os, json
args = sys.orig_argv
with open(os.environ['STARTUP_TEST_LOG'], 'a', encoding='utf8') as stream:
    stream.write(json.dumps({'exe': sys.executable, 'args': args}) + '\\n')
version = tuple(map(int, os.environ.get('STARTUP_TEST_VERSION', '3.13').split('.')))
mode = os.environ.get('STARTUP_TEST_MODE', '')
code = args[args.index('-c')+1] if '-c' in args else ''
rc = 0
if 'sys.version_info' in code:
    rc = 0 if version >= (3, 9) else 2
elif 'sys.version.split' in code:
    print('Python '+'.'.join(map(str, version)), file=sys.stderr if mode=='stderr' else sys.stdout)
    if mode=='broken':
        print('SIMULATED interpreter initialization failure', file=sys.stderr)
        rc = 17
elif 'import fastapi' in code:
    if mode=='dependencies':
        print('ModuleNotFoundError: simulated dependency failure', file=sys.stderr)
        rc = 1
elif 'import tm1_insight.cli' in code:
    if mode=='entry':
        print('ImportError: simulated project entry failure', file=sys.stderr)
        rc = 1
    else:
        print('[TM1 Insight] Startup checks passed.')
elif '-m' in args:
    print('SIMULATED Web command failed', file=sys.stderr)
    rc = 7
sys.stdout.flush()
sys.stderr.flush()
os._exit(rc)
'''


@pytest.fixture
def launch(tmp_path):
    # A copied venv redirector plus a NEW fixture config; never edit the project .venv.
    root=tmp_path/'中文 空格 ! launcher'
    scripts=root/'.venv/Scripts'
    scripts.mkdir(parents=True)
    shutil.copyfile(sys.executable,scripts/'python.exe')
    (root/'.venv/pyvenv.cfg').write_text('home = '+sys.base_prefix+'\ninclude-system-site-packages = true\n',encoding='utf8')
    shutil.copyfile(ROOT/'start.bat',root/'start.bat')
    shim=tmp_path/'shim';shim.mkdir()
    (shim/'sitecustomize.py').write_text(SHIM,encoding='utf8')
    log=tmp_path/'calls.jsonl'
    env=os.environ.copy()
    env.update(PYTHONPATH=str(shim),PYTHONUTF8='1',STARTUP_TEST_LOG=str(log),TM1_INSIGHT_HOME=str(tmp_path/'home'))
    env['PATH']=str(Path(sys.executable).parent)+os.pathsep+env.get('PATH','')
    def run(version='3.13',mode='',args='--check'):
        log.write_text('',encoding='utf8')
        selected=env.copy();selected.update(STARTUP_TEST_VERSION=version,STARTUP_TEST_MODE=mode)
        completed=subprocess.run(['cmd.exe','/d','/v:on','/c','start.bat '+args],cwd=root,
            env=selected,input=b'\n',capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        records=[json.loads(s) for s in log.read_text(encoding='utf8').splitlines()]
        output=(completed.stdout+completed.stderr).decode('utf8',errors='replace')
        return completed.returncode,output,records
    return root,run


@pytest.mark.parametrize('version',['3.9','3.13'])
def test_supported_exit_code_probe_with_chinese_spaces_and_delayed_expansion(launch,version):
    root,run=launch
    rc,output,records=run(version)
    assert rc==0 and 'Startup checks passed.' in output
    assert all(Path(r['exe'])==root/'.venv/Scripts/python.exe' for r in records)
    assert not any('--version' in r['args'] for r in records)


def test_stderr_version_output_is_not_used_for_parsing(launch):
    _,run=launch
    rc,output,records=run(mode='stderr')
    assert rc==0 and 'Python 3.13' in output


def test_old_version_stops_before_dependency_import(launch):
    _,run=launch
    rc,output,records=run('3.8')
    assert rc==2 and 'Python 3.9 or newer is required' in output
    assert not any('import fastapi' in ' '.join(r['args']) for r in records)


def test_present_but_unrunnable_venv_never_falls_back(launch):
    root,run=launch
    rc,output,records=run(mode='broken')
    assert rc==1 and 'Selected Python could not run' in output
    assert 'SIMULATED interpreter initialization failure' in output
    assert len(records)==1 and Path(records[0]['exe'])==root/'.venv/Scripts/python.exe'


def test_non_executable_venv_file_stops_without_path_fallback(launch):
    root,run=launch
    (root/'.venv/Scripts/python.exe').write_bytes(b'Not a Windows executable')
    rc,output,records=run()
    assert rc==1 and 'Selected Python could not run' in output
    assert records==[]


def test_missing_venv_uses_available_system_python(launch):
    root,run=launch
    (root/'.venv/Scripts/python.exe').unlink()  # Delete only this test's copied redirector.
    rc,output,records=run()
    assert rc==0 and records,output
    assert all(Path(r['exe'])!=root/'.venv/Scripts/python.exe' for r in records)


@pytest.mark.parametrize('mode,rc,message',[('dependencies',3,'Required dependencies'),('entry',4,'Project entry import')])
def test_failures_show_exception_and_never_run_pip(launch,mode,rc,message):
    _,run=launch
    actual,output,records=run(mode=mode)
    assert actual==rc and message in output and 'simulated' in output
    assert not any('pip' in r['args'] for r in records)


def test_real_web_failure_exit_code_is_preserved(launch):
    _,run=launch
    rc,output,records=run(args='--no-browser')
    assert rc==7 and 'SIMULATED Web command failed' in output
    assert records[-1]['args'][-1]=='--no-browser'


def test_current_project_venv_passes_actual_preflight(tmp_path):
    env=os.environ.copy();env.update(TM1_INSIGHT_HOME=str(tmp_path/'home'),PYTHONUTF8='1')
    result=subprocess.run(['cmd.exe','/d','/c','start.bat --check'],cwd=ROOT,env=env,
        capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    output=(result.stdout+result.stderr).decode('utf8',errors='replace')
    assert result.returncode==0,output
    assert 'Startup checks passed.' in output
    assert str(ROOT/'.venv/Scripts/python.exe') in output


def test_real_start_avoids_old_http_service_and_owns_new_listener(tmp_path,monkeypatch):
    import http.server
    import re
    import socket
    import threading
    import time
    import urllib.request

    # The suite forbids outside connections. Permit only this test's loopback HTTP.
    def loopback(address,timeout=5,source_address=None,**kwargs):
        assert address[0]=='127.0.0.1'
        s=socket.socket();s.settimeout(timeout)
        try:s.connect(address)
        except BaseException:s.close();raise
        return s
    monkeypatch.setattr(socket,'create_connection',loopback)
    class Old(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'{"old_service":true}')
        def log_message(self,*args):pass
    old=http.server.ThreadingHTTPServer(('127.0.0.1',0),Old)
    old_port=old.server_address[1]
    threading.Thread(target=old.serve_forever,daemon=True).start()
    env=os.environ.copy()
    env.pop('DATABASE_FILE',None)
    env.update(TM1_INSIGHT_HOME=str(tmp_path/'home'),DATA_DIR=str(tmp_path/'data'),
               WEB_HOST='127.0.0.1',WEB_PORT=str(old_port),PYTHONUTF8='1',
               HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9',NO_PROXY='127.0.0.1')
    log=tmp_path/'startup.log'
    process=None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with log.open('wb') as stream:
            process=subprocess.Popen(['cmd.exe','/d','/c','start.bat --no-browser'],cwd=ROOT,env=env,
                stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+30;port=pid=None
        while time.monotonic()<deadline:
            text=log.read_text(encoding='utf8',errors='replace')
            ports=re.findall(r'http://127\.0\.0\.1:(\d+)',text)
            pids=re.findall(r'Started server process \[(\d+)\]',text)
            if ports and pids:
                port,pid=int(ports[-1]),int(pids[-1]);break
            if process.poll() is not None:pytest.fail(text)
            time.sleep(.1)
        assert port and pid,log.read_text(encoding='utf8',errors='replace')
        assert port!=old_port and pid!=os.getpid()
        def read(path):
            with opener.open('http://127.0.0.1:'+str(port)+path,timeout=8) as response:return response.read()
        status=None
        while time.monotonic()<deadline:
            try:
                status=json.loads(read('/api/status'))
                break
            except OSError:
                time.sleep(.1)
        assert status is not None,log.read_text(encoding='utf8',errors='replace')
        assert 'tables' in status and 'old_service' not in status
        assert str(tmp_path) in status['db_path']
        assert b'architecture' in read('/architecture')
        source=json.loads(read('/api/datasource/status'))
        assert source['ready'] and source['type']=='demo'
        command=f"Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort {port} -State Listen | Select-Object -ExpandProperty OwningProcess"
        powershell=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
        owner=subprocess.check_output([powershell,'-NoProfile','-Command',command],text=True,timeout=15)
        assert int(owner.strip())==pid
        # Confirm ownership, not just that some service answered HTTP 200.
        chain=[];current=pid
        for _ in range(5):
            if current==process.pid:break
            parent=subprocess.check_output([powershell,'-NoProfile','-Command',
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={current}').ParentProcessId"],text=True,timeout=10)
            current=int(parent.strip());chain.append(current)
        assert process.pid in chain
        with opener.open('http://127.0.0.1:'+str(old_port),timeout=5) as response:
            assert json.load(response)['old_service'] is True
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10)
            process.wait(timeout=10)
        old.shutdown();old.server_close()
