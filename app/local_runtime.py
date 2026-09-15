"""Explicit loopback-only personal mode; no company credentials or paid plans."""
import base64
import os
from app import studio, accounts, membership


def configure():
    os.environ['YOURSTORY_LOCAL']='1'
    # Ignore inherited service secrets in personal mode.
    os.environ['STRIPE_MODE']='disabled'
    for name in ['GEMINI_API_KEY','GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','SMTP_HOST','SMTP_FROM','YOURSTORY_ALLOWED_EMAILS']:
        os.environ[name]=''
    key_file=studio.DATA.parent/'local-key-encryption'
    key_file.parent.mkdir(parents=True,exist_ok=True)
    if not key_file.exists():
        fd=os.open(key_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(base64.urlsafe_b64encode(os.urandom(32)).decode())
    os.environ['BYOK_ENCRYPTION_KEY']=key_file.read_text().strip()
    # Local workspaces have no subscription requirement or practical storage quota.
    membership.CONFIG['free']=dict(membership.CONFIG['free'],projects=100000,label='ローカル')


def identity():
    guest,_=studio.session()
    token,user=accounts.complete('local','personal','local@example.test',guest['id'])
    return token
