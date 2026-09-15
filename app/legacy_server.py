"""Loopback-only local prototype, no external API calls."""
import argparse
import io
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote
from app import core
from app.render import frame

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass  # Never log manuscript text.
    def response(self,code,data,ctype='application/json'):
        if not isinstance(data,bytes): data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(data)
    def allowed(self):
        return self.headers.get('Host') in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']
    def do_GET(self):
        if not self.allowed(): return self.response(403,{'error':'Loopback only'})
        path=unquote(urlparse(self.path).path)
        try:
            if path=='/api/projects':
                with core.LOCK:
                    rows=[{'id':p.parent.name,'original':json.loads(p.read_text())['original'][:40]} for p in sorted(core.DATA.glob('*/project.json'),key=lambda p:p.stat().st_mtime,reverse=True)]
                return self.response(200,rows)
            if path.startswith('/api/project/'):
                with core.LOCK: p=core.load(path.rsplit('/',1)[1])
                return self.response(200,p)
            if path.startswith('/board/'):
                _,_,pid,sid=path.split('/')
                with core.LOCK: p=core.load(pid)
                shot=next(s for s in p['shots'] if s['id']==sid)
                out=io.BytesIO(); frame(p,shot).save(out,format='PNG'); return self.response(200,out.getvalue(),'image/png')
            if path.startswith('/media/'):
                root=core.DATA.resolve(); file=(root/path[len('/media/'):]).resolve()
                if not file.is_relative_to(root) or file.suffix not in ['.mp4','.png','.wav','.json','.srt']: raise ValueError('ファイルが不正です')
            else:
                root=core.ROOT/'web'; file=(root/('index.html' if path=='/' else path.lstrip('/'))).resolve()
                if not file.is_relative_to(root): raise ValueError('パスが不正です')
            return self.response(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        except (ValueError,FileNotFoundError,StopIteration): self.response(404,{'error':'見つかりません'})
    def do_POST(self):
        origin=self.headers.get('Origin')
        if not self.allowed() or self.headers.get('X-Story-Anime')!='local' or (origin and origin not in [f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}']): return self.response(403,{'error':'ローカル画面から操作してください'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=100000: raise ValueError('リクエストサイズが不正です')
            body=json.loads(self.rfile.read(n))
            with core.LOCK:
                if self.path=='/api/create': result=core.create(body['text'],body.get('fixed',''),body.get('ending',''))
                else:
                    p=core.load(body['id'])
                    if self.path=='/api/save': result=core.update(p,body)
                    elif self.path=='/api/quote': result=core.quote(p,body['ids'])
                    elif self.path=='/api/generate': result=core.start(p,body['quote_id'])
                    elif self.path=='/api/restore': result=core.restore(p)
                    elif self.path=='/api/export': result=core.export(p)
                    else: raise ValueError('操作が不正です')
            self.response(200,result)
        except (ValueError,KeyError,TypeError,FileNotFoundError) as e: self.response(400,{'error':str(e)})
        except Exception: self.response(500,{'error':'処理に失敗しました。元の素材は保存されています。'})

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); args=parser.parse_args()
    core.DATA.mkdir(exist_ok=True)
    for f in core.DATA.glob('*/project.json'):
        p=json.loads(f.read_text())
        for j in p['jobs']:
            if j['status']=='running': j.update(status='failed',error='再起動で中断しました。枠は消費していません。自動再送はしません。')
        core.save(p)
    print(f'Story Anime: http://127.0.0.1:{args.port} (local animatic, external cost ¥0)',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
if __name__=='__main__': main()
