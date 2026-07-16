from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="备份 Speech Flow 账户和任务数据")
    parser.add_argument("--output", type=Path, default=Path("/data/backups"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = output / f"speech-flow-{stamp}"
    backup_dir.mkdir()

    if settings.auth_db_path.exists():
        with sqlite3.connect(settings.auth_db_path) as source:
            with sqlite3.connect(backup_dir / "auth.db") as destination:
                source.backup(destination)

    archive_path = backup_dir / "jobs.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        if settings.jobs_dir.exists():
            archive.add(settings.jobs_dir, arcname="jobs")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auth_database": settings.auth_db_path.exists(),
        "jobs_archive": archive_path.name,
    }
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(backup_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
