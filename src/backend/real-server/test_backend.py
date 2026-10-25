import json, re
import pytest
from fastapi.testclient import TestClient
from app import create_app
from core import Extraction,MediaTranscript,AskSelection,Task

T='2026-10-25T10:00:00-07:00';E='2026-10-25T10:01:00-07:00'
class Provider:
    fail=False; bad=False; action='todo'; uncertain=False; due='2026-10-26T17:00:00-07:00'
    async def json(self,prompt,schema,media=None):
        if self.fail:raise RuntimeError('secret_api_key_should_not_leak')
        if schema is MediaTranscript:return MediaTranscript(transcript=[dict(speaker='Speaker 1',text='I will deliver the report tomorrow.',start_ts=T,end_ts=E)])
        data=json.loads(prompt.split('Data: ')[1] if 'Data: ' in prompt else prompt.split('Records: ')[1])
        if schema is AskSelection:return AskSelection(evidence_ids=['invented'] if self.bad else [data[0]['evidence_id']])
        return Extraction(summary='Report commitment.',tasks=[Task(promise='Deliver report',quote='invented' if self.bad else data[0]['text'],evidence_id=data[0]['evidence_id'],owner_speaker=data[0]['speaker'],action_type=self.action,due_at=self.due,uncertain=self.uncertain,draft='Please review the report.')])
@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('SCENE_API_TOKEN','test-token')
    p=Provider();a=create_app(str(tmp_path/'db.sqlite'),p)
    c=TestClient(a,headers={'Authorization':'Bearer test-token'})
    yield c,p,a
    a.state.store.db.close()
def setup(c):
    person=c.post('/api/v1/people',data={'name':'Nayan'}).json()
    s=c.post('/api/v1/sessions',json={'wearer_person_id':person['id']}).json()
    return s,person
def ingest(c,s):
    r=c.post('/api/v1/transcripts',json={'session_id':s['id'],'start_ts':T,'end_ts':E,'transcript':[{'speaker':'Speaker 1','text':'I will deliver the report tomorrow.','start_ts':T,'end_ts':E}]})
    assert r.status_code==202,r.text
    return c.get('/api/v1/chunks/'+r.json()['chunk_id']).json()
def follow(c,s,p=None):
    ch=ingest(c,s)
    if p:
        assert c.post('/api/v1/sessions/'+s['id']+'/speakers',json={'chunk_id':ch['chunk_id'],'speaker':'Speaker 1','person_id':p['id']}).status_code==200
    run=c.post('/api/v1/followups/generate',json={'session_id':s['id']}).json()
    return c.get('/api/v1/followups',params={'run_id':run['run_id']}).json()['followups'][-1]
def test_auth(env):
    c,_,_=env
    assert c.get('/api/v1/status',headers={'Authorization':'Bearer nope'}).status_code==401
    assert c.get('/').status_code==200
    assert c.get('/openapi.json',headers={'Authorization':''}).status_code==401

def test_disabled_auth_rejects_remote(tmp_path,monkeypatch):
    monkeypatch.delenv('SCENE_API_TOKEN',raising=False);monkeypatch.setenv('SCENE_ALLOW_LOCAL_NO_AUTH','1')
    a=create_app(str(tmp_path/'d'),Provider())
    assert TestClient(a,client=('203.0.113.1',123)).get('/api/v1/status').status_code==401
    assert TestClient(a,client=('127.0.0.1',123)).get('/api/v1/status').status_code==200
    monkeypatch.delenv('SCENE_ALLOW_LOCAL_NO_AUTH')
    assert TestClient(a,client=('127.0.0.1',123)).get('/api/v1/status').status_code==401

