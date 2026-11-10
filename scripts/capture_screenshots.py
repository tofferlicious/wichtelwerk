"""Capture actual app screens using a disposable, synthetic local round.

Run: python scripts/capture_screenshots.py (requires requirements-dev.txt).
No production server, database, account or email transport is used.
"""
from datetime import date, timedelta
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wichtelwerk import create_app


def main():
    output = ROOT/'docs/screenshots'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wichtelwerk-screenshots-') as tmp:
        app = create_app({'TESTING': True, 'COOKIE_SECURE': False, 'MAIL_MODE': 'memory',
                          'DATABASE': str(Path(tmp)/'demo.db'),
                          'BASE_URL': 'http://localhost', 'PUBLIC_EVENT_CREATION': False,
                          'EVENT_CREATOR_EMAILS': 'alex@example.invalid'})

        def post(client, path, payload):
            csrf = client.get('/api/me').json['csrf']
            response = client.post('/api'+path, json=payload, headers={'X-CSRF-Token':csrf})
            assert response.status_code == 200, (path, response.status_code, response.json)
            return response.json

        def sign_in(email):
            client = app.test_client()
            post(client, '/login', {'email':email})
            match = re.search(r'#token=([^\s]+)', app.extensions['outbox'][-1]['body'])
            assert match, 'Synthetic login email did not contain a sign-in link'
            post(client, '/auth', {'token':match.group(1)})
            return client

        owner = sign_in('alex@example.invalid')
        day = (date.today()+timedelta(days=40)).isoformat()
        event = post(owner, '/events', {'title':'Wichteln im Freundeskreis', 'date':day,
                     'budget':'25 €', 'invitation':'Ein schöner Abend, ein kleines Geschenk und Zeit füreinander.'})['id']
        base = '/events/'+event
        post(owner, base+'/join', {'name':'Alex'})
        post(owner, base+'/wishes', {'wishes':'Ein gutes Buch oder etwas für den Garten. Ich mag natürliche Materialien.'})
        people = [
            ('Lina', 'lina@example.invalid', 'Ein Notizbuch, Kräutertee oder ein kleines Puzzle. Meine Lieblingsfarbe ist Grün.'),
            ('Jonas', 'jonas@example.invalid', 'Kaffee, ein spannender Krimi oder eine Kleinigkeit für meine Küche.'),
            ('Mara', 'mara@example.invalid', 'Etwas zum Zeichnen, ein schönes Lesezeichen oder eine kleine Pflanze.'),
        ]
        guests = []
        for name, email, wishes in people:
            post(owner, base+'/invite', {'name':name, 'email':email})
            client = sign_in(email)
            post(client, base+'/respond', {'status':'accepted'})
            post(client, base+'/wishes', {'wishes':wishes})
            guests.append(client)
        post(owner, '/events', {'title':'Wichteln im Team', 'date':day, 'budget':'15 €'})
        post(owner, base+'/draw', {'confirmed':True})

        server = make_server('127.0.0.1', 0, app, threaded=True)
        url = f'http://127.0.0.1:{server.server_port}'
        app.config['BASE_URL'] = url
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        errors, external = [], []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('CHROME_PATH', p.chromium.executable_path))
                try:
                    def page_for(client=None, locale='de-DE'):
                        context = browser.new_context(viewport={'width':1360,'height':900},
                                  locale=locale, timezone_id='Europe/Berlin', reduced_motion='reduce',
                                  device_scale_factor=1, color_scheme='light')
                        if client:
                            context.add_cookies([{'name':'ww_session','value':client.get_cookie('ww_session').value,'url':url}])
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('request', lambda request: external.append(request.url)
                                if urlparse(request.url).netloc != urlparse(url).netloc else None)
                        return page

                    def capture(page, name, full_page=False):
                        page.evaluate('document.fonts.ready')
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), name
                        assert page.evaluate('document.body.scrollWidth <= innerWidth'), name
                        page.screenshot(path=str(output/name), full_page=full_page)

                    home = page_for()
                    home.goto(url)
                    expect(home.get_by_role('heading', name='Kleine Geste. Große Freude.')).to_be_visible()
                    home.wait_for_function('document.querySelector(".hero-photo img")?.naturalWidth > 0')
                    capture(home, 'home-desktop.png')
                    english = page_for(locale='en-US')
                    english.goto(url)
                    expect(english.get_by_role('heading', name='Small gesture. Great joy.')).to_be_visible()
                    english.wait_for_function('document.querySelector(".hero-photo img")?.naturalWidth > 0')
                    capture(english, 'home-english.png')
                    dashboard = page_for(owner)
                    dashboard.goto(url+'/#dashboard')
                    expect(dashboard.locator('.event-card')).to_have_count(2)
                    capture(dashboard, 'dashboard.png')
                    recipient = page_for(guests[0])
                    recipient.goto(url+'/#event='+event)
                    expect(recipient.locator('.recipient-name')).to_be_visible()
                    expect(recipient.locator('.recipient-wishes')).to_be_visible()
                    capture(recipient, 'recipient.png', full_page=True)
                    recipient.set_viewport_size({'width':390,'height':844})
                    capture(recipient, 'mobile.png', full_page=True)
                    assert not errors, errors
                    assert not external, external
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
        expected = {'home-desktop.png','home-english.png','dashboard.png','recipient.png','mobile.png'}
        assert {p.name for p in output.glob('*.png')} == expected
        for name in sorted(expected):
            target = output/name
            assert target.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
            print(f'Captured {target.relative_to(ROOT)} ({target.stat().st_size} bytes)')
        print('Synthetic data only; memory email only; temporary database removed on exit.')


if __name__ == '__main__':
    main()
