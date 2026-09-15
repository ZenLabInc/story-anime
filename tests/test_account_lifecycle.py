import json
import tempfile
import unittest
from pathlib import Path

from app import accounts as a, studio as s, workspace as w


class AccountLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = s.DATA, s.DB, a.DEV_AUTH
        s.DATA = Path(self.tmp.name)
        s.DB = s.DATA / "studio.db"
        a.DEV_AUTH = True
        s.init()
        self.guest, self.guest_cookie = s.session()
        challenge = a.email_start("owner@example.test", self.guest_cookie, "127.0.0.1")
        self.token, self.user = a.email_finish(challenge["challenge"], challenge["dev_code"], self.guest_cookie, self.guest["id"])
        a.save_profile(self.user, "作者")
        a.accept_consent(self.user, self.token, "127.0.0.1", "test")

    def tearDown(self):
        s.DATA, s.DB, a.DEV_AUTH = self.old
        self.tmp.cleanup()

    def test_consent_is_versioned_and_deletion_is_logical(self):
        work = w.create(self.user, "残す作品")
        self.assertFalse(a.consent_status(self.user)["required"])
        with s.transaction() as db:db.execute("INSERT INTO user_gemini_keys VALUES(?,?,0)",(self.user,b"encrypted-fixture"))
        result = a.delete_account(self.user, self.token, True, "127.0.0.1", "test")
        with s.transaction() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM user_gemini_keys").fetchone()[0],0)
        self.assertTrue(result["deleted"])
        with self.assertRaises(PermissionError):
            a.authenticate(self.token)
        self.assertIsNone(a.profile(self.user))
        with s.transaction() as db:
            row = db.execute("SELECT deleted_at, deleted_consent_version, deleted_by FROM accounts WHERE user=?", (self.user,)).fetchone()
            retained = json.loads(db.execute("SELECT data FROM works WHERE id=?", (work["id"],)).fetchone()[0])
        self.assertIsNotNone(row["deleted_at"])
        self.assertEqual(row["deleted_consent_version"], a.TERMS_VERSION)
        self.assertEqual(row["deleted_by"], self.user)
        self.assertEqual(retained["account_deleted_at"], row["deleted_at"])
        with self.assertRaises(PermissionError):
            a.complete("dev", "owner@example.test", "owner@example.test", self.guest["id"], True)

    def test_deletion_requires_recent_auth_and_finished_billing_or_jobs(self):
        with s.transaction() as db:
            db.execute("UPDATE sessions SET authenticated_at=0 WHERE hash=?", (a.digest(self.token),))
        with self.assertRaises(PermissionError):
            a.delete_account(self.user, self.token, True)
        with s.transaction() as db:
            db.execute("UPDATE sessions SET authenticated_at=strftime('%s','now') WHERE hash=?", (a.digest(self.token),))
            db.execute("INSERT INTO billing_subscriptions VALUES(?,?,?,?,?,?,?)", (self.user, "sub_test", "active", "plus", 0, 9999999999, 0))
        with self.assertRaises(ValueError):
            a.delete_account(self.user, self.token, True)
        with s.transaction() as db:
            db.execute("DELETE FROM billing_subscriptions WHERE user=?", (self.user,))
        work = w.create(self.user, "生成中")
        with s.transaction() as db:
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?)", ("job", "quote", work["id"], self.user, json.dumps({"status": "running"})))
        with self.assertRaises(ValueError):
            a.delete_account(self.user, self.token, True)


if __name__ == "__main__":
    unittest.main()
