"""Verify a YourStory backup and restore it to an isolated staging folder.

This deliberately does not know the live `.local` path. A human must inspect
the result before a production cutover, which prevents a bad archive from
silently reactivating deleted accounts or replacing the running database.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import tarfile
from pathlib import Path


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_members(archive, target):
    root = target.resolve()
    for member in archive.getmembers():
        path = (root / member.name).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"バックアップに安全でないパスがあります: {member.name}")
        if member.issym() or member.islnk():
            raise ValueError(f"リンクを含むバックアップは復元できません: {member.name}")
    return archive.getmembers()


def restore(archive_path: Path, target: Path, replace=False):
    archive_path = archive_path.resolve()
    target = target.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    if target == Path.cwd().resolve() or target.name in {".local", "studio"}:
        raise ValueError("復元先には専用のステージングディレクトリを指定してください。")
    if target.exists() and any(target.iterdir()) and not replace:
        raise FileExistsError(f"復元先が空ではありません: {target}（空のディレクトリか --replace を指定）")
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = safe_members(archive, target)
        archive.extractall(target, members=members)
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("manifest.json がありません。")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != 2:
        raise ValueError("未対応のバックアップ形式です。")
    for item in manifest.get("databases", []) + manifest.get("files", []):
        path = target / item["path"]
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise ValueError(f"チェックサムが一致しません: {item['path']}")
    for item in manifest.get("databases", []):
        path = target / item["path"]
        with sqlite3.connect(path) as db:
            result = db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"SQLite整合性確認に失敗しました: {item['path']}: {result}")
    os.chmod(manifest_path, 0o600)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--replace", action="store_true", help="空でないステージング先を置き換える")
    args = parser.parse_args()
    manifest = restore(args.archive, args.target, args.replace)
    print(json.dumps({"ok": True, "target": str(args.target.resolve()), "databases": len(manifest.get("databases", [])), "files": len(manifest.get("files", [])), "deleted_accounts": len(manifest.get("deleted_accounts", []))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
