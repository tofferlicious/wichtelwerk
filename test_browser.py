import re
import os
import pytest
import threading
from datetime import date, timedelta
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect
from wichtelwerk import create_app


def test_browser_round_lifecycle(tmp_path):
    app = create_app({'TESTING': True, 'MAIL_MODE': 'memory', 'COOKIE_SECURE': False, 'DATABASE': str(tmp_path/'test.db'), 'BASE_URL': 'http://127.0.0.1:18765', 'EVENT_CREATOR_EMAILS': 'owner@example.invalid', 'PUBLIC_EVENT_CREATION': False})
    server = make_server('127.0.0.1', 18765, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:18765'
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH', p.chromium.executable_path))
        contexts=[]
        def login(email):
            ctx=browser.new_context(); contexts.append(ctx); page=ctx.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url+'/#login')
            page.locator('[name=email]').fill(email)
            page.get_by_role('button',name='Anmeldelink senden').click()
            expect(page.locator('#notice')).to_contain_text('Mailserver')
            token=re.search(r'#token=([^\s]+)',app.extensions['outbox'][-1]['body']).group(1)
            page.goto(url+'/#token='+token)
            page.get_by_role('button',name='Sicher anmelden').click()
            expect(page.get_by_role('heading',name='Meine Wichtelrunden')).to_be_visible()
            return page
        def api(page,path,payload=None):
            return page.evaluate('async ([path,payload])=>{const m=await (await fetch("/api/me")).json();const r=await fetch("/api"+path,payload===null?{}:{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":m.csrf},body:JSON.stringify(payload)});return {status:r.status,data:await r.json()}}',[path,payload])
        owner=login('owner@example.invalid')
        owner.get_by_role('link',name='+ Neue Runde').click()
        owner.locator('[name=title]').fill('Browser Weihnachtsrunde')
        owner.locator('[name=date]').fill((date.today()+timedelta(days=40)).isoformat())
        owner.locator('[name=postal]').check()
        owner.get_by_role('button',name='Runde erstellen').click()
        expect(owner.get_by_role('heading',name='Browser Weihnachtsrunde')).to_be_visible()
        eid=owner.url.split('event=')[1]
        owner.locator('form[data-form=owner-join] [name=name]').fill('Owner')
        owner.get_by_role('button',name='Ich bin dabei',exact=True).click()
        expect(owner.get_by_role('heading',name='Hallo, Owner.')).to_be_visible()
        pages=[owner]
        for i in range(2):
            form=owner.locator('form[data-form=invite]');form.locator('[name=name]').fill('Person '+str(i));form.locator('[name=email]').fill(f'person{i}@example.invalid');form.get_by_role('button').click()
            expect(owner.locator('.roster')).to_contain_text(f'person{i}@example.invalid')
            page=login(f'person{i}@example.invalid');page.goto(url+'/#event='+eid)
            page.get_by_role('button',name='Ja, ich mache mit').click()
            expect(page.locator('.pill').filter(has_text='Dabei')).to_be_visible()
            pages.append(page)
        base='/events/'+eid
        event=api(owner,base)['data']; ids=[x['id'] for x in event['participants']]
        assert api(owner,base+'/exclusions',{'pairs':[[ids[0],ids[1]],[ids[1],ids[2]]]})['status']==200
        assert api(owner,base+'/feasibility',{})['data']['possible']
        owner.reload();owner.on('dialog',lambda d:d.accept())
        owner.locator('[data-action=draw]').click()
        expect(owner.get_by_text('Du schenkst an …')).to_be_visible()
        assert api(owner,base+'/draw',{'confirmed':True})['status']==409
        views=[api(page,base)['data'] for page in pages]
        assert all(v['recipient'] for v in views)
        assert len({v['recipient']['id'] for v in views})==3
        assert 'participants' not in views[1]
        pages[1].reload();pages[1].locator('[name=wishes]').fill('Bücher nach der Auslosung');pages[1].get_by_role('button',name='Wünsche speichern').click()
        expect(pages[1].locator('#notice')).to_contain_text('gespeichert')
        giver=next(page for page,v in zip(pages,views) if v['recipient']['id']==ids[1])
        giver.reload();expect(giver.get_by_text('Bücher nach der Auslosung',exact=True)).to_be_visible()
        copy=api(owner,base+'/copy',{'title':'Folgejahr','date':(date.today()+timedelta(days=400)).isoformat(),'participants':ids,'copy_exclusions':True,'avoid_previous':True})
        assert copy['status']==200
        copied=api(owner,'/events/'+copy['data']['id'])['data']
        assert len(copied['participants'])==3 and len(copied['exclusions'])==2
        assert all(x['status']=='pending' for x in copied['participants'])
        owner.set_viewport_size({'width':390,'height':844});owner.goto(url+'/#dashboard')
        expect(owner.get_by_role('heading',name='Meine Wichtelrunden')).to_be_visible()
        assert owner.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
    server.shutdown()


@pytest.mark.skipif(not os.environ.get("WICHTEL_TEST_URL"), reason="Set WICHTEL_TEST_URL for an optional read-only deployment check")
def test_production_public_browser():
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH', p.chromium.executable_path));page=browser.new_page(viewport={'width':390,'height':844});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        response=page.goto(os.environ['WICHTEL_TEST_URL'].rstrip('/'))
        assert response.status==200
        expect(page.get_by_role('heading',name='Kleine Geste. Große Freude.')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='production-mobile.png',full_page=True)
        page.goto(os.environ['WICHTEL_TEST_URL'].rstrip('/')+'/#login')
        expect(page.get_by_role('button',name='Anmeldelink senden')).to_be_visible()
        assert not errors
        browser.close()
