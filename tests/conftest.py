from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def synthetic_wav(tmp_path: Path) -> Path:
    sample_rate = 16000

    def tone(duration: float, frequency: float, amplitude: float) -> np.ndarray:
        times = np.arange(int(duration * sample_rate)) / sample_rate
        envelope = np.minimum(1.0, np.minimum(times * 30, (duration - times) * 30))
        return (np.sin(2 * math.pi * frequency * times) * amplitude * envelope).astype(np.float32)

    samples = np.concatenate(
        [
            np.zeros(int(0.12 * sample_rate), dtype=np.float32),
            tone(0.72, 145, 0.16),
            np.zeros(int(0.34 * sample_rate), dtype=np.float32),
            tone(0.65, 195, 0.27),
            np.zeros(int(0.55 * sample_rate), dtype=np.float32),
            tone(0.78, 125, 0.2),
        ]
    )
    output = tmp_path / "sample.wav"
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return output
