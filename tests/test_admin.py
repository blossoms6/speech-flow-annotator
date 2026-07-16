from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.auth import AuthStore
from app.store import JobStore


@pytest.fixture
def admin_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    auth_store = AuthStore(tmp_path / "auth.db")
    job_store = JobStore(tmp_path / "jobs")
    monkeypatch.setattr(main_module, "auth_store", auth_store)
    monkeypatch.setattr(main_module, "store", job_store)
    admin = auth_store.create_user("site_admin", "StrongPass123!", is_admin=True)
    with TestClient(main_module.app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "site_admin", "password": "StrongPass123!"},
        )
        assert login.status_code == 200
        yield client, auth_store, job_store, admin


def test_admin_routes_require_admin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_store = AuthStore(tmp_path / "auth.db")
    monkeypatch.setattr(main_module, "auth_store", auth_store)
    monkeypatch.setattr(main_module, "store", JobStore(tmp_path / "jobs"))
    with TestClient(main_module.app) as anonymous, TestClient(main_module.app) as regular:
        assert anonymous.get("/api/admin/overview").status_code == 401
        assert anonymous.get("/admin", follow_redirects=False).headers["location"].startswith(
            "/login"
        )
        regular.post(
            "/api/auth/register",
            json={"username": "regular_user", "password": "StrongPass123!"},
        )
        assert regular.get("/api/admin/overview").status_code == 403
        denied_page = regular.get("/admin", follow_redirects=False)
        assert denied_page.status_code == 303
        assert denied_page.headers["location"] == "/"


def test_admin_overview_and_user_management(admin_context) -> None:
    client, auth_store, _job_store, admin = admin_context
    member = auth_store.create_user("member_01", "StrongPass123!")

    overview = client.get("/api/admin/overview")
    assert overview.status_code == 200
    assert overview.json()["users"]["total"] == 2
    assert overview.json()["users"]["admins"] == 1
    assert client.get("/admin").status_code == 200

    users = client.get("/api/admin/users?query=member").json()["items"]
    assert [item["username"] for item in users] == ["member_01"]
    disabled = client.patch(
        f"/api/admin/users/{member.id}", json={"is_active": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["user"]["is_active"] is False
    assert auth_store.authenticate("member_01", "StrongPass123!") is None

    assert client.patch(
        f"/api/admin/users/{admin.id}", json={"is_active": False}
    ).status_code == 400
    assert client.patch(
        f"/api/admin/users/{admin.id}", json={"is_admin": False}
    ).status_code == 400


def test_admin_job_management_and_guest_cleanup(admin_context) -> None:
    client, _auth_store, job_store, _admin = admin_context
    old_job = job_store.create("old.wav", {}, owner_id="guest:" + "a" * 64)
    job_store.update(
        old_job["id"],
        status="completed",
        created_at="2020-01-01T00:00:00+00:00",
    )
    failed_job = job_store.create("failed.wav", {}, owner_id="guest:" + "b" * 64)
    job_store.update(failed_job["id"], status="failed", error="test failure")
    active_job = job_store.create("active.wav", {}, owner_id="guest:" + "c" * 64)
    job_store.update(active_job["id"], status="processing")

    jobs = client.get("/api/admin/jobs?owner_type=guest")
    assert jobs.status_code == 200
    assert len(jobs.json()["items"]) == 3
    assert client.delete(f"/api/admin/jobs/{active_job['id']}").status_code == 409
    assert client.delete(f"/api/admin/jobs/{failed_job['id']}").status_code == 200

    cleanup = client.post(
        "/api/admin/cleanup", json={"guest_older_than_days": 30}
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["deleted_job_ids"] == [old_job["id"]]
    with pytest.raises(KeyError):
        job_store.get(old_job["id"])
    assert job_store.get(active_job["id"])["status"] == "processing"
