"""Browser coverage for explicit German/English frontend localization."""
import json
import os
import threading
from copy import deepcopy

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from .test_creation_permissions import app_for


CHROME = os.environ.get('CHROME_PATH')


def serve(app):
    server = make_server('127.0.0.1', 0, app, threaded=True)
    url = f'http://127.0.0.1:{server.server_port}'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, url


def api_fixture(user=None):
    return {
        'me': {'user': user, 'csrf': 'csrf-test', 'can_create_events': True},
        'events': [],
        'event': {
            'id': 'event-1', 'title': '<b>User round</b>', 'date': '2026-12-24',
            'budget': '<i>User budget</i>', 'invitation': '<script>User invitation</script>',
            'organizer': True, 'drawn': False, 'postal': True, 'public_code': 'public-code',
            'retention': 24, 'expires': 1830297600,
            'membership': {'name': '<em>User name</em>', 'status': 'pending',
                           'wishes': '<img src=x onerror=alert(1)>User wish',
                           'address': '<strong>User address</strong>'},
            'recipient': None,
            'participants': [
                {'id': 1, 'name': '<u>Alice</u>', 'email': 'alice@example.invalid',
                 'status': 'accepted', 'mail_status': 'submitted', 'mailed': 1796947200},
                {'id': 2, 'name': 'Bob', 'email': 'bob@example.invalid',
                 'status': 'pending', 'mail_status': 'retrying', 'mailed': None},
                {'id': 3, 'name': 'Carla', 'email': 'carla@example.invalid',
                 'status': 'declined', 'mail_status': 'failed', 'mailed': None},
            ],
            'exclusions': [[1, 2]],
        },
    }


def install_api(page, state, requests):
    def handle(route):
        request = route.request
        path = request.url.split('/api', 1)[1]
        body = json.loads(request.post_data) if request.post_data else None
        requests.append((request.method, path, request.headers.get('accept-language'), body))
        if path == '/me':
            data = state['me']
        elif path == '/events':
            data = {'events': state['events']}
        elif path == '/events/event-1':
            data = state['event']
        elif path == '/language':
            data = {'ok': True, 'language': body['language']}
        else:
            data = {'ok': True, 'id': 'event-1', 'message': 'Server message',
                    'submitted': 1, 'failed': 0, 'possible': True, 'accepted': 2}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data))
    page.route('**/api/**', handle)


def new_page(browser, url, *, locale='de-DE', saved=None, broken_storage=False, user=None):
    context = browser.new_context(locale=locale, viewport={'width': 390, 'height': 844})
    if saved:
        context.add_init_script(f"localStorage.setItem('ww_language', {json.dumps(saved)})")
    if broken_storage:
        context.add_init_script("""
            Storage.prototype.getItem = () => { throw new Error('storage disabled') };
            Storage.prototype.setItem = () => { throw new Error('storage disabled') };
        """)
    page = context.new_page()
    state = api_fixture(user)
    requests = []
    install_api(page, state, requests)
    page.goto(url)
    return context, page, state, requests


