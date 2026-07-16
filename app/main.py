from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import settings
from app.exports import render_markdown, render_pdf, render_srt, render_standalone_html
from app.pipeline import analyze_job
from app.schemas import JobPublic, ReanalyzeRequest
from app.store import store
from app.text_standard import build_standard_reading
from app.tts import apply_synthesis_boundaries, synthesize_standard_audio
from app.transcription import faster_whisper_available


app = FastAPI(title="Speech Flow Annotator", version=__version__)
executor = ThreadPoolExecutor(max_workers=settings.worker_count, thread_name_prefix="speech-analysis")
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".mp4", ".webm"}


def public_job(data: dict) -> dict:
    return JobPublic(**{key: data.get(key) for key in JobPublic.model_fields}).model_dump()


def run_job(job_id: str, source_path: Path, options: dict) -> None:
    def progress(percent: int, stage: str, message: str) -> None:
        store.update(
            job_id,
            status="completed" if percent >= 100 else "processing",
            progress=percent,
            stage=stage,
            message=message,
            result_url=f"/api/jobs/{job_id}/result" if percent >= 100 else None,
        )

    try:
        store.update(job_id, status="processing", stage="starting", progress=1, message="任务开始处理。")
        analyze_job(
            job_id=job_id,
            job_dir=store.directory(job_id),
            source_path=source_path,
            original_name=options["original_name"],
            transcript=options.get("transcript", ""),
            auto_transcribe=options.get("auto_transcribe", False),
            model_name=options.get("model_name", settings.default_model),
            device=options.get("device", "auto"),
            accent=options.get("accent", "general-american"),
            progress=progress,
        )
    except Exception as exc:  # surfaced to the local user through job status
        store.update(
            job_id,
            status="failed",
            stage="failed",
            message="分析失败。",
            error=str(exc),
        )


def run_text_job(job_id: str, options: dict) -> None:
    try:
        store.update(
            job_id,
            status="processing",
            stage="text_planning",
            progress=25,
            message="正在查询标准发音并划分意群。",
        )
        result = build_standard_reading(
            job_id=job_id,
            transcript=options["transcript"],
            accent=options.get("accent", "general-american"),
        )
        store.update(
            job_id,
            status="processing",
            stage="synthesizing",
            progress=55,
            message="正在生成标准英语参考音频。",
        )
        job_dir = store.directory(job_id)
        try:
            normalized_path, voice_metadata = synthesize_standard_audio(
                result.transcript,
                job_dir,
                options.get("accent", "general-american"),
                options.get("tts_engine", "neural"),
            )
            from app.audio import analyze_audio_quality, attach_word_acoustics, extract_acoustic_features, load_wav

            audio = load_wav(normalized_path)
            features = extract_acoustic_features(audio)
            boundary_quality = apply_synthesis_boundaries(
                result.words, voice_metadata.get("boundaries", []), audio.duration
            )
            if boundary_quality == 0:
                planned_duration = max(0.1, result.words[-1].end)
                scale = audio.duration / planned_duration
                for word in result.words:
                    word.start = round(word.start * scale, 3)
                    word.end = round(word.end * scale, 3)
            for phrase in result.phrases:
                phrase.start = result.words[phrase.start_word].start
                phrase.end = result.words[phrase.end_word].end
            attach_word_acoustics(result.words, features)
            voice_name = voice_metadata.get("voice", "Windows English Voice")
            is_online = bool(voice_metadata.get("online"))
            audio_label = "自然参考朗读" if is_online else "本地基础朗读"
            result.audio = analyze_audio_quality(audio, f"{audio_label} · {voice_name}", features)
            result.contours = features.compact()
            result.alignment_quality = round(boundary_quality, 3)
            result.summary["duration_seconds"] = round(audio.duration, 2)
            result.summary["generated_voice"] = voice_name
            result.summary["speech_engine"] = voice_metadata.get("engine", "Windows System.Speech")
            result.summary["speech_online"] = is_online
            result.summary["word_boundary_quality"] = round(boundary_quality, 3)
            rhythm = result.summary.get("rhythm", {})
            rhythm["syllables_per_second"] = round(
                rhythm.get("syllables", 0) / max(0.1, audio.duration), 2
            )
            stress_times = [
                (result.words[item.start_word].start + result.words[item.start_word].end) / 2
                for item in result.annotations
                if item.type == "prominence"
            ]
            stress_intervals = [
                round(current - previous, 3)
                for previous, current in zip(stress_times, stress_times[1:])
                if current > previous
            ]
            rhythm["stress_intervals"] = stress_intervals
            rhythm["mean_stress_interval"] = (
                round(sum(stress_intervals) / len(stress_intervals), 3) if stress_intervals else None
            )
            if is_online:
                result.limitations.insert(0, "自然参考音由 Microsoft Edge 在线神经语音生成；生成时英文文稿会发送到该在线语音服务。")
                result.limitations.insert(1, "逐词播放位置来自神经语音返回的单词边界，不是音素级强制对齐。")
            else:
                if voice_metadata.get("fallback_reason"):
                    result.limitations.insert(0, "在线自然语音暂不可用，本次已自动使用 Windows 离线基础声音。")
                else:
                    result.limitations.insert(0, "本次按你的选择使用 Windows 离线基础声音。")
                result.limitations.insert(1, "离线声音的逐词播放时间按规划时长估算，定位可能有轻微偏差。")
        except Exception as synthesis_error:
            result.limitations.insert(0, f"本次未能生成参考音频：{synthesis_error}")
        store.update(
            job_id,
            status="processing",
            stage="annotation",
            progress=82,
            message="正在生成重音、弱读、节奏和语调建议。",
        )
        (job_dir / "result.json").write_text(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        store.update(
            job_id,
            status="completed",
            stage="completed",
            progress=100,
            message="标准英语朗读稿生成完成。",
            result_url=f"/api/jobs/{job_id}/result",
        )
    except Exception as exc:
        store.update(
            job_id,
            status="failed",
            stage="failed",
            message="朗读稿生成失败。",
            error=str(exc),
        )


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "transcription_available": faster_whisper_available(),
        "default_model": settings.default_model,
    }


