from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Phone(BaseModel):
    phone: str
    start: float
    end: float
    confidence: float = 0.0


class Word(BaseModel):
    index: int
    text: str
    normalized: str
    punctuation_after: str = ""
    start: float
    end: float
    confidence: float = 0.0
    alignment_method: str = "estimated"
    syllables: int = 1
    pronunciation: str | None = None
    lexical_stress: list[int] = Field(default_factory=list)
    phones: list[Phone] = Field(default_factory=list)
    acoustic: dict[str, float | None] = Field(default_factory=dict)


class Annotation(BaseModel):
    id: str
    type: Literal[
        "pause",
        "phrase_boundary",
        "prominence",
        "rhythm",
        "intonation",
        "weak_form",
        "linking",
        "unreleased_stop",
    ]
    start_word: int
    end_word: int
    label: str
    symbol: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    experimental: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


class Phrase(BaseModel):
    index: int
    start_word: int
    end_word: int
    start: float
    end: float
    text: str
    intonation: str = "level"
    intonation_symbol: str = "→"
    confidence: float = 0.0
    rhythm_pattern: str = ""


class AudioInfo(BaseModel):
    original_name: str
    duration: float
    sample_rate: int
    channels: int = 1
    rms_dbfs: float
    peak_dbfs: float
    clipping_ratio: float
    speech_ratio: float
    quality: str
    warnings: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    version: str = "1.0.0"
    job_id: str
    created_at: str
    language: str = "en"
    accent: str = "general-american"
    input_mode: Literal["audio", "text"] = "audio"
    transcript: str
    transcript_source: str
    alignment_quality: float
    audio: AudioInfo | None = None
    words: list[Word]
    phrases: list[Phrase]
    annotations: list[Annotation]
    contours: dict[str, list[float]]
    summary: dict[str, Any]
    limitations: list[str] = Field(default_factory=list)


class JobPublic(BaseModel):
    id: str
    status: Literal["queued", "processing", "completed", "failed"]
    stage: str
    progress: int
    message: str = ""
    error: str | None = None
    created_at: str
    updated_at: str
    result_url: str | None = None


class ReanalyzeRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=100_000)
    accent: str = "general-american"
