import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from app import studio as s, accounts as a, membership as m, workspace as w, gemini

class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA,s.DB,m.ENFORCE,m.CONFIG
        s.DATA=Path(self.tmp.name);s.DB=s.DATA/'studio.db';m.ENFORCE=True;m.CONFIG=copy.deepcopy(m.CONFIG);s.init()
        user,_=s.session();self.token,self.user=a.complete('dev','test@example.test','test@example.test',user['id'],False);a.accept_consent(self.user,self.token);self.p=w.create(self.user,'test');m.set_plan(self.user,'plus',1,'paid quota test')
    def tearDown(self):s.DATA,s.DB,m.ENFORCE,m.CONFIG=self.old;self.tmp.cleanup()
    def reserve(self,kind='text',tokens=100,cap=1):return m.reserve(self.p['id'],kind,tokens,cap,'model')
    def test_tokens_cost_settlement_and_unknown_reservation(self):
        rid=self.reserve(tokens=1000,cap=10);m.settle(rid,'succeeded',{'promptTokenCount':50,'candidatesTokenCount':20,'thoughtsTokenCount':10},.1)
        status=m.status(self.user);self.assertEqual(status['used']['tokens'],80);self.assertEqual(status['used']['cost_jpy'],.1)
        unknown=self.reserve(tokens=500,cap=10);m.settle(unknown,'unknown');self.assertEqual(m.status(self.user)['used']['tokens'],580)
        m.settle(unknown,'released');self.assertEqual(m.status(self.user)['used']['tokens'],580)
    def test_concurrent_reservation_cannot_overrun_image_limit(self):
        m.CONFIG['plus']['monthly_budget_usd']=1/m.USD_JPY
        def attempt(_):
            try:return self.reserve('image')
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(x is not None for x in r),1)
    def test_paid_budget_resets_monthly_and_expired_plan_returns_free(self):
        self.reserve('image',cap=m.CONFIG['plus']['monthly_budget_usd']*m.USD_JPY)
        with self.assertRaises(ValueError):self.reserve()
        with patch('app.membership.month',return_value='2099-12'):
            self.reserve('image')
            self.assertGreater(m.public_status(self.user)['usage_percent'],0)
            self.assertLess(m.public_status(self.user)['usage_percent'],100)
        m.set_plan(self.user,'plus',1,'test grant')
        with s.transaction() as db:db.execute('UPDATE memberships SET until=0 WHERE user=?',(self.user,))
        self.assertEqual(m.status(self.user)['plan'],'free')
    def test_all_limits_and_pro_greater_than_plus(self):
        m.CONFIG['plus']['text_calls']=1;self.reserve();self.reserve()
        self.assertGreater(m.CONFIG['pro']['monthly_budget_usd'],m.CONFIG['plus']['monthly_budget_usd'])
        m.set_plan(self.user,'plus',1,'test')
        self.reserve(tokens=m.CONFIG['plus']['tokens']+1)  # Tokens are weighted by price, not a separate quota.
        with self.assertRaises(ValueError):self.reserve(cap=m.CONFIG['plus']['monthly_budget_usd']*m.USD_JPY+1)
    def test_global_budget_reject_releases_member_reservation(self):
        with patch.object(gemini,'ENABLED',True),patch('app.gemini.key',return_value='test'),patch('app.gemini.reserve_global',side_effect=ValueError('global cap')),patch('urllib.request.urlopen') as network:
            with self.assertRaises(ValueError):gemini.request(self.p['id'],'text','test')
            network.assert_not_called()
        self.assertEqual(m.status(self.user)['used']['text_calls'],0)
    def test_unauthenticated_calls_rejected_and_pending_recovered(self):
        guest,_=s.session();p=w.create(guest['id'],'guest')
        with self.assertRaises(PermissionError):m.reserve(p['id'],'text',10,1,'model')
        self.reserve();m.recover();self.assertEqual(m.status(self.user)['used']['unknown_calls'],1)
    def test_public_plans_have_no_ad_entitlement(self):
        self.assertNotIn('ads',m.public_plans()['free'])
        self.assertNotIn('ad',m.public_status(self.user))

    def test_project_limit_is_atomic_and_ignores_readonly_legacy(self):
        # The default Free plan intentionally allows one active work; use two
        # here so the parallel create race remains observable.
        m.CONFIG['plus']['projects']=2
        with s.transaction() as db:
            db.execute('INSERT INTO works VALUES(?,?,?,?)',('legacy',self.user,s.dump({'version':3}),time.time()))
        def attempt(_):
            try:return w.create(self.user,'parallel')['id']
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(x is not None for x in r),1)

    def test_public_usage_hides_costs_and_combines_image_and_text(self):
        m.CONFIG['plus']['monthly_budget_usd']=1
        a=self.reserve('text',cap=18);m.settle(a,'succeeded',{'promptTokenCount':2,'candidatesTokenCount':2},9)
        b=self.reserve('image',cap=18)
        public=m.public_status(self.user)
        self.assertEqual(public['usage_percent'],15)
        self.assertNotIn('used',public);self.assertNotIn('events',public)
        self.assertNotIn('monthly_budget_usd',public['limits'])
        m.settle(b,'released');self.assertEqual(m.public_status(self.user)['usage_percent'],5)
    def test_legacy_migration_is_idempotent_and_fx_is_stable(self):
        with s.transaction() as db:
            db.execute('INSERT INTO consumption(id,user,work,kind,period,status,tokens,cost,created) VALUES(?,?,?,?,?,?,?,?,?)',('legacy',self.user,self.p['id'],'image',m.month(),'succeeded',10,18,time.time()))
        m.init()
        with patch.object(m,'USD_JPY',200):m.init()
        with s.transaction() as db:
            row=db.execute("SELECT cost_usd,usd_jpy FROM consumption WHERE id='legacy'").fetchone()
        self.assertAlmostEqual(row['cost_usd'],.1);self.assertEqual(row['usd_jpy'],180)
    def test_http_payload_removes_nested_provider_costs(self):
        from app.server import public_payload
        result=public_payload({'project':{'chats':[{'reply':'案','api':{'estimated_jpy':1,'usage':{'tokens':100}}}],'quotes':{'x':{'cap_jpy':60,'target':'x'}}},'budget':{'limit_jpy':700}})
        self.assertEqual(result,{'project':{'chats':[{'reply':'案'}],'quotes':{'x':{'target':'x'}}}})