def test_language_detection_override_storage_failure_and_switch(tmp_path):
    app = app_for(tmp_path)
    server, thread, url = serve(app)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME or p.chromium.executable_path,
                                        args=['--no-sandbox'])
            cases = [
                ('en-US', None, False, 'en', 'Small gesture.'),
                ('de-AT', None, False, 'de', 'Kleine Geste.'),
                ('fr-FR', None, False, 'de', 'Kleine Geste.'),
                ('en-US', 'de', False, 'de', 'Kleine Geste.'),
                ('en-US', None, True, 'en', 'Small gesture.'),
            ]
            for locale, saved, broken, language, heading in cases:
                context, page, _, requests = new_page(
                    browser, url, locale=locale, saved=saved, broken_storage=broken)
                expect(page.get_by_role('heading', name=heading, exact=False)).to_be_visible()
                assert page.evaluate('document.documentElement.lang') == language
                assert all(method != 'POST' or path != '/language' for method, path, _, _ in requests)
                assert not page.locator('script[src^="http"], link[href^="http"]').count()
                context.close()

            user = {'id': 9, 'email': 'owner@example.invalid', 'language': None}
            context, page, _, requests = new_page(browser, url, locale='en-US', user=user)
            expect(page.get_by_role('button', name='Deutsch')).to_be_visible()
            page.get_by_role('button', name='Deutsch').click()
            expect(page.get_by_role('heading', name='Meine Wichtelrunden')).to_be_visible()
            assert page.evaluate("localStorage.getItem('ww_language')") == 'de'
            assert page.evaluate('document.documentElement.lang') == 'de'
            page.reload()
            expect(page.get_by_role('heading', name='Meine Wichtelrunden')).to_be_visible()
            language_posts = [r for r in requests if r[0] == 'POST' and r[1] == '/language']
            assert language_posts[-1][3] == {'language': 'de'}
            assert language_posts[-1][2] == 'de'
            for width in (320, 390):
                page.set_viewport_size({'width': width, 'height': 844})
                page.reload()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                for item in page.locator('.site-header a, .site-header button').all():
                    box = item.bounding_box()
                    assert box and box['x'] >= 0 and box['x'] + box['width'] <= width, box
            context.close()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_english_all_views_states_headers_dates_and_user_content(tmp_path):
    app = app_for(tmp_path)
    server, thread, url = serve(app)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME or p.chromium.executable_path,
                                        args=['--no-sandbox'])
            user = {'id': 9, 'email': 'owner@example.invalid', 'language': 'en'}
            context, page, state, requests = new_page(browser, url, locale='en-US', user=user)

            state['events'] = [{
                'id': 'event-1', 'title': '<b>User round</b>', 'date': '2026-12-24',
                'budget': '<i>User budget</i>', 'drawn': False, 'owner': 9,
            }]
            page.goto(url + '/#dashboard')
            expect(page.get_by_role('heading', name='My Secret Santa rounds')).to_be_visible()
            expect(page.get_by_text('December 24, 2026', exact=True)).to_be_visible()
            expect(page.get_by_text('<b>User round</b>', exact=True)).to_be_visible()
            assert page.locator('b', has_text='User round').count() == 0

            page.goto(url + '/#new')
            expect(page.get_by_role('heading', name='Who are you bringing together?')).to_be_visible()
            assert page.locator('[name=title]').get_attribute('placeholder') == 'Christmas with favorite people'

            page.goto(url + '/#account')
            expect(page.get_by_role('heading', name='Until next time.')).to_be_visible()
            expect(page.get_by_text('owner@example.invalid', exact=True)).to_be_visible()

            page.goto(url + '/#privacy')
            expect(page.get_by_role('heading', name='Private stays personal.')).to_be_visible()
            expect(page.get_by_role('heading', name='What is stored?')).to_be_visible()
            expect(page.get_by_role('heading', name='Public join links')).to_be_visible()

            page.goto(url + '/#about')
            expect(page.get_by_role('heading', name='For genuine anticipation.')).to_be_visible()

            page.goto(url + '/#token=secret')
            expect(page.get_by_role('heading', name='Welcome to Wichtelwerk.')).to_be_visible()

            page.goto(url + '/#event=event-1')
            expect(page.get_by_text('1 accepted · 1 awaiting reply · 1 declined', exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name='Who must not draw whom?')).to_be_visible()
            expect(page.get_by_text('<script>User invitation</script>', exact=True)).to_be_visible()
            expect(page.get_by_text('<img src=x onerror=alert(1)>User wish', exact=True)).to_be_visible()
            assert page.locator('script', has_text='User invitation').count() == 0
            assert page.locator('img[src=x]').count() == 0
            expect(page.get_by_text('12/11/26', exact=False)).to_be_visible()

            state['event']['organizer'] = False
            state['event'].pop('participants')
            state['event'].pop('exclusions')
            for status, label in [('pending', 'Awaiting reply'), ('accepted', 'Participating'),
                                  ('declined', 'Declined')]:
                state['event']['membership']['status'] = status
                page.reload()
                expect(page.locator('.pill').filter(has_text=label)).to_be_visible()
                expect(page.get_by_role('heading', name='Hello, <em>User name</em>.')).to_be_visible()

            state['event']['drawn'] = True
            state['event']['recipient'] = {
                'id': 2, 'name': '<u>Recipient</u>', 'wishes': '<b>Recipient wish</b>',
                'address': '<i>Recipient address</i>',
            }
            page.reload()
            expect(page.get_by_role('heading', name='You are giving to …')).to_be_visible()
            expect(page.get_by_text('<u>Recipient</u>', exact=True)).to_be_visible()
            expect(page.get_by_text('<b>Recipient wish</b>', exact=True)).to_be_visible()
            assert page.locator('u', has_text='Recipient').count() == 0

            assert requests
            assert all(language == 'en' for _, _, language, _ in requests)
            assert any(method == 'GET' for method, _, _, _ in requests)
            page.locator('[name=wishes]').fill('Unchanged <user> content')
            page.get_by_role('button', name='Save wishes').click()
            assert any(method == 'POST' and language == 'en' for method, _, language, _ in requests)
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            context.close()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_localized_delete_confirmations(tmp_path):
    app = app_for(tmp_path)
    server, thread, url = serve(app)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME or p.chromium.executable_path,
                                        args=['--no-sandbox'])
            user = {'id': 9, 'email': 'owner@example.invalid', 'language': None}
            for locale, answer, prompt_text in [
                ('en-US', 'DELETE', 'Type DELETE'), ('de-DE', 'LÖSCHEN', 'Tippe LÖSCHEN')
            ]:
                context, page, _, requests = new_page(browser, url, locale=locale, user=user)
                page.goto(url + '/#event=event-1')
                dialogs = []
                page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.accept(answer)))
                page.locator('details').filter(has=page.get_by_text(
                    'Permanently delete round' if locale == 'en-US' else 'Runde endgültig löschen',
                    exact=True)).locator('summary').click()
                page.get_by_role('button', name='Delete round' if locale == 'en-US' else 'Runde löschen').click()
                page.wait_for_timeout(50)
                assert prompt_text in dialogs[-1]
                delete = [r for r in requests if r[1].endswith('/delete')][-1]
                assert delete[3] == {'confirm': answer}
                context.close()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
