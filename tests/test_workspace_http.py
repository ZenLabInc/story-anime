"""HTTP boundary checks with an isolated database and no paid calls."""
import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from app import studio as s, gemini
from app.server import Handler

class WorkspaceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA,s.DB,gemini.ENABLED
        s.DATA=Path(self.tmp.name);s.DB=s.DATA/'studio.db';gemini.ENABLED=False;s.init()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.client.open(self.base+'/app').read()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();s.DATA,s.DB,gemini.ENABLED=self.old;self.tmp.cleanup()
    def call(self,path,body=None,client=None,headers=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers or {'Content-Type':'application/json','X-Story-Anime':'local'})
        with (client or self.client).open(req) as response:return json.load(response)
    def test_chat_stream_flush_and_public_filter(self):
        def fake(user,b,on_text=None):
            on_text('返答の途中')
            return {'id':'demo','api':{'secret':'hidden'},'chats':[]}
        with patch('app.manga_agent.chat',side_effect=fake):
            req=urllib.request.Request(self.base+'/api/project/chat/stream',data=b'{}',headers={'Content-Type':'application/json','X-Story-Anime':'local'})
            with self.client.open(req) as response:
                self.assertIn('text/event-stream',response.headers['Content-Type'])
                text=response.read().decode()
                self.assertIn('event: reply',text);self.assertIn('返答の途中',text);self.assertIn('event: done',text);self.assertNotIn('secret',text)

    def test_public_landing_and_private_workspace_boundaries(self):
        with urllib.request.urlopen(self.base+'/') as r:
            page=r.read().decode();self.assertIsNone(r.headers.get('Set-Cookie'))
            self.assertIn('og:image',page);self.assertNotIn('/ads.js',self.client.open(self.base+'/app').read().decode())
        with urllib.request.urlopen(self.base+'/app') as r:
            self.assertIn('noindex',r.read().decode());self.assertIsNotNone(r.headers.get('Set-Cookie'))
        for removed in ['/api/ads-config','/ads.txt','/ads.js']:
            with self.assertRaises(urllib.error.HTTPError) as ads_config:self.call(removed)
            self.assertEqual(ads_config.exception.code,404);ads_config.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as bad:
            self.call('/api/billing/webhook',{'id':'unsigned'},headers={'Content-Type':'application/json'})
        self.assertIn(bad.exception.code,(400,503));bad.exception.close()
    def test_deep_pages_require_login_and_serve_shared_shell(self):
        from app import accounts
        previous=accounts.DEV_AUTH;accounts.DEV_AUTH=True
        try:
            url='/app/manga/example/materials/world'
            with self.client.open(self.base+url) as r:
                self.assertIn('/login?next=',r.url)
                self.assertNotIn('/navigation.js',r.read().decode())
            x=self.call('/api/auth/email/start',{'email':'routes@example.test'})
            self.call('/api/auth/email/finish',{'challenge':x['challenge'],'code':x['dev_code']})
            for url in ['/app/account','/app/new','/app/manga/example','/app/manga/example/materials/world']:
                with self.client.open(self.base+url) as r:
                    self.assertEqual(r.url,self.base+url);self.assertIn('/navigation.js',r.read().decode())
            with self.client.open(self.base+'/router.js') as r:self.assertIn('YourStoryRouter',r.read().decode())
        finally:accounts.DEV_AUTH=previous

    def test_project_routes_revision_and_owner(self):
        p=self.call('/api/project/new',{'title':'HTTP確認'})
        catalog=self.call('/api/projects');self.assertEqual(catalog['projects'][0]['id'],p['id'])
        self.assertEqual(self.call('/api/work/'+p['id'])['title'],'HTTP確認')
        p2=self.call('/api/project/edit',dict(id=p['id'],revision=p['revision'],op='world_save',text='世界'))
        with self.assertRaises(urllib.error.HTTPError) as stale:self.call('/api/project/edit',dict(id=p['id'],revision=p['revision'],op='character_new'))
        self.assertEqual(stale.exception.code,400);stale.exception.close()
        other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));other.open(self.base).read()
        with self.assertRaises(urllib.error.HTTPError) as denied:self.call('/api/work/'+p['id'],client=other)
        self.assertEqual(denied.exception.code,403);denied.exception.close()
        self.assertEqual(self.call('/api/work/'+p['id'])['world']['text'],'世界')
    def test_old_generation_routes_disabled_and_csrf(self):
        with self.assertRaises(urllib.error.HTTPError) as old:self.call('/api/new',{'title':'旧制作'})
        self.assertEqual(old.exception.code,400);old.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as csrf:self.call('/api/project/new',{'title':'拒否'},headers={'Origin':'https://example.com','X-Story-Anime':'local'})
        self.assertEqual(csrf.exception.code,403);csrf.exception.close()
    def test_disabled_ai_does_not_call_provider(self):
        p=self.call('/api/project/new',{'title':'オフライン'})
        with patch('app.gemini.text') as provider:
            with self.assertRaises(urllib.error.HTTPError) as disabled:self.call('/api/project/chat',dict(id=p['id'],revision=p['revision'],context='world',text='おまかせ'))
            disabled.exception.close();provider.assert_not_called()
        self.assertIsNone(self.call('/api/work/'+p['id'])['busy'])
    def test_passwordless_login_survives_reload_and_logout_revokes(self):
        from app import accounts,membership
        previous=accounts.DEV_AUTH,membership.ENFORCE
        accounts.DEV_AUTH=True;membership.ENFORCE=True
        try:
            with self.assertRaises(urllib.error.HTTPError) as blocked:self.call('/api/project/new',{'title':'not logged in'})
            self.assertEqual(blocked.exception.code,403);blocked.exception.close()
            x=self.call('/api/auth/email/start',{'email':'http@example.test'})
            self.call('/api/auth/email/finish',{'challenge':x['challenge'],'code':x['dev_code']})
            self.client.open(self.base+'/app').read()
            account=self.call('/api/account');self.assertEqual(account['account']['email'],'http@example.test');self.assertNotIn('ad',account)
            p=self.call('/api/project/new',{'title':'owned'})
            self.call('/api/auth/logout',{'ok':True})
            self.assertIsNone(self.call('/api/account')['account'])
            with self.assertRaises(urllib.error.HTTPError) as private:self.call('/api/work/'+p['id'])
            self.assertEqual(private.exception.code,403);private.exception.close()
        finally:accounts.DEV_AUTH,membership.ENFORCE=previous

    def test_consent_and_account_delete_routes_require_server_checks(self):
        from app import accounts, membership
        previous=accounts.DEV_AUTH,membership.ENFORCE
        accounts.DEV_AUTH=True;membership.ENFORCE=True
        try:
            x=self.call('/api/auth/email/start',{'email':'delete-http@example.test'})
            self.call('/api/auth/email/finish',{'challenge':x['challenge'],'code':x['dev_code']})
            self.assertTrue(self.call('/api/account')['account']['consent_required'])
            self.call('/api/account/consent',{'accepted':True})
            self.call('/api/account/profile',{'display_name':'削除テスト'})
            work=self.call('/api/project/new',{'title':'削除対象'})
            with self.assertRaises(urllib.error.HTTPError) as missing:self.call('/api/account/delete',{'confirmed':False})
            self.assertEqual(missing.exception.code,400);missing.exception.close()
            self.call('/api/account/delete',{'confirmed':True})
            with self.assertRaises(urllib.error.HTTPError) as revoked:self.call('/api/account/delete',{'confirmed':True})
            self.assertEqual(revoked.exception.code,403);revoked.exception.close()
            with s.transaction() as db:
                row=db.execute('SELECT deleted_at FROM accounts WHERE email=?',('delete-http@example.test',)).fetchone()
                retained=db.execute('SELECT data FROM works WHERE id=?',(work['id'],)).fetchone()
            self.assertIsNotNone(row['deleted_at']);self.assertIsNotNone(retained)
        finally:accounts.DEV_AUTH,membership.ENFORCE=previous

    def test_auth_gate_blocks_guests_on_html_data_and_mutations(self):
        from app import accounts,membership
        previous=accounts.DEV_AUTH,membership.ENFORCE
        accounts.DEV_AUTH=True;membership.ENFORCE=True
        try:
            for path in ['/app','/legacy']:
                with self.client.open(self.base+path) as r:self.assertTrue(r.url.split('?')[0].endswith('/login'))
            for path in ['/api/projects','/api/state','/api/work/missing','/file/missing']:
                with self.assertRaises(urllib.error.HTTPError) as e:self.call(path)
                self.assertEqual(e.exception.code,403);e.exception.close()
            x=self.call('/api/auth/email/start',{'email':'gate@example.test'})
            self.call('/api/auth/email/finish',{'challenge':x['challenge'],'code':x['dev_code']})
            with self.client.open(self.base+'/app') as r:
                self.assertTrue(r.url.endswith('/app'));self.assertIn('new-project',r.read().decode())
            self.call('/api/auth/logout',{})
            with self.client.open(self.base+'/app') as r:self.assertTrue(r.url.split('?')[0].endswith('/login'))
        finally:accounts.DEV_AUTH,membership.ENFORCE=previous

    def test_export_download_owner_and_video_range(self):
        p=self.call('/api/project/new',{'title':'書き出し確認'})
        dest=s.DATA/p['id']/'workspace'/'export';dest.mkdir(parents=True)
        payload=b'0123456789abcdef';(dest/'shorts.mp4').write_bytes(payload)
        url=self.base+'/file/'+p['id']+'/workspace/export/shorts.mp4'
        req=urllib.request.Request(url,headers={'Range':'bytes=4-9'})
        with self.client.open(req) as response:
            self.assertEqual(response.status,206);self.assertEqual(response.headers['Content-Type'],'video/mp4');self.assertEqual(response.read(),payload[4:10])
        with self.assertRaises(urllib.error.HTTPError) as denied:urllib.request.urlopen(url)
        self.assertEqual(denied.exception.code,403);denied.exception.close()

    def test_api_key_routes_are_private_and_never_return_the_key(self):
        import base64,os,io
        from app import accounts
        guest,_=s.session();token,user=accounts.complete('dev','key-http@example.test','key-http@example.test',guest['id'],False)
        headers={'Content-Type':'application/json','X-Story-Anime':'local','Cookie':'studio_session='+token}
        key='synthetic_http_key_1234567890'
        with patch.dict(os.environ,{'BYOK_ENCRYPTION_KEY':base64.urlsafe_b64encode(os.urandom(32)).decode()}),patch('urllib.request.urlopen',side_effect=lambda *a,**k:io.BytesIO(b'{"supportedGenerationMethods":["generateContent"]}')):
            result=self.call('/api/account/gemini-key',{'key':key,'user':'someone-else'},headers=headers)
            self.assertEqual(result,{'gemini_key':{'configured':True}})
            public=self.call('/api/account',headers=headers)
            self.assertTrue(public['gemini_key']['configured']);self.assertNotIn(key,json.dumps(public))
            other_guest,_=s.session();other_token,other=accounts.complete('dev','other-http@example.test','other-http@example.test',other_guest['id'],False)
            other_headers=dict(headers,Cookie='studio_session='+other_token)
            self.assertFalse(self.call('/api/account',headers=other_headers)['gemini_key']['configured'])
            self.call('/api/account/gemini-key',{'delete':True,'user':user},headers=other_headers)
            self.assertTrue(self.call('/api/account',headers=headers)['gemini_key']['configured'])
            with self.assertRaises(urllib.error.HTTPError) as error:self.call('/api/account/gemini-key',{'key':key},headers={'Cookie':'studio_session='+token})
            self.assertEqual(error.exception.code,403);error.exception.close()
            self.assertFalse(self.call('/api/account/gemini-key',{'delete':True},headers=headers)['gemini_key']['configured'])
