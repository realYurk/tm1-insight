"""Rebuildable, source-bound large-dimension indexes and job lifecycle."""
import hashlib
import json
import re
import threading
import time

import pytest

from test_datasource_api import client  # noqa: F401
from test_dimension_workspace import prepare_client
from tm1_insight.config import get_settings
from tm1_insight.store import dimensions, dimension_index
from tm1_insight.store.db import Store
from tm1_insight.tasks import TaskCancelled


def wait(client, task):
    deadline = time.monotonic() + 10
    while True:
        response = client.get('/api/dimensions/index/' + task)
        assert response.status_code == 200
        state = response.json()
        if state['status'] not in {'running', 'queued'}:
            return state
        assert time.monotonic() < deadline
        time.sleep(.01)


def context(client):
    prepare_client(client)
    response = client.get('/dimensions?name=Example')
    return re.search(r'name="source" value="([a-f0-9]+)"', response.text)[1]


def test_index_matches_direct_evidence_and_preserves_source(client):
    source = context(client)
    settings = get_settings()
    before = hashlib.sha256(settings.db_path.read_bytes()).hexdigest()
    con = Store(settings).connect(read_only=True)
    try:
        meta = dimensions.metadata(con, 'Example')
        expected = {field: dimensions.records(con, 'Example', field) for field in dimensions.FIELDS}
    finally:
        con.close()
    events = []
    artifact = dimension_index.build(settings, 'Example', source, meta, lambda **event: events.append(event), lambda: True)
    try:
        for field in dimensions.FIELDS:
            assert dimension_index.records(artifact.path, field) == expected[field]
        assert dimension_index.records(artifact.path, 'edges', element='Expense')['items'][0]['weight'] == '-1'
        assert dimension_index.records(artifact.path, 'subsets', index=1)['items'][0]['expression'] == ''
        assert {event['stage_index'] for event in events} == set(range(1, 7))
        assert any(event.get('current') == 6 and event.get('total') == 6 for event in events)
    finally:
        artifact.cleanup()
    assert hashlib.sha256(settings.db_path.read_bytes()).hexdigest() == before


def test_index_cancellation_and_source_change_publish_nothing(client):
    source = context(client)
    settings = get_settings()
    con = Store(settings).connect(read_only=True)
    try: meta = dimensions.metadata(con, 'Example')
    finally: con.close()
    def cancel(**event):
        if event.get('stage_index') == 3:
            raise TaskCancelled()
    with pytest.raises(TaskCancelled):
        dimension_index.build(settings, 'Example', source, meta, cancel, lambda: True)
    assert not list((settings.user_data_root / 'cache' / 'dimension-workers').iterdir())
    with pytest.raises(ValueError):
        dimension_index.build(settings, 'Example', source, meta, lambda **event: None, lambda: False)
    assert dimension_index.cached(settings, 'Example', source) is None


def test_large_page_jobs_and_disk_cache_survive_new_manager(client, monkeypatch):
    source = context(client)
    monkeypatch.setattr(dimension_index, 'THRESHOLD', 1)
    response = client.get('/dimensions?name=Example')
    assert 'id="dimension-index"' in response.text and 'dimension-records' not in response.text
    body = {'name': 'Example', 'source': source}
    task = client.post('/api/dimensions/index', json=body)
    assert task.status_code == 202
    assert wait(client, task.json()['task_id'])['status'] == 'completed'
    assert 'dimension-records' in client.get('/dimensions?name=Example').text
    settings = get_settings()
    dimension_index.manager(settings).close()
    monkeypatch.setattr(dimension_index, '_manager', None)
    state = client.post('/api/dimensions/index', json=body).json()
    final = wait(client, state['task_id'])
    assert final['status'] == 'completed' and final['cached']
    # Missing paired index is detected and rebuilt, never an infinite reload.
    header = dimension_index.path(settings, 'Example', source)
    dimension_index.index_path(header).unlink()
    state = client.post('/api/dimensions/index', json=body).json()
    assert wait(client, state['task_id'])['status'] == 'completed'
    assert dimension_index.cached(settings, 'Example', source)


def test_job_dedup_cancel_and_retry(client, monkeypatch):
    source = context(client)
    entered, release = threading.Event(), threading.Event()
    original = dimension_index.build
    def paused(settings, name, source, meta, progress, valid):
        progress(stage='测试等待检查点', stage_index=1)
        entered.set()
        assert release.wait(5)
        return original(settings, name, source, meta, progress, valid)
    monkeypatch.setattr(dimension_index, 'build', paused)
    body = {'name': 'Example', 'source': source}
    task = client.post('/api/dimensions/index', json=body).json()['task_id']
    assert entered.wait(5)
    try:
        assert client.post('/api/dimensions/index', json=body).json()['task_id'] == task
        assert client.post(f'/api/dimensions/index/{task}/cancel').status_code == 200
    finally: release.set()
    assert wait(client, task)['status'] == 'cancelled'
    assert dimension_index.cached(get_settings(), 'Example', source) is None
    monkeypatch.setattr(dimension_index, 'build', original)
    next_task = client.post('/api/dimensions/index', json=body).json()['task_id']
    assert wait(client, next_task)['status'] == 'completed'


def test_stale_job_status_and_index_requests_rejected(client):
    source = context(client)
    assert client.post('/api/dimensions/index', json={'name': 'Missing', 'source': source}).status_code == 404
    assert client.post('/api/dimensions/index', json={'name': 'Example', 'source': 'old'}).status_code == 409
    task = client.post('/api/dimensions/index', json={'name': 'Example', 'source': source}).json()['task_id']
    assert wait(client, task)['status'] == 'completed'
    con = Store(get_settings()).connect()
    con.execute("UPDATE dimensions SET element_count=99 WHERE name='Example'")
    con.close()
    assert client.get('/api/dimensions/index/' + task).status_code == 409
    assert client.post('/api/dimensions/index/' + task + '/cancel').status_code == 409
    assert dimension_index.cached(get_settings(), 'Example', 'new-source') is None


def test_index_literals_and_duplicate_names_keep_original_positions(client):
    source = context(client)
    con = Store(get_settings()).connect()
    con.execute('UPDATE dimensions SET elements=?, element_count=3 WHERE name=?',
                [json.dumps(['Same', 'Same', '%_Last']), 'Example'])
    meta = dimensions.metadata(con, 'Example')
    con.close()
    artifact = dimension_index.build(get_settings(), 'Example', source, meta, lambda **event: None, lambda: True)
    try:
        result = dimension_index.records(artifact.path, 'elements', keyword='Same')
        assert [row['position'] for row in result['items']] == [0, 1]
        assert dimension_index.records(artifact.path, 'elements', keyword='%_')['total'] == 1
    finally: artifact.cleanup()
