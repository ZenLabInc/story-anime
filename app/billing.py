"""Stripe Checkout with webhook-authoritative subscription entitlements."""
import secrets
import string
import threading
import time
import stripe
from app import studio as s, settings, accounts, membership
LOCK=threading.RLock()
API_VERSION='2026-08-26.dahlia'
EVENTS=['checkout.session.completed','checkout.session.async_payment_succeeded','checkout.session.async_payment_failed','customer.subscription.created','customer.subscription.updated','customer.subscription.deleted','invoice.paid','invoice.payment_failed']

def init():
    with s.transaction() as db:db.executescript('''
    CREATE TABLE IF NOT EXISTS billing_customers(user TEXT PRIMARY KEY REFERENCES users(id),customer TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS billing_attempts(user TEXT PRIMARY KEY,plan TEXT NOT NULL,nonce TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS billing_sessions(user TEXT PRIMARY KEY,session TEXT NOT NULL,plan TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS billing_subscriptions(user TEXT PRIMARY KEY,subscription TEXT UNIQUE NOT NULL,status TEXT NOT NULL,plan TEXT NOT NULL,period_start REAL NOT NULL,period_end REAL NOT NULL,cancel_pending INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS billing_events(id TEXT PRIMARY KEY,type TEXT NOT NULL,created REAL NOT NULL);
    ''')

def mode():
    value=str(settings.get('STRIPE_MODE','test')).lower()
    return value if value in ['test','live'] else 'disabled'


def enabled():
    current=mode();key=settings.get('STRIPE_SECRET_KEY','')
    prefix=('rk_live_','sk_live_') if current=='live' else ('rk_test_','sk_test_')
    return current in ['test','live'] and key.startswith(prefix) and all(settings.get(k) for k in ['STRIPE_PRICE_PLUS','STRIPE_PRICE_PRO','STRIPE_WEBHOOK_SECRET'])

def client():
    if not enabled():raise ValueError('決済は準備中です。現在、実課金は開始していません。')
    return stripe.StripeClient(settings.get('STRIPE_SECRET_KEY'),stripe_version=API_VERSION,max_network_retries=0)

def test_access(user):
    allowed={x.strip().lower() for x in settings.get('STRIPE_TEST_ALLOWED_EMAILS').split(',') if x.strip()}
    account=accounts.profile(user)
    return not allowed or bool(account and account['email'].lower() in allowed)

def state(user):
    with s.transaction() as db:
        row=db.execute('SELECT status,plan,period_start,period_end,cancel_pending FROM billing_subscriptions WHERE user=?',(user,)).fetchone()
    available=enabled() and (mode()=='live' or test_access(user))
    return {'enabled':available,'mode':mode(),'subscription':dict(row) if row else None}

