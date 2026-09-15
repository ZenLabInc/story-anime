import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from scripts.purge_retention import purge
from app import metrics


class RetentionTests(unittest.TestCase):
    def make_db(self, root):
        db_path=root/'studio.db'
        with sqlite3.connect(db_path) as db:
            db.executescript('''
            CREATE TABLE users(id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, balance INTEGER NOT NULL);
            CREATE TABLE accounts(user TEXT PRIMARY KEY,email TEXT NOT NULL,provider TEXT NOT NULL,subject TEXT NOT NULL,verified INTEGER NOT NULL,created REAL NOT NULL,deleted_at REAL,deleted_consent_version TEXT,deleted_consent_at REAL,deleted_by TEXT,UNIQUE(provider,subject));
            CREATE TABLE account_tombstones(id TEXT PRIMARY KEY,user_hash TEXT NOT NULL,provider_subject_hash TEXT NOT NULL,email_hash TEXT NOT NULL,deleted_at REAL NOT NULL,reusable_at REAL NOT NULL,UNIQUE(provider_subject_hash),UNIQUE(email_hash));
            CREATE TABLE account_profiles(user TEXT PRIMARY KEY,display_name TEXT NOT NULL,updated REAL NOT NULL);
            CREATE TABLE works(id TEXT PRIMARY KEY,owner TEXT NOT NULL,data TEXT NOT NULL,updated REAL NOT NULL);
            CREATE TABLE jobs(id TEXT PRIMARY KEY,quote_id TEXT UNIQUE NOT NULL,work TEXT NOT NULL,owner TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE likes(work TEXT,user TEXT);
            CREATE TABLE ledger(id TEXT PRIMARY KEY,owner TEXT NOT NULL,job TEXT NOT NULL,kind TEXT NOT NULL,delta INTEGER NOT NULL);
            CREATE TABLE consumption(id TEXT PRIMARY KEY,user TEXT NOT NULL,work TEXT NOT NULL,kind TEXT NOT NULL,period TEXT NOT NULL,status TEXT NOT NULL,tokens INTEGER NOT NULL,cost REAL NOT NULL);
            CREATE TABLE plan_events(id TEXT PRIMARY KEY,user TEXT NOT NULL,plan TEXT NOT NULL,until REAL,reason TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE memberships(user TEXT PRIMARY KEY,plan TEXT NOT NULL,until REAL);
            CREATE TABLE billing_attempts(user TEXT PRIMARY KEY,plan TEXT NOT NULL,nonce TEXT NOT NULL);
            CREATE TABLE billing_sessions(user TEXT PRIMARY KEY,session TEXT NOT NULL,plan TEXT NOT NULL);
            CREATE TABLE account_consents(id TEXT PRIMARY KEY,user TEXT NOT NULL,terms_version TEXT NOT NULL,privacy_version TEXT NOT NULL,accepted_at REAL NOT NULL,ip TEXT NOT NULL,user_agent TEXT NOT NULL);
            CREATE TABLE account_events(id TEXT PRIMARY KEY,user TEXT NOT NULL,kind TEXT NOT NULL,version TEXT,created REAL NOT NULL,metadata TEXT NOT NULL);
            CREATE TABLE metric_events(event_id TEXT PRIMARY KEY,occurred_at REAL NOT NULL,event TEXT NOT NULL,user_hash TEXT NOT NULL,project_hash TEXT,plan TEXT,app_release TEXT,provider TEXT,model TEXT,latency_ms REAL,status TEXT,error_class TEXT,image_count INTEGER,text_tokens INTEGER,image_tokens INTEGER,cost_usd_estimated REAL,cost_usd_invoiced REAL,attrs TEXT NOT NULL);
            ''')
            old=time.time()-31*86400;db.execute("INSERT INTO users VALUES('u','token','Old',1)");db.execute("INSERT INTO accounts(user,email,provider,subject,verified,created,deleted_at,deleted_consent_version,deleted_consent_at,deleted_by) VALUES(?,?,?,?,?,?,?,?,?,?)",('u','old@example.test','dev','old-sub',1,old,old,'v1',old,'u'));db.execute("INSERT INTO account_profiles VALUES(?,?,?)",('u','Old',old));db.execute("INSERT INTO works VALUES(?,?,?,?)",('w','u','{}',old));db.execute("INSERT INTO consumption VALUES(?,?,?,?,?,?,?,?)",('c','u','w','image','2026-09','succeeded',1,1));db.execute("INSERT INTO account_consents VALUES(?,?,?,?,?,?,?)",('cons','u','v1','v1',old,'ip','ua'));db.commit()
            db.execute("INSERT INTO metric_events(event_id,occurred_at,event,user_hash,attrs) VALUES(?,?,?,?,?)",('m',old,'chat_turn_completed',metrics.opaque('u'),'{}'));db.commit()
        (root/'w'/'workspace').mkdir(parents=True);(root/'w'/'workspace'/'asset.png').write_bytes(b'x')
        return db_path

    def test_dry_run_does_not_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=self.make_db(root);result=purge(db,root,now=time.time(),apply=False);self.assertEqual(result['purged'],0);self.assertTrue((root/'w').exists())

    def test_apply_anonymizes_and_removes_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=self.make_db(root);result=purge(db,root,now=time.time(),apply=True);self.assertEqual(result['purged'],1);self.assertFalse((root/'w').exists())
            with sqlite3.connect(db) as conn:
                self.assertIsNone(conn.execute("SELECT 1 FROM works WHERE id='w'").fetchone());row=conn.execute("SELECT email,provider,subject FROM accounts WHERE user='u'").fetchone();self.assertEqual(row[1],'deleted');self.assertTrue(row[0].startswith('deleted+'));self.assertTrue(row[2].startswith('deleted:'));self.assertIsNotNone(conn.execute("SELECT 1 FROM account_consents WHERE user='u'").fetchone())
                self.assertIsNone(conn.execute("SELECT 1 FROM metric_events WHERE event_id='m'").fetchone())


if __name__=='__main__':unittest.main()
