import re
import sqlite3
import time
from datetime import date,timedelta
import pytest
from wichtelwerk import create_app, matching

@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING':True,'MAIL_MODE':'memory','COOKIE_SECURE':False,'DATABASE':str(tmp_path/'db.sqlite'),'PUBLIC_EVENT_CREATION':False,'EVENT_CREATOR_EMAILS':'owner@example.invalid'})

def post(c,path,payload):
    csrf=c.get('/api/me').json['csrf']
    return c.post('/api'+path,json=payload,headers={'X-CSRF-Token':csrf})

def login(app,email):
    c=app.test_client();assert post(c,'/login',{'email':email}).status_code==200
    token=re.search(r'#token=([^\s]+)',app.extensions['outbox'][-1]['body']).group(1)
    assert post(c,'/auth',{'token':token}).status_code==200
    return c,token

def event(c):
    r=post(c,'/events',{'title':'Runde','date':(date.today()+timedelta(days=30)).isoformat(),'retention':24,'history':True})
    assert r.status_code==200
    return r.json['id']

def test_auth_csrf_replay_and_hashing(app):
    c,token=login(app,'one@example.invalid')
    assert post(c,'/auth',{'token':token}).status_code==400
    assert c.post('/api/events',json={}).status_code==403
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert not db.execute('SELECT * FROM tokens WHERE digest=?',(token,)).fetchall()
    assert post(c,'/logout',{}).status_code==200
    assert c.get('/api/me').json['user'] is None
    assert c.get('/api/events').status_code==401

def test_event_isolation_and_account_deletion(app):
    a,_=login(app,'owner@example.invalid');b,_=login(app,'outsider@example.invalid');eid=event(a)
    assert b.get('/api/events/'+eid).status_code==404
    assert post(b,'/events/'+eid+'/delete',{'confirm':'LÖSCHEN'}).status_code==404
    assert post(a,'/account/delete',{'confirm':'LÖSCHEN'}).status_code==200
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0]==0

def test_matching_constraints_and_impossible():
    people=list(range(20));blocked={(0,1),(0,2),(0,3),(1,0)}
    for _ in range(50):
        result=matching(people,blocked)
        assert set(result)==set(people)==set(result.values())
        assert all(a!=b and (a,b) not in blocked for a,b in result.items())
    assert matching([1,2],{(1,2)}) is None
    assert matching([1],set()) is None

def test_cleanup_retains_accounts_and_cascades(app):
    a,_=login(app,'owner@example.invalid');eid=event(a)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE events SET expires=? WHERE id=?',(int(time.time())-10,eid))
    assert a.get('/api/events/'+eid).status_code==404
    result=app.test_cli_runner().invoke(args=['cleanup']);assert result.exit_code==0
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM users').fetchone()[0]==1

def test_mail_failure_is_truthful(app):
    a,_=login(app,'owner@example.invalid');eid=event(a);app.config['MAIL_MODE']='disabled'
    result=post(a,'/events/'+eid+'/invite',{'name':'Guest','email':'guest@example.invalid'})
    assert result.json['mail_status']=='failed'
    participants=a.get('/api/events/'+eid).json['participants']
    assert participants[0]['mail_status']=='failed'
    result=post(a,'/events/'+eid+'/remind',{'participant':participants[0]['id']})
    assert result.json=={'submitted':0,'failed':1}
