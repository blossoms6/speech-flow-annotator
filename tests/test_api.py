from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_and_index() -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["version"] == "1.0.0"
    assert client.get("/").status_code == 200


def test_end_to_end_job_without_whisper(synthetic_wav: Path) -> None:
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
    deadline = time.monotonic() + 25
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in {"completed", "failed"}:
            break
        time.sleep(0.15)
    assert status is not None
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


def test_text_only_standard_reading_job() -> None:
    response = client.post(
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
    deadline = time.monotonic() + 15
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)
    assert status is not None
    assert status["status"] == "completed", status.get("error")
    result = client.get(f"/api/jobs/{job_id}/result").json()
    assert result["input_mode"] == "text"
    assert result["audio"] is not None
    assert result["audio"]["duration"] > 0
    assert result["summary"]["generated_voice"]
    expected_rate = result["summary"]["rhythm"]["syllables"] / result["audio"]["duration"]
    assert abs(result["summary"]["rhythm"]["syllables_per_second"] - expected_rate) < 0.02
    assert result["transcript_source"] == "text-standard"
    assert result["phrases"][0]["intonation_symbol"] == "↘"
    assert client.get(f"/api/jobs/{job_id}/audio").status_code == 200
    assert client.get(f"/api/jobs/{job_id}/export/html").status_code == 200
