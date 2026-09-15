"""Server-authoritative membership limits, reservations and token/cost ledger."""
from contextlib import nullcontext
import datetime
import json
import os
import time
from app import studio as s, accounts
from scripts.cost_model import load_config
CONFIG=load_config()['membership']
ENFORCE=False
USD_JPY=load_config()['gemini']['usd_jpy_planning']

def month():return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m')
def init():
    with s.transaction() as db:db.executescript('''
    CREATE TABLE IF NOT EXISTS memberships(user TEXT PRIMARY KEY REFERENCES users(id),plan TEXT NOT NULL,until REAL);
    CREATE TABLE IF NOT EXISTS consumption(id TEXT PRIMARY KEY,user TEXT NOT NULL REFERENCES users(id),work TEXT NOT NULL,kind TEXT NOT NULL,period TEXT NOT NULL,status TEXT NOT NULL,tokens INTEGER NOT NULL,cost REAL NOT NULL,input_tokens INTEGER,output_tokens INTEGER,model TEXT,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS plan_events(id TEXT PRIMARY KEY,user TEXT NOT NULL,plan TEXT NOT NULL,until REAL,reason TEXT NOT NULL,created REAL NOT NULL);
    ''')
    with s.transaction() as db:
        columns={r[1] for r in db.execute('PRAGMA table_info(consumption)')}
        if 'payer' not in columns:db.execute("ALTER TABLE consumption ADD COLUMN payer TEXT NOT NULL DEFAULT 'operator'")
        if 'cost_usd' not in columns:db.execute('ALTER TABLE consumption ADD COLUMN cost_usd REAL')
        if 'usd_jpy' not in columns:db.execute('ALTER TABLE consumption ADD COLUMN usd_jpy REAL')
        db.execute('UPDATE consumption SET cost_usd=cost/?,usd_jpy=? WHERE cost_usd IS NULL',(USD_JPY,USD_JPY))

def plan(db,user):
    if os.environ.get('YOURSTORY_LOCAL')=='1':return 'free',CONFIG['free']
    row=db.execute('SELECT * FROM memberships WHERE user=?',(user,)).fetchone()
    name=row['plan'] if row and (row['until'] is None or row['until']>time.time()) else 'free'
    return name,CONFIG[name]

def period(db,user):
    row=db.execute('SELECT period_start,period_end,status FROM billing_subscriptions WHERE user=?',(user,)).fetchone()
    if row and row['status']=='active' and row['period_end']>time.time():return 'billing:'+str(int(row['period_start']))
    return month()

def totals(db,user,kind=None,lifetime=False):
    rows=db.execute("SELECT * FROM consumption WHERE user=? AND payer='operator' AND status!='released'"+('' if lifetime else ' AND period=?'),(user,) if lifetime else (user,period(db,user))).fetchall()
    return {'tokens':sum(r['tokens'] for r in rows),'cost_jpy':round(sum(r['cost'] for r in rows),4),'cost_usd':sum(r['cost_usd'] if r['cost_usd'] is not None else r['cost']/USD_JPY for r in rows),'text_calls':sum(r['kind']=='text' for r in rows),'images':sum(r['kind']=='image' for r in rows),'unknown_calls':sum(r['status']=='unknown' for r in rows),'pending':sum(r['status']=='reserved' for r in rows)}

def status(user):
    with s.transaction() as db:
        name,p=plan(db,user);cycle=period(db,user);used=totals(db,user);images=totals(db,user,lifetime=p['image_period']=='lifetime')['images']
        events=[dict(r) for r in db.execute('SELECT kind,status,tokens,input_tokens,output_tokens,cost,model,created FROM consumption WHERE user=? ORDER BY created DESC LIMIT 30',(user,))]
    return {'plan':name,'limits':p,'used':dict(used,images=images),'period':cycle,'events':events,'plans':{k:CONFIG[k] for k in ['free','plus','pro']}}

def token_usage(user):
    """Report provider token counts only, never reservation bounds or prices."""
    with s.transaction() as db:
        rows=db.execute("SELECT kind,model,status,input_tokens,output_tokens,created FROM consumption WHERE user=? AND status!='released' ORDER BY created DESC",(user,)).fetchall()
    records=[]
    for row in rows:
        record=dict(row)
        known=record['status']!='reserved' and all(record[k] is not None for k in ['input_tokens','output_tokens'])
        record['total_tokens']=record['input_tokens']+record['output_tokens'] if known else None
        if not known:record.update(input_tokens=None,output_tokens=None)
        records.append(record)
    return {'input_tokens':sum(r['input_tokens'] or 0 for r in records),'output_tokens':sum(r['output_tokens'] or 0 for r in records),'total_tokens':sum(r['total_tokens'] or 0 for r in records),'unreported_calls':sum(r['total_tokens'] is None for r in records),'records':records[:100]}

def project_allowed(user,connection=None):
    with (nullcontext(connection) if connection is not None else s.transaction()) as db:
        _,p=plan(db,user)
        count=sum((work:=json.loads(row[0])).get('version')==4 and not work.get('deleted_at') for row in db.execute('SELECT data FROM works WHERE owner=?',(user,)))
        if count>=p['projects']:raise ValueError('漫画の保存数がプラン上限に達しました。')

