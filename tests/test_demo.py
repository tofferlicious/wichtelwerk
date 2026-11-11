"""Exercise the actual frontend as a read-only, subpath-hosted static demo."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import threading

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def test_static_demo_navigation_language_and_no_data_submission(tmp_path):
    builder = ROOT/'scripts/build_demo.py'
    assert builder.is_file(), 'Static demo builder is missing'
    subprocess.run([sys.executable, str(builder), str(tmp_path/'wichtelwerk')], check=True)
    assert {p.name for p in (tmp_path/'wichtelwerk').iterdir()} == {'static', 'index.html', 'demo.js', '.nojekyll'}
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/wichtelwerk/'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('CHROME_PATH', p.chromium.executable_path))
            context = browser.new_context(locale='en-US', viewport={'width': 390, 'height': 844})
            page = context.new_page()
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url))
            page.goto(url)
            expect(page.get_by_role('heading', name='Small gesture. Great joy.')).to_be_visible()
            expect(page.locator('#demo-banner')).to_contain_text('No emails')
            page.wait_for_function('document.querySelector(".hero-photo img").naturalWidth > 0')
            page.get_by_role('button', name='Deutsch', exact=True).click()
            expect(page.get_by_role('heading', name='Kleine Geste. Große Freude.')).to_be_visible()
            expect(page.locator('#demo-banner')).to_contain_text('Keine E-Mails')
            page.get_by_role('button', name='English', exact=True).click()
            page.locator('#demo-banner a[href="#dashboard"]').click()
            expect(page.get_by_role('heading', name='My Secret Santa rounds')).to_be_visible()
            expect(page.locator('.event-card')).to_have_count(2)
            page.locator('#demo-banner a[href="#event=demo-owner"]').click()
            expect(page.get_by_role('heading', name='Who must not draw whom?')).to_be_visible()
            wishes = page.locator('[name=wishes]')
            original = wishes.input_value()
            wishes.fill('This must never leave the browser')
            page.get_by_role('button', name='Save wishes').click()
            expect(page.locator('#notice')).to_contain_text('Demo:')
            page.reload()
            expect(page.locator('[name=wishes]')).to_have_value(original)
            page.locator('#demo-banner a[href="#event=demo-guest"]').click()
            expect(page.get_by_role('heading', name='You are giving to …')).to_be_visible()
            page.locator('#demo-banner a[href="#new"]').click()
            expect(page.get_by_role('heading', name='Who are you bringing together?')).to_be_visible()
            page.goto(url+'#login')
            page.locator('[name=email]').fill('synthetic@example.invalid')
            page.locator('form button').click()
            expect(page.locator('#notice')).to_contain_text('Demo:')
            page.set_viewport_size({'width': 320, 'height': 844})
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert not errors, errors
            assert all(request.startswith(url) for request in requests), requests
            assert not any('/api/' in request for request in requests), requests
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
