"""Explicit opt-in Google API, durable conservative spend guard; never log secrets."""
import base64
import json
import os
import sqlite3
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path
from contextlib import contextmanager
from scripts.cost_model import load_config, gemini_usage_estimate
from app import membership, settings
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'.local/gemini-usage.db'
CONFIG=load_config()['gemini']
ENABLED=False

def production_runtime():
    """本番はプロバイダー側の自動チャージ上限を正とする。"""
    return os.environ.get('YOURSTORY_RUNTIME','validation') == 'production'

def validation_limit_jpy():
    """検証CLIだけに適用する累計安全枠。"""
    return None if production_runtime() else CONFIG['budget_jpy']

def key():
    value=settings.get('GEMINI_API_KEY')
    if not value:raise ValueError('GEMINI_API_KEYが未設定です。')
    return value

@contextmanager
def db():
    DB.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB,timeout=30)
    c.execute('BEGIN IMMEDIATE')
    c.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,work TEXT,kind TEXT,model TEXT,cap REAL,status TEXT,estimate REAL,usage TEXT,created REAL)')
    if 'payer' not in {r[1] for r in c.execute('PRAGMA table_info(calls)')}:c.execute("ALTER TABLE calls ADD COLUMN payer TEXT NOT NULL DEFAULT 'operator'")
    c.commit()
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback();raise
    finally: c.close()

def budget():
    with db() as c:
        rows=c.execute("SELECT status,cap,estimate FROM calls WHERE payer='operator'").fetchall()
    return {'limit_jpy':validation_limit_jpy(),'reserved_or_spent_jpy':round(sum(r[2]*CONFIG['safety_multiplier'] if r[0]=='succeeded' and r[2] is not None else r[1] for r in rows),2),
            'estimated_jpy':round(sum(r[2] or 0 for r in rows),4),'calls':len(rows),'unknown_calls':sum(r[0]!='succeeded' for r in rows)}

def request(work,kind,prompt,images=None,aspect_ratio='16:9',on_text=None):
    if not ENABLED:raise ValueError('Geminiは停止中です。--geminiで起動してください。')
    images=images or []
    if len(prompt.encode())>18000 or len(images)>1:raise ValueError('API入力上限を超えています。')
    model=CONFIG['text_model' if kind=='text' else 'image_model'];cap=CONFIG[kind+'_request_cap_jpy']
    parts=[{'text':prompt}]
    for image in images:
        raw=Path(image).read_bytes()
        if len(raw)>8_000_000:raise ValueError('参照画像が大きすぎます。')
        parts.append({'inlineData':{'mimeType':'image/png','data':base64.b64encode(raw).decode()}})
    config={'maxOutputTokens':CONFIG[kind+'_output_tokens'],'candidateCount':1}
    if kind=='text':config.update(responseMimeType='application/json',thinkingConfig={'thinkingLevel':'low'})
    else:config.update(responseModalities=['IMAGE'],imageConfig={'aspectRatio':aspect_ratio,'imageSize':'1K'})
    body=json.dumps({'contents':[{'role':'user','parts':parts}],'generationConfig':config}).encode()
    rid,token,payer=membership.reserve(work,kind,len(prompt.encode())+(8192 if images else 0)+CONFIG[kind+'_output_tokens'],cap,model,credential=True)
    cid=uuid.uuid4().hex
    try:
        reserve_global(cid,work,kind,model,cap,payer)
    except Exception:
        membership.settle(rid,'released');raise
    return send_request(cid,rid,token,model,body,kind,on_text) if on_text else send_request(cid,rid,token,model,body,kind)

