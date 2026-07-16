from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    jobs_dir: Path = Path(os.getenv("SFA_JOBS_DIR", ROOT / "data" / "jobs"))
    static_dir: Path = ROOT / "static"
    max_upload_mb: int = int(os.getenv("SFA_MAX_UPLOAD_MB", "250"))
    max_duration_seconds: int = int(os.getenv("SFA_MAX_DURATION_SECONDS", "1800"))
    worker_count: int = int(os.getenv("SFA_WORKERS", "1"))
    default_model: str = os.getenv("SFA_WHISPER_MODEL", "tiny.en")

    def ensure_directories(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
