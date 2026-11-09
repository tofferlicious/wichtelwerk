"""Wichtelwerk: private, self-hosted Secret Santa."""
import secrets
import hashlib
import os
import re
import sqlite3
import subprocess
import time
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path
from flask import Flask, g, request, jsonify, send_from_directory, abort


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def create_app(config=None):
    app = Flask(__name__, static_folder='static')
    app.config.update(DATABASE=os.environ.get('DATABASE', 'instance/wichtelwerk.db'),
                      BASE_URL=os.environ.get('BASE_URL', 'http://localhost:8765'),
                      MAIL_MODE=os.environ.get('MAIL_MODE', 'disabled'),
                      MAIL_FROM=os.environ.get('MAIL_FROM', 'wichtelwerk@example.invalid'),
                      PUBLIC_EVENT_CREATION=os.environ.get('PUBLIC_EVENT_CREATION', 'false'),
                      EVENT_CREATOR_EMAILS=os.environ.get('EVENT_CREATOR_EMAILS', ''),
                      COOKIE_SECURE=True, MAX_CONTENT_LENGTH=32768)
    if config:
        app.config.update(config)
    public = app.config['PUBLIC_EVENT_CREATION']
    if isinstance(public, str) and public.strip().lower() in ('true', '1', 'yes', 'on', 'false', '0', 'no', 'off'):
        public = public.strip().lower() in ('true', '1', 'yes', 'on')
    if type(public) is not bool:
        raise ValueError('PUBLIC_EVENT_CREATION must be true or false')
    app.config['PUBLIC_EVENT_CREATION'] = public
    creator_emails = {email.strip().lower() for email in app.config['EVENT_CREATOR_EMAILS'].split(',') if email.strip()}
    if app.config['MAIL_MODE'] == 'memory' and not app.config['TESTING']:
        raise RuntimeError('Memory mail is test-only')
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.executescript(Path(__file__).with_name('schema.sql').read_text())
    os.chmod(app.config['DATABASE'], 0o600)
    app.extensions['outbox'] = []

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=15, isolation_level=None)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
            g.db.execute('PRAGMA journal_mode=WAL')
        return g.db

    @app.teardown_appcontext
    def close(_error):
        conn = g.pop('db', None)
        if conn is not None:
            conn.close()

    def fail(message, code=400):
        abort(code, description=message)

    def rate(key, limit, seconds=3600):
        now = int(time.time())
        c = db()
        c.execute('BEGIN IMMEDIATE')
        try:
            c.execute('DELETE FROM limits WHERE expires < ?', (now,))
            row = c.execute('SELECT count FROM limits WHERE key=?', (key,)).fetchone()
            if row and row['count'] >= limit:
                c.rollback()
                fail('Zu viele Versuche. Bitte später erneut probieren.', 429)
            c.execute('INSERT INTO limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, now + seconds))
            c.commit()
        except Exception:
            c.rollback()
            raise

    @app.before_request
    def session_and_csrf():
        if not request.path.startswith('/api/'):
            return
        now = int(time.time())
        cookie = request.cookies.get('ww_session', '')
        g.session = db().execute('SELECT * FROM sessions WHERE digest=? AND expires>?', (digest(cookie), now)).fetchone() if cookie else None
        if not g.session:
            rate('sessions:' + (request.remote_addr or 'unknown'), 120, 60)
            g.new_cookie = secrets.token_urlsafe(32)
            db().execute('INSERT INTO sessions VALUES(?,NULL,?,?)', (digest(g.new_cookie), secrets.token_urlsafe(32), now + 3600))
            g.session = db().execute('SELECT * FROM sessions WHERE digest=?', (digest(g.new_cookie),)).fetchone()
        g.user = db().execute('SELECT id,email,name FROM users WHERE id=?', (g.session['user_id'],)).fetchone()
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            provided = request.headers.get('X-CSRF-Token', '')
            if not secrets.compare_digest(provided, g.session['csrf']):
                fail('Sicherheitsprüfung fehlgeschlagen. Seite neu laden.', 403)
            origin = request.headers.get('Origin')
            if origin and origin != app.config['BASE_URL'].rstrip('/'):
                fail('Ungültige Herkunft.', 403)

    @app.after_request
    def security(response):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if app.config['COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        if hasattr(g, 'new_cookie'):
            response.set_cookie('ww_session', g.new_cookie, secure=app.config['COOKIE_SECURE'], httponly=True, samesite='Lax', max_age=30*86400, path='/')
        return response

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(429)
    @app.errorhandler(503)
    def error(exc):
        return jsonify(error=exc.description), exc.code

    def user():
        if not g.user:
            fail('Bitte zuerst per E-Mail anmelden.', 401)
        return g.user['id']

    def can_create_events():
        return bool(g.user and (app.config['PUBLIC_EVENT_CREATION'] or g.user['email'].lower() in creator_emails))

    def require_event_creator():
        uid = user()
        if not can_create_events():
            fail('Nur freigegebene Konten dürfen Runden erstellen oder kopieren. Du kannst an eingeladenen Runden teilnehmen.', 403)
        return uid

    def data():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            fail('Ungültige Anfrage.')
        return payload

    def text(payload, key, maximum=200, required=False):
        value = payload.get(key, '')
        if not isinstance(value, str) or len(value) > maximum:
            fail('Ungültiges Feld: ' + key)
        value = value.strip()
        if required and not value:
            fail('Bitte ausfüllen: ' + key)
        return value

    def email_address(value):
        if not isinstance(value, str):
            fail('Ungültige E-Mail-Adresse.')
        value = value.strip().lower()
        if len(value) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", value):
            fail('Ungültige E-Mail-Adresse.')
        return value

    def ensure_user(email):
        db().execute('INSERT OR IGNORE INTO users(email,name,created) VALUES(?,?,?)', (email, email.split('@')[0], int(time.time())))
        return db().execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()['id']

    def send_link(uid, subject, introduction, expiry=1800):
        account = db().execute('SELECT email FROM users WHERE id=?', (uid,)).fetchone()
        token = secrets.token_urlsafe(32)
        hashed = digest(token)
        db().execute('INSERT INTO tokens VALUES(?,?,?)', (hashed, uid, int(time.time()) + expiry))
        body = introduction + '\n\nDein persönlicher, einmaliger Zugang:\n' + app.config['BASE_URL'].rstrip('/') + '/#token=' + token + '\n\nBitte nicht weitergeben. Wichtelwerk fragt nie nach deinem E-Mail-Passwort.\n'
        try:
            if app.config['MAIL_MODE'] == 'memory':
                app.extensions['outbox'].append({'to': account['email'], 'subject': subject, 'body': body})
            elif app.config['MAIL_MODE'] == 'sendmail':
                message = EmailMessage()
                message['From'] = app.config['MAIL_FROM']
                message['To'] = account['email']
                message['Subject'] = subject
                message.set_content(body)
                subprocess.run(['/usr/sbin/sendmail', '-i', '-t'], input=message.as_bytes(), check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                raise RuntimeError('Mail disabled')
        except (RuntimeError, OSError, subprocess.SubprocessError):
            db().execute('DELETE FROM tokens WHERE digest=?', (hashed,))
            return False
        return True

    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.get('/healthz')
    def health():
        db().execute('SELECT 1')
        return jsonify(status='ok', application='Wichtelwerk')

    @app.get('/api/me')
    def me():
        return jsonify(user=dict(g.user) if g.user else None, csrf=g.session['csrf'], can_create_events=can_create_events())

    @app.post('/api/login')
    def login():
        email = email_address(data().get('email'))
        rate('login-ip:' + (request.remote_addr or ''), 20)
        rate('login-email:' + digest(email), 3)
        uid = ensure_user(email)
        if not send_link(uid, 'Dein Zugang zu Wichtelwerk', 'Willkommen zurück – oder schön, dass du dabei bist! Dieser Link gilt 30 Minuten.'):
            fail('E-Mail konnte nicht übergeben werden. Bitte später erneut versuchen.', 503)
        return jsonify(message='Der Anmeldelink wurde an den Mailserver übergeben. Bitte auch den Spamordner prüfen.')

    @app.post('/api/auth')
    def authenticate():
        token = text(data(), 'token', 100, True)
        rate('auth-ip:' + (request.remote_addr or ''), 60)
        c = db()
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT user_id FROM tokens WHERE digest=? AND expires>?', (digest(token), int(time.time()))).fetchone()
        if not row:
            c.rollback()
            fail('Dieser Link ist abgelaufen oder wurde bereits benutzt. Fordere einen neuen Anmeldelink an.')
        c.execute('DELETE FROM tokens WHERE digest=?', (digest(token),))
        c.execute('DELETE FROM sessions WHERE digest=?', (g.session['digest'],))
        g.new_cookie = secrets.token_urlsafe(32)
        c.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(g.new_cookie), row['user_id'], secrets.token_urlsafe(32), int(time.time()) + 30*86400))
        c.commit()
        return jsonify(ok=True)

    @app.post('/api/logout')
    def logout():
        db().execute('DELETE FROM sessions WHERE digest=?', (g.session['digest'],))
        return jsonify(ok=True)

    def event(eid, owner=False):
        uid = user()
        row = db().execute('SELECT * FROM events WHERE id=? AND (expires IS NULL OR expires>?)', (eid, int(time.time()))).fetchone()
        member = db().execute('SELECT * FROM participants WHERE event=? AND user_id=?', (eid, uid)).fetchone()
        if not row or (row['owner'] != uid and (owner or not member)):
            fail('Runde nicht gefunden.', 404)
        return row, member

    def mutable(row):
        if row['drawn']:
            fail('Nach der Auslosung bleibt die Teilnehmerliste unverändert.', 409)

    def event_values(payload):
        title = text(payload, 'title', 100, True)
        day = text(payload, 'date', 10, True)
        try:
            when = date.fromisoformat(day)
        except ValueError:
            fail('Ungültiges Datum.')
        if when < date.today() or when.year > date.today().year + 10:
            fail('Bitte ein Datum in den nächsten zehn Jahren wählen.')
        retention = payload.get('retention', 24)
        if type(retention) is not int or retention not in (0, 6, 12, 24, 60):
            fail('Ungültige Aufbewahrung.')
        expires = int(time.time()) + ((when - date.today()).days + retention * 31 + 1) * 86400 if retention else None
        return (title, day, text(payload, 'budget', 50), text(payload, 'invitation', 3000), int(payload.get('postal') is True), retention, expires, int(payload.get('history') is True))

    @app.get('/api/events')
    def list_events():
        uid = user()
        rows = db().execute('SELECT DISTINCT e.id,e.title,e.date,e.budget,e.drawn,e.owner FROM events e LEFT JOIN participants p ON p.event=e.id WHERE (e.owner=? OR p.user_id=?) AND (e.expires IS NULL OR e.expires>?) ORDER BY e.created DESC', (uid, uid, int(time.time()))).fetchall()
        return jsonify(events=[dict(r) for r in rows])

    @app.post('/api/events')
    def new_event():
        uid = require_event_creator()
        payload = data()
        values = event_values(payload)
        if db().execute('SELECT count(*) FROM events WHERE owner=?', (uid,)).fetchone()[0] >= 30:
            fail('Maximal 30 Runden pro Konto.')
        eid = secrets.token_urlsafe(16)
        code = secrets.token_urlsafe(24) if payload.get('public') is True else None
        db().execute('INSERT INTO events(id,owner,title,date,budget,invitation,postal,retention,expires,history,public_code,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (eid, uid, *values, code, int(time.time())))
        return jsonify(id=eid)

    @app.get('/api/events/<eid>')
    def view_event(eid):
        row, member = event(eid)
        is_owner = row['owner'] == user()
        result = {k: row[k] for k in ('id','title','date','budget','invitation','postal','retention','expires','history','drawn')}
        result['organizer'] = is_owner
        result['membership'] = {k: member[k] for k in ('id','name','status','wishes','address')} if member else None
        result['recipient'] = None
        if member and row['drawn']:
            recipient = db().execute('SELECT p.id,p.name,p.wishes,p.address FROM assignments a JOIN participants p ON p.id=a.receiver WHERE a.event=? AND a.giver=?', (eid, member['id'])).fetchone()
            if recipient:
                result['recipient'] = dict(recipient)
                if not row['postal']:
                    result['recipient']['address'] = ''
        if is_owner:
            result['participants'] = [dict(p) for p in db().execute('SELECT p.id,p.name,p.status,p.mail_status,p.mailed,u.email FROM participants p JOIN users u ON u.id=p.user_id WHERE p.event=? ORDER BY p.id', (eid,))]
            result['exclusions'] = [list(p) for p in db().execute('SELECT giver,receiver FROM exclusions WHERE event=?', (eid,))]
            result['public_code'] = row['public_code']
        return jsonify(result)

    @app.post('/api/events/<eid>/invite')
    def invite(eid):
        payload = data()
        email = email_address(payload.get('email'))
        name = text(payload, 'name', 100, True)
        rate('invite-owner:' + str(user()), 100)
        db().execute('BEGIN IMMEDIATE')
        row, _ = event(eid, True)
        mutable(row)
        if db().execute('SELECT count(*) FROM participants WHERE event=?', (eid,)).fetchone()[0] >= 100:
            fail('Maximal 100 Personen pro Runde.')
        uid = ensure_user(email)
        try:
            cursor = db().execute('INSERT INTO participants(event,user_id,name) VALUES(?,?,?)', (eid, uid, name))
        except sqlite3.IntegrityError:
            fail('Diese Person ist bereits eingeladen.', 409)
        db().commit()
        sent = send_link(uid, 'Einladung: ' + row['title'], row['invitation'] + '\n\nDu bist zu „' + row['title'] + '“ eingeladen. Bitte im Konto zu- oder absagen. Zugang gilt 7 Tage.', 7*86400)
        db().execute('UPDATE participants SET mail_status=?,mailed=? WHERE id=?', ('submitted' if sent else 'failed', int(time.time()), cursor.lastrowid))
        return jsonify(ok=True, mail_status='submitted' if sent else 'failed')

    @app.post('/api/events/<eid>/respond')
    def respond(eid):
        db().execute('BEGIN IMMEDIATE')
        row, member = event(eid)
        mutable(row)
        if not member:
            fail('Du nimmst noch nicht teil.', 403)
        status = data().get('status')
        if status not in ('accepted', 'declined'):
            fail('Ungültige Antwort.')
        db().execute('UPDATE participants SET status=? WHERE id=?', (status, member['id']))
        db().commit()
        return jsonify(ok=True)

    @app.post('/api/events/<eid>/wishes')
    def wishes(eid):
        row, member = event(eid)
        if not member:
            fail('Du nimmst noch nicht teil.', 403)
        payload = data()
        wishes = text(payload, 'wishes', 5000)
        address = text(payload, 'address', 1000) if row['postal'] else ''
        db().execute('UPDATE participants SET wishes=?,address=? WHERE id=?', (wishes, address, member['id']))
        return jsonify(ok=True)

    @app.post('/api/events/<eid>/exclusions')
    def exclusions(eid):
        row, _ = event(eid, True)
        mutable(row)
        pairs = data().get('pairs')
        ids = {p[0] for p in db().execute('SELECT id FROM participants WHERE event=?', (eid,))}
        if not isinstance(pairs, list) or len(pairs) > 10000:
            fail('Ungültige Ausschlüsse.')
        if any(not isinstance(p, list) or len(p) != 2 or any(type(x) is not int or x not in ids for x in p) or p[0] == p[1] for p in pairs):
            fail('Ausschlüsse müssen zwei verschiedene Personen dieser Runde betreffen.')
        db().execute('BEGIN IMMEDIATE')
        current, _ = event(eid, True)
        mutable(current)
        db().execute('DELETE FROM exclusions WHERE event=?', (eid,))
        db().executemany('INSERT OR IGNORE INTO exclusions VALUES(?,?,?)', [(eid, a, b) for a, b in pairs])
        db().commit()
        return jsonify(ok=True)

    def draw_options(row):
        participants = db().execute("SELECT id,user_id FROM participants WHERE event=? AND status='accepted'", (row['id'],)).fetchall()
        ids = [p['id'] for p in participants]
        blocked = {tuple(p) for p in db().execute('SELECT giver,receiver FROM exclusions WHERE event=?', (row['id'],))}
        return matching(ids, blocked), len(ids)

    @app.post('/api/events/<eid>/feasibility')
    def feasibility(eid):
        row, _ = event(eid, True)
        mutable(row)
        result, count = draw_options(row)
        return jsonify(possible=result is not None, accepted=count)

    @app.post('/api/events/<eid>/draw')
    def draw(eid):
        if data().get('confirmed') is not True:
            fail('Bitte bestätigen: Es werden nur Zusagen ausgelost. Die Auslosung ist endgültig.')
        c = db()
        c.execute('BEGIN IMMEDIATE')
        try:
            row, _ = event(eid, True)
            mutable(row)
            result, _ = draw_options(row)
            if result is None:
                fail('Keine gültige Auslosung möglich. Zusagen und Ausschlüsse prüfen.', 409)
            c.executemany('INSERT INTO assignments VALUES(?,?,?)', [(eid,a,b) for a,b in result.items()])
            c.execute('UPDATE events SET drawn=? WHERE id=?', (int(time.time()), eid))
            c.executemany('INSERT INTO draw_mail(event,participant) VALUES(?,?)', [(eid, pid) for pid in result])
            c.execute("UPDATE participants SET mail_status='queued',mailed=NULL WHERE event=? AND status='accepted'", (eid,))
            c.commit()
        except Exception:
            c.rollback()
            raise
        return jsonify(ok=True, message='Ausgelost. Benachrichtigungen werden automatisch im Hintergrund versendet; die Zuordnungen stehen ausschließlich im persönlichen Konto.')

    def join_event(row, name):
        mutable(row)
        uid = user()
        if db().execute('SELECT count(*) FROM participants WHERE event=?', (row['id'],)).fetchone()[0] >= 100:
            fail('Die Runde ist voll.')
        db().execute("INSERT INTO participants(event,user_id,name,status) VALUES(?,?,?,'accepted') ON CONFLICT(event,user_id) DO UPDATE SET status='accepted'", (row['id'], uid, name))
        return jsonify(id=row['id'])

    @app.get('/api/join/<code>')
    def public_event(code):
        row = db().execute('SELECT title,date,budget,invitation,drawn FROM events WHERE public_code=? AND (expires IS NULL OR expires>?)', (code,int(time.time()))).fetchone()
        if not row:
            fail('Anmeldelink nicht gefunden.', 404)
        return jsonify(dict(row))

    @app.post('/api/join/<code>')
    def public_join(code):
        user()
        name = text(data(), 'name', 100, True)
        db().execute('BEGIN IMMEDIATE')
        row = db().execute('SELECT * FROM events WHERE public_code=? AND (expires IS NULL OR expires>?)', (code,int(time.time()))).fetchone()
        if not row:
            fail('Anmeldelink nicht gefunden.', 404)
        result = join_event(row, name)
        db().commit()
        return result

    @app.post('/api/events/<eid>/join')
    def owner_join(eid):
        db().execute('BEGIN IMMEDIATE')
        row, _ = event(eid, True)
        result = join_event(row, text(data(), 'name', 100, True))
        db().commit()
        return result

    @app.post('/api/events/<eid>/remove')
    def remove(eid):
        db().execute('BEGIN IMMEDIATE')
        row, _ = event(eid, True)
        mutable(row)
        pid = data().get('participant')
        if type(pid) is not int:
            fail('Ungültige Person.')
        db().execute('DELETE FROM participants WHERE id=? AND event=?', (pid, eid))
        db().commit()
        return jsonify(ok=True)

    @app.post('/api/events/<eid>/remind')
    def remind(eid):
        row, _ = event(eid, True)
        pid = data().get('participant')
        if type(pid) is not int:
            fail('Bitte eine Person wählen.')
        member = db().execute('SELECT * FROM participants WHERE id=? AND event=?', (pid,eid)).fetchone()
        if not member:
            fail('Person nicht gefunden.',404)
        rate('remind-owner:' + str(user()), 100)
        rate('remind-member:' + str(pid), 3, 86400)
        intro = 'Die Auslosung ist fertig. Dein Wichtelkind findest du ausschließlich in deinem Konto.' if row['drawn'] else 'Bitte antworte auf die Einladung und ergänze deine Wünsche.'
        sent = send_link(member['user_id'], 'Erinnerung: ' + row['title'], row['invitation'] + '\n\n' + intro + '\nZugang gilt 7 Tage.', 7*86400)
        db().execute('UPDATE participants SET mail_status=?,mailed=? WHERE id=?', ('submitted' if sent else 'failed', int(time.time()),pid))
        return jsonify(submitted=int(sent), failed=int(not sent))

    @app.post('/api/events/<eid>/copy')
    def copy_event(eid):
        require_event_creator()
        db().execute('BEGIN IMMEDIATE')
        row, _ = event(eid, True)
        payload = data()
        selected = payload.get('participants', [])
        source = {p['id']:p for p in db().execute('SELECT id,user_id,name FROM participants WHERE event=?',(eid,))}
        if not isinstance(selected,list) or len(selected)>100 or any(type(x) is not int or x not in source for x in selected):
            fail('Ungültige Teilnehmerauswahl.')
        if db().execute('SELECT count(*) FROM events WHERE owner=?',(user(),)).fetchone()[0] >= 30:
            fail('Maximal 30 Runden pro Konto.')
        settings = dict(row)
        settings.update(title=payload.get('title'), date=payload.get('date'), postal=bool(row['postal']), history=bool(row['history']))
        values = event_values(settings)
        new_id = secrets.token_urlsafe(16)
        code = secrets.token_urlsafe(24) if row['public_code'] else None
        db().execute('INSERT INTO events(id,owner,title,date,budget,invitation,postal,retention,expires,history,public_code,previous,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (new_id,user(),*values,code,None,int(time.time())))
        mapping = {}
        for old_id in set(selected):
            person = source[old_id]
            mapping[old_id] = db().execute('INSERT INTO participants(event,user_id,name) VALUES(?,?,?)',(new_id,person['user_id'],person['name'])).lastrowid
        if payload.get('copy_exclusions') is True:
            for a,b in db().execute('SELECT giver,receiver FROM exclusions WHERE event=?',(eid,)).fetchall():
                if a in mapping and b in mapping:
                    db().execute('INSERT INTO exclusions VALUES(?,?,?)',(new_id,mapping[a],mapping[b]))
        db().commit()
        return jsonify(id=new_id, message='Kopie erstellt. Keine Wünsche, Adressen oder Zusagen übernommen. Einladungen über „Erinnerung senden“ verschicken.')

    @app.post('/api/events/<eid>/retention')
    def retention(eid):
        row, _ = event(eid, True)
        payload = data()
        months = payload.get('retention')
        if type(months) is not int or months not in (0,6,12,24,60):
            fail('Ungültige Aufbewahrung.')
        event_day = date.fromisoformat(row['date'])
        expires = int(time.time()) + (max(0,(event_day-date.today()).days) + months*31 + 1)*86400 if months else None
        db().execute('UPDATE events SET retention=?,expires=?,history=? WHERE id=?',(months,expires,int(payload.get('history') is True),eid))
        return jsonify(ok=True)

    @app.post('/api/events/<eid>/delete')
    def delete_event(eid):
        event(eid, True)
        if data().get('confirm') != 'LÖSCHEN':
            fail('Bitte LÖSCHEN bestätigen.')
        db().execute('DELETE FROM events WHERE id=?',(eid,))
        return jsonify(ok=True)

    @app.post('/api/account/delete')
    def delete_account():
        uid = user()
        if data().get('confirm') != 'LÖSCHEN':
            fail('Bitte LÖSCHEN bestätigen.')
        db().execute('DELETE FROM users WHERE id=?',(uid,))
        return jsonify(ok=True)

    @app.cli.command('send-draw-mail')
    def send_draw_mail():
        # One transaction per delivery serializes workers; crash recovery is at-least-once.
        # Never backfill old draws: only the draw endpoint creates queue entries.
        processed = 0
        for _ in range(100):
            c = db()
            c.execute('BEGIN IMMEDIATE')
            try:
                now = int(time.time())
                job = c.execute("SELECT q.*,p.user_id,e.title FROM draw_mail q JOIN participants p ON p.id=q.participant JOIN events e ON e.id=q.event WHERE q.status='queued' AND q.next_attempt<=? AND e.drawn IS NOT NULL AND (e.expires IS NULL OR e.expires>?) ORDER BY q.next_attempt LIMIT 1", (now,now)).fetchone()
                if not job:
                    c.rollback()
                    break
                sent = send_link(job['user_id'], 'Ausgelost: ' + job['title'], 'Die Auslosung ist fertig. Dein Wichtelkind findest du ausschließlich in deinem Konto. Zugang gilt 7 Tage.', 7*86400)
                attempts = job['attempts'] + 1
                status = 'submitted' if sent else ('failed' if attempts >= 8 else 'queued')
                delay = min(86400, 60 * 2 ** min(attempts, 10))
                c.execute('UPDATE draw_mail SET status=?,attempts=?,next_attempt=? WHERE event=? AND participant=?', (status,attempts,now+delay,job['event'],job['participant']))
                c.execute('UPDATE participants SET mail_status=?,mailed=? WHERE id=?', ('submitted' if sent else ('failed' if status=='failed' else 'retrying'),now,job['participant']))
                c.commit()
                processed += 1
            except Exception:
                c.rollback()
                raise
        print(f'Draw notifications processed: {processed}')

    @app.cli.command('cleanup')
    def cleanup():
        now = int(time.time())
        c = db()
        c.execute('BEGIN IMMEDIATE')
        deleted = c.execute('DELETE FROM events WHERE expires IS NOT NULL AND expires<?',(now,)).rowcount
        c.execute('DELETE FROM tokens WHERE expires<?',(now,))
        c.execute('DELETE FROM sessions WHERE expires<?',(now,))
        c.execute('DELETE FROM limits WHERE expires<?',(now,))
        c.commit()
        print(f'Expired events removed: {deleted}')

    return app


def matching(people, blocked):
    """Randomized augmenting paths: complete matching, not uniformly distributed."""
    if len(people) < 2:
        return None
    rng = secrets.SystemRandom()
    options = {a: [b for b in people if a != b and (a, b) not in blocked] for a in people}
    for choices in options.values():
        rng.shuffle(choices)
    receivers = {}

    def augment(a, seen):
        for b in options[a]:
            if b in seen:
                continue
            seen.add(b)
            if b not in receivers or augment(receivers[b], seen):
                receivers[b] = a
                return True
        return False

    order = list(people)
    rng.shuffle(order)
    if not all(augment(a, set()) for a in order):
        return None
    return {a: b for b, a in receivers.items()}
