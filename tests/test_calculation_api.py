import hashlib
import json
import re
import shutil
import pytest
from test_datasource_api import client  # noqa: F401
from tm1_insight.config import get_settings, set_data_dir
from tm1_insight.store.db import Store


def seed(client):
    client.get('/')
    con=Store(get_settings()).connect()
    for name in ['Input','Driver','Result','}Audit']:
        con.execute('INSERT INTO cubes (name,dimension_count) VALUES (?,1)',[name])
        con.execute('INSERT INTO cube_has_dimension VALUES (?,\'Dept\',0)',[name])
    con.execute("INSERT INTO dimensions (name) VALUES ('Dept')")
    con.execute('INSERT INTO processes (name,data,parameters) VALUES (?,?,?)',['Compute',
        "base=CellGetN('Input',pDept);\nrate=CellGetN('Driver',pDept);\nv=base*rate/100;\nCellPutN(v,'Result',pDept);\nCellPutN(1,'}Audit',pDept);\nExecuteProcess(pChild);",
        json.dumps([dict(name='pDept'),dict(name='pChild')])])
    con.close()


def test_selected_ti_page_exports_and_original_source_unchanged(client):
    seed(client)
    settings=get_settings();before=hashlib.sha256(settings.db_path.read_bytes()).hexdigest()
    response=client.get('/calculation?name=Compute')
    assert response.status_code==200
    assert 'base * rate / 100' in response.text and '读取依赖' in response.text
    assert '另有 1 条 } 前缀写入点未显示' in response.text
    assert 'class="scope-bar" data-mode="business"' in response.text
    assert '当前范围：1 条写入点' in response.text
    assert '看全部（含 } 前缀）' in response.text
    assert 'UNKNOWN' in response.text
    source=re.search(r'source=([a-f0-9]{64})',response.text)[1]
    exported=client.get('/api/calculation/export',params=dict(name='Compute',source=source))
    assert exported.status_code==200 and exported.headers['cache-control']=='no-store'
    result=exported.json()
    # 导出与页面同一把尺子：屏幕上 1 条，文件里就是 1 条，差的那条要留名字
    assert len(result['writes'])==1 and result['writes'][0]['cube']=='Result'
    assert result['scope_view']==dict(scope='business',visible=1,hidden=1,cubes=['}Audit'],write_ids=[1],system_count=1)
    assert result['calls'][0]['target'] is None
    assert result['model_fingerprint']==source and not result['runtime_verified']
    full=client.get('/api/calculation/export',params=dict(name='Compute',source=source,system=1)).json()
    assert len(full['writes'])==2 and full['scope_view']['scope']=='all'
    md=client.get('/api/calculation/export',params=dict(name='Compute',source=source,format='markdown'))
    assert '静态读取依赖：Input' in md.text and 'TI_Calculation.md' in md.headers['content-disposition']
    assert '另有 1 条记录未包含在本文件内' in md.text and '`}Audit`' in md.text
    assert '静态读取依赖：Input' in client.get('/api/calculation/export',
        params=dict(name='Compute',source=source,format='markdown',system=1)).text
    assert client.get('/calculation',params=dict(name='Compute',write=1)).status_code==404
    assert client.get('/calculation',params=dict(name='Compute',write=1,system='true')).status_code==200
    assert hashlib.sha256(settings.db_path.read_bytes()).hexdigest()==before
    assert '/calculation?name=Compute' in client.get('/explorer/process/Compute').text


def test_source_and_selected_location_invalidate_on_model_change(client,tmp_path):
    seed(client)
    response=client.get('/calculation?name=Compute')
    source=re.search(r'source=([a-f0-9]{64})',response.text)[1]
    other=tmp_path/'other.duckdb';shutil.copy2(get_settings().db_path,other)
    set_data_dir(other)
    assert client.get('/calculation',params=dict(name='Compute',source=source)).status_code==409
    assert client.get('/api/calculation/export',params=dict(name='Compute',source=source)).status_code==409


@pytest.mark.parametrize('url', ['/calculation?name=Missing','/calculation?name=Compute&write=999'])
def test_missing_objects_or_write_points(client,url):
    seed(client)
    assert client.get(url).status_code==404


@pytest.mark.parametrize('url', ['/calculation?name=Compute&page=0','/calculation?name=Compute&write=-1',
    '/api/calculation/export?name=Compute','/calculation?name='+'x'*1001])
def test_invalid_requests(client,url):
    assert client.get(url).status_code==422


def test_current_process_source_change_during_analysis_rejected(client,tmp_path,monkeypatch):
    from tm1_insight.store import calculation
    seed(client)
    other=tmp_path/'changed.duckdb';shutil.copy2(get_settings().db_path,other)
    original=calculation.inspect
    def switch(*args):
        report=original(*args);set_data_dir(other);return report
    monkeypatch.setattr(calculation,'inspect',switch)
    assert client.get('/calculation?name=Compute').status_code==409


def test_paging_is_bounded_and_unknown_budget_does_not_show_fake_success(client):
    seed(client)
    con=Store(get_settings()).connect()
    con.execute('UPDATE processes SET data=? WHERE name=?',["CellPutN(1,'Result',pDept);"*120,'Compute'])
    con.close()
    response=client.get('/calculation?name=Compute&page=3')
    assert response.status_code==200 and response.text.count('aria-current="page"')>=1
    listing=re.search(r'<ul class="list calculation-list">(.*?)</ul>',response.text,re.S)[1]
    assert listing.count('<li>')==20 and 'write=100' in listing and 'write=119' in listing
    con=Store(get_settings()).connect()
    con.execute('UPDATE processes SET data=? WHERE name=?',['x'*250001,'Compute']);con.close()
    response=client.get('/calculation?name=Compute')
    assert response.status_code==200 and '未分析截断片段' in response.text
