from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.auth import GUEST_COOKIE, AuthStore, guest_owner_id
from app.store import JobStore


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main_module, "auth_store", AuthStore(tmp_path / "auth.db"))
    monkeypatch.setattr(main_module, "store", JobStore(tmp_path / "jobs"))
    with TestClient(main_module.app) as test_client:
        response = test_client.post(
            "/api/auth/register",
            json={"username": "test_reader", "password": "StrongPass123!"},
        )
        assert response.status_code == 201
        yield test_client


@pytest.fixture
def guest_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main_module, "auth_store", AuthStore(tmp_path / "auth.db"))
    monkeypatch.setattr(main_module, "store", JobStore(tmp_path / "jobs"))
    with TestClient(main_module.app) as test_client:
        response = test_client.get("/")
        assert response.status_code == 200
        assert test_client.cookies.get(GUEST_COOKIE)
        yield test_client


def wait_for_job(client: TestClient, job_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    status: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        status = response.json()
        if status["status"] in {"completed", "failed"}:
            return status
        time.sleep(0.15)
    return status


def test_auth_pages_and_session_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "auth_store", AuthStore(tmp_path / "auth.db"))
    monkeypatch.setattr(main_module, "store", JobStore(tmp_path / "jobs"))
    with TestClient(main_module.app) as test_client:
        root = test_client.get("/?job=abc", follow_redirects=False)
        assert root.status_code == 200
        assert "交互式语流文稿" in root.text
        guest_cookie = root.headers["set-cookie"].lower()
        assert GUEST_COOKIE in guest_cookie
        assert "httponly" in guest_cookie
        assert test_client.get("/login").status_code == 200
        assert test_client.get("/api/auth/me").json() == {
            "authenticated": False,
            "user": None,
        }
        assert test_client.post("/api/jobs", data={"input_mode": "text"}).status_code == 400

        registered = test_client.post(
            "/api/auth/register",
            json={"username": "Local_User", "password": "StrongPass123!"},
        )
        assert registered.status_code == 201
        cookie = registered.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert test_client.get("/api/auth/me").json()["user"]["username"] == "Local_User"
        assert "交互式语流文稿" in test_client.get("/").text

        assert test_client.post("/api/auth/logout").status_code == 200
        assert test_client.get("/api/auth/me").json()["authenticated"] is False
        assert test_client.get("/").status_code == 200
        assert test_client.post("/api/jobs", data={"input_mode": "text"}).status_code == 400
        assert test_client.post(
            "/api/auth/login",
            json={"username": "local_user", "password": "wrong-pass"},
        ).status_code == 401
        assert test_client.post(
            "/api/auth/login",
            json={"username": "local_user", "password": "StrongPass123!"},
        ).status_code == 200


def test_guest_jobs_are_isolated_and_transfer_on_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_store = AuthStore(tmp_path / "auth.db")
    job_store = JobStore(tmp_path / "jobs")
    monkeypatch.setattr(main_module, "auth_store", auth_store)
    monkeypatch.setattr(main_module, "store", job_store)
    with TestClient(main_module.app) as owner, TestClient(main_module.app) as stranger:
        assert owner.get("/").status_code == 200
        assert stranger.get("/").status_code == 200
        guest_id = guest_owner_id(owner.cookies.get(GUEST_COOKIE))
        assert guest_id is not None
        job = job_store.create("private.wav", {}, owner_id=guest_id)
        assert owner.get(f"/api/jobs/{job['id']}").status_code == 200
        assert stranger.get(f"/api/jobs/{job['id']}").status_code == 404

        owner_user = owner.post(
            "/api/auth/register",
            json={"username": "job_owner", "password": "StrongPass123!"},
        ).json()["user"]
        assert job_store.get(job["id"])["owner_id"] == owner_user["id"]
        stranger.post(
            "/api/auth/register",
            json={"username": "other_user", "password": "StrongPass123!"},
        )
        assert owner.get(f"/api/jobs/{job['id']}").status_code == 200
        assert stranger.get(f"/api/jobs/{job['id']}").status_code == 404
        assert stranger.get(f"/api/jobs/{job['id']}/export/json").status_code == 404


def test_health_and_index(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["version"] == "1.0.0"
    assert health.json()["local_tts_available"] is (sys.platform == "win32")
    assert client.get("/").status_code == 200


def test_end_to_end_job_without_whisper(client: TestClient, synthetic_wav: Path) -> None:
    with synthetic_wav.open("rb") as audio:
        response = client.post(
            "/api/jobs",
            files={"audio": ("sample.wav", audio, "audio/wav")},
            data={
                "transcript": "We need it, but we can finish today.",
                "auto_transcribe": "false",
                "accent": "general-american",
            },
        )
    assert response.status_code == 202
    job_id = response.json()["id"]
    status = wait_for_job(client, job_id, 25)
    assert status["status"] == "completed", status.get("error")
    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.json()["transcript_source"] == "user-estimated"
    assert client.get(f"/api/jobs/{job_id}/export/srt").status_code == 200
    assert client.get(f"/api/jobs/{job_id}/export/html").status_code == 200
    pdf = client.get(f"/api/jobs/{job_id}/export/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_text_only_standard_reading_job_as_guest(guest_client: TestClient) -> None:
    response = guest_client.post(
        "/api/jobs",
        data={
            "transcript": "What do we learn from previous studies about anxiety?",
            "input_mode": "text",
            "accent": "general-american",
            "tts_engine": "local",
        },
    )
    assert response.status_code == 202
    job_id = response.json()["id"]
    status = wait_for_job(guest_client, job_id, 15)
    assert status["status"] == "completed", status.get("error")
    result = guest_client.get(f"/api/jobs/{job_id}/result").json()
    assert result["input_mode"] == "text"
    assert result["transcript_source"] == "text-standard"
    assert result["phrases"][0]["intonation_symbol"] == "↘"
    if sys.platform == "win32":
        assert result["audio"] is not None
        assert result["audio"]["duration"] > 0
        assert result["summary"]["generated_voice"]
        expected_rate = result["summary"]["rhythm"]["syllables"] / result["audio"]["duration"]
        assert abs(result["summary"]["rhythm"]["syllables_per_second"] - expected_rate) < 0.02
        assert guest_client.get(f"/api/jobs/{job_id}/audio").status_code == 200
    else:
        assert result["audio"] is None
        assert result["summary"].get("generated_voice") is None
        assert "Windows System.Speech" in result["limitations"][0]
        assert guest_client.get(f"/api/jobs/{job_id}/audio").status_code == 404
    assert guest_client.get(f"/api/jobs/{job_id}/export/html").status_code == 200
