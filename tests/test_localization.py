"""Real API locale negotiation and additive SQLite migration checks."""
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest
from wichtelwerk import create_app
from .test_creation_permissions import app_for, login, post, payload, ADMIN


def localized_post(client, path, data, language='en'):
    headers = {'Accept-Language':language}
    csrf = client.get('/api/me', headers=headers).json['csrf']
    return client.post(path, json=data, headers={**headers,'X-CSRF-Token':csrf})


@pytest.mark.parametrize('language,expected', [
    ('en-US,en;q=0.9','Please sign in by email first.'),
    ('de-AT,en;q=0.5','Bitte zuerst per E-Mail anmelden.'),
    ('fr-FR','Bitte zuerst per E-Mail anmelden.'),
    ('fr-FR,en-US;q=0.8','Please sign in by email first.'),
])
def test_api_negotiates_language(tmp_path, language, expected):
    response = app_for(tmp_path).test_client().get('/api/events', headers={'Accept-Language':language})
    assert response.status_code == 401
    assert response.json['error'] == expected


def test_login_email_language_and_verified_preference(tmp_path):
    app = app_for(tmp_path)
    client = app.test_client()
    assert localized_post(client, '/api/login', {'email':'english@example.invalid'}).status_code == 200
    mail = app.extensions['outbox'][-1]
    assert mail['subject'] == 'Your Wichtelwerk sign-in link'
    assert '30 minutes' in mail['body'] and 'personal, single-use sign-in link' in mail['body']
    token = re.search(r'#token=([^\s]+)', mail['body']).group(1)
    assert localized_post(client, '/api/auth', {'token':token}).status_code == 200
    assert client.get('/api/me').json['user']['language'] == 'en'
    assert localized_post(client, '/api/language', {'language':'de'}).status_code == 200
    assert client.get('/api/me').json['user']['language'] == 'de'
    assert localized_post(client, '/api/language', {'language':'fr'}).status_code == 400
    assert client.get('/api/me').json['user']['language'] == 'de'
    assert client.post('/api/language',json={'language':'en'}).status_code == 403
    assert localized_post(app.test_client(), '/api/language', {'language':'en'}).status_code == 401


def test_locale_migration_is_idempotent_and_preserves_existing_users(tmp_path):
    database = tmp_path/'old.db'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT NOT NULL UNIQUE,name TEXT NOT NULL,created INTEGER NOT NULL)')
        db.execute('INSERT INTO users VALUES(7,?,?,123)',('old@example.invalid','Original name'))
    config = {'TESTING':True,'MAIL_MODE':'memory','DATABASE':str(database)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _:create_app(config), range(2)))
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT id,email,name,created,language FROM users').fetchall() == [(7,'old@example.invalid','Original name',123,None)]
        assert sum(row[1]=='language' for row in db.execute('PRAGMA table_info(users)')) == 1


def test_invites_and_worker_use_recipient_preference_not_user_content(tmp_path):
    app = app_for(tmp_path, EVENT_CREATOR_EMAILS=ADMIN)
    owner = login(app, ADMIN)
    guest = login(app, 'english@example.invalid')
    assert localized_post(guest, '/api/language', {'language':'en'}).status_code == 200
    title = 'Kleine Geste. <My own title>'
    invitation = 'Privat bleibt persönlich. <Keep these exact words>'
    eid = post(owner,'/api/events',payload(title=title,invitation=invitation)).json['id']
    base = '/api/events/'+eid
    assert post(owner,base+'/invite',{'email':'english@example.invalid','name':'Guest'}).status_code == 200
    email = app.extensions['outbox'][-1]
    assert email['subject'] == 'Invitation: '+title
    assert invitation in email['body'] and '7 days' in email['body']
    assert localized_post(guest,base+'/respond',{'status':'accepted'}).status_code == 200
    assert post(owner,base+'/join',{'name':'Owner'}).status_code == 200
    assert post(owner,base+'/draw',{'confirmed':True}).status_code == 200
    result=app.test_cli_runner().invoke(args=['send-draw-mail'])
    assert result.exit_code==0,result.output
    mails=[m for m in app.extensions['outbox'] if m['to']=='english@example.invalid']
    assert mails[-1]['subject']=='Draw complete: '+title
    assert 'only in your account' in mails[-1]['body']
    assert localized_post(guest,'/api/account/delete',{'confirm':'NOT DELETE'}).status_code==400
    assert guest.get('/api/me').json['user'] is not None
    assert localized_post(guest,'/api/account/delete',{'confirm':'DELETE'}).status_code==200


def test_unknown_invitee_uses_sender_language(tmp_path):
    app=app_for(tmp_path,EVENT_CREATOR_EMAILS=ADMIN)
    owner=login(app,ADMIN)
    eid=post(owner,'/api/events',payload()).json['id']
    assert localized_post(owner,'/api/events/'+eid+'/invite',{'name':'New','email':'new@example.invalid'}).status_code==200
    assert app.extensions['outbox'][-1]['subject'].startswith('Invitation: ')
