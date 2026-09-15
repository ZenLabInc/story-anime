"""Purge expired logically deleted accounts without touching billing audit rows.

The command is dry-run by default. ``--apply`` is required for irreversible
data removal. Account identifiers are anonymized before works, conversations,
usage records, and generated files are removed. Billing/consent/audit rows stay
with a random internal user id so legal and support records remain available.
"""
import argparse
import hashlib
import json
import secrets
import shutil
import sqlite3
import time
from pathlib import Path


def anon(value):
    return hashlib.sha256(("yourstory-retention-v1:" + value).encode()).hexdigest()


def purge(db_path: Path, data_root: Path, *, now=None, retention_days=30, apply=False, gemini_db=None):
    now = time.time() if now is None else float(now)
    cutoff = now - retention_days * 86400
    summary = {"ok": True, "dry_run": not apply, "accounts": [], "files_removed": 0, "errors": []}
    db_path = Path(db_path); data_root = Path(data_root)
    if not db_path.is_file():
        return summary
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("CREATE TABLE IF NOT EXISTS account_tombstones(id TEXT PRIMARY KEY,user_hash TEXT NOT NULL,provider_subject_hash TEXT NOT NULL,email_hash TEXT NOT NULL,deleted_at REAL NOT NULL,reusable_at REAL NOT NULL,UNIQUE(provider_subject_hash),UNIQUE(email_hash))")
        rows = db.execute("SELECT user,deleted_at FROM accounts WHERE deleted_at IS NOT NULL AND deleted_at<=? ORDER BY deleted_at", (cutoff,)).fetchall()
        for row in rows:
            user = row["user"]
            works = [r["id"] for r in db.execute("SELECT id FROM works WHERE owner=?", (user,)).fetchall()]
            paths = [data_root / wid for wid in works]
            item = {"user": anon(user), "deleted_at": row["deleted_at"], "works": len(works), "files": [str(p) for p in paths]}
            if apply:
                try:
                    if works:
                        marks=','.join('?' for _ in works)
                        db.execute(f"DELETE FROM likes WHERE work IN ({marks})", works)
                        db.execute(f"DELETE FROM ledger WHERE job IN (SELECT id FROM jobs WHERE work IN ({marks}))", works)
                        db.execute(f"DELETE FROM jobs WHERE work IN ({marks})", works)
                        db.execute(f"DELETE FROM consumption WHERE work IN ({marks})", works)
                        db.execute(f"DELETE FROM works WHERE id IN ({marks})", works)
                    # Product measurement contains only opaque hashes; remove
                    # raw events after the same retention period as works.
                    try:
                        from app import metrics
                        db.execute("DELETE FROM metric_events WHERE user_hash=?", (metrics.opaque(user),))
                    except sqlite3.OperationalError:
                        pass
                    db.execute("DELETE FROM plan_events WHERE user=?", (user,))
                    db.execute("DELETE FROM memberships WHERE user=?", (user,))
                    db.execute("DELETE FROM billing_attempts WHERE user=?", (user,))
                    db.execute("DELETE FROM billing_sessions WHERE user=?", (user,))
                    db.execute("DELETE FROM account_profiles WHERE user=?", (user,))
                    db.execute("UPDATE accounts SET email=?,provider='deleted',subject=?,verified=0 WHERE user=?", ("deleted+"+anon(user)[:40]+"@invalid.local", "deleted:"+anon(user), user))
                    db.execute("UPDATE users SET name='削除済み',balance=0,token_hash=? WHERE id=?", (hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest(), user))
                    db.execute("DELETE FROM account_tombstones WHERE user_hash=? AND reusable_at<=?", (digest_user(user), now))
                    for path in paths:
                        if path.exists():
                            shutil.rmtree(path)
                            item["files_removed"] = item.get("files_removed", 0) + 1
                    if gemini_db and Path(gemini_db).is_file() and works:
                        with sqlite3.connect(gemini_db) as usage_db:
                            marks=','.join('?' for _ in works)
                            usage_db.execute(f"DELETE FROM calls WHERE work IN ({marks})", works)
                            usage_db.commit()
                    summary["files_removed"] += item.get("files_removed", 0)
                    item["purged"] = True
                except Exception as error:
                    item["purged"] = False; item["error"] = type(error).__name__+": "+str(error)[:200]
                    summary["errors"].append(item["error"])
                    db.rollback()
            summary["accounts"].append(item)
        if apply: db.commit()
    summary["purged"] = sum(1 for x in summary["accounts"] if x.get("purged"))
    summary["ok"] = not summary["errors"]
    return summary


def digest_user(user):
    return hashlib.sha256(user.encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path('.local/studio/studio.db'))
    parser.add_argument('--data-root',type=Path,default=Path('.local/studio'))
    parser.add_argument('--retention-days',type=int,default=30)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--gemini-db',type=Path,help='任意。作品に紐づくGemini利用台帳も消去します。')
    args=parser.parse_args()
    if args.retention_days<1:parser.error('--retention-days must be positive')
    print(json.dumps(purge(args.db,args.data_root,retention_days=args.retention_days,apply=args.apply,gemini_db=args.gemini_db),ensure_ascii=False))


if __name__ == '__main__': main()
