"""Passwordless email and Google OIDC with expiring, revocable server sessions."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from urllib.parse import urlencode
import urllib.request
from app import studio as s, settings, ops_alerts
DEV_AUTH=False
SESSION_AGE=7*86400
TERMS_VERSION='2026-09-14'
PRIVACY_VERSION='2026-09-14'
RECENT_AUTH_AGE=15*60

def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def init():
    with s.transaction() as db:db.executescript('''
    CREATE TABLE IF NOT EXISTS accounts(user TEXT PRIMARY KEY REFERENCES users(id),email TEXT NOT NULL,provider TEXT NOT NULL,subject TEXT NOT NULL,verified INTEGER NOT NULL,created REAL NOT NULL,UNIQUE(provider,subject));
    CREATE TABLE IF NOT EXISTS account_profiles(user TEXT PRIMARY KEY REFERENCES accounts(user),display_name TEXT NOT NULL,updated REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT NOT NULL REFERENCES users(id),expires REAL NOT NULL,authenticated_at REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS login_challenges(id TEXT PRIMARY KEY,email TEXT NOT NULL,code TEXT NOT NULL,browser TEXT NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,used INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,ip TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS oauth_states(hash TEXT PRIMARY KEY,browser TEXT NOT NULL,nonce TEXT NOT NULL,verifier TEXT NOT NULL,expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS auth_limits(id TEXT PRIMARY KEY,kind TEXT NOT NULL,subject TEXT NOT NULL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS account_tombstones(id TEXT PRIMARY KEY,user_hash TEXT NOT NULL,provider_subject_hash TEXT NOT NULL,email_hash TEXT NOT NULL,deleted_at REAL NOT NULL,reusable_at REAL NOT NULL,UNIQUE(provider_subject_hash),UNIQUE(email_hash));
    CREATE TABLE IF NOT EXISTS account_consents(id TEXT PRIMARY KEY,user TEXT NOT NULL REFERENCES accounts(user),terms_version TEXT NOT NULL,privacy_version TEXT NOT NULL,accepted_at REAL NOT NULL,ip TEXT NOT NULL,user_agent TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS account_events(id TEXT PRIMARY KEY,user TEXT NOT NULL,kind TEXT NOT NULL,version TEXT,created REAL NOT NULL,metadata TEXT NOT NULL);
    ''')
    with s.transaction() as db:
        from app import user_keys
        user_keys.init(db)
        columns={r[1] for r in db.execute('PRAGMA table_info(accounts)')}
        for name,definition in [('terms_version','TEXT'),('privacy_version','TEXT'),('terms_accepted_at','REAL'),('privacy_accepted_at','REAL'),('deleted_at','REAL'),('deleted_consent_version','TEXT'),('deleted_consent_at','REAL'),('deleted_by','TEXT')]:
            if name not in columns:db.execute(f'ALTER TABLE accounts ADD COLUMN {name} {definition}')
        columns={r[1] for r in db.execute('PRAGMA table_info(sessions)')}
        if 'authenticated_at' not in columns:db.execute('ALTER TABLE sessions ADD COLUMN authenticated_at REAL NOT NULL DEFAULT 0')

def config():
    return {'google':bool(settings.get('GOOGLE_CLIENT_ID') and settings.get('GOOGLE_CLIENT_SECRET')),
            'email':bool(settings.get('SMTP_HOST') and settings.get('SMTP_FROM')),'dev':DEV_AUTH}

def profile(user):
    with s.transaction() as db:
        row=db.execute("SELECT a.email,a.provider,a.verified,COALESCE(p.display_name,'') AS display_name,a.terms_version,a.privacy_version,a.terms_accepted_at,a.privacy_accepted_at,a.deleted_at FROM accounts a LEFT JOIN account_profiles p ON p.user=a.user WHERE a.user=?",(user,)).fetchone()
        if not row or row['deleted_at']:return None
        value=dict(row);value['consent_required']=value['terms_version']!=TERMS_VERSION or value['privacy_version']!=PRIVACY_VERSION
        return value

def consent_status(user):
    value=profile(user)
    if not value:return None
    return {'terms_version':value['terms_version'],'privacy_version':value['privacy_version'],'accepted_at':value['terms_accepted_at'],'required':value['consent_required'],'current_terms_version':TERMS_VERSION,'current_privacy_version':PRIVACY_VERSION}

def accept_consent(user, token, ip='', user_agent=''):
    require(user)
    with s.transaction() as db:
        if not db.execute('SELECT 1 FROM sessions WHERE hash=? AND user=? AND expires>?',(digest(token or ''),user,time.time())).fetchone():raise PermissionError('ログイン状態を確認できません。')
        now=time.time();db.execute('UPDATE accounts SET terms_version=?,privacy_version=?,terms_accepted_at=?,privacy_accepted_at=? WHERE user=?',(TERMS_VERSION,PRIVACY_VERSION,now,now,user))
        db.execute('INSERT INTO account_consents VALUES(?,?,?,?,?,?,?)',(s.uid(),user,TERMS_VERSION,PRIVACY_VERSION,now,digest(ip or ''),str(user_agent or '')[:300]))
        db.execute('INSERT INTO account_events VALUES(?,?,?,?,?,?)',(s.uid(),user,'consent',TERMS_VERSION,now,json.dumps({'privacy_version':PRIVACY_VERSION},ensure_ascii=False)))
        from app import metrics
        metrics.track_conn(db, user, 'consent_accepted', attrs={'source':'account'})
    return consent_status(user)

def save_profile(user, name):
    require(user)
    if not isinstance(name,str):raise ValueError('ユーザー名を入力してください。')
    name=name.strip()
    if not 1<=len(name)<=30 or any(ord(c)<32 or ord(c)==127 for c in name):raise ValueError('ユーザー名は改行なしの1〜30文字で入力してください。')
    with s.transaction() as db:
        db.execute('INSERT INTO account_profiles VALUES(?,?,?) ON CONFLICT(user) DO UPDATE SET display_name=excluded.display_name,updated=excluded.updated',(user,name,time.time()))
    return profile(user)

def require(user):
    value=profile(user)
    if not value:raise PermissionError('生成を始めるにはログインしてください。')
    return value

def authenticate(token):
    with s.transaction() as db:
        row=db.execute('SELECT u.id,u.name,u.balance FROM sessions x JOIN users u ON x.user=u.id JOIN accounts a ON a.user=u.id WHERE x.hash=? AND x.expires>? AND a.deleted_at IS NULL',(digest(token or ''),time.time())).fetchone()
    return dict(row) if row else s.authenticate(token)

def logout(token):
    with s.transaction() as db:
        db.execute('DELETE FROM sessions WHERE hash=?',(digest(token or ''),))
        # Rotate legacy guest token too; never leave an authenticated account behind it.
        db.execute('UPDATE users SET token_hash=? WHERE token_hash=?',(digest(secrets.token_urlsafe(32)),digest(token or '')))

def complete(provider,subject,email,guest,verified=True):
    allowed={x.strip().lower() for x in settings.get('YOURSTORY_ALLOWED_EMAILS').split(',') if x.strip()}
    if allowed and email.lower() not in allowed:raise PermissionError('現在は招待されたアカウントのみログインできます。')
    now=time.time();subject_hash=digest(provider+'\x00'+subject);email_hash=digest(email.lower())
    created=False
    with s.transaction() as db:
        blocked=db.execute('SELECT reusable_at FROM account_tombstones WHERE provider_subject_hash=? OR email_hash=?',(subject_hash,email_hash)).fetchone()
        if blocked and blocked['reusable_at']>now:raise PermissionError('削除したアカウントは30日間、同じ認証情報で再登録できません。')
        row=db.execute('SELECT user FROM accounts WHERE provider=? AND subject=?',(provider,subject)).fetchone()
        if row:
            user=row[0]
            deleted=db.execute('SELECT deleted_at FROM accounts WHERE user=?',(user,)).fetchone()
            if deleted and deleted['deleted_at']:raise PermissionError('このアカウントは削除済みです。再登録が必要です。')
        else:
            # Same email is not an automatic account link across identity providers.
            existing=db.execute('SELECT 1 FROM accounts WHERE user=?',(guest,)).fetchone()
            user=s.uid() if existing else guest
            if existing:db.execute('INSERT INTO users VALUES(?,?,?,?)',(user,digest(secrets.token_urlsafe(32)),email.split('@')[0],0))
            db.execute('INSERT INTO accounts(user,email,provider,subject,verified,created) VALUES(?,?,?,?,?,?)',(user,email,provider,subject,int(verified),time.time()))
            created=True
        if guest!=user and not db.execute('SELECT 1 FROM accounts WHERE user=?',(guest,)).fetchone():
            # Possession of the existing guest cookie is required. Copy ownership, not other accounts.
            for row in db.execute('SELECT data FROM works WHERE owner=?',(guest,)):
                p=json.loads(row[0]);p['owner']=user;s.put(db,p)
            db.execute('UPDATE works SET owner=? WHERE owner=?',(user,guest))
        # Invalidate all old guest cookies after attaching work to a verified identity.
        for uid in {guest,user}:db.execute('UPDATE users SET token_hash=? WHERE id=?',(digest(secrets.token_urlsafe(32)),uid))
        token=secrets.token_urlsafe(32)
        db.execute('INSERT INTO sessions(hash,user,expires,authenticated_at) VALUES(?,?,?,?)',(digest(token),user,time.time()+SESSION_AGE,time.time()))
        from app import metrics
        if created:metrics.track_conn(db, user, 'account_created', attrs={'provider':provider})
    return token,user

def delete_account(user, token, confirmed, ip='', user_agent=''):
    if confirmed is not True:raise ValueError('削除への同意が必要です。')
    current=require(user)
    if current.get('consent_required'):raise PermissionError('削除前に最新の利用規約とプライバシーポリシーへ同意してください。')
    now=time.time()
    with s.transaction() as db:
        session=db.execute('SELECT authenticated_at FROM sessions WHERE hash=? AND user=? AND expires>?',(digest(token or ''),user,now)).fetchone()
        if not session or now-session['authenticated_at']>RECENT_AUTH_AGE:raise PermissionError('安全のため、いったんログアウトして再ログインしてから削除してください。')
        identity=db.execute('SELECT email,provider,subject FROM accounts WHERE user=?',(user,)).fetchone()
        sub=db.execute('SELECT status,cancel_pending FROM billing_subscriptions WHERE user=?',(user,)).fetchone()
        if sub and (sub['status'] not in ['canceled','incomplete_expired'] or sub['cancel_pending']):raise ValueError('契約管理で解約が完了してからアカウントを削除してください。')
        if db.execute("SELECT 1 FROM jobs WHERE owner=? AND json_extract(data,'$.status')='running' LIMIT 1",(user,)).fetchone():raise ValueError('生成処理が完了してから削除してください。')
        for row in db.execute('SELECT id,data FROM works WHERE owner=?',(user,)):
            value=json.loads(row['data']);value['account_deleted_at']=now;db.execute('UPDATE works SET data=?,updated=? WHERE id=?',(json.dumps(value,ensure_ascii=False),now,row['id']))
        db.execute('INSERT OR REPLACE INTO account_tombstones VALUES(?,?,?,?,?,?)',(s.uid(),digest(user),digest(identity['provider']+'\x00'+identity['subject']),digest(identity['email'].lower()),now,now+30*86400))
        db.execute('UPDATE accounts SET deleted_at=?,deleted_consent_version=?,deleted_consent_at=?,deleted_by=? WHERE user=?',(now,TERMS_VERSION,now,user,user))
        db.execute('INSERT INTO account_events VALUES(?,?,?,?,?,?)',(s.uid(),user,'account_deleted',TERMS_VERSION,now,json.dumps({'ip':digest(ip or ''),'user_agent':str(user_agent or '')[:300]},ensure_ascii=False)))
        from app import metrics
        metrics.track_conn(db, user, 'account_deleted', attrs={'source':'account'})
        db.execute('DELETE FROM user_gemini_keys WHERE user=?',(user,))
        db.execute('DELETE FROM sessions WHERE user=?',(user,))
        db.execute('UPDATE users SET token_hash=? WHERE id=?',(digest(secrets.token_urlsafe(32)),user))
    return {'deleted':True,'retained_data':'論理削除として保管方針に従い保持されます。'}

def email_start(email,browser,ip):
    email=email.strip().lower() if isinstance(email,str) else ''
    if len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('メールアドレスを確認してください。')
    dev=DEV_AUTH and email.endswith('@example.test')
    if not dev and not config()['email']:raise ValueError('メール配信が未設定です。Googleログイン、または開発用メール認証を利用してください。')
    cid=secrets.token_urlsafe(24);code=f'{secrets.randbelow(1000000):06d}';now=time.time()
    with s.transaction() as db:
        if db.execute('SELECT COUNT(*) FROM login_challenges WHERE created>?',(now-86400,)).fetchone()[0]>=200:raise ValueError('本日の認証メール送信上限に達しました。Googleログインをご利用ください。')
        for subject,column,limit in [(email,'email',3),(digest(ip),'ip',10)]:
            if db.execute(f'SELECT COUNT(*) FROM login_challenges WHERE {column}=? AND created>?',(subject,now-600)).fetchone()[0]>=limit:raise ValueError('送信回数の上限です。10分後にお試しください。')
        db.execute('INSERT INTO login_challenges(id,email,code,browser,expires,created,ip) VALUES(?,?,?,?,?,?,?)',(cid,email,digest(cid+code),digest(browser),now+600,now,digest(ip)))
    if dev:return {'challenge':cid,'dev_code':code,'message':'開発用認証です。メールは送信していません。example.test専用。'}
    msg=EmailMessage();msg['From']=settings.get('SMTP_FROM');msg['To']=email;msg['Subject']='YourStory ログイン認証コード';msg.set_content(f'YourStoryの認証コード: {code}\n10分間有効です。心当たりがなければ無視してください。')
    try:
        with smtplib.SMTP(settings.get('SMTP_HOST'),int(settings.get('SMTP_PORT','587')),timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings.get('SMTP_USER'):smtp.login(settings.get('SMTP_USER'),settings.get('SMTP_PASSWORD'))
            smtp.send_message(msg)
    except Exception as error:
        with s.transaction() as db:db.execute('UPDATE login_challenges SET used=1 WHERE id=?',(cid,))
        ops_alerts.notify('認証メールの配信失敗', f'宛先: {ops_alerts.masked_email(email)}\nエラー種別: {type(error).__name__}')
        raise ValueError('メールを配信できませんでした。自動再送はしません。') from None
    return {'challenge':cid,'message':'認証コードを送信しました。10分以内に入力してください。'}

def email_finish(cid,code,browser,guest):
    valid=False;email=''
    with s.transaction() as db:
        r=db.execute('SELECT * FROM login_challenges WHERE id=?',(cid,)).fetchone()
        if r and not r['used'] and r['expires']>time.time() and r['attempts']<5 and hmac.compare_digest(r['browser'],digest(browser)):
            db.execute('UPDATE login_challenges SET attempts=attempts+1 WHERE id=?',(cid,))
            valid=isinstance(code,str) and hmac.compare_digest(r['code'],digest(cid+code))
            if valid:
                email=r['email'];db.execute('UPDATE login_challenges SET used=1 WHERE id=?',(cid,))
    if not valid:raise ValueError('コードが無効、期限切れ、または試行上限です。')
    dev=email.endswith('@example.test') and DEV_AUTH
    return complete('dev' if dev else 'email',email,email,guest,not dev)

def google_start(browser,base):
    if not config()['google']:raise ValueError('GoogleログインのOAuth設定が未完了です。')
    state=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
    with s.transaction() as db:
        db.execute('DELETE FROM oauth_states WHERE expires<?',(time.time(),))
        if db.execute('SELECT COUNT(*) FROM oauth_states WHERE browser=?',(digest(browser),)).fetchone()[0]>=5:raise ValueError('ログイン試行が多すぎます。10分後にお試しください。')
        db.execute('INSERT INTO oauth_states VALUES(?,?,?,?,?)',(digest(state),digest(browser),nonce,verifier,time.time()+600))
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return 'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':settings.get('GOOGLE_CLIENT_ID'),'redirect_uri':base+'/auth/google/callback','response_type':'code','scope':'openid email profile','state':state,'nonce':nonce,'code_challenge':challenge,'code_challenge_method':'S256','prompt':'select_account'})

def verify_google(token,audience,nonce):
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request
    claims=id_token.verify_oauth2_token(token,Request(),audience)
    if claims.get('nonce')!=nonce or claims.get('email_verified') is not True or not claims.get('sub'):raise ValueError('Googleの本人確認に失敗しました。')
    return claims

def google_finish(state,code,browser,guest,base):
    with s.transaction() as db:
        r=db.execute('SELECT * FROM oauth_states WHERE hash=?',(digest(state),)).fetchone()
        if not r or r['expires']<time.time() or not hmac.compare_digest(r['browser'],digest(browser)):raise ValueError('ログイン状態が無効です。最初からやり直してください。')
        db.execute('DELETE FROM oauth_states WHERE hash=?',(digest(state),))
    data=urlencode({'client_id':settings.get('GOOGLE_CLIENT_ID'),'client_secret':settings.get('GOOGLE_CLIENT_SECRET'),'code':code,'code_verifier':r['verifier'],'grant_type':'authorization_code','redirect_uri':base+'/auth/google/callback'}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token',data=data),timeout=15) as response:token=json.load(response)['id_token']
        claims=verify_google(token,settings.get('GOOGLE_CLIENT_ID'),r['nonce'])
    except Exception:raise ValueError('Googleログインを検証できませんでした。再度ログインしてください。') from None
    return complete('google',claims['sub'],claims['email'],guest)