def test_lifecycle_persistence(env,tmp_path):
    c,p,a=env;s,person=setup(c);ch=ingest(c,s)
    assert ch['status']=='indexed'
    detail=c.get('/api/v1/scenes/'+ch['scene_id']).json();assert detail['verified'] is False
    assert c.get('/api/v1/scenes/today',params={'session_id':s['id']}).json()['scenes'][0]['id']==ch['scene_id']
    assert c.post('/api/v1/pin',json={'scene_id':ch['scene_id']}).json()['pinned']
    assert c.get('/api/v1/facts').json()['facts']
    assert c.post('/api/v1/sessions/'+s['id']+'/end').json()['scene_count']==1
    assert c.get('/api/v1/status').json()['recording'] is False
    b=create_app(str(tmp_path/'db.sqlite'),p)
    assert len(b.state.store.all('scene'))==1;b.state.store.db.close()

def test_provider_failure_sanitized(env):
    c,p,_=env;s,_=setup(c);p.fail=True;ch=ingest(c,s)
    assert ch['status']=='failed';assert 'secret' not in json.dumps(ch)

def test_source_grounded_ask(env):
    c,p,_=env;s,_=setup(c);ingest(c,s)
    r=c.post('/api/v1/ask',json={'query':'What report?','session_id':s['id']})
    assert r.status_code==200;assert r.json()['receipts'][0]['physical_truth_verified'] is False
    p.bad=True;assert c.post('/api/v1/ask',json={'query':'report'}).status_code==502

def test_ask_empty_and_isolation(env):
    c,_,_=env;s,_=setup(c);ingest(c,s);s2,_=setup(c)
    r=c.post('/api/v1/ask',json={'query':'report','session_id':s2['id']}).json();assert r['receipts']==[]

def test_approval_idempotent_and_persisted(env):
    c,_,_=env;s,p=setup(c);f=follow(c,s,p)
    r=c.post('/api/v1/followups/'+f['id']+'/approve',json={'reviewed':True});assert r.status_code==200,r.text
    assert r.json()['execution_status']=='todo_created'
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={}).json()['todo_id']==r.json()['todo_id']
    assert len(c.get('/api/v1/todos').json()['todos'])==1

def test_unknown_owner_blocks(env):
    c,_,_=env;s,p=setup(c);f=follow(c,s)
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={}).status_code==409
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={'owner':'Nayan','reviewed':True}).status_code==200

def test_other_owner_blocks(env):
    c,_,_=env;s,p=setup(c);other=c.post('/api/v1/people',data={'name':'Srijan'}).json();f=follow(c,s,other)
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={'reviewed':True}).status_code==409

def test_bad_quote_blocks(env):
    c,p,_=env;s,person=setup(c);p.bad=True;f=follow(c,s,person)
    assert not f['quote_verified'];assert c.post('/api/v1/followups/'+f['id']+'/approve',json={'reviewed':True}).status_code==409

def test_mapping_session_isolation(env):
    c,_,_=env;s,p=setup(c);ch=ingest(c,s);other,_=setup(c)
    assert c.post('/api/v1/sessions/'+other['id']+'/speakers',json={'chunk_id':ch['chunk_id'],'speaker':'Speaker 1','person_id':p['id']}).status_code==409
    c.post('/api/v1/sessions/'+s['id']+'/speakers',json={'chunk_id':ch['chunk_id'],'speaker':'Speaker 1','person_id':p['id']})
    nextchunk=ingest(c,s);assert c.get('/api/v1/scenes/'+nextchunk['scene_id']).json()['people']==[]

@pytest.mark.parametrize('action,expected',[('email','compose_url_ready'),('calendar','calendar_url_ready')])
def test_compose_not_send(env,action,expected):
    c,provider,_=env;s,p=setup(c);provider.action=action;f=follow(c,s,p)
    body={'recipient':'person@example.com','reviewed':True} if action=='email' else {'reviewed':True}
    if action=='email':assert c.post('/api/v1/followups/'+f['id']+'/approve',json={}).status_code==409
    r=c.post('/api/v1/followups/'+f['id']+'/approve',json=body)
    assert r.status_code==200,r.text
    assert r.json()['execution_status']==expected;assert r.json()['action_url'].startswith('https://')

