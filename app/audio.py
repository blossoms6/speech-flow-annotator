from __future__ import annotations

import math
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from scipy.ndimage import median_filter

from app.schemas import AudioInfo, Word


EPSILON = 1e-9


@dataclass
class AudioData:
    samples: np.ndarray
    sample_rate: int
    path: Path

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


@dataclass
class AcousticFeatures:
    times: np.ndarray
    rms_db: np.ndarray
    f0_hz: np.ndarray
    speech_mask: np.ndarray

    def compact(self, max_points: int = 2400) -> dict[str, list[float]]:
        if len(self.times) <= max_points:
            indices = np.arange(len(self.times))
        else:
            indices = np.linspace(0, len(self.times) - 1, max_points).astype(int)
        return {
            "times": np.round(self.times[indices], 3).tolist(),
            "f0_hz": np.round(self.f0_hz[indices], 2).tolist(),
            "intensity_db": np.round(self.rms_db[indices], 2).tolist(),
        }


def convert_to_wav(source: Path, destination: Path) -> Path:
    """Convert any FFmpeg-supported input to 16 kHz mono PCM WAV."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "FFmpeg could not decode this file."
        raise ValueError(f"音频转换失败：{detail}")
    return destination


def load_wav(path: Path) -> AudioData:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_rate = handle.getframerate()
        sample_width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if sample_width != 2:
        raise ValueError("内部 WAV 必须是 16-bit PCM。")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return AudioData(samples=samples, sample_rate=sample_rate, path=path)


def _frame_signal(samples: np.ndarray, frame_size: int, hop_size: int) -> np.ndarray:
    if len(samples) < frame_size:
        samples = np.pad(samples, (0, frame_size - len(samples)))
    count = 1 + max(0, (len(samples) - frame_size) // hop_size)
    shape = (count, frame_size)
    strides = (samples.strides[0] * hop_size, samples.strides[0])
    return np.lib.stride_tricks.as_strided(samples, shape=shape, strides=strides).copy()


def extract_acoustic_features(audio: AudioData) -> AcousticFeatures:
    sr = audio.sample_rate
    frame_size = max(320, int(sr * 0.04))
    hop_size = max(160, int(sr * 0.02))
    frames = _frame_signal(audio.samples, frame_size, hop_size)
    windowed = frames * np.hanning(frame_size)[None, :]
    rms = np.sqrt(np.mean(frames * frames, axis=1) + EPSILON)
    rms_db = 20.0 * np.log10(rms + EPSILON)

    noise_floor = float(np.percentile(rms_db, 20))
    speech_threshold = max(noise_floor + 9.0, -42.0)
    speech_mask = rms_db > speech_threshold
    speech_mask = median_filter(speech_mask.astype(np.uint8), size=5) > 0

    f0 = np.zeros(len(frames), dtype=np.float32)
    min_lag = max(1, int(sr / 350.0))
    max_lag = min(frame_size - 2, int(sr / 70.0))
    nfft = 1 << int(math.ceil(math.log2(frame_size * 2 - 1)))

    for index in np.flatnonzero(speech_mask):
        frame = windowed[index] - np.mean(windowed[index])
        spectrum = np.fft.rfft(frame, n=nfft)
        autocorrelation = np.fft.irfft(spectrum * np.conjugate(spectrum), n=nfft)[:frame_size]
        if autocorrelation[0] <= EPSILON:
            continue
        search = autocorrelation[min_lag : max_lag + 1]
        lag_offset = int(np.argmax(search))
        correlation = float(search[lag_offset] / (autocorrelation[0] + EPSILON))
        if correlation >= 0.28:
            lag = min_lag + lag_offset
            f0[index] = sr / lag

    voiced = f0 > 0
    if np.count_nonzero(voiced) >= 5:
        filtered = median_filter(np.where(voiced, f0, np.nan), size=5, mode="nearest")
        f0[voiced] = np.nan_to_num(filtered[voiced], nan=f0[voiced])

    times = (np.arange(len(frames)) * hop_size + frame_size / 2) / sr
    return AcousticFeatures(times=times, rms_db=rms_db, f0_hz=f0, speech_mask=speech_mask)


def analyze_audio_quality(audio: AudioData, original_name: str, features: AcousticFeatures) -> AudioInfo:
    peak = float(np.max(np.abs(audio.samples))) if len(audio.samples) else 0.0
    rms = float(np.sqrt(np.mean(audio.samples * audio.samples) + EPSILON))
    clipping_ratio = float(np.mean(np.abs(audio.samples) >= 0.995))
    speech_ratio = float(np.mean(features.speech_mask)) if len(features.speech_mask) else 0.0
    warnings: list[str] = []

    if rms < 0.008:
        warnings.append("录音音量较低，弱读和重音分析可能不稳定。")
    if clipping_ratio > 0.002:
        warnings.append("录音存在削波，音量和爆破音分析可能受到影响。")
    if speech_ratio < 0.25:
        warnings.append("有效语音比例较低，音频可能包含较长静音或音乐。")
    if audio.duration > 1800:
        warnings.append("音频超过30分钟，处理时间会明显增加。")

    quality = "good"
    if len(warnings) >= 2:
        quality = "poor"
    elif warnings:
        quality = "fair"

    return AudioInfo(
        original_name=original_name,
        duration=round(audio.duration, 3),
        sample_rate=audio.sample_rate,
        rms_dbfs=round(20 * math.log10(rms + EPSILON), 2),
        peak_dbfs=round(20 * math.log10(peak + EPSILON), 2),
        clipping_ratio=round(clipping_ratio, 6),
        speech_ratio=round(speech_ratio, 4),
        quality=quality,
        warnings=warnings,
    )


def attach_word_acoustics(words: list[Word], features: AcousticFeatures) -> None:
    for word in words:
        mask = (features.times >= word.start) & (features.times <= word.end)
        rms_values = features.rms_db[mask]
        f0_values = features.f0_hz[mask]
        f0_values = f0_values[f0_values > 0]
        word.acoustic = {
            "duration": round(max(0.0, word.end - word.start), 3),
            "intensity_mean": round(float(np.mean(rms_values)), 2) if len(rms_values) else None,
            "intensity_peak": round(float(np.max(rms_values)), 2) if len(rms_values) else None,
            "f0_median": round(float(np.median(f0_values)), 2) if len(f0_values) else None,
            "f0_peak": round(float(np.max(f0_values)), 2) if len(f0_values) else None,
            "voiced_ratio": round(float(len(f0_values) / max(1, np.count_nonzero(mask))), 3),
        }


def boundary_energy(audio: AudioData, boundary_seconds: float, radius_ms: float = 25.0) -> float:
    center = int(boundary_seconds * audio.sample_rate)
    radius = max(1, int(radius_ms / 1000.0 * audio.sample_rate))
    segment = audio.samples[max(0, center - radius) : min(len(audio.samples), center + radius)]
    if not len(segment):
        return 0.0
    return float(np.sqrt(np.mean(segment * segment) + EPSILON))


def release_burst_score(audio: AudioData, boundary_seconds: float) -> float:
    """Return a conservative high-frequency burst indicator around a word boundary."""
    sr = audio.sample_rate
    center = int(boundary_seconds * sr)
    width = max(64, int(0.025 * sr))
    segment = audio.samples[max(0, center - width) : min(len(audio.samples), center + width)]
    if len(segment) < 128:
        return 0.0
    segment = segment * np.hanning(len(segment))
    spectrum = np.abs(np.fft.rfft(segment)) ** 2
    frequencies = np.fft.rfftfreq(len(segment), 1 / sr)
    total = float(np.sum(spectrum) + EPSILON)
    high = float(np.sum(spectrum[frequencies >= 3000]))
    return min(1.0, high / total * 12.0)
