"""Local secrets stay in ignored environment configuration; never returned to clients."""
import os
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def get(name,default=''):
    if name in os.environ:return os.environ[name]
    secret=Path(os.environ.get('YOURSTORY_SECRETS_FILE') or '/run/secrets/runtime')
    if secret.is_file():
        values=json.loads(secret.read_text())
        if name in values:return values[name]
    path=ROOT/'.env.local'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip().startswith(name+'='):return line.split('=',1)[1].strip().strip('\"\'')
    return default
