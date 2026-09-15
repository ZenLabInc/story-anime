"""Account-bound Gemini credentials. Never return plaintext to the client."""
import base64
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app import studio as s, accounts, settings


def init(db):
    db.execute('CREATE TABLE IF NOT EXISTS user_gemini_keys(user TEXT PRIMARY KEY REFERENCES accounts(user),ciphertext BLOB NOT NULL,updated REAL NOT NULL)')


def cipher():
    try:
        value=settings.get('BYOK_ENCRYPTION_KEY')
        if not value:value=Path(os.environ.get('YOURSTORY_KEY_ENCRYPTION_FILE','/run/secrets/gemini_key_encryption')).read_text().strip()
        raw=base64.urlsafe_b64decode(value)
        if len(raw)!=32:raise ValueError()
        return AESGCM(raw)
    except Exception:raise ValueError('APIキーの保存設定を確認中です。時間をおいてお試しください。') from None


def status(user):
    with s.transaction() as db:
        row=db.execute('SELECT updated FROM user_gemini_keys WHERE user=?',(user,)).fetchone()
    return {'configured':bool(row)}


def read(db,user):
    row=db.execute('SELECT ciphertext FROM user_gemini_keys WHERE user=?',(user,)).fetchone()
    if not row:raise ValueError('Freeで制作するには、アカウント設定にご自身のGemini APIキーを登録してください。')
    try:
        blob=bytes(row[0]);return cipher().decrypt(blob[:12],blob[12:],user.encode()).decode()
    except Exception:raise ValueError('登録したAPIキーを読み込めません。設定画面で再登録してください。') from None


def save(user,value):
    accounts.require(user)
    if not isinstance(value,str) or not re.fullmatch(r'[!-~]{20,2048}',value.strip()):raise ValueError('Gemini APIキーを入力してください。')
    value=value.strip();box=cipher()
    with s.transaction() as db:
        now=time.time()
        if db.execute("SELECT COUNT(*) FROM auth_limits WHERE kind='gemini_key' AND subject=? AND created>?",(user,now-3600)).fetchone()[0]>=10:raise ValueError('キーの確認回数が多すぎます。1時間ほどおいてお試しください。')
        db.execute('INSERT INTO auth_limits VALUES(?,?,?,?)',(s.uid(),'gemini_key',user,now))
    # Check model access without generating content or spending tokens.
    from app import gemini
    try:
        for model in {gemini.CONFIG['text_model'],gemini.CONFIG['image_model']}:
            req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+model,headers={'x-goog-api-key':value})
            with urllib.request.urlopen(req,timeout=15) as response:
                info=json.load(response)
                if 'generateContent' not in info.get('supportedGenerationMethods',[]):raise ValueError()
    except Exception:raise ValueError('APIキーを確認できませんでした。キーの有効性、Gemini APIのアクセス制限、利用可能なモデルをご確認ください。') from None
    nonce=os.urandom(12);blob=nonce+box.encrypt(nonce,value.encode(),user.encode())
    with s.transaction() as db:
        if not db.execute('SELECT 1 FROM accounts WHERE user=? AND deleted_at IS NULL',(user,)).fetchone():raise PermissionError('ログインが必要です。')
        db.execute('INSERT INTO user_gemini_keys VALUES(?,?,?) ON CONFLICT(user) DO UPDATE SET ciphertext=excluded.ciphertext,updated=excluded.updated',(user,blob,time.time()))
    return {'configured':True}


def delete(user):
    accounts.require(user)
    with s.transaction() as db:db.execute('DELETE FROM user_gemini_keys WHERE user=?',(user,))
    return {'configured':False}
