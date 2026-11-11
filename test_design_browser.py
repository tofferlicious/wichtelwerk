"""Browser regression for creator-only controls and stylized local artwork."""
import os
from pathlib import Path
import threading
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from test_creation_permissions import app_for, login, post, payload, ADMIN, OTHER


def test_creator_controls_and_stylized_art(tmp_path):
    app = app_for(tmp_path, EVENT_CREATOR_EMAILS=ADMIN, PUBLIC_EVENT_CREATION=True)
    guest = login(app, OTHER)
    legacy = post(guest, '/api/events', payload()).json['id']
    app.config['PUBLIC_EVENT_CREATION'] = False
    admin = login(app, ADMIN)
    own = post(admin, '/api/events', payload()).json['id']
    server = make_server('127.0.0.1', 0, app, threaded=True)
    url = f'http://127.0.0.1:{server.server_port}'
    app.config['BASE_URL'] = url
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    artifacts = Path(__file__).parent/'artifacts'
    artifacts.mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            executable = os.environ.get('CHROME_PATH', p.chromium.executable_path)
            browser = p.chromium.launch(executable_path=executable, args=['--no-sandbox'])
            try:
                errors = []
                anonymous = browser.new_page(locale='de-DE')
                anonymous.on('pageerror', lambda error: errors.append(str(error)))
                external = []
                anonymous.on('request', lambda request: external.append(request.url)
                             if urlparse(request.url).netloc != urlparse(url).netloc else None)
                for width, height in [(1280,800), (390,844)]:
                    anonymous.set_viewport_size({'width':width,'height':height})
                    anonymous.goto(url)
                    expect(anonymous.get_by_role('heading',name='Kleine Geste. Große Freude.')).to_be_visible()
                    images = anonymous.locator('[data-festive-photo]')
                    expect(images).to_have_count(2)
                    for image in images.all():
                        assert image.get_attribute('src').endswith('.svg')
                        image.scroll_into_view_if_needed()
                        anonymous.wait_for_function('(img) => img.complete && img.naturalWidth > 0',arg=image.element_handle())
                    assert anonymous.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    anonymous.screenshot(path=str(artifacts/f'homepage-{width}.png'),full_page=True)
                assert not external, external
                for client, creator, event_id in [(guest,False,legacy),(admin,True,own)]:
                    context = browser.new_context(locale='de-DE')
                    context.add_cookies([{'name':'ww_session','value':client.get_cookie('ww_session').value,'url':url}])
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    for width in [1280,390,320]:
                        page.set_viewport_size({'width':width,'height':844})
                        page.goto(url+'/#dashboard')
                        expect(page.get_by_role('heading',name='Meine Wichtelrunden')).to_be_visible()
                        for link in page.locator('.site-header a').all():
                            box = link.bounding_box()
                            assert box and box['x'] >= 0 and box['x']+box['width'] <= width, box
                        assert page.locator('a[href="#new"]').count() == (1 if creator else 0)
                        page.goto(url+'/#new')
                        if creator:
                            expect(page.locator('form[data-form="create"]')).to_be_visible()
                        else:
                            expect(page.get_by_text('Runden erstellt die Organisation.',exact=True)).to_be_visible()
                            assert page.locator('form[data-form="create"]').count() == 0
                        page.goto(url+'/#event='+event_id)
                        expect(page.get_by_role('heading',name='Private test round',exact=True)).to_be_visible()
                        assert page.locator('form[data-form="copy"]').count() == (1 if creator else 0)
                        assert page.locator('form[data-form="retention"]').count() == 1
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    context.close()
                assert not errors, errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
