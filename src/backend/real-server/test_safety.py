from urllib.parse import urlparse,parse_qs
from datetime import datetime
from fastapi.testclient import TestClient
from test_backend import env,setup,follow,Provider,T,E
from app import create_app
from core import Task

def test_no_coercion(env):
    c,_,_=env
    assert c.post('/api/v1/ask',json={'query':'test','top_k':True}).status_code==422
    assert c.post('/api/v1/sessions',json={'timezone':123}).status_code==422

def test_jobs_bounded(env):
    c,_,a=env;s,_=setup(c)
    for i in range(4):a.state.store.put('chunk',{'id':'busy'+str(i),'status':'processing','session_id':s['id']})
    r=c.post('/api/v1/transcripts',json={'session_id':s['id'],'start_ts':T,'end_ts':E,'transcript':[{'speaker':'A','text':'hello','start_ts':T,'end_ts':E}]})
    assert r.status_code==429

def test_media_retry_dedup_even_after_end(env):
    c,_,_=env;s,_=setup(c);data={'session_id':s['id'],'start_ts':T,'end_ts':E}
    files={'video':('x.mp4',b'\x00\x00\x00\x18ftypisom'+b'x'*20,'video/mp4')}
    a=c.post('/api/v1/chunks',data=data,files=files).json()
    c.post('/api/v1/sessions/'+s['id']+'/end')
    b=c.post('/api/v1/chunks',data=data,files=files)
    assert b.status_code==202 and a['chunk_id']==b.json()['chunk_id']
    assert len(c.get('/api/v1/scenes/today',params={'session_id':s['id']}).json()['scenes'])==1

def test_local_cross_origin_and_proxy_denied(tmp_path,monkeypatch):
    monkeypatch.delenv('SCENE_API_TOKEN',raising=False);monkeypatch.setenv('SCENE_ALLOW_LOCAL_NO_AUTH','1')
    app=create_app(str(tmp_path/'db'),Provider());c=TestClient(app,client=('127.0.0.1',123))
    assert c.post('/api/v1/sessions',headers={'Origin':'https://evil.invalid'},json={}).status_code==403
    assert c.get('/api/v1/status',headers={'X-Forwarded-For':'203.0.113.1'}).status_code==403

def test_duration_used(env):
    c,p,a=env;p.action='calendar';s,person=setup(c);f=follow(c,s,person)
    stored=a.state.store.get('followup',f['id']);stored['duration_min']=20;a.state.store.put('followup',stored)
    out=c.post('/api/v1/followups/'+f['id']+'/approve',json={'reviewed':True}).json()
    start,end=parse_qs(urlparse(out['action_url']).query)['dates'][0].split('/')
    fmt='%Y%m%dT%H%M%SZ'
    assert (datetime.strptime(end,fmt)-datetime.strptime(start,fmt)).total_seconds()==1200

def test_all_approval_requires_review(env):
    c,_,_=env;s,p=setup(c);f=follow(c,s,p)
    assert c.post('/api/v1/followups/'+f['id']+'/approve',json={}).status_code==409