def test_missing_date_review_and_calendar(env):
    c,pr,_=env;s,p=setup(c);pr.due=None;f=follow(c,s,p)
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={}).status_code==409
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={'reviewed':True}).status_code==200
    pr.action='calendar';f=follow(c,s,p)
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={'reviewed':True}).status_code==409

def test_dismiss_and_purge(env):
    c,_,_=env;s,p=setup(c);f=follow(c,s,p)
    assert c.post('/api/v1/followups/'+f['id']+'/dismiss').json()['status']=='dismissed'
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={}).status_code==409
    assert c.delete('/api/v1/data').json()['deleted']
    assert c.get('/api/v1/people').json()['people']==[]
    assert c.get('/api/v1/facts').json()['facts']==[]
    assert c.get('/api/v1/followups').json()['followups']==[]

def test_upload_validation_and_processing(env):
    c,_,_=env;s,p=setup(c);data={'session_id':s['id'],'start_ts':T,'end_ts':E}
    assert c.post('/api/v1/chunks',data=data).status_code==422
    assert c.post('/api/v1/chunks',data=data,files={'video':('x.mp4',b'not video','video/mp4')}).status_code==415
    r=c.post('/api/v1/chunks',data=data,files={'video':('x.mp4',b'\x00\x00\x00\x18ftypisom'+b'x'*20,'video/mp4')})
    assert r.status_code==202,r.text
    assert c.get('/api/v1/chunks/'+r.json()['chunk_id']).json()['status']=='indexed'
    assert c.post('/api/v1/chunks',data=data,files={'audio':('x.wav',b'x'*(15*1024*1024+1),'audio/wav')}).status_code==413

def test_strict_input_and_biometrics(env):
    c,_,_=env
    assert c.post('/api/v1/sessions',json={'made_up':True}).status_code==422
    assert c.post('/api/v1/ask',json={'query':123}).status_code==422
    assert c.post('/api/v1/people',data={'name':'Nayan'},files={'voice_sample':('a.wav',b'RIFF','audio/wav')}).status_code==422

def test_websocket(env):
    c,_,_=env
    with c.websocket_connect('/api/v1/live') as ws:
        assert ws.receive_json()['event']=='status';ws.send_json({'event':'ping'});assert ws.receive_json()['event']=='pong'

def test_restart_marks_interrupted(env,tmp_path):
    c,p,a=env
    a.state.store.put('chunk',{'id':'interrupted','status':'processing'})
    b=create_app(str(tmp_path/'db.sqlite'),p)
    assert b.state.store.get('chunk','interrupted')['status']=='failed';b.state.store.db.close()

def test_missing_wearer_blocks(env):
    c,_,_=env
    s=c.post('/api/v1/sessions',json={}).json();f=follow(c,s)
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={'owner':'Nayan','reviewed':True}).status_code==409

def test_uncertain_requires_review(env):
    c,provider,_=env;provider.uncertain=True;s,p=setup(c);f=follow(c,s,p)
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={}).status_code==409
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={'reviewed':True}).status_code==200

def test_corrections_need_explicit_review(env):
    c,_,_=env;s,p=setup(c);f=follow(c,s,p)
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={'owner':'Nayan'}).status_code==422

def test_ended_session_rejects_ingestion(env):
    c,_,_=env;s,p=setup(c);c.post('/api/v1/sessions/'+s['id']+'/end')
    r=c.post('/api/v1/transcripts',json={'session_id':s['id'],'start_ts':T,'end_ts':E,'transcript':[{'speaker':'A','text':'hi','start_ts':T,'end_ts':E}]})
    assert r.status_code==409

def test_generation_provider_failure(env):
    c,pr,_=env;s,p=setup(c);ingest(c,s);ingest(c,s);pr.fail=True
    r=c.post('/api/v1/followups/generate',json={'session_id':s['id']}).json()
    result=c.get('/api/v1/followups',params={'run_id':r['run_id']}).json()
    assert result['run']['status']=='failed';assert result['followups']==[]