def reserve_global(cid,work,kind,model,cap,payer='operator'):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        used=c.execute("SELECT COALESCE(SUM(CASE WHEN status='succeeded' AND estimate IS NOT NULL THEN estimate*? ELSE cap END),0) FROM calls WHERE payer='operator'", (CONFIG['safety_multiplier'],)).fetchone()[0]
        limit=validation_limit_jpy()
        if payer=='operator' and limit is not None and used+cap>limit:raise ValueError('検証費用の安全上限に達しました。自動追加・自動再試行はしません。')
        c.execute('INSERT INTO calls(id,work,kind,model,cap,status,estimate,usage,created,payer) VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,work,kind,model,cap,'pending',None,None,time.time(),payer))
def send_request(cid,rid,token,model,body,kind,on_text=None,json_reply=True):
    # Cap remains consumed even after errors: HTTP failure/timeout may have incurred cost.
    try:
        req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+(':streamGenerateContent?alt=sse' if on_text else ':generateContent'),data=body,headers={'Content-Type':'application/json','x-goog-api-key':token})
        with urllib.request.urlopen(req,timeout=120) as response:
            if on_text:
                from app.streaming import collect
                data=collect(response,on_text,json_reply)
            else:data=json.load(response)
    except Exception as error:
        with db() as c:c.execute('UPDATE calls SET status=? WHERE id=?',('unknown',cid))
        membership.settle(rid,'unknown')
        status=f'HTTP {error.code}' if isinstance(error,urllib.error.HTTPError) else '通信エラー'
        if isinstance(error,urllib.error.HTTPError):
            try:
                detail=json.loads(error.read()).get('error',{}).get('message','')
                detail=detail.replace(token,'[REDACTED]')[:500]
                with db() as c:c.execute('UPDATE calls SET usage=? WHERE id=?',(json.dumps({'error':detail}),cid))
            except Exception: pass
        raise ValueError(f'Gemini {status}。APIキーの有効性、対象モデルの利用権限、Google側の請求設定・利用上限をご確認ください。自動再送はしません。') from None
    usage=data.get('usageMetadata',{})
    # Images conservatively price all output incl. thoughts at image rate; not a billing receipt.
    estimated=gemini_usage_estimate(kind,usage,{'gemini':CONFIG}) if 'promptTokenCount' in usage and 'candidatesTokenCount' in usage else None
    with db() as c:c.execute('UPDATE calls SET status=?,estimate=?,usage=? WHERE id=?',('succeeded',estimated,json.dumps(usage),cid))
    membership.settle(rid,'succeeded',usage,estimated)
    candidates=data.get('candidates',[])
    if not candidates or candidates[0].get('finishReason') not in [None,'STOP']:raise ValueError('Geminiの出力が完了しませんでした。安全枠は保持し、自動再生成しません。')
    return candidates[0].get('content',{}).get('parts',[]),{'call_id':cid,'model':model,'estimated_jpy':round(estimated,4) if estimated is not None else None,'usage':usage}

def text(work,prompt,on_text=None):
    parts,meta=request(work,'text',prompt,on_text=on_text) if on_text else request(work,'text',prompt)
    try:return json.loads(''.join(p.get('text','') for p in parts if not p.get('thought'))),meta
    except (ValueError,TypeError):raise ValueError('AIの回答形式が不正です。台本を変更せず停止しました。') from None

def image(work,prompt,target,reference=None,aspect_ratio='16:9'):
    parts,meta=request(work,'image',prompt,[reference] if reference else [],aspect_ratio)
    for p in parts:
        inline=p.get('inlineData',{})
        if inline.get('mimeType','').startswith('image/'):
            Path(target).write_bytes(base64.b64decode(inline['data']));return meta
    raise ValueError('AIから画像が返りませんでした。自動再試行しません。')

def agent_turn(work,system,contents,tools,on_text=None):
    """Native function calling. Keep model parts intact, including thought signatures."""
    if not ENABLED:raise ValueError('AI会話は停止中です。')
    model=CONFIG['text_model'];cap=CONFIG['text_request_cap_jpy']
    payload={'systemInstruction':{'parts':[{'text':system}]},'contents':contents,
             'tools':[{'functionDeclarations':tools}],
             'generationConfig':{'maxOutputTokens':CONFIG['text_output_tokens'],'candidateCount':1,'thinkingConfig':{'thinkingLevel':'low'}}}
    body=json.dumps(payload).encode()
    if len(body)>100000:raise ValueError('会話の情報量が上限を超えました。内容を切り捨てず停止しました。')
    rid,token,payer=membership.reserve(work,'text',len(body)+CONFIG['text_output_tokens'],cap,model,credential=True);cid=uuid.uuid4().hex
    try:reserve_global(cid,work,'text',model,cap,payer)
    except Exception:membership.settle(rid,'released');raise
    return send_request(cid,rid,token,model,body,'text',on_text,False)
