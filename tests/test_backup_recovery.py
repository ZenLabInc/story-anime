import json
import tempfile
import unittest
from pathlib import Path

from app import studio as s
from scripts import backup_local, restore_local


class BackupRecoveryTests(unittest.TestCase):
    def test_archive_manifest_and_staging_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_data, old_db = s.DATA, s.DB
            try:
                s.DATA = root / "studio"
                s.DB = s.DATA / "studio.db"
                s.init()
                (s.DATA / "assets").mkdir(parents=True)
                (s.DATA / "assets" / "page.txt").write_text("page", encoding="utf-8")
                archive = root / "latest.tar.gz"
                manifest = backup_local.create(archive)
                self.assertEqual(manifest["format"], 2)
                staging = root / "restore"
                restored = restore_local.restore(archive, staging)
                self.assertEqual(len(restored["databases"]), 1)
                self.assertEqual((staging / "data/assets/page.txt").read_text(encoding="utf-8"), "page")
                self.assertEqual(json.loads((staging / "manifest.json").read_text(encoding="utf-8"))["format"], 2)
            finally:
                s.DATA, s.DB = old_data, old_db


if __name__ == "__main__":
    unittest.main()
