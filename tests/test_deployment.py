from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.auth import AuthStore
from app.store import JobStore


ROOT = Path(__file__).resolve().parents[1]


def production_environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "SFA_AUTH_DB": str(tmp_path / "auth.db"),
            "SFA_JOBS_DIR": str(tmp_path / "jobs"),
            "SFA_ENABLE_DOCS": "false",
            "SFA_SECURE_COOKIES": "true",
        }
    )
    return environment


def test_production_configuration_disables_api_docs(tmp_path: Path) -> None:
    code = """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    assert client.get('/api/health').status_code == 200
    assert client.get('/docs').status_code == 404
    assert client.get('/openapi.json').status_code == 404
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=production_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_backup_script_creates_database_and_job_archive(tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.db"
    jobs_path = tmp_path / "jobs"
    AuthStore(auth_path).create_user("backup_user", "StrongPass123!")
    JobStore(jobs_path).create("sample.wav", {}, owner_id="guest:" + "a" * 64)
    environment = production_environment(tmp_path)
    output = tmp_path / "backups"
    result = subprocess.run(
        [sys.executable, "scripts/backup.py", "--output", str(output)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    backup_directories = list(output.glob("speech-flow-*"))
    assert len(backup_directories) == 1
    assert (backup_directories[0] / "auth.db").exists()
    assert (backup_directories[0] / "jobs.tar.gz").exists()
    assert (backup_directories[0] / "manifest.json").exists()
