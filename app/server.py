from app import publication, user_keys
"""Loopback-only v2 studio; use separate browsers for local multi-user testing."""
import argparse
import fcntl
import json
import mimetypes
import re
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse, parse_qs, quote
from app import studio
from app import gemini, ai_story, yourstory, workspace, accounts, membership, billing, manga_agent, style_catalog, ops_alerts

def public_payload(value):
    # Internal cost accounting and provider usage never belong in browser responses.
    hidden={'budget','api','usage','cap_jpy','cost_cap_jpy','monthly_budget_usd','cost_usd','cost_jpy','estimated_jpy','estimate_jpy','reserved_or_spent_jpy','usd_jpy','events'}
    if isinstance(value,dict):return {k:public_payload(v) for k,v in value.items() if k not in hidden}
    if isinstance(value,list):return [public_payload(v) for v in value]
    return value


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def allowed(self):
        return self.headers.get('Host') in [urlparse(self.base()).netloc, f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}']

    def base(self):
        return getattr(self.server,'public_base',f'http://127.0.0.1:{self.server.server_port}')

    def redirect(self,url,cookie=None):
        self.send_headers(303,'text/plain',0,cookie,{'Location':url})

    def identity(self):
        if getattr(self.server,'local_mode',False):
            # Personal mode has exactly one local identity. Ignore cookies left by
            # an earlier hosted/dev session so /app cannot loop through /login.
            return accounts.authenticate(self.server.local_token)
        return accounts.authenticate(self.token())

    def token(self):
        if getattr(self.server,'local_mode',False):return self.server.local_token
        c = SimpleCookie(); c.load(self.headers.get('Cookie', ''))
        return c['studio_session'].value if 'studio_session' in c else getattr(self.server,'local_token',None)

    def send_headers(self, code, ctype, length, cookie=None, extra=None):
        self.send_response(code)
        policy="default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        styles=style_catalog.public_styles()
        if styles and styles[0]['image'].startswith('https://'):
            origin=urlparse(styles[0]['image']).scheme+'://'+urlparse(styles[0]['image']).netloc
            policy=policy.replace("img-src 'self' data:","img-src 'self' data: "+origin)
        for key, value in {'Content-Type': ctype, 'Content-Length': str(length), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': policy}.items(): self.send_header(key, value) if not (key=='Content-Length' and length is None) else None
        if cookie: self.send_header('Set-Cookie', f'studio_session={cookie}; HttpOnly; SameSite=Lax; Path=/; Max-Age={accounts.SESSION_AGE}'+('; Secure' if self.base().startswith('https://') else ''))
        for key, value in (extra or {}).items(): self.send_header(key, value)
        self.end_headers()

    def reply(self, code, obj, cookie=None):
        data = json.dumps(public_payload(obj), ensure_ascii=False).encode()
        self.send_headers(code, 'application/json; charset=utf-8', len(data), cookie)
        self.wfile.write(data)

    def send_file(self, file, cookie=None):
        size = file.stat().st_size; start, end, code = 0, size-1, 200
        extra = {'Accept-Ranges': 'bytes'}
        requested = self.headers.get('Range')
        if requested:
            m = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
            if not m: return self.reply(416, {'error': 'Unsupported range'})
            start = int(m[1]); end = min(size-1, int(m[2])) if m[2] else size-1
            if start > end or start >= size: return self.reply(416, {'error': 'Invalid range'})
            code = 206; extra['Content-Range'] = f'bytes {start}-{end}/{size}'
        self.send_headers(code, mimetypes.guess_type(file.name)[0] or 'application/octet-stream', end-start+1, cookie, extra)
        with file.open('rb') as stream:
            stream.seek(start); remaining = end-start+1
            while remaining:
                chunk = stream.read(min(65536, remaining))
                self.wfile.write(chunk); remaining -= len(chunk)

    def do_GET(self):
        if not self.allowed(): return self.reply(403, {'error': 'Local only'})
        path = unquote(urlparse(self.path).path)
        try:
            if getattr(self.server,'local_mode',False) and path in ['/','/login']:
                return self.redirect('/app')
            if path in ['/','/index.html']:return self.send_file(studio.ROOT/'web/landing.html')
            if path=='/login':
                try:
                    user=self.identity();cookie=None
                    if accounts.profile(user['id']):
                        destination=parse_qs(urlparse(self.path).query).get('next',['/app'])[0]
                        return self.redirect(destination if re.fullmatch(r'/app(?:/[A-Za-z0-9_/-]*)?',destination) else '/app')
                except PermissionError:_,cookie=studio.session()
                return self.send_file(studio.ROOT/'web/login.html',cookie)
            if path in ['/app','/app/','/legacy'] or path.startswith('/app/'):
                try:accounts.require(self.identity()['id'])
                except PermissionError:return self.redirect('/login?next='+quote(self.path,safe=''))
                return self.send_file(studio.ROOT/('web/legacy.html' if path=='/legacy' else 'web/index.html'))
            if path=='/healthz':
                with studio.transaction() as db:db.execute('SELECT COUNT(*) FROM billing_subscriptions').fetchone()
                if gemini.ENABLED and not getattr(self.server,'local_mode',False):gemini.key()
                return self.reply(200,{'ok':True})
            if path in ['/api/ads-config','/ads.txt','/ads.js']:
                return self.reply(404,{'error':'見つかりません。'})
            if path=='/api/plans':return self.reply(200,{'plans':membership.public_plans()})
            if path.startswith('/styles/') and re.fullmatch(r'/styles/[a-z-]+\.webp',path):return self.send_file(studio.ROOT/'web'/path[1:])
            if path in ['/terms','/privacy','/commerce','/support']:return self.send_file(studio.ROOT/'web'/(path[1:]+'.html'))
            if path in ['/landing.css','/landing.js','/favicon.svg','/favicon.ico','/apple-touch-icon.png','/og.png','/robots.txt','/sitemap.xml']:return self.send_file(studio.ROOT/'web'/path[1:])
            if path in ['/chat-stream.js','/markdown.js','/voice.js','/shell.js','/router.js','/navigation.js','/login.js', '/login.css', '/app.js', '/style.css', '/legacy-app.js', '/legacy-style.css', '/icons.js', '/LUCIDE-LICENSE.txt']: return self.send_file(studio.ROOT/'web'/path[1:])
            user = self.identity()
            if path == '/auth/google/callback':
                query=parse_qs(urlparse(self.path).query);token,_=accounts.google_finish(query.get('state',[''])[0],query.get('code',[''])[0],self.token(),user['id'],self.base());return self.redirect('/app',token)
            if path == '/api/account':
                if getattr(self.server,'local_mode',False):
                    return self.reply(200,{'local':True,'account':{'local':True},'membership':{'plan':'free','limits':{'label':'ローカル'}},'token_usage':membership.token_usage(user['id']),'gemini_key':user_keys.status(user['id'])})
                return self.reply(200, {'account':accounts.profile(user['id']),'consent':accounts.consent_status(user['id']),'auth':accounts.config(),'membership':membership.public_status(user['id']),'billing':billing.state(user['id']),'gemini_key':user_keys.status(user['id'])})
            if membership.ENFORCE:accounts.require(user['id'])
            if path == '/api/projects': return self.reply(200, {'projects':workspace.projects(user['id']),'layouts':{k:v[0] for k,v in workspace.LAYOUTS.items()},'styles':style_catalog.public_styles(),'publication_formats':publication.catalog(),'budget':gemini.budget(),'enabled':gemini.ENABLED,'local':urlparse(self.base()).hostname in ['127.0.0.1','localhost']})
            if path == '/api/state': return self.reply(200, studio.state(user['id']))
            if path.startswith('/api/work/'): return self.reply(200, studio.read_work(user['id'], path.split('/')[-1]))
            if path.startswith('/file/'): return self.send_file(studio.file_path(user['id'], path[6:]))
            self.reply(404, {'error': '見つかりません。'})
        except PermissionError as e: self.reply(403, {'error': str(e)})
        except (ValueError, KeyError): self.reply(400, {'error': '入力が不正です。'})
        except (BrokenPipeError, ConnectionResetError): pass

    def chat_stream(self,user,body):
        self.send_headers(200,'text/event-stream; charset=utf-8',None,extra={'X-Accel-Buffering':'no','Connection':'close'})
        self.close_connection=True
        connected=True
        def emit(event,payload):
            nonlocal connected
            if not connected:return
            try:
                self.wfile.write(('event: '+event+'\ndata: '+json.dumps(public_payload(payload),ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,OSError):connected=False
        emit('status',{'text':'返答を考えています…'})
        try:
            result=manga_agent.chat(user,body,on_text=lambda text:emit('reply',{'text':text}))
            emit('done',result)
        except (ValueError,KeyError,TypeError,PermissionError) as error:emit('error',{'error':str(error)})
        except Exception:emit('error',{'error':'処理できませんでした。作品を開き直して確認してください。'})

    def do_POST(self):
        if self.path=='/api/billing/webhook':
            try:
                if not self.allowed():return self.reply(403,{'error':'Invalid host'})
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=1048576:raise ValueError('Invalid payload')
                billing.webhook(self.rfile.read(length),self.headers.get('Stripe-Signature',''))
                return self.reply(200,{'received':True})
            except ValueError as e:return self.reply(400,{'error':str(e)})
            except Exception as error:
                ops_alerts.notify('Stripe Webhook処理失敗', f'エラー種別: {type(error).__name__}\nメッセージ: {str(error)[:500]}')
                return self.reply(500,{'error':'Webhook processing failed'})
        origin = self.headers.get('Origin')
        if not self.allowed() or self.headers.get('X-Story-Anime') != 'local' or (origin and origin not in [self.base(), f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}']): return self.reply(403, {'error': 'ローカル画面から操作してください。'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 12000: raise ValueError('入力が長すぎます。')
            b = json.loads(self.rfile.read(length)); user = self.identity()['id']
            if self.path == '/api/billing/checkout':return self.reply(200,billing.checkout(user,b.get('plan'),self.base()))
            if self.path == '/api/billing/portal':return self.reply(200,billing.portal(user,self.base()))
            if self.path == '/api/auth/email/start':return self.reply(200,accounts.email_start(b.get('email'),self.token(),self.client_address[0]))
            if self.path == '/api/auth/email/finish':
                token,_=accounts.email_finish(b.get('challenge',''),b.get('code',''),self.token(),user);return self.reply(200,{'ok':True},token)
            if self.path == '/api/account/gemini-key':return self.reply(200,{'gemini_key':user_keys.delete(user) if b.get('delete') is True else user_keys.save(user,b.get('key'))})
            if self.path == '/api/account/profile':return self.reply(200,{'account':accounts.save_profile(user,b.get('display_name'))})
            if self.path == '/api/account/consent':
                if b.get('accepted') is not True: raise ValueError('利用規約とプライバシーポリシーへの同意が必要です。')
                return self.reply(200,{'consent':accounts.accept_consent(user,self.token(),self.client_address[0],self.headers.get('User-Agent',''))})
            if self.path == '/api/account/delete':
                return self.reply(200,accounts.delete_account(user,self.token(),b.get('confirmed') is True,self.client_address[0],self.headers.get('User-Agent','')))
            if self.path == '/api/auth/google':return self.reply(200,{'url':accounts.google_start(self.token(),self.base())})
            if self.path == '/api/auth/logout':
                accounts.logout(self.token());_,token=studio.session();return self.reply(200,{'ok':True},token)
            if membership.ENFORCE:accounts.require(user)
            if self.path == '/api/project/new' and membership.ENFORCE:membership.project_allowed(user)
            if self.path in ['/api/new','/api/chat','/api/script','/api/approve','/api/generate','/api/publish','/api/export','/api/like']: raise ValueError('以前の作品は閲覧専用です。漫画ワークスペースで制作してください。')
            if self.path in ['/api/approve','/api/generate'] and studio.read_work(user,b['id']).get('version') != 3: raise ValueError('旧作品の新規生成は停止しました。YourStoryの新しい漫画を作成してください。')
            if self.path == '/api/project/new': result = workspace.create(user, b.get('title',''))
            elif self.path == '/api/project/delete': result = workspace.soft_delete(user,b)
            elif self.path == '/api/project/confirm':
                from app.confirmations import accept
                result=accept(user,b)
            elif self.path == '/api/project/edit': result = workspace.mutate(user,b)
            elif self.path == '/api/project/chat/stream': return self.chat_stream(user,b)
            elif self.path == '/api/project/chat': result = manga_agent.chat(user,b)
            elif self.path == '/api/project/quote': result = workspace.quote(user,b)
            elif self.path == '/api/project/generate': result = workspace.generate(user,b)
            elif self.path == '/api/new': result = yourstory.create(user)
            elif self.path == '/api/chat': result = yourstory.chat(user, b['id'], b['text'], b['revision'])
            elif self.path == '/api/approve': result = studio.approve(user, b['id'], b['revision'])
            elif self.path == '/api/generate': result = studio.generate(user, b['id'], b['quote_id'])
            elif self.path == '/api/export': result = studio.export(user, b['id'], b['revision'])
            elif self.path == '/api/publish': result = studio.publish(user, b['id'], b['revision'], b['visible'])
            elif self.path == '/api/like': result = studio.like(user, b['id'], b['liked'])
            elif self.path == '/api/script': result = yourstory.script(user, b['id'], b['revision'])
            else: raise ValueError('操作が見つかりません。')
            self.reply(200, result)
        except PermissionError as e: self.reply(403, {'error': str(e)})
        except (ValueError, KeyError, TypeError) as e: self.reply(400, {'error': str(e)})
        except Exception: self.reply(500, {'error': '処理できませんでした。作品を開き直してください。'})


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8765); parser.add_argument('--gemini', action='store_true'); parser.add_argument('--dev-auth',action='store_true');parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--base-url');parser.add_argument('--local',action='store_true',help='自分のPC専用。クラウド認証・課金を使わず起動');args = parser.parse_args()
    if args.local and args.host not in ['127.0.0.1','localhost']:raise SystemExit('--local は自分のPCからのみ接続できます。')
    if args.local:
        from app.local_runtime import configure
        configure()
    if args.dev_auth and args.host not in ['127.0.0.1','localhost']:raise SystemExit('開発用メール認証はループバック専用です。')
    if args.host not in ['127.0.0.1','localhost'] and (not args.base_url or not args.base_url.startswith('https://')):raise SystemExit('外部リスンにはHTTPSのbase-urlが必要です。')
    accounts.DEV_AUTH=args.dev_auth;membership.ENFORCE=True
    gemini.ENABLED = args.gemini or args.local
    if gemini.ENABLED and not args.local: gemini.key()
    studio.DATA.mkdir(parents=True, exist_ok=True)
    with (studio.DATA/'server.lock').open('w') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Story Animeはすでに起動しています。')
        studio.init()
        workspace.init()
        membership.recover()
        print(f'YourStory: http://127.0.0.1:{args.port} / Gemini={gemini.ENABLED}', flush=True)
        server=ThreadingHTTPServer((args.host,args.port),Handler)
        if args.local:
            from app.local_runtime import identity
            server.local_mode=True
            server.local_token=identity()
        if args.base_url:server.public_base=args.base_url.rstrip('/')
        server.serve_forever()

if __name__ == '__main__': main()