def checkout(user,plan,base):
    a=accounts.require(user)
    if mode()=='test' and not test_access(user):raise PermissionError('テスト購入は運営の検証アカウントに限定しています。販売開始までお待ちください。')
    if plan not in ['plus','pro']:raise ValueError('プランを選択してください。')
    with LOCK:
        c=client()
        with s.transaction() as db:
            sub=db.execute('SELECT * FROM billing_subscriptions WHERE user=?',(user,)).fetchone()
            old=db.execute('SELECT * FROM billing_sessions WHERE user=?',(user,)).fetchone()
            row=db.execute('SELECT customer FROM billing_customers WHERE user=?',(user,)).fetchone()
        if sub and sub['status'] not in ['canceled','incomplete_expired']:raise ValueError('契約は既にあります。契約管理から解約し、終了後に別プランを選択してください。')
        if old:
            previous=c.v1.checkout.sessions.retrieve(old['session'])
            if previous.status=='complete':raise ValueError('決済結果の反映を待っています。利用状況を更新してください。')
            if previous.status=='open':
                if old['plan']==plan:return {'url':previous.url}
                c.v1.checkout.sessions.expire(previous.id)
        if row:customer=row['customer']
        else:
            customer=c.v1.customers.create({'email':a['email'],'metadata':{'yourstory_user':user}},options={'idempotency_key':'yourstory-customer-'+user}).id
            with s.transaction() as db:db.execute('INSERT INTO billing_customers VALUES(?,?)',(user,customer))
        price=settings.get('STRIPE_PRICE_'+plan.upper())
        p=c.v1.prices.retrieve(price)
        if p.livemode != (mode()=='live') or p.currency!='jpy' or p.unit_amount!=membership.CONFIG[plan]['price_gross'] or p.recurring.interval!='month':raise ValueError('Stripe料金とサービス設定が一致しません。')
        with s.transaction() as db:
            attempt=db.execute('SELECT * FROM billing_attempts WHERE user=?',(user,)).fetchone()
            if attempt and attempt['plan']!=plan:raise ValueError('前の決済開始結果を確認中です。先に同じプランのボタンで再開してください。')
            nonce=attempt['nonce'] if attempt else ''.join(secrets.choice(string.ascii_lowercase) for _ in range(24))
            if not attempt:db.execute('INSERT INTO billing_attempts VALUES(?,?,?)',(user,plan,nonce))
        session=c.v1.checkout.sessions.create({'mode':'subscription','customer':customer,'line_items':[{'price':price,'quantity':1}],'client_reference_id':user,'subscription_data':{'metadata':{'yourstory_user':user}},'success_url':base+'/app?billing=success','cancel_url':base+'/app?billing=cancel','locale':'ja','integration_identifier':'yourstory_'+nonce[-8:]},options={'idempotency_key':'yourstory-checkout-'+nonce})
        with s.transaction() as db:db.execute('INSERT INTO billing_sessions VALUES(?,?,?) ON CONFLICT(user) DO UPDATE SET session=excluded.session,plan=excluded.plan',(user,session.id,plan))
        with s.transaction() as db:db.execute('DELETE FROM billing_attempts WHERE user=?',(user,))
        return {'url':session.url}

def validate_portal_configuration(config):
    """Fail closed if a Dashboard edit re-enables unsafe mid-cycle changes."""
    features=config.get('features',{})
    update=features.get('subscription_update',{})
    cancel=features.get('subscription_cancel',{})
    conditions=update.get('schedule_at_period_end',{}).get('conditions',[])
    if (bool(config.get('livemode')) != (mode()=='live') or not config.get('active')
        or not update.get('enabled') or update.get('default_allowed_updates') != ['price']
        or update.get('billing_cycle_anchor') != 'now'
        or update.get('proration_behavior') != 'always_invoice'
        or not any(item.get('type')=='decreasing_item_amount' for item in conditions)
        or not cancel.get('enabled') or cancel.get('mode') != 'at_period_end'):
        raise ValueError('契約管理の設定を確認中です。お問い合わせからご連絡ください。')

def portal(user,base):
    accounts.require(user)
    if mode()=='test' and not test_access(user):raise PermissionError('テスト契約管理は運営の検証アカウントに限定しています。')
    with s.transaction() as db:row=db.execute('SELECT customer FROM billing_customers WHERE user=?',(user,)).fetchone()
    if not row:raise ValueError('契約がありません。')
    c=client();configuration=settings.get('STRIPE_PORTAL_CONFIGURATION')
    config=c.v1.billing_portal.configurations.retrieve(configuration).to_dict()
    validate_portal_configuration(config)
    return {'url':c.v1.billing_portal.sessions.create({'customer':row['customer'],'return_url':base+'/app/account','configuration':configuration}).url}

def oid(value):return value.get('id') if isinstance(value,dict) else value

