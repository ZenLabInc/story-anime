"""Small, dependency-free readiness check for a scheduled health probe."""
import argparse
import json
import shutil
import time
import urllib.request
from pathlib import Path

from app import ops_alerts


def probe(url, backup, max_age_hours, disk_path, min_free_gb):
    result = {"checked_at": time.time(), "url": url, "ok": True, "checks": {}}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "YourStory-healthcheck/1"})
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read())
            result["checks"]["health"] = {"status": response.status, "body": body}
            if response.status != 200 or body.get("ok") is not True:
                result["ok"] = False
    except Exception as exc:
        result["ok"] = False
        result["checks"]["health"] = {"error": str(exc)}

    if backup:
        path = Path(backup)
        if not path.is_file():
            result["ok"] = False
            result["checks"]["backup"] = {"error": "backup_not_found", "path": str(path)}
        else:
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            result["checks"]["backup"] = {"path": str(path), "age_hours": round(age_hours, 2), "size": path.stat().st_size}
            if age_hours > max_age_hours or path.stat().st_size == 0:
                result["ok"] = False
    usage = shutil.disk_usage(disk_path)
    free_gb = usage.free / (1024 ** 3)
    result["checks"]["disk"] = {"path": disk_path, "free_gb": round(free_gb, 2), "used_percent": round(usage.used / usage.total * 100, 2)}
    if free_gb < min_free_gb:
        result["ok"] = False
    return result


def notify_on_transition(result, state_file):
    """Notify only when health changes state, avoiding five-minute spam."""
    path = Path(state_file)
    previous = None
    try:
        if path.is_file():
            previous = json.loads(path.read_text()).get('ok')
    except (OSError, ValueError, TypeError):
        previous = None
    current = bool(result.get('ok'))
    if previous is not None and previous == current:
        return False
    if current:
        subject = '監視が復旧しました'
        body = 'YourStoryのヘルスチェックが正常へ戻りました。\n' + json.dumps(result, ensure_ascii=False)
    else:
        subject = '監視チェックが失敗しました'
        body = 'YourStoryのヘルスチェックに失敗しました。\n' + json.dumps(result, ensure_ascii=False)
    sent = ops_alerts.notify(subject, body)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'ok': current, 'checked_at': result.get('checked_at')}, ensure_ascii=False))
    except OSError:
        pass
    return sent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://yourstory.example.test/healthz")
    parser.add_argument("--backup", default=".local/backups/latest.tar.gz")
    parser.add_argument("--max-backup-age-hours", type=float, default=36)
    parser.add_argument("--disk-path", default="/")
    parser.add_argument("--min-free-gb", type=float, default=2)
    parser.add_argument("--state-file", default=".local/ops/health-state.json")
    parser.add_argument("--notify-on-transition", action="store_true")
    args = parser.parse_args()
    result = probe(args.url, args.backup, args.max_backup_age_hours, args.disk_path, args.min_free_gb)
    if args.notify_on_transition:
        notify_on_transition(result, args.state_file)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
