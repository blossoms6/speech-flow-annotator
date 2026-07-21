from __future__ import annotations

import json
import shutil
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

    def create(self, original_name: str, options: dict[str, Any], owner_id: str) -> dict[str, Any]:
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
            "owner_id": owner_id,
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

    def transfer_owner(self, previous_owner_id: str, new_owner_id: str) -> int:
        transferred = 0
        with self._lock:
            for job_file in self.root.glob("*/job.json"):
                try:
                    data = json.loads(job_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if data.get("owner_id") != previous_owner_id:
                    continue
                data["owner_id"] = new_owner_id
                data["updated_at"] = utc_now()
                self._write(job_file, data)
                transferred += 1
        return transferred

    @staticmethod
    def _directory_size(path: Path) -> int:
        total = 0
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
        return total

    def list_jobs(
        self,
        query: str = "",
        status: str = "",
        owner_type: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        needle = query.strip().lower()
        with self._lock:
            for job_file in self.root.glob("*/job.json"):
                try:
                    data = json.loads(job_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                owner_id = str(data.get("owner_id") or "")
                current_owner_type = "guest" if owner_id.startswith("guest:") else "user"
                if status and data.get("status") != status:
                    continue
                if owner_type and current_owner_type != owner_type:
                    continue
                searchable = " ".join(
                    str(data.get(key) or "") for key in ("id", "original_name", "message", "error")
                ).lower()
                if needle and needle not in searchable:
                    continue
                jobs.append(
                    {
                        **data,
                        "owner_type": current_owner_type,
                        "size_bytes": self._directory_size(job_file.parent),
                    }
                )
        jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return jobs[:limit]

    def stats(self) -> dict[str, Any]:
        jobs = self.list_jobs(limit=1_000_000)
        counts = {name: 0 for name in ("queued", "processing", "completed", "failed")}
        guest_jobs = 0
        total_bytes = 0
        for job in jobs:
            current_status = str(job.get("status") or "")
            if current_status in counts:
                counts[current_status] += 1
            guest_jobs += int(job.get("owner_type") == "guest")
            total_bytes += int(job.get("size_bytes") or 0)
        return {
            "total": len(jobs),
            "guest": guest_jobs,
            "registered": len(jobs) - guest_jobs,
            "counts": counts,
            "size_bytes": total_bytes,
        }

    def delete(self, job_id: str) -> None:
        with self._lock:
            path = self.directory(job_id)
            shutil.rmtree(path)

    def cleanup_guest_jobs(self, older_than: datetime) -> list[str]:
        deleted: list[str] = []
        for job in self.list_jobs(owner_type="guest", limit=1_000_000):
            if job.get("status") in {"queued", "processing"}:
                continue
            try:
                created_at = datetime.fromisoformat(str(job.get("created_at")))
            except (TypeError, ValueError):
                continue
            if created_at >= older_than:
                continue
            try:
                self.delete(job["id"])
            except (KeyError, OSError):
                continue
            deleted.append(job["id"])
        return deleted

    @staticmethod
    def _write(path: Path, data: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


store = JobStore()
