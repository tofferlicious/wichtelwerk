"""Creation policy: real email-link login, isolated DB, no external mail."""
import re
import sqlite3
from datetime import date, timedelta
import pytest
from wichtelwerk import create_app

ADMIN = 'admin@example.invalid'
OTHER = 'guest@example.invalid'


def app_for(tmp_path, **policy):
    return create_app({'TESTING': True, 'COOKIE_SECURE': False, 'MAIL_MODE': 'memory',
                       'DATABASE': str(tmp_path/'permissions.db'),
                       'BASE_URL': 'http://localhost', **policy})


def post(client, path, payload):
    csrf = client.get('/api/me').json['csrf']
    return client.post(path, json=payload, headers={'X-CSRF-Token': csrf})


def login(app, email):
    client = app.test_client()
    assert post(client, '/api/login', {'email': email}).status_code == 200
    token = re.search(r'#token=([^\s]+)', app.extensions['outbox'][-1]['body']).group(1)
    assert post(client, '/api/auth', {'token': token}).status_code == 200
    return client


def payload(**extra):
    return {'title': 'Private test round', 'date': (date.today()+timedelta(days=40)).isoformat(), **extra}


def count(app, table):
    assert table in ('events', 'participants', 'draw_mail')
    with sqlite3.connect(app.config['DATABASE']) as db:
        return db.execute('SELECT count(*) FROM '+table).fetchone()[0]


def test_default_denies_first_account_and_self_asserted_admin(tmp_path, monkeypatch):
    monkeypatch.delenv('PUBLIC_EVENT_CREATION', raising=False)
    monkeypatch.delenv('EVENT_CREATOR_EMAILS', raising=False)
    app = app_for(tmp_path)
    client = login(app, OTHER)
    assert post(client, '/api/events', payload(is_admin=True, can_create_events=True,
                PUBLIC_EVENT_CREATION=True, EVENT_CREATOR_EMAILS=OTHER)).status_code == 403
    assert client.get('/api/me').json['can_create_events'] is False
    assert count(app, 'events') == 0


def test_exact_allowlist_admin_allowed_other_denied(tmp_path):
    app = app_for(tmp_path, PUBLIC_EVENT_CREATION=False, EVENT_CREATOR_EMAILS='  ADMIN@EXAMPLE.INVALID  ')
    admin, guest = login(app, ADMIN), login(app, OTHER)
    assert admin.get('/api/me').json['can_create_events'] is True
    assert guest.get('/api/me').json['can_create_events'] is False
    assert post(admin, '/api/events', payload()).status_code == 200
    assert post(guest, '/api/events', payload()).status_code == 403
    impostor = login(app, 'admin+alias@example.invalid')
    assert post(impostor, '/api/events', payload()).status_code == 403
    assert count(app, 'events') == 1


def test_copy_denied_even_for_owner_of_legacy_round(tmp_path):
    app = app_for(tmp_path, PUBLIC_EVENT_CREATION=True, EVENT_CREATOR_EMAILS=ADMIN)
    guest = login(app, OTHER)
    event = post(guest, '/api/events', payload()).json['id']
    app.config['PUBLIC_EVENT_CREATION'] = False
    before = count(app, 'events')
    assert post(guest, '/api/events/'+event+'/copy', payload(participants=[])).status_code == 403
    assert count(app, 'events') == before
    assert count(app, 'draw_mail') == 0
    assert guest.get('/api/events/'+event).status_code == 200


def test_admin_copy_allowed_and_other_event_stays_private(tmp_path):
    app = app_for(tmp_path, PUBLIC_EVENT_CREATION=False, EVENT_CREATOR_EMAILS=ADMIN)
    admin, guest = login(app, ADMIN), login(app, OTHER)
    event = post(admin, '/api/events', payload()).json['id']
    assert post(admin, '/api/events/'+event+'/copy', payload(participants=[])).status_code == 200
    assert post(guest, '/api/events/'+event+'/copy', payload(participants=[])).status_code == 403
    assert guest.get('/api/events/'+event).status_code == 404
    assert count(app, 'events') == 2


@pytest.mark.parametrize('public', [True, False])
def test_anonymous_cannot_create_or_copy_even_in_public_mode(tmp_path, public):
    app = app_for(tmp_path, PUBLIC_EVENT_CREATION=public, EVENT_CREATOR_EMAILS=ADMIN)
    client = app.test_client()
    assert post(client, '/api/events', payload()).status_code == 401
    assert post(client, '/api/events/missing/copy', payload()).status_code == 401
    assert client.get('/api/me').json['can_create_events'] is False
    assert count(app, 'events') == 0


@pytest.mark.parametrize('value,allowed', [('true',True), ('1',True), ('false',False), ('0',False), ('off',False)])
def test_environment_switch_is_parsed_not_string_truthiness(tmp_path, monkeypatch, value, allowed):
    monkeypatch.setenv('PUBLIC_EVENT_CREATION', value)
    monkeypatch.setenv('EVENT_CREATOR_EMAILS', ADMIN)
    app = app_for(tmp_path)
    guest = login(app, OTHER)
    assert guest.get('/api/me').json['can_create_events'] is allowed
    assert post(guest, '/api/events', payload()).status_code == (200 if allowed else 403)
    admin = login(app, ADMIN)
    assert post(admin, '/api/events', payload()).status_code == 200


def test_invalid_public_setting_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('PUBLIC_EVENT_CREATION', 'definitely')
    with pytest.raises(ValueError, match='PUBLIC_EVENT_CREATION'):
        app_for(tmp_path)


def test_participant_login_invitation_response_wishes_and_public_join_unchanged(tmp_path):
    app = app_for(tmp_path, PUBLIC_EVENT_CREATION=False, EVENT_CREATOR_EMAILS=ADMIN)
    admin, guest = login(app, ADMIN), login(app, OTHER)
    event = post(admin, '/api/events', payload(public=True)).json['id']
    base = '/api/events/'+event
    assert post(admin, base+'/invite', {'email':OTHER, 'name':'Guest'}).status_code == 200
    assert post(guest, base+'/respond', {'status':'accepted'}).status_code == 200
    assert post(guest, base+'/wishes', {'wishes':'Books'}).status_code == 200
    detail = guest.get(base).json
    assert detail['membership']['status'] == 'accepted'
    assert detail['membership']['wishes'] == 'Books'
    assert 'participants' not in detail
    link = admin.get(base).json['public_code']
    new_guest = login(app, 'joined@example.invalid')
    assert post(new_guest, '/api/join/'+link, {'name':'Joined'}).status_code == 200
    assert post(new_guest, '/api/events', payload()).status_code == 403
    assert count(app, 'events') == 1
    assert count(app, 'participants') == 2
