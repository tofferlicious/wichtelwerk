"""Isolated lifecycle regression check; never sends external mail."""
import tempfile
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wichtelwerk import create_app

with tempfile.TemporaryDirectory() as tmp:
    app=create_app({'TESTING':True,'COOKIE_SECURE':False,'DATABASE':tmp+'/check.db','MAIL_MODE':'memory','BASE_URL':'http://localhost','EVENT_CREATOR_EMAILS':'owner@example.test'})
    def post(c,path,data):
        csrf=c.get('/api/me').json['csrf']
        return c.post(path,json=data,headers={'X-CSRF-Token':csrf})
    def login(email):
        c=app.test_client()
        assert post(c,'/api/login',{'email':email}).status_code==200
        token=app.extensions['outbox'][-1]['body'].split('#token=')[1].split()[0]
        assert post(c,'/api/auth',{'token':token}).status_code==200
        assert post(c,'/api/auth',{'token':token}).status_code==400
        return c
    owner=login('owner@example.test')
    users=[login(f'person{i}@example.test') for i in range(3)]
    outsider=login('outsider@example.test')
    day=(date.today()+timedelta(days=30)).isoformat()
    r=post(owner,'/api/events',{'title':'Verification','date':day,'budget':'20 EUR','invitation':'Hello','retention':24,'history':True})
    assert r.status_code==200,r.json
    eid=r.json['id']; base='/api/events/'+eid
    assert outsider.get(base).status_code==404
    assert owner.post(base+'/draw',json={'confirmed':True}).status_code==403
    for i,c in enumerate(users):
        assert post(owner,base+'/invite',{'email':f'person{i}@example.test','name':f'Person {i}'}).status_code==200
        assert post(c,base+'/respond',{'status':'accepted'}).status_code==200
        assert post(c,base+'/wishes',{'wishes':f'Wish {i}'}).status_code==200
    roster=owner.get(base).json['participants']; ids=[p['id'] for p in roster]
    assert post(owner,base+'/exclusions',{'pairs':[[ids[0],ids[1]]]}).status_code==200
    assert post(owner,base+'/feasibility',{}).json['possible']
    assert post(owner,base+'/draw',{'confirmed':True}).status_code==200
    assert owner.get(base).json['recipient'] is None
    assert all('wishes' not in p and 'address' not in p for p in owner.get(base).json['participants'])
    recipients=[c.get(base).json['recipient']['id'] for c in users]
    assert len(set(recipients))==3 and all(a!=b for a,b in zip(ids,recipients))
    assert recipients[0]!=ids[1]
    assert post(owner,base+'/draw',{'confirmed':True}).status_code==409
    assert post(users[0],base+'/respond',{'status':'declined'}).status_code==409
    assert post(users[0],base+'/wishes',{'wishes':'Updated after draw'}).status_code==200
    with sqlite3.connect(tmp+'/check.db') as db:
        assert db.execute('select count(*) from draw_mail').fetchone()[0]==3
    result=app.test_cli_runner().invoke(args=['send-draw-mail'])
    assert result.exit_code==0,result.output
    assert '3' in result.output
    copied=post(owner,base+'/copy',{'title':'Next year','date':day,'participants':ids,'copy_exclusions':True,'avoid_previous':True})
    assert copied.status_code==200,copied.json
    with sqlite3.connect(tmp+'/check.db') as db:
        assert db.execute('select previous from events where id=?',(copied.json['id'],)).fetchone()[0] is None
        assert db.execute('select count(*) from draw_mail').fetchone()[0]==3
    detail=users[0].get('/api/events/'+copied.json['id']).json
    assert detail['membership']['status']!='accepted' and detail['membership']['wishes']==''
    print('PASS: isolated login/token replay, CSRF, authorization, invites, acceptance, exclusions, feasibility, draw privacy, queue, post-draw wishlist, annual copy checks. No external mail sent.')