def reserve(work,kind,token_bound,cap,model,credential=False):
    from app import gemini, user_keys
    if not ENFORCE:
        if gemini.production_runtime():raise PermissionError('本番の生成にはアカウント管理が必要です。')
        return (None,gemini.key(),'operator') if credential else None
    with s.transaction() as db:
        row=db.execute('SELECT owner FROM works WHERE id=?',(work,)).fetchone()
        if not row:raise ValueError('作品がありません。')
        user=row[0]
        account=db.execute('SELECT terms_version,privacy_version FROM accounts WHERE user=? AND deleted_at IS NULL',(user,)).fetchone()
        if not account:raise PermissionError('生成にはログインが必要です。')
        if os.environ.get('YOURSTORY_LOCAL')!='1' and (account['terms_version']!=accounts.TERMS_VERSION or account['privacy_version']!=accounts.PRIVACY_VERSION):raise PermissionError('制作を続ける前に、更新した利用規約・プライバシーポリシーをご確認ください。')
        name,p=plan(db,user);used=totals(db,user)
        payer='user' if name=='free' else 'operator'
        token=user_keys.read(db,user) if payer=='user' else (gemini.key() if credential else None)
        if payer=='operator' and used['cost_usd']+cap/USD_JPY>p['monthly_budget_usd']+1e-10:raise ValueError('今月の利用枠に収まりません。次の更新をお待ちいただくか、プランをご確認ください。')
        rid=s.uid();db.execute('INSERT INTO consumption(id,user,work,kind,period,status,tokens,cost,model,created,cost_usd,usd_jpy) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,user,work,kind,period(db,user),'reserved',token_bound,cap,model,time.time(),cap/USD_JPY,USD_JPY))
        db.execute('UPDATE consumption SET payer=? WHERE id=?',(payer,rid))
    return (rid,token,payer) if credential else rid

def settle(rid,status,usage=None,estimate=None):
    if not rid:return
    with s.transaction() as db:
        row=db.execute('SELECT * FROM consumption WHERE id=?',(rid,)).fetchone()
        if not row or row['status']!='reserved':return
        if status=='released':db.execute("UPDATE consumption SET status='released',tokens=0,cost=0,cost_usd=0 WHERE id=?",(rid,));return
        usage=usage or {};inp=usage.get('promptTokenCount');out=usage.get('candidatesTokenCount');thoughts=usage.get('thoughtsTokenCount',0)
        known=all(type(v) is int and v>=0 for v in [inp,out,thoughts])
        db.execute('UPDATE consumption SET status=?,tokens=?,cost=?,input_tokens=?,output_tokens=? WHERE id=?',('succeeded' if known and estimate is not None else 'unknown',inp+out+thoughts if known else row['tokens'],estimate if estimate is not None else row['cost'],inp if known else None,out+thoughts if known else None,rid))
        if estimate is not None:db.execute('UPDATE consumption SET cost_usd=? WHERE id=?',(estimate/row['usd_jpy'],rid))

def recover():
    with s.transaction() as db:db.execute("UPDATE consumption SET status='unknown' WHERE status='reserved'")

def check_images(user,count,connection=None):
    with (nullcontext(connection) if connection is not None else s.transaction()) as db:
        name,p=plan(db,user)
        if name=='free':
            from app import user_keys
            user_keys.read(db,user)
            return
        used=totals(db,user);images=totals(db,user,lifetime=p['image_period']=='lifetime')['images']
        from app import gemini
        if used['cost_usd']+count*gemini.CONFIG['image_request_cap_jpy']/USD_JPY>p['monthly_budget_usd']+1e-10:raise ValueError('選択した生成が今月の残り利用枠を超えます。生成対象を減らしてください。')

def set_plan(user,name,days,reason):
    if name not in ['free','plus','pro'] or not reason or not 1<=days<=366:raise ValueError('plan / days / reasonを確認してください。')
    accounts.require(user)
    with s.transaction() as db:
        until=time.time()+days*86400
        db.execute('INSERT INTO memberships VALUES(?,?,?) ON CONFLICT(user) DO UPDATE SET plan=excluded.plan,until=excluded.until',(user,name,until))
        db.execute('INSERT INTO plan_events VALUES(?,?,?,?,?,?)',(s.uid(),user,name,until,reason,time.time()))

def public_plans():
    return {k:{field:CONFIG[k][field] for field in ['label','price_gross','projects']} for k in ['free','plus','pro']}


def public_status(user):
    with s.transaction() as db:
        name,p=plan(db,user);used=totals(db,user)
        pct=None if name=='free' else min(100,round(used['cost_usd']/p['monthly_budget_usd']*100,1))
        sub=db.execute('SELECT period_end,status FROM billing_subscriptions WHERE user=?',(user,)).fetchone()
        now=datetime.datetime.now(datetime.timezone.utc)
        next_month=(now.replace(day=28)+datetime.timedelta(days=4)).replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp()
        reset=sub['period_end'] if sub and sub['status']=='active' and sub['period_end']>time.time() else next_month
    plans=public_plans()
    return {'plan':name,'limits':plans[name],'plans':plans,'usage_percent':pct,'resets_at':None if name=='free' else reset,'generation_source':'user_key' if name=='free' else 'plan'}
