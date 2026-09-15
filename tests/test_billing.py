import copy
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from app import studio as s,accounts,membership as m,billing as b

class BillingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA,s.DB;s.DATA=Path(self.tmp.name);s.DB=s.DATA/'studio.db';s.init();guest,_=s.session();_,self.user=accounts.complete('google','test','billing@example.test',guest['id'])
  with s.transaction() as db:db.execute('INSERT INTO billing_customers VALUES(?,?)',(self.user,'cus_test'))
  vals={'STRIPE_MODE':'test','STRIPE_SECRET_KEY':'rk_'+'test_'+'placeholder','STRIPE_PRICE_PLUS':'price_plus','STRIPE_PRICE_PRO':'price_pro','STRIPE_WEBHOOK_SECRET':'whsec_placeholder'}
  self.config=patch('app.billing.settings.get',side_effect=lambda k,d='':vals.get(k,d));self.config.start()
  self.sub={'id':'sub_test','customer':'cus_test','livemode':False,'status':'active','latest_invoice':{'status':'paid'},'items':{'data':[{'price':{'id':'price_plus'},'quantity':1,'current_period_start':int(time.time())-100,'current_period_end':int(time.time())+3600}]},'cancel_at_period_end':False}
 def tearDown(self):self.config.stop();s.DATA,s.DB=self.old;self.tmp.cleanup()
 def sign(self,event,stamp=None):
  raw=json.dumps(event).encode();t=int(time.time()) if stamp is None else stamp
  sig=hmac.new(b'whsec_placeholder',str(t).encode()+b'.'+raw,hashlib.sha256).hexdigest()
  return raw,f't={t},v1={sig}'
 def test_paid_and_cancel_pending_keep_entitlement_and_expired_returns_free(self):
  b.apply_subscription(self.sub);self.assertEqual(m.status(self.user)['plan'],'plus')
  self.sub['cancel_at_period_end']=True;b.apply_subscription(self.sub);self.assertEqual(m.status(self.user)['plan'],'plus')
  self.sub['status']='canceled';b.apply_subscription(self.sub);self.assertEqual(m.status(self.user)['plan'],'free')
 def test_live_mode_is_explicit_and_accepts_only_live_subscription(self):
  vals={'STRIPE_MODE':'live','STRIPE_SECRET_KEY':'rk_'+'live_'+'placeholder','STRIPE_PRICE_PLUS':'price_plus','STRIPE_PRICE_PRO':'price_pro','STRIPE_WEBHOOK_SECRET':'whsec_live'}
  with patch('app.billing.settings.get',side_effect=lambda k,d='':vals.get(k,d)):
   self.assertTrue(b.enabled());self.assertEqual(b.mode(),'live')
   self.sub['livemode']=True;b.apply_subscription(self.sub);self.assertEqual(m.status(self.user)['plan'],'plus')
   self.sub['livemode']=False
   with self.assertRaises(ValueError):b.apply_subscription(self.sub)
 def test_unpaid_unrecognized_price_and_live_never_grant(self):
  for status in ['open','uncollectible','draft']:
   self.sub['latest_invoice']['status']=status;b.apply_subscription(self.sub);self.assertEqual(m.status(self.user)['plan'],'free')
  self.sub['latest_invoice']['status']='paid';self.sub['items']['data'][0]['price']['id']='unknown';b.apply_subscription(self.sub);self.assertEqual(m.status(self.user)['plan'],'free')
  self.sub['livemode']=True
  with self.assertRaises(ValueError):b.apply_subscription(self.sub)
 def test_duplicate_signature_and_out_of_order(self):
  event={'id':'evt_test','object':'event','type':'invoice.paid','livemode':False,'data':{'object':{'parent':{'subscription_details':{'subscription':'sub_test'}}}}}
  c=MagicMock();c.v1.subscriptions.retrieve.return_value.to_dict.return_value=self.sub
  with patch('app.billing.client',return_value=c):
   raw,sig=self.sign(event);b.webhook(raw,sig);b.webhook(raw,sig);self.assertEqual(c.v1.subscriptions.retrieve.call_count,1)
   self.sub['status']='past_due';event['id']='evt_late';b.webhook(*self.sign(event));self.assertEqual(m.status(self.user)['plan'],'free')
  with self.assertRaises(ValueError):b.webhook(raw,sig+'broken')
  with self.assertRaises(ValueError):b.webhook(*self.sign(event,int(time.time())-1000))
 def test_other_customer_cannot_change_account(self):
  self.sub['customer']='cus_other';b.apply_subscription(self.sub);self.assertEqual(m.status(self.user)['plan'],'free')
 def test_renewal_changes_usage_period_without_deleting_ledger(self):
  b.apply_subscription(self.sub)
  with s.transaction() as db:
   period=m.period(db,self.user);db.execute('INSERT INTO consumption(id,user,work,kind,period,status,tokens,cost,created) VALUES(?,?,?,?,?,?,?,?,?)',('used',self.user,'test','text',period,'succeeded',120,1,time.time()))
  self.assertEqual(m.status(self.user)['used']['text_calls'],1)
  self.sub['items']['data'][0]['current_period_start']+=50;b.apply_subscription(self.sub);self.assertEqual(m.status(self.user)['used']['text_calls'],0)
  with s.transaction() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption').fetchone()[0],1)
 def test_checkout_does_not_grant_and_blocks_duplicate_subscription(self):
  b.apply_subscription(self.sub)
  with patch('app.billing.client',return_value=MagicMock()):
   with self.assertRaises(ValueError):b.checkout(self.user,'pro','https://example.test')
  with self.assertRaises(ValueError):b.checkout(self.user,'arbitrary','https://example.test')
 def test_portal_cancel_at_timestamp_and_old_deleted_event(self):
  self.sub['cancel_at']=self.sub['items']['data'][0]['current_period_end'];b.apply_subscription(self.sub);self.assertTrue(b.state(self.user)['subscription']['cancel_pending'])
  old=copy.deepcopy(self.sub);old['id']='sub_old';old['status']='canceled';b.apply_subscription(old);self.assertEqual(m.status(self.user)['plan'],'plus')
 def test_expired_paid_period_removes_entitlement_without_webhook(self):
  b.apply_subscription(self.sub)
  with patch('app.membership.time.time',return_value=time.time()+7200):self.assertEqual(m.status(self.user)['plan'],'free')
 def test_checkout_unknown_response_reuses_idempotency_key(self):
  c=MagicMock();c.v1.prices.retrieve.return_value=type('Price',(),{'livemode':False,'currency':'jpy','unit_amount':1480,'recurring':type('Recurring',(),{'interval':'month'})()})()
  result=type('Session',(),{'id':'cs_test_example','url':'https://checkout.stripe.com/test'})()
  c.v1.checkout.sessions.create.side_effect=[TimeoutError('uncertain response'),result]
  with patch('app.billing.client',return_value=c):
   with self.assertRaises(TimeoutError):b.checkout(self.user,'plus','https://example.test')
   self.assertEqual(m.status(self.user)['plan'],'free')
   with self.assertRaises(ValueError):b.checkout(self.user,'pro','https://example.test')
   b.checkout(self.user,'plus','https://example.test')
  calls=c.v1.checkout.sessions.create.call_args_list;self.assertEqual(calls[0],calls[1]);self.assertEqual(m.status(self.user)['plan'],'free')

 def test_public_signup_cannot_use_operator_test_checkout(self):
  with patch('app.billing.settings.get',side_effect=lambda k,d='':'owner@example.test' if k=='STRIPE_TEST_ALLOWED_EMAILS' else d),patch('app.billing.client') as client:
   self.assertFalse(b.state(self.user)['enabled'])
   with self.assertRaises(PermissionError):b.checkout(self.user,'pro','https://yourstory.example.test')
   client.assert_not_called()
 def test_plan_change_keeps_consumption_and_waits_for_paid_invoice(self):
  self.sub['items']['data'][0]['price']['id']='price_pro';b.apply_subscription(self.sub)
  with s.transaction() as db:
   cycle=m.period(db,self.user)
   db.execute('INSERT INTO consumption(id,user,work,kind,period,status,tokens,cost,cost_usd,usd_jpy,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)',('use',self.user,'test','image',cycle,'succeeded',10,180,1,180,time.time()))
  self.sub['items']['data'][0]['price']['id']='price_plus';b.apply_subscription(self.sub)
  self.assertEqual(m.status(self.user)['plan'],'plus');self.assertAlmostEqual(m.status(self.user)['used']['cost_usd'],1)
  self.sub['items']['data'][0]['price']['id']='price_pro';self.sub['latest_invoice']['status']='open';b.apply_subscription(self.sub)
  self.assertNotEqual(m.status(self.user)['plan'],'pro')
  self.sub['latest_invoice']['status']='paid';b.apply_subscription(self.sub)
  self.assertEqual(m.status(self.user)['plan'],'pro');self.assertAlmostEqual(m.status(self.user)['used']['cost_usd'],1)

 def test_portal_policy_rejects_immediate_downgrade_and_partial_month_upgrade(self):
  config={'active':True,'livemode':False,'features':{'subscription_update':{'enabled':True,'default_allowed_updates':['price'],'billing_cycle_anchor':'now','proration_behavior':'always_invoice','schedule_at_period_end':{'conditions':[{'type':'decreasing_item_amount'}]}},'subscription_cancel':{'enabled':True,'mode':'at_period_end'}}}
  b.validate_portal_configuration(config)
  for field,value in [('billing_cycle_anchor','unchanged'),('proration_behavior','none'),('schedule_at_period_end',{'conditions':[]}),('default_allowed_updates',['price','quantity'])]:
   unsafe=copy.deepcopy(config);unsafe['features']['subscription_update'][field]=value
   with self.subTest(field=field),self.assertRaises(ValueError):b.validate_portal_configuration(unsafe)
  c=MagicMock();c.v1.billing_portal.configurations.retrieve.return_value.to_dict.return_value=unsafe
  with patch('app.billing.client',return_value=c),self.assertRaises(ValueError):b.portal(self.user,'https://example.test')
  c.v1.billing_portal.sessions.create.assert_not_called()

 def test_scheduled_downgrade_keeps_pro_usage_until_paid_renewal(self):
  self.sub['items']['data'][0]['price']['id']='price_pro';b.apply_subscription(self.sub)
  with s.transaction() as db:
   cycle=m.period(db,self.user)
   db.execute('INSERT INTO consumption(id,user,work,kind,period,status,tokens,cost,cost_usd,usd_jpy,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)',('use',self.user,'test','image',cycle,'succeeded',10,1800,10,180,time.time()))
  self.sub['schedule']='sub_sched_qa';b.apply_subscription(self.sub)
  self.assertEqual(m.status(self.user)['plan'],'pro');self.assertEqual(m.status(self.user)['used']['cost_usd'],10)
  self.sub['items']['data'][0]['price']['id']='price_plus';self.sub['items']['data'][0]['current_period_start']+=50
  self.sub['latest_invoice']['status']='open';b.apply_subscription(self.sub);self.assertEqual(m.status(self.user)['plan'],'free')
  self.sub['latest_invoice']['status']='paid';b.apply_subscription(self.sub)
  self.assertEqual(m.status(self.user)['plan'],'plus');self.assertEqual(m.status(self.user)['used']['cost_usd'],0)
  with s.transaction() as db:self.assertEqual(db.execute('SELECT cost_usd FROM consumption WHERE id=?',('use',)).fetchone()[0],10)
