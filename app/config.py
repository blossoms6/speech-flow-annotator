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
    auth_db_path: Path = Path(os.getenv("SFA_AUTH_DB", ROOT / "data" / "auth.db"))
    secure_cookies: bool = os.getenv("SFA_SECURE_COOKIES", "false").lower() in {"1", "true", "yes"}
    enable_docs: bool = os.getenv("SFA_ENABLE_DOCS", "true").lower() in {"1", "true", "yes"}
    chrome_no_sandbox: bool = os.getenv("SFA_CHROME_NO_SANDBOX", "false").lower() in {"1", "true", "yes"}
    max_upload_mb: int = int(os.getenv("SFA_MAX_UPLOAD_MB", "250"))
    max_duration_seconds: int = int(os.getenv("SFA_MAX_DURATION_SECONDS", "1800"))
    worker_count: int = int(os.getenv("SFA_WORKERS", "1"))
    default_model: str = os.getenv("SFA_WHISPER_MODEL", "tiny.en")

    def ensure_directories(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