def apply_subscription(sub):
    """Called only after a verified webhook; owner comes from our customer mapping."""
    customer=oid(sub.get('customer'));items=sub.get('items',{}).get('data',[])
    if bool(sub.get('livemode')) != (mode()=='live'):raise ValueError('Stripeのlive/testモードが設定と一致しません。')
    with s.transaction() as db:
        row=db.execute('SELECT user FROM billing_customers WHERE customer=?',(customer,)).fetchone()
        if not row:return
        user=row['user'];old=db.execute('SELECT subscription,status,period_start FROM billing_subscriptions WHERE user=?',(user,)).fetchone()
        if old and old['subscription']!=sub['id']:
            if sub['status'] in ['canceled','incomplete_expired']:return
            if old['status'] not in ['canceled','incomplete_expired']:raise ValueError('重複契約を検出しました。')
        price=oid(items[0].get('price')) if len(items)==1 else None
        tier=next((k for k in ['plus','pro'] if price and settings.get('STRIPE_PRICE_'+k.upper())==price),None)
        invoice=sub.get('latest_invoice') or {}
        start=items[0].get('current_period_start',0) if items else 0
        end=items[0].get('current_period_end',0) if items else 0
        paid=isinstance(invoice,dict) and invoice.get('status')=='paid'
        active=tier and paid and sub['status']=='active' and end>time.time() and items[0].get('quantity')==1
        granted=tier if active else 'free'
        db.execute('INSERT INTO billing_subscriptions VALUES(?,?,?,?,?,?,?) ON CONFLICT(user) DO UPDATE SET subscription=excluded.subscription,status=excluded.status,plan=excluded.plan,period_start=excluded.period_start,period_end=excluded.period_end,cancel_pending=excluded.cancel_pending',(user,sub['id'],sub['status'],tier or 'free',start,end,int(bool(sub.get('cancel_at_period_end') or sub.get('cancel_at')))))
        db.execute('INSERT INTO memberships VALUES(?,?,?) ON CONFLICT(user) DO UPDATE SET plan=excluded.plan,until=excluded.until',(user,granted,end if active else time.time()))
        db.execute('INSERT INTO plan_events VALUES(?,?,?,?,?,?)',(s.uid(),user,granted,end,'stripe_webhook',time.time()))
        from app import metrics
        if not old:
            metrics.track_conn(db, user, 'subscription_started', attrs={'plan':granted,'source':'stripe_webhook'})
        elif sub['status'] in ['canceled','incomplete_expired']:
            metrics.track_conn(db, user, 'subscription_canceled', attrs={'plan':granted,'source':'stripe_webhook'})
        elif old and old['subscription']==sub['id'] and old['status'] == 'active' and start and start != old['period_start']:
            metrics.track_conn(db, user, 'subscription_renewed', attrs={'plan':granted,'source':'stripe_webhook'})
        db.execute('DELETE FROM billing_sessions WHERE user=?',(user,))

def webhook(raw,signature):
    if not enabled():raise ValueError('Webhook未設定')
    try:event=stripe.Webhook.construct_event(raw,signature,settings.get('STRIPE_WEBHOOK_SECRET'))
    except (ValueError,stripe.SignatureVerificationError):raise ValueError('Webhook署名が不正です。')
    if bool(event.livemode) != (mode()=='live'):raise ValueError('Stripeのlive/testモードが設定と一致しません。')
    with LOCK:
        with s.transaction() as db:
            if db.execute('SELECT 1 FROM billing_events WHERE id=?',(event.id,)).fetchone():return
        if event.type in EVENTS:
            obj=event.data.object.to_dict();subid=None
            if event.type.startswith('customer.subscription.'):subid=obj['id']
            elif event.type.startswith('checkout.session.'):subid=oid(obj.get('subscription'))
            elif event.type.startswith('invoice.'):
                subid=oid((obj.get('parent') or {}).get('subscription_details',{}).get('subscription')) or oid(obj.get('subscription'))
            if subid:
                # Fetch current state instead of trusting delivery order or stale event bodies.
                sub=client().v1.subscriptions.retrieve(subid,{'expand':['latest_invoice']}).to_dict()
                apply_subscription(sub)
        with s.transaction() as db:db.execute('INSERT INTO billing_events VALUES(?,?,?)',(event.id,event.type,time.time()))
