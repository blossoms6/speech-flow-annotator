from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.jobs_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def directory(self, job_id: str) -> Path:
        if not job_id or any(character not in "0123456789abcdef" for character in job_id):
            raise KeyError(job_id)
        path = self.root / job_id
        if not path.exists():
            raise KeyError(job_id)
        return path

    def create(self, original_name: str, options: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job_dir = self.root / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        now = utc_now()
        data = {
            "id": job_id,
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "message": "任务已进入队列。",
            "error": None,
            "created_at": now,
            "updated_at": now,
            "original_name": original_name,
            "options": options,
            "result_url": None,
        }
        self._write(job_dir / "job.json", data)
        return data

    def get(self, job_id: str) -> dict[str, Any]:
        path = self.directory(job_id) / "job.json"
        with self._lock:
            return json.loads(path.read_text(encoding="utf-8"))

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            job_dir = self.directory(job_id)
            data = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            data.update(changes)
            data["updated_at"] = utc_now()
            self._write(job_dir / "job.json", data)
            return data

    def result(self, job_id: str) -> dict[str, Any]:
        path = self.directory(job_id) / "result.json"
        if not path.exists():
            raise FileNotFoundError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, data: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


store = JobStore()