@app.post("/api/jobs", status_code=202)
async def create_job(
    audio: UploadFile | None = File(None),
    transcript: str = Form(""),
    input_mode: str = Form("audio"),
    auto_transcribe: bool = Form(False),
    model_name: str = Form(settings.default_model),
    device: str = Form("auto"),
    accent: str = Form("general-american"),
    tts_engine: str = Form("neural"),
) -> JSONResponse:
    transcript = transcript.strip()
    if input_mode == "text":
        if not transcript:
            raise HTTPException(400, "文稿模式需要输入英文文稿。")
        options = {
            "original_name": "standard-reading.txt",
            "transcript": transcript,
            "input_mode": "text",
            "auto_transcribe": False,
            "accent": accent,
            "tts_engine": tts_engine if tts_engine in {"neural", "local"} else "neural",
        }
        job = store.create("standard-reading.txt", options)
        executor.submit(run_text_job, job["id"], options)
        return JSONResponse(public_job(job), status_code=202)
    if input_mode != "audio":
        raise HTTPException(400, "未知输入模式。")
    if audio is None:
        raise HTTPException(400, "音频分析模式需要上传音频。")
    filename = Path(audio.filename or "audio.wav").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持 {suffix or '未知'} 格式。")
    if not transcript and not auto_transcribe:
        raise HTTPException(400, "请提供英文原文，或启用自动转写。")
    options = {
        "original_name": filename,
        "transcript": transcript,
        "input_mode": "audio",
        "auto_transcribe": auto_transcribe,
        "model_name": model_name,
        "device": device,
        "accent": accent,
    }
    job = store.create(filename, options)
    job_dir = store.directory(job["id"])
    source_path = job_dir / f"source{suffix}"
    total = 0
    try:
        with source_path.open("wb") as destination:
            while chunk := await audio.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, f"文件不能超过 {settings.max_upload_mb} MB。")
                destination.write(chunk)
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    executor.submit(run_job, job["id"], source_path, options)
    return JSONResponse(public_job(job), status_code=202)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return public_job(store.get(job_id))
    except KeyError as exc:
        raise HTTPException(404, "任务不存在。") from exc


@app.get("/api/jobs/{job_id}/result")
def get_result(job_id: str) -> dict:
    try:
        return store.result(job_id)
    except KeyError as exc:
        raise HTTPException(404, "任务不存在。") from exc
    except FileNotFoundError as exc:
        raise HTTPException(409, "任务尚未完成。") from exc


@app.get("/api/jobs/{job_id}/audio")
def get_audio(job_id: str) -> FileResponse:
    try:
        path = store.directory(job_id) / "normalized.wav"
    except KeyError as exc:
        raise HTTPException(404, "任务不存在。") from exc
    if not path.exists():
        raise HTTPException(409, "该任务没有音频，或音频尚未处理完成。")
    return FileResponse(path, media_type="audio/wav", filename="analysis-audio.wav")


@app.post("/api/jobs/{job_id}/reanalyze", status_code=202)
def reanalyze(job_id: str, request: ReanalyzeRequest) -> dict:
    try:
        job = store.get(job_id)
        job_dir = store.directory(job_id)
    except KeyError as exc:
        raise HTTPException(404, "任务不存在。") from exc
    options = dict(job.get("options", {}))
    options.update({"transcript": request.transcript, "accent": request.accent, "auto_transcribe": False})
    store.update(job_id, status="queued", stage="queued", progress=0, message="修正文稿已提交，正在重新分析。", error=None)
    if options.get("input_mode") == "text":
        executor.submit(run_text_job, job_id, options)
    else:
        source_candidates = list(job_dir.glob("source.*"))
        if not source_candidates:
            raise HTTPException(409, "原始音频已丢失。")
        executor.submit(run_job, job_id, source_candidates[0], options)
    return public_job(store.get(job_id))


@app.get("/api/jobs/{job_id}/export/{kind}")
def export_result(job_id: str, kind: str):
    try:
        result = store.result(job_id)
        job_dir = store.directory(job_id)
    except KeyError as exc:
        raise HTTPException(404, "任务不存在。") from exc
    except FileNotFoundError as exc:
        raise HTTPException(409, "任务尚未完成。") from exc
    if kind == "json":
        return FileResponse(job_dir / "result.json", media_type="application/json", filename="speech-analysis.json")
    if kind == "md":
        return PlainTextResponse(
            render_markdown(result),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="speech-analysis.md"'},
        )
    if kind == "srt":
        return PlainTextResponse(
            render_srt(result),
            media_type="application/x-subrip; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="speech-analysis.srt"'},
        )
    if kind == "html":
        audio_path = job_dir / "normalized.wav"
        content = render_standalone_html(result, audio_path if audio_path.exists() else None)
        return HTMLResponse(
            content,
            headers={"Content-Disposition": 'attachment; filename="speech-analysis.html"'},
        )
    if kind == "pdf":
        pdf_path = job_dir / "speech-analysis.pdf"
        try:
            render_pdf(result, pdf_path)
        except (RuntimeError, subprocess.SubprocessError) as exc:
            raise HTTPException(500, str(exc)) from exc
        return FileResponse(pdf_path, media_type="application/pdf", filename="speech-analysis.pdf")
    raise HTTPException(404, "不支持的导出格式。")


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(settings.static_dir / "index.html")


app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
