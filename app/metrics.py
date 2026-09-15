"""Small, privacy-preserving product measurement ledger.

The ledger is deliberately separate from the product and billing tables.  It
stores opaque identifiers and bounded operational attributes only; story text,
prompts, images and email addresses never enter this database.
"""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

EVENTS = {
    'account_created', 'consent_accepted', 'project_created', 'chat_turn_completed',
    'first_value', 'character_visual_confirmed', 'world_confirmed', 'scene_confirmed',
    'generation_started', 'generation_completed', 'generation_failed', 'exported',
    'subscription_started', 'subscription_renewed', 'subscription_canceled', 'account_deleted',
}
SAFE_ATTRS = {
    'kind', 'image_count', 'text_tokens', 'image_tokens', 'model', 'provider',
    'status', 'error_class', 'latency_ms', 'cost_usd_estimated', 'cost_usd_invoiced',
    'format', 'plan', 'source', 'payer',
}
DB = Path(os.environ.get('YOURSTORY_METRICS_DB', '.local/studio/metrics.db'))


def opaque(value):
    return hashlib.sha256(('yourstory-metrics-v1:' + str(value)).encode()).hexdigest()


def _schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS metric_events(
      event_id TEXT PRIMARY KEY, occurred_at REAL NOT NULL, event TEXT NOT NULL,
      user_hash TEXT NOT NULL, project_hash TEXT, plan TEXT, app_release TEXT,
      provider TEXT, model TEXT, latency_ms REAL, status TEXT, error_class TEXT,
      image_count INTEGER, text_tokens INTEGER, image_tokens INTEGER,
      cost_usd_estimated REAL, cost_usd_invoiced REAL, attrs TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS metric_events_time ON metric_events(occurred_at);
    CREATE INDEX IF NOT EXISTS metric_events_event ON metric_events(event);
    CREATE TABLE IF NOT EXISTS metric_monthly(
      month TEXT NOT NULL, event TEXT NOT NULL, plan TEXT,
      event_count INTEGER NOT NULL, unique_users INTEGER NOT NULL,
      cost_usd_estimated REAL NOT NULL, PRIMARY KEY(month,event,plan)
    );
    ''')


def init(path=None):
    """Create the ledger.  ``path`` is useful for tests and local reports."""
    target = Path(path or DB)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as db:
        _schema(db)
    return target


def _bounded_attrs(attrs):
    result = {}
    for key, value in (attrs or {}).items():
        if key not in SAFE_ATTRS:
            continue
        if isinstance(value, bool):
            result[key] = value
        elif isinstance(value, (int, float)) and value == value and abs(value) < 1e12:
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:120]
    return result


def _plan(db, user):
    try:
        row = db.execute('SELECT plan FROM memberships WHERE user=?', (user,)).fetchone()
        if row and row[0] in ('free', 'plus', 'pro'):
            return row[0]
    except sqlite3.OperationalError:
        pass
    return 'free'


def track_conn(db, user, event, project=None, attrs=None, occurred=None):
    """Append one event to an existing transaction without committing it."""
    if event not in EVENTS:
        raise ValueError('未知の計測イベントです。')
    _schema(db)
    clean = _bounded_attrs(attrs)
    values = {
        'event_id': hashlib.sha256(f'{time.time_ns()}:{user}:{event}:{project}'.encode()).hexdigest(),
        'occurred_at': time.time() if occurred is None else float(occurred),
        'event': event, 'user_hash': opaque(user),
        'project_hash': opaque(project) if project else None,
        'plan': clean.get('plan') or _plan(db, user),
        'app_release': str(os.environ.get('YOURSTORY_RELEASE') or os.environ.get('APP_RELEASE') or 'local')[:80],
        'provider': clean.get('provider'), 'model': clean.get('model'),
        'latency_ms': clean.get('latency_ms'), 'status': clean.get('status'),
        'error_class': clean.get('error_class'), 'image_count': clean.get('image_count'),
        'text_tokens': clean.get('text_tokens'), 'image_tokens': clean.get('image_tokens'),
        'cost_usd_estimated': clean.get('cost_usd_estimated'),
        'cost_usd_invoiced': clean.get('cost_usd_invoiced'),
        'attrs': json.dumps(clean, ensure_ascii=False, separators=(',', ':')),
    }
    db.execute('''INSERT INTO metric_events
      (event_id,occurred_at,event,user_hash,project_hash,plan,app_release,provider,model,
       latency_ms,status,error_class,image_count,text_tokens,image_tokens,cost_usd_estimated,
       cost_usd_invoiced,attrs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', tuple(values[k] for k in [
        'event_id','occurred_at','event','user_hash','project_hash','plan','app_release','provider','model',
        'latency_ms','status','error_class','image_count','text_tokens','image_tokens',
        'cost_usd_estimated','cost_usd_invoiced','attrs']))
    return values['event_id']


def track_once_conn(db, user, event, project=None, attrs=None, occurred=None):
    """Append an event only when this user/project has not emitted it before."""
    if event not in EVENTS:
        raise ValueError('未知の計測イベントです。')
    project_hash = opaque(project) if project else None
    query = 'SELECT 1 FROM metric_events WHERE event=? AND user_hash=?'
    args = [event, opaque(user)]
    if project_hash is None:
        query += ' AND project_hash IS NULL'
    else:
        query += ' AND project_hash=?'; args.append(project_hash)
    if db.execute(query, args).fetchone():
        return None
    return track_conn(db, user, event, project, attrs, occurred)


def track(user, event, project=None, attrs=None, occurred=None, path=None):
    target = init(path)
    with sqlite3.connect(target) as db:
        track_conn(db, user, event, project, attrs, occurred)


def rollup(path=None, start=None, end=None):
    """Rebuild month buckets for a time range and return the number written."""
    target = init(path)
    with sqlite3.connect(target) as db:
        db.row_factory = sqlite3.Row
        clauses = []; args = []
        if start is not None: clauses.append('occurred_at>=?'); args.append(float(start))
        if end is not None: clauses.append('occurred_at<?'); args.append(float(end))
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        rows = db.execute('''SELECT strftime('%Y-%m',occurred_at,'unixepoch') month,event,COALESCE(plan,'free') plan,
            COUNT(*) event_count,COUNT(DISTINCT user_hash) unique_users,
            COALESCE(SUM(cost_usd_estimated),0) cost_usd_estimated
            FROM metric_events''' + where + ' GROUP BY 1,2,3', args).fetchall()
        for row in rows:
            db.execute('''INSERT INTO metric_monthly(month,event,plan,event_count,unique_users,cost_usd_estimated)
              VALUES(?,?,?,?,?,?) ON CONFLICT(month,event,plan) DO UPDATE SET
              event_count=excluded.event_count,unique_users=excluded.unique_users,
              cost_usd_estimated=excluded.cost_usd_estimated''', tuple(row))
        db.commit()
    return len(rows)


def report(path=None, start=None, end=None):
    target = init(path)
    with sqlite3.connect(target) as db:
        db.row_factory = sqlite3.Row
        clauses = []; args = []
        if start is not None: clauses.append('occurred_at>=?'); args.append(float(start))
        if end is not None: clauses.append('occurred_at<?'); args.append(float(end))
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        rows = db.execute('''SELECT event,COALESCE(plan,'free') plan,COUNT(*) event_count,
          COUNT(DISTINCT user_hash) unique_users,COALESCE(SUM(cost_usd_estimated),0) cost_usd_estimated
          FROM metric_events''' + where + ' GROUP BY event,plan ORDER BY event,plan', args).fetchall()
    return [dict(row) for row in rows]
