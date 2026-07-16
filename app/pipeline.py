from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from app import __version__
from app.analyzers import run_all_analyzers
from app.audio import (
    analyze_audio_quality,
    attach_word_acoustics,
    convert_to_wav,
    extract_acoustic_features,
    load_wav,
)
from app.config import settings
from app.schemas import AnalysisResult
from app.store import utc_now
from app.transcription import build_transcript_result


ProgressCallback = Callable[[int, str, str], None]


def analyze_job(
    job_id: str,
    job_dir: Path,
    source_path: Path,
    original_name: str,
    transcript: str,
    auto_transcribe: bool,
    model_name: str,
    device: str,
    accent: str,
    progress: ProgressCallback,
) -> AnalysisResult:
    progress(4, "preprocessing", "正在转换音频格式。")
    normalized_path = job_dir / "normalized.wav"
    convert_to_wav(source_path, normalized_path)
    audio = load_wav(normalized_path)
    if audio.duration <= 0.1:
        raise ValueError("音频过短，无法分析。")
    if audio.duration > settings.max_duration_seconds:
        raise ValueError(f"1.0 单个音频最长支持 {settings.max_duration_seconds // 60} 分钟。")

    progress(10, "acoustic_features", "正在提取音量、静音和音高曲线。")
    features = extract_acoustic_features(audio)
    audio_info = analyze_audio_quality(audio, original_name, features)

    progress(15, "transcript", "正在准备英文文稿。")
    transcript_result = build_transcript_result(
        audio=audio,
        features=features,
        supplied_transcript=transcript,
        auto_transcribe=auto_transcribe,
        model_name=model_name,
        device=device,
        progress=progress,
    )

    progress(62, "alignment", "正在整理逐词时间轴和声学特征。")
    attach_word_acoustics(transcript_result.words, features)

    progress(72, "annotation", "正在分析停顿、重音、节奏和语调。")
    phrases, annotations, summary = run_all_analyzers(transcript_result.words, features, audio)
    summary.update(
        {
            "word_count": len(transcript_result.words),
            "phrase_count": len(phrases),
            "duration_seconds": round(audio.duration, 2),
            "transcript_source": transcript_result.source,
        }
    )
    limitations = [
        "1.0 的弱读、连读和失爆属于实验性候选，应结合对应音频片段复核。",
        "未接入独立音素识别模型；提供原文但关闭自动转写时，单词时间轴为能量估计。",
        "多人重叠、强背景音乐和明显混响会降低分析可靠性。",
    ]
    if transcript_result.source == "user-estimated":
        limitations.insert(0, "当前使用低置信度能量对齐；安装并启用自动转写可改善时间轴。")

    progress(90, "rendering", "正在生成交互结果和导出数据。")
    result = AnalysisResult(
        version=__version__,
        job_id=job_id,
        created_at=utc_now(),
        accent=accent,
        input_mode="audio",
        transcript=transcript_result.transcript,
        transcript_source=transcript_result.source,
        alignment_quality=transcript_result.alignment_quality,
        audio=audio_info,
        words=transcript_result.words,
        phrases=phrases,
        annotations=annotations,
        contours=features.compact(),
        summary=summary,
        limitations=limitations,
    )
    (job_dir / "result.json").write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    progress(100, "completed", "分析完成。")
    return result
