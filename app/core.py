import copy
import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path
from app.render import render, frame, run

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'.local'
LOCK=threading.RLock()

def uid(): return uuid.uuid4().hex

def digest(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def save(p):
    folder=DATA/p['id']; folder.mkdir(parents=True,exist_ok=True)
    temp=folder/'project.tmp'; temp.write_text(json.dumps(p,ensure_ascii=False,indent=2)); temp.replace(folder/'project.json')

def load(pid):
    if not re.fullmatch('[a-f0-9]{32}',pid): raise ValueError('作品IDが不正です')
    return json.loads((DATA/pid/'project.json').read_text())

def create(text, fixed='', ending=''):
    if not isinstance(text,str) or not isinstance(fixed,str) or not isinstance(ending,str) or len(fixed)>240 or len(ending)>300: raise ValueError('文章・固定セリフ・結末の入力が不正です')
    if not text.strip() or len(text)>240: raise ValueError('文章は1〜240文字で入力してください')
    if fixed and fixed not in text: raise ValueError('固定セリフは原文に含まれる文字列を指定してください')
    lines=[s.strip() for s in text.splitlines() if s.strip()]
    if len(lines)==1:
        lines=[s for s in re.findall(r'.+?(?:[。！？]|$)',text) if s]
    if len(lines)>6 or any(len(s)>55 for s in lines):
        raise ValueError('30秒では6場面までです。6行以内、各行55文字以内に整理してください。原文は自動で削りません。')
    if fixed and not any(fixed in line for line in lines): raise ValueError('固定セリフが場面をまたいでいます。1つの行にまとめてください')
    p={'id':uid(),'revision':1,'original':text,'fixed':fixed,'ending':ending,'characters':[{'name':'主人公','color':'#78a9b2','voice':'Kyoko'},{'name':'もう一人','color':'#bb8a80','voice':'Eddy (日本語（日本）)'}], 'shots':[], 'jobs':[], 'quotes':{}, 'history':[], 'used_seconds':0, 'budget_seconds':120, 'export':None}
    for i in range(6):
        p['shots'].append({'id':str(i+1),'text':lines[i] if i<len(lines) else '', 'direction':'静かな対話' if i<5 else '結末を静かに見せる', 'speaker':i%2,'pause':0.3,'expression':'neutral','locked':False,'asset':None})
    save(p); return p

def editable(p): return {'characters':p['characters'],'shots':p['shots']}

def update(p, body):
    if body['revision']!=p['revision']: raise ValueError('別の編集が保存されています。再読み込みしてください')
    if any(j['status']=='running' for j in p['jobs']): raise ValueError('生成中は編集できません')
    chars=copy.deepcopy(body['characters']); shots=copy.deepcopy(body['shots'])
    if len(chars)!=2 or len(shots)!=6: raise ValueError('人物2人・6場面に限定しています')
    for c in chars:
        if not isinstance(c['name'],str) or not 1<=len(c['name'])<=20 or not re.fullmatch('#[0-9a-fA-F]{6}',c['color']) or c['voice'] not in ['Kyoko','Eddy (日本語（日本）)']: raise ValueError('人物設定が不正です')
    if [s['id'] for s in shots]!=[s['id'] for s in p['shots']]: raise ValueError('場面IDを変更できません')
    changed_chars=chars!=p['characters']
    for old,new in zip(p['shots'],shots):
        if type(new.get('locked')) is not bool: raise ValueError('保持状態が不正です')
        if not isinstance(new['text'],str) or len(new['text'])>55 or not isinstance(new['direction'],str) or len(new['direction'])>80 or new['speaker'] not in [0,1] or not isinstance(new['pause'],(float,int)) or not 0<=new['pause']<=3 or new['expression'] not in ['neutral','smile']: raise ValueError('場面設定が不正です')
        if old['locked'] and (changed_chars or any(old[k]!=new[k] for k in ['text','direction','speaker','pause','expression'])): raise ValueError('保持した場面は変更できません。先に保持を解除して保存してください')
        if p['fixed'] and p['fixed'] in old['text'] and p['fixed'] not in new['text']: raise ValueError('固定セリフは変更・移動できません')
        new['asset']=old['asset']
        if changed_chars or any(old[k]!=new[k] for k in ['text','direction','speaker','pause','expression']): new['asset']=None
    p['history'].append(copy.deepcopy(editable(p)))
    p['characters']=chars; p['shots']=shots; p['revision']+=1; p['export']=None; p['quotes']={}; save(p); return p

def quote(p, ids):
    if not ids or len(ids)!=len(set(ids)) or any(i not in [s['id'] for s in p['shots']] for i in ids): raise ValueError('対象の場面を選んでください')
    if any(s['locked'] for s in p['shots'] if s['id'] in ids): raise ValueError('保持した場面は生成対象にできません')
    seconds=5*len(ids)
    if p['used_seconds']+seconds>p['budget_seconds']: raise ValueError('試用枠120秒を超えます。追加消費は開始しません')
    q={'id':uid(),'revision':p['revision'],'ids':ids,'seconds':seconds,'images':len(ids),'external_cost_jpy':0,'mode':'local-animatic','expires':time.time()+600}
    p['quotes'][q['id']]=q; save(p); return q

def start(p, qid):
    previous=next((j for j in p['jobs'] if j['quote_id']==qid),None)
    if previous: return previous
    if any(j['status']=='running' for j in p['jobs']): raise ValueError('生成中です')
    q=p['quotes'].get(qid)
    if not q or q['revision']!=p['revision'] or q['expires']<time.time(): raise ValueError('見積が古くなりました。再見積してください')
    if p['used_seconds']+q['seconds']>p['budget_seconds']: raise ValueError('残量不足です')
    j={'id':uid(),'quote_id':qid,'status':'running','completed':0,'seconds':q['seconds'],'external_cost_jpy':0,'started':time.time(),'ids':q['ids']}
    p['jobs'].append(j); save(p)
    threading.Thread(target=worker,args=(copy.deepcopy(p),j['id']),daemon=True).start()
    return j

def worker(snapshot,jid):
    job=next(j for j in snapshot['jobs'] if j['id']==jid)
    assets={}
    try:
        for shot in snapshot['shots']:
            if shot['id'] not in job['ids']: continue
            aid=uid(); folder=DATA/snapshot['id']/'assets'/aid
            meta=render(snapshot,shot,folder)
            assets[shot['id']]={**meta,'id':aid,'sha256':hashlib.sha256((folder/'clip.mp4').read_bytes()).hexdigest()}
            with LOCK:
                p=load(snapshot['id']); j=next(j for j in p['jobs'] if j['id']==jid); j['completed']+=1; save(p)
        with LOCK:
            p=load(snapshot['id']); p['history'].append(copy.deepcopy(editable(p)))
            for s in p['shots']:
                if s['id'] in assets: s['asset']=assets[s['id']]
            p['revision']+=1; p['used_seconds']+=job['seconds']; p['quotes']={}; p['export']=None
            j=next(j for j in p['jobs'] if j['id']==jid); j.update(status='succeeded',elapsed_seconds=round(time.time()-j['started'],2)); save(p)
    except Exception as e:
        with LOCK:
            p=load(snapshot['id']); j=next(j for j in p['jobs'] if j['id']==jid)
            j.update(status='failed',error=str(e) if isinstance(e,ValueError) else 'ローカル生成処理に失敗しました。FFmpegと音声の設定を確認してください。',elapsed_seconds=round(time.time()-j['started'],2)); save(p)

def restore(p):
    if any(j['status']=='running' for j in p['jobs']): raise ValueError('生成中は復元できません')
    if not p['history']: raise ValueError('戻せる履歴がありません')
    previous=p['history'].pop(); p.update(previous); p['revision']+=1; p['quotes']={}; p['export']=None; save(p); return p

def export(p):
    if any(j['status']=='running' for j in p['jobs']): raise ValueError('生成完了を待ってください')
    if any(not s['asset'] for s in p['shots']): raise ValueError('未生成または編集済みの場面があります')
    folder=DATA/p['id']/'exports'/uid(); folder.mkdir(parents=True)
    clips=[DATA/p['id']/'assets'/s['asset']['id']/'clip.mp4' for s in p['shots']]
    (folder/'concat.txt').write_text('\n'.join("file '"+str(c)+"'" for c in clips))
    run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(folder/'concat.txt'),'-c','copy','-movflags','+faststart',str(folder/'film.mp4')])
    def ts(n): return f'00:00:{n:02d},000'
    (folder/'captions.srt').write_text('\n\n'.join(f"{i+1}\n{ts(i*5)} --> {ts((i+1)*5)}\n{s['text']}" for i,s in enumerate(p['shots']) if s['text']))
    (folder/'project.json').write_text(json.dumps(p,ensure_ascii=False,indent=2))
    p['export']=str(folder.relative_to(DATA))+'/film.mp4'; save(p); return p
