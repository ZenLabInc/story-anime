import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from app import studio as s, accounts as a, workspace as w

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA,s.DB,a.DEV_AUTH
        s.DATA=Path(self.tmp.name);s.DB=s.DATA/'studio.db';a.DEV_AUTH=True;s.init();self.user,self.cookie=s.session()
    def tearDown(self):s.DATA,s.DB,a.DEV_AUTH=self.old;self.tmp.cleanup()
    def start(self,email='one@example.test',browser=None):return a.email_start(email,browser or self.cookie,'127.0.0.1')
    def finish(self,x,browser=None):return a.email_finish(x['challenge'],x['dev_code'],browser or self.cookie,self.user['id'])
    def test_session_rotation_replay_logout(self):
        x=self.start();token,user=self.finish(x);self.assertEqual(a.authenticate(token)['id'],user);self.assertFalse(a.profile(user)['verified'])
        with self.assertRaises(PermissionError):a.authenticate(self.cookie)
        with self.assertRaises(ValueError):self.finish(x)
        a.logout(token)
        with self.assertRaises(PermissionError):a.authenticate(token)
    def test_expiry_browser_binding_and_attempt_limit(self):
        x=self.start()
        with self.assertRaises(ValueError):self.finish(x,'different-browser')
        for _ in range(5):
            with self.assertRaises(ValueError):a.email_finish(x['challenge'],'bad',self.cookie,self.user['id'])
        with self.assertRaises(ValueError):self.finish(x)
        y=self.start('two@example.test')
        with s.transaction() as db:db.execute('UPDATE login_challenges SET expires=? WHERE id=?',(time.time()-1,y['challenge']))
        with self.assertRaises(ValueError):self.finish(y)
    def test_send_rate_limit_and_real_email_requires_provider(self):
        for _ in range(3):self.start()
        with self.assertRaises(ValueError):self.start()
        with patch('app.settings.get',return_value=''):
            with self.assertRaises(ValueError):self.start('person@real-domain.com')
    def test_relogin_merges_only_owned_guest_works_and_expires(self):
        first=w.create(self.user['id'],'first');token,owner=self.finish(self.start())
        guest,cookie=s.session();other=w.create(guest['id'],'second');x=self.start(browser=cookie)
        token2,user=a.email_finish(x['challenge'],x['dev_code'],cookie,guest['id'])
        self.assertEqual(user,owner);self.assertEqual(len(w.projects(owner)),2)
        with self.assertRaises(PermissionError):a.authenticate(cookie)
        with s.transaction() as db:db.execute('UPDATE sessions SET expires=0 WHERE hash=?',(a.digest(token2),))
        with self.assertRaises(PermissionError):a.authenticate(token2)
    def test_google_subject_does_not_auto_link_email_and_nonce_required(self):
        _,one=self.finish(self.start())
        guest,_=s.session();_,two=a.complete('google','subject-id','one@example.test',guest['id'])
        self.assertNotEqual(one,two)
        claims={'sub':'x','email':'x@example.com','email_verified':True,'nonce':'wrong'}
        with patch('google.oauth2.id_token.verify_oauth2_token',return_value=claims):
            with self.assertRaises(ValueError):a.verify_google('token','audience','expected')
    def test_google_state_is_bound_and_consumed_once(self):
        from urllib.parse import urlparse,parse_qs
        with patch('app.settings.get',side_effect=lambda k,*args:'configured'):
            url=a.google_start(self.cookie,'http://127.0.0.1:8765');state=parse_qs(urlparse(url).query)['state'][0]
            with self.assertRaises(ValueError):a.google_finish(state,'code','wrong',self.user['id'],'http://127.0.0.1:8765')
            with patch('urllib.request.urlopen',side_effect=OSError):
                with self.assertRaises(ValueError):a.google_finish(state,'code',self.cookie,self.user['id'],'http://127.0.0.1:8765')
            with self.assertRaises(ValueError):a.google_finish(state,'code',self.cookie,self.user['id'],'http://127.0.0.1:8765')
    def test_smtp_uses_tls_and_does_not_expose_code_in_http_result(self):
        vals={'SMTP_HOST':'smtp.example.test','SMTP_FROM':'no-reply@example.test','SMTP_PORT':'587'}
        a.DEV_AUTH=False
        with patch('app.settings.get',side_effect=lambda k,d='':vals.get(k,d)),patch('smtplib.SMTP') as smtp:
            out=self.start('actual@example.com')
            self.assertNotIn('dev_code',out);client=smtp.return_value.__enter__.return_value;client.starttls.assert_called_once();client.send_message.assert_called_once()

    def test_private_beta_rejects_non_invited_identity(self):
        with patch('app.accounts.settings.get',return_value='allowed@example.test'):
            with self.assertRaises(PermissionError):
                a.complete('google','stranger','other@example.test',self.user['id'])
            token,user=a.complete('google','invited','allowed@example.test',self.user['id'])
            self.assertEqual(a.authenticate(token)['id'],user)

    def test_user_name_is_explicit_persistent_and_account_scoped(self):
        token,user=self.finish(self.start())
        self.assertEqual(a.profile(user)['display_name'],'')
        a.save_profile(user,'  物語の作者  ')
        self.assertEqual(a.profile(user)['display_name'],'物語の作者')
        self.assertEqual(a.profile(user)['email'],'one@example.test')
        a.init()
        self.assertEqual(a.profile(user)['display_name'],'物語の作者')
        for name in ['', ' '*3, 'a'*31, 'a\nb', None]:
            with self.assertRaises(ValueError):a.save_profile(user,name)
        guest,_=s.session()
        with self.assertRaises(PermissionError):a.save_profile(guest['id'],'他人')
        a.save_profile(user,'新しい名前')
        self.assertEqual(a.profile(user)['display_name'],'新しい名前')
