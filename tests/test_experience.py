import time
import pytest
from test_datasource_api import client
from tm1_insight.config import get_settings
from tm1_insight.learning import experience,pages
from tm1_insight.api.knowledge_tasks import manager


def learning(client):
    task=client.post('/api/learning/tasks',json={'query':'*'}).json()['task_id']
    deadline=time.monotonic()+10
    while True:
        state=client.get('/api/learning/tasks/'+task).json()
        if state['status'] not in {'queued','running'}:break
        assert time.monotonic()<deadline
        time.sleep(.01)
    assert state['status']=='completed',state
    return task


def test_learning_index_serves_pages_without_loading_whole_report(client,monkeypatch):
    task=learning(client)
    monkeypatch.setattr(manager(),'result',lambda *args,**kwargs:pytest.fail('Decoded full report for a page'))
    result=client.get(f'/api/learning/tasks/{task}/result?section=processes&limit=1').json()
    assert result['total']==3 and len(result['items'])==1
    assert result['coverage']['runtime_verified_processes']==0
    contract=client.get(f'/api/learning/tasks/{task}/contract',params={'process':'Load_Sales'}).json()
    assert not contract['equivalence_verified']
    assert contract['structure']['references'][0]['target']=='Sales'
    assert client.get(f'/api/learning/tasks/{task}/result?section=dimensions').json()['total']==6


def test_review_requires_evidence_notes_versions_and_isolates_models(client,tmp_path):
    from test_datasource import _make_real_db
    task=learning(client)
    body={'task_id':task,'process':'Load_Sales'}
    card=client.post('/api/experience/cards',json=body).json()
    assert client.post('/api/experience/cards',json=body).json()['id']==card['id']
    assert card['status']=='candidate'
    patch={'expected_revision':1,'title':'Synthetic allocation','problem':'','applicability':'','limitations':'',
           'validation_notes':'','reviewer':'','change_reason':'Review','method':'proportion','status':'validated'}
    assert client.post('/api/experience/cards/'+card['id'],json=patch).status_code==400
    patch.update(problem='Allocate a synthetic pool',applicability='One period',limitations='No negative weights',reviewer='Fixture reviewer',validation_notes='100 split by 10:30 gives 25:75; zero driver rejected')
    result=client.post('/api/experience/cards/'+card['id'],json=patch)
    assert result.status_code==200,result.text
    assert result.json()['revision']==2
    assert client.post('/api/experience/cards/'+card['id'],json=patch).status_code==409
    assert len(client.get('/api/experience/cards/'+card['id']+'/history').json())==2
    exported=client.get('/api/experience/export').json()
    assert len(exported['cards'])==1 and len(exported['history'])==2
    other=_make_real_db(tmp_path/'different-project')
    client.post('/api/datasource/use',json={'source':'local','path':str(other)})
    assert client.get('/api/experience/cards').json()['total']==0
    assert client.get('/api/experience/cards/'+card['id']).status_code==404
    assert client.get('/api/experience/export').json()['cards']==[]


def test_changed_model_marks_old_evidence_and_cannot_confirm_it(client):
    from tm1_insight.store.db import Store
    task=learning(client)
    card=client.post('/api/experience/cards',json={'task_id':task,'process':'Load_Sales'}).json()
    con=Store(get_settings()).connect();con.execute("UPDATE processes SET epilog='# synthetic change'");con.close()
    assert not client.get('/api/experience/cards/'+card['id']).json()['source_current']
    patch={'expected_revision':1,'title':'Test','problem':'P','applicability':'A','limitations':'L',
           'validation_notes':'Test record','reviewer':'R','change_reason':'Review','method':'proportion','status':'reviewed'}
    assert client.post('/api/experience/cards/'+card['id'],json=patch).status_code==409


def test_comparison_explains_hard_constraint_and_rejects_coerced_booleans(client):
    client.get('/')
    body={'frequency':'scheduled','persist_results':True,'multi_stage':True,'varying_rules':True,'audit':True,'concurrent':False}
    result=client.post('/api/experience/compare',json=body).json()
    assert next(c for c in result['choices'] if c['id']=='rule')['status']=='excluded_as_standalone'
    assert all(not c['reviewed_examples'] for c in result['choices'])
    assert client.post('/api/experience/compare',json={**body,'audit':'yes'}).status_code==422


def personal_card(client):
    from tm1_insight.api.knowledge_tasks import fingerprint
    client.get('/')
    return experience.create(get_settings(),fingerprint(),dict(process='Synthetic.Personal',source_hash='a'*64,
        patterns=[],reads=[],writes=[],calls=[]))


def test_personal_notes_need_no_reviewer_but_validation_requires_notes(client):
    import hashlib
    card=personal_card(client)
    source_before=hashlib.sha256(get_settings().db_path.read_bytes()).hexdigest()
    body=dict(expected_revision=1,title='My method',problem='Synthetic calculation',applicability='One period',
        limitations='Unknown external inputs',change_reason='Organize my note',method='custom',status='reviewed')
    result=client.post('/api/experience/cards/'+card['id'],json=body)
    assert result.status_code==200,result.text
    assert result.json()['reviewer']=='' and result.json()['revision']==2
    body.update(expected_revision=2,status='validated')
    assert client.post('/api/experience/cards/'+card['id'],json=body).status_code==400
    assert client.get('/api/experience/cards/'+card['id']).json()['revision']==2
    body['validation_notes']='Synthetic sample: expected 10, actual 10; recorded locally'
    result=client.post('/api/experience/cards/'+card['id'],json=body)
    assert result.status_code==200 and result.json()['validation_origin']=='human_record_only'
    assert len(client.get('/api/experience/cards/'+card['id']+'/history').json())==3
    assert hashlib.sha256(get_settings().db_path.read_bytes()).hexdigest()==source_before


def test_omitted_legacy_fields_and_history_survive_personal_note_edit(client):
    card=personal_card(client)
    body=dict(expected_revision=1,title='Old note',problem='P',applicability='A',limitations='L',
        validation_notes='Existing local test record',reviewer='Legacy author',change_reason='Initial note',
        method='custom',status='reviewed')
    assert client.post('/api/experience/cards/'+card['id'],json=body).status_code==200
    edit=dict(expected_revision=2,title='Updated personal note',change_reason='Clarify title',status='reviewed')
    result=client.post('/api/experience/cards/'+card['id'],json=edit)
    assert result.status_code==200,result.text
    assert result.json()['reviewer']=='Legacy author'
    assert result.json()['validation_notes']=='Existing local test record'
    records=client.get('/api/experience/cards/'+card['id']+'/history').json()
    assert records[1]['title']=='Old note' and records[1]['reviewer']=='Legacy author'
