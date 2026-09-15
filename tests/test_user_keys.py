import base64
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from app import accounts, gemini, membership as m, studio as s, user_keys, workspace


class UserKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA,s.DB,gemini.DB,gemini.ENABLED,m.ENFORCE
        s.DATA=Path(self.tmp.name);s.DB=s.DATA/'studio.db';gemini.DB=s.DATA/'usage.db';gemini.ENABLED=True;m.ENFORCE=True;s.init()
        self.env=patch.dict(os.environ,{'BYOK_ENCRYPTION_KEY':base64.urlsafe_b64encode(os.urandom(32)).decode()});self.env.start()
        self.users=[];self.works=[]
        for i in range(2):
            guest,_=s.session();token,uid=accounts.complete('dev',f'{i}@example.test',f'{i}@example.test',guest['id'],False)
            accounts.accept_consent(uid,token)
            self.users.append(uid);self.works.append(workspace.create(uid,'fixture')['id'])
        self.keys=['synthetic_'+'test_key_'+v+'_123456789' for v in ['A','B']]
    def tearDown(self):
        self.env.stop();s.DATA,s.DB,gemini.DB,gemini.ENABLED,m.ENFORCE=self.old;self.tmp.cleanup()
    def save(self,i=0):
        with patch('urllib.request.urlopen',side_effect=lambda *a,**k:io.BytesIO(b'{"supportedGenerationMethods":["generateContent"]}')):
            return user_keys.save(self.users[i],self.keys[i])
    def response(self,*a,**k):
        return io.BytesIO(json.dumps({'candidates':[{'content':{'parts':[{'text':'{}'}]}}],'usageMetadata':{'promptTokenCount':5,'candidatesTokenCount':5}}).encode())
    def test_missing_free_key_never_reads_operator_key_or_sends(self):
        with patch.object(gemini,'key') as operator,patch('urllib.request.urlopen') as network:
            for call in [lambda:gemini.request(self.works[0],'image','draw'),lambda:gemini.agent_turn(self.works[0],'system',[],[])]:
                with self.assertRaisesRegex(ValueError,'APIキー'):call()
            operator.assert_not_called();network.assert_not_called()
        self.assertEqual(gemini.budget()['calls'],0)
    def test_encryption_is_bound_to_account_and_plaintext_is_not_returned(self):
        self.assertEqual(self.save(),{'configured':True})
        with s.transaction() as db:
            blob=db.execute('SELECT ciphertext FROM user_gemini_keys WHERE user=?',(self.users[0],)).fetchone()[0]
            self.assertNotIn(self.keys[0].encode(),blob)
            self.assertEqual(user_keys.read(db,self.users[0]),self.keys[0])
            db.execute('INSERT INTO user_gemini_keys VALUES(?,?,0)',(self.users[1],blob))
            with self.assertRaises(ValueError):user_keys.read(db,self.users[1])
        self.assertNotIn(self.keys[0],json.dumps(user_keys.status(self.users[0])))
    def test_parallel_accounts_text_and_image_use_only_their_own_keys(self):
        self.save(0);self.save(1);sent=[]
        def response(req,**kw):
            sent.append((req.get_header('X-goog-api-key'),req.full_url));return self.response()
        with patch.object(gemini,'key',side_effect=AssertionError('operator fallback')),patch('urllib.request.urlopen',side_effect=response):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda i:gemini.request(self.works[i],'image','draw'),range(2)))
            gemini.agent_turn(self.works[0],'system',[],[])
        self.assertEqual(sorted(x[0] for x in sent),sorted([self.keys[0],self.keys[0],self.keys[1]]))
        self.assertEqual(gemini.budget()['calls'],0)
        for u in self.users:self.assertEqual(m.status(u)['used']['cost_usd'],0)
        with s.transaction() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM consumption WHERE payer='user'").fetchone()[0],3)
        self.assertIsNone(m.public_status(self.users[0])['usage_percent'])
    def test_paid_plan_uses_operator_and_downgrade_requires_user_key(self):
        m.set_plan(self.users[0],'plus',1,'test')
        with patch.object(gemini,'key',return_value='operator-test'),patch('urllib.request.urlopen',side_effect=self.response) as network:
            gemini.request(self.works[0],'text','hello')
            self.assertEqual(network.call_args.args[0].get_header('X-goog-api-key'),'operator-test')
            with s.transaction() as db:db.execute('UPDATE memberships SET until=0 WHERE user=?',(self.users[0],))
            with self.assertRaises(ValueError):gemini.request(self.works[0],'text','hello')
            self.assertEqual(network.call_count,1)
    def test_invalid_replacement_preserves_old_key_and_delete_stops_generation(self):
        self.save()
        with patch('urllib.request.urlopen',side_effect=TimeoutError(self.keys[1])):
            with self.assertRaises(ValueError) as failure:user_keys.save(self.users[0],self.keys[1])
            self.assertNotIn(self.keys[1],str(failure.exception))
        with s.transaction() as db:self.assertEqual(user_keys.read(db,self.users[0]),self.keys[0])
        user_keys.delete(self.users[0]);self.assertFalse(user_keys.status(self.users[0])['configured'])
        with patch('urllib.request.urlopen') as network:
            with self.assertRaises(ValueError):gemini.request(self.works[0],'text','hello')
            network.assert_not_called()
    def test_provider_error_has_no_fallback_or_key_disclosure(self):
        self.save()
        with patch.object(gemini,'key',side_effect=AssertionError('fallback')),patch('urllib.request.urlopen',side_effect=TimeoutError(self.keys[0])) as network:
            with self.assertRaises(ValueError) as error:gemini.request(self.works[0],'text','hello')
            self.assertNotIn(self.keys[0],str(error.exception));self.assertEqual(network.call_count,1)
        self.assertEqual(gemini.budget()['calls'],0)
    def test_own_key_cost_does_not_reduce_future_paid_quota(self):
        self.save();rid=m.reserve(self.works[0],'image',100,600,'model');m.settle(rid,'unknown')
        m.set_plan(self.users[0],'plus',1,'upgrade')
        self.assertEqual(m.public_status(self.users[0])['usage_percent'],0)
        m.reserve(self.works[0],'image',100,60,'model')
        self.assertGreater(m.public_status(self.users[0])['usage_percent'],0)
    def test_no_unmanaged_operator_calls_in_production(self):
        with patch.object(m,'ENFORCE',False),patch.dict(os.environ,{'YOURSTORY_RUNTIME':'production'}),patch('urllib.request.urlopen') as network:
            with self.assertRaises(PermissionError):gemini.request(self.works[0],'text','hello')
            network.assert_not_called()
    def test_guest_cannot_save_or_delete_keys(self):
        guest,_=s.session()
        with self.assertRaises(PermissionError):user_keys.delete(guest['id'])
        with patch('urllib.request.urlopen') as network:
            with self.assertRaises(PermissionError):user_keys.save(guest['id'],self.keys[0])
            network.assert_not_called()
