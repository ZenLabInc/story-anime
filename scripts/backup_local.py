"""Create a consistent, private YourStory backup archive.

The command only writes the requested local archive. Uploading it to S3 is a
separate operator action so cloud credentials never need to be stored on the
application host.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path

from app import studio as s


def db_snapshot(source: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(dest) as out:
        src.backup(out)
        result = out.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {source}: {result}")
    return result


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deleted_accounts():
    db = s.DB
    if not db.exists():
        return []
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT user, deleted_at, deleted_consent_version, deleted_consent_at FROM accounts WHERE deleted_at IS NOT NULL").fetchall()
        keys = ("user", "deleted_at", "deleted_consent_version", "deleted_consent_at")
        return [dict(zip(keys, row)) for row in rows]
    except sqlite3.OperationalError:
        return []


def create(output: Path):
    output = output.resolve()
    local_root = s.DATA.parent.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yourstory-backup-") as tmp:
        staging = Path(tmp)
        snapshots = []
        sources = sorted(local_root.rglob("*.db")) if local_root.exists() else []
        for source in sources:
            relative = source.relative_to(local_root)
            dest = staging / "databases" / relative
            db_snapshot(source, dest)
            snapshots.append((dest, Path("databases") / relative))

        files = []
        data_sources = sorted(s.DATA.rglob("*")) if s.DATA.exists() else []
        for source in data_sources:
            if not source.is_file() or source.suffix == ".db" or "backups" in source.parts:
                continue
            files.append((source, Path("data") / source.relative_to(s.DATA)))

        manifest = {
            "format": 2,
            "created_at": time.time(),
            "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": str(s.ROOT),
            "databases": [],
            "files": [],
            "deleted_accounts": deleted_accounts(),
            "restore_note": "Restore into a staging directory first. Deleted accounts must remain inaccessible after any recovery.",
        }
        for path, arcname in snapshots:
            manifest["databases"].append({"path": str(arcname), "sha256": sha256(path), "integrity": "ok"})
        for source, arcname in files:
            manifest["files"].append({"path": str(arcname), "sha256": sha256(source), "size": source.stat().st_size})

        manifest_file = staging / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with tarfile.open(output, "w:gz") as archive:
            archive.add(manifest_file, arcname="manifest.json")
            for path, arcname in snapshots:
                archive.add(path, arcname=str(arcname))
            for source, arcname in files:
                archive.add(source, arcname=str(arcname))
    os.chmod(output, 0o600)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = create(args.output)
    print(json.dumps({"ok": True, "output": str(args.output), "databases": len(manifest["databases"]), "files": len(manifest["files"]), "deleted_accounts": len(manifest["deleted_accounts"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
