from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

from app.audio import convert_to_wav
from app.config import settings
from app.schemas import Word


TICKS_PER_SECOND = 10_000_000
NEURAL_VOICES = {
    "general-american": "en-US-AvaNeural",
    "received-pronunciation": "en-GB-SoniaNeural",
}


def _remove_stale_outputs(job_dir: Path) -> None:
    for name in ("tts-neural.mp3", "tts-raw.wav", "tts-metadata.json", "normalized.wav"):
        path = job_dir / name
        if path.exists():
            path.unlink()


async def _stream_neural_audio(text: str, output_path: Path, voice: str) -> list[dict]:
    import edge_tts

    communicate = edge_tts.Communicate(
        text,
        voice=voice,
        rate="+5%",
        volume="+0%",
        pitch="+0Hz",
        boundary="WordBoundary",
    )
    boundaries: list[dict] = []
    with output_path.open("wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                boundaries.append(
                    {
                        "text": chunk["text"],
                        "start": round(chunk["offset"] / TICKS_PER_SECOND, 4),
                        "end": round((chunk["offset"] + chunk["duration"]) / TICKS_PER_SECOND, 4),
                    }
                )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("在线语音服务没有返回音频数据。")
    return boundaries


def _synthesize_neural(text: str, job_dir: Path, accent: str) -> tuple[Path, dict]:
    voice = NEURAL_VOICES.get(accent, NEURAL_VOICES["general-american"])
    media_path = job_dir / "tts-neural.mp3"
    normalized_path = job_dir / "normalized.wav"
    boundaries = asyncio.run(_stream_neural_audio(text, media_path, voice))
    convert_to_wav(media_path, normalized_path)
    return normalized_path, {
        "voice": voice,
        "engine": "Microsoft Edge Neural TTS",
        "online": True,
        "rate": "+5%",
        "boundaries": boundaries,
    }


def _synthesize_sapi(text_path: Path, job_dir: Path, accent: str) -> tuple[Path, dict]:
    if sys.platform != "win32":
        raise RuntimeError("离线参考音目前需要 Windows System.Speech。")
    script = settings.root / "scripts" / "synthesize-sapi.ps1"
    if not script.exists():
        raise RuntimeError("找不到本地语音合成脚本。")

    raw_path = job_dir / "tts-raw.wav"
    normalized_path = job_dir / "normalized.wav"
    metadata_path = job_dir / "tts-metadata.json"
    culture = "en-GB" if accent == "received-pronunciation" else "en-US"
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-TextFile",
        str(text_path),
        "-OutputFile",
        str(raw_path),
        "-MetadataFile",
        str(metadata_path),
        "-Culture",
        culture,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=180)
    if completed.returncode != 0 or not raw_path.exists():
        detail = completed.stderr.strip() or completed.stdout.strip() or "System.Speech synthesis failed."
        raise RuntimeError(f"离线参考音生成失败：{detail}")
    convert_to_wav(raw_path, normalized_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig")) if metadata_path.exists() else {}
    metadata.update({"online": False, "boundaries": []})
    return normalized_path, metadata


def synthesize_standard_audio(
    text: str,
    job_dir: Path,
    accent: str,
    engine: str = "neural",
) -> tuple[Path, dict]:
    _remove_stale_outputs(job_dir)
    text_path = job_dir / "tts-input.txt"
    text_path.write_text(text, encoding="utf-8")
    if engine == "local":
        return _synthesize_sapi(text_path, job_dir, accent)

    try:
        return _synthesize_neural(text, job_dir, accent)
    except Exception as neural_error:
        normalized_path, metadata = _synthesize_sapi(text_path, job_dir, accent)
        metadata["fallback_reason"] = str(neural_error)
        return normalized_path, metadata


def _canonical_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def apply_synthesis_boundaries(words: list[Word], boundaries: list[dict], duration: float) -> float:
    """Apply neural TTS word boundaries and return the matched-word ratio."""
    if not words or not boundaries:
        return 0.0
    planned_duration = max(0.1, words[-1].end)
    scale = duration / planned_duration
    original_times = [(word.start * scale, word.end * scale) for word in words]
    cursor = 0
    matched = 0

    for word, fallback in zip(words, original_times):
        target = _canonical_token(word.text)
        match: tuple[int, int] | None = None
        for candidate in range(cursor, min(len(boundaries), cursor + 4)):
            combined = ""
            for end_index in range(candidate, min(len(boundaries), candidate + 4)):
                combined += _canonical_token(str(boundaries[end_index].get("text", "")))
                if combined == target:
                    match = (candidate, end_index)
                    break
                if len(combined) >= len(target):
                    break
            if match:
                break
        if match:
            start_index, end_index = match
            word.start = round(max(0.0, float(boundaries[start_index]["start"])), 3)
            word.end = round(min(duration, float(boundaries[end_index]["end"])), 3)
            word.alignment_method = "neural-tts-word-boundary"
            word.confidence = 0.98
            cursor = end_index + 1
            matched += 1
        else:
            word.start = round(fallback[0], 3)
            word.end = round(fallback[1], 3)

    return matched / len(words)
