"""Audio loudness envelope and hype analysis (numpy only, no extra deps)."""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..config import require_binary
from .ffmpeg import FFmpegError

SAMPLE_RATE = 16000
WINDOW = 0.1  # seconds per envelope bin
FLOOR_DB = -90.0


def decode_mono(path: Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode any media file's audio to float32 mono samples in [-1, 1]."""
    cmd = [
        require_binary("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace")
        if "does not contain any stream" in stderr or "Output file #0 does not contain" in stderr:
            return np.zeros(0, dtype=np.float32)
        raise FFmpegError(f"audio decode failed: {stderr[-400:]}")
    return np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
    import wave

    pcm = np.clip(samples, -1, 1)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes((pcm * 32767).astype("<i2").tobytes())
    return path


def envelope_db(samples: np.ndarray, sample_rate: int = SAMPLE_RATE, window: float = WINDOW) -> np.ndarray:
    """RMS loudness in dBFS per `window` seconds."""
    hop = max(int(sample_rate * window), 1)
    if samples.size == 0:
        return np.zeros(0, dtype=np.float32)
    n = int(np.ceil(samples.size / hop))
    padded = np.zeros(n * hop, dtype=np.float32)
    padded[: samples.size] = samples
    rms = np.sqrt(np.mean(padded.reshape(n, hop) ** 2, axis=1))
    return np.maximum(20 * np.log10(np.maximum(rms, 1e-9)), FLOOR_DB).astype(np.float32)


@dataclass
class AudioAnalysis:
    duration: float
    mean_db: float
    median_db: float
    peak_db: float
    peak_time: float
    loud_peaks: int
    dynamic_range: float
    silent_ratio: float
    hype: float  # 0..1 loudness-based excitement score
    envelope: list[float] = field(default_factory=list, repr=False)
    window: float = WINDOW

    def to_dict(self, include_envelope: bool = False) -> dict:
        data = asdict(self)
        if not include_envelope:
            data.pop("envelope")
        return data

    @property
    def env(self) -> np.ndarray:
        return np.asarray(self.envelope, dtype=np.float32)


def smooth(values: np.ndarray, bins: int) -> np.ndarray:
    if values.size == 0 or bins <= 1:
        return values
    kernel = np.ones(bins, dtype=np.float32) / bins
    return np.convolve(values, kernel, mode="same")


def analyze(samples: np.ndarray, sample_rate: int = SAMPLE_RATE, silence_db: float = -42.0) -> AudioAnalysis:
    env = envelope_db(samples, sample_rate)
    duration = samples.size / sample_rate if sample_rate else 0.0
    if env.size == 0:
        return AudioAnalysis(duration, FLOOR_DB, FLOOR_DB, FLOOR_DB, 0.0, 0, 0.0, 1.0, 0.0, [], WINDOW)

    # Mean loudness in the energy domain (what you'd perceive), not mean of dB.
    mean_db = float(10 * np.log10(max(np.mean(10 ** (env / 10)), 1e-12)))
    median_db = float(np.median(env))
    smoothed = smooth(env, 5)  # ~0.5 s
    peak_idx = int(np.argmax(smoothed))
    peak_db = float(np.max(env))
    voiced = env[env > silence_db]
    baseline = float(np.median(voiced)) if voiced.size else median_db

    # Count distinct loud bursts: crossings above baseline + 8 dB.
    above = smoothed > baseline + 8
    loud_peaks = int(np.sum(above[1:] & ~above[:-1]) + (1 if above.size and above[0] else 0))
    dynamic_range = float(np.percentile(env, 95) - np.percentile(env, 30))
    silent_ratio = float(np.mean(env <= silence_db))

    # Hype: how far the loudest moment pokes out of the clip's own baseline,
    # how many bursts there are, and how little dead air there is.
    burst = np.clip((float(smoothed[peak_idx]) - baseline) / 18.0, 0, 1)
    bursts = np.clip(loud_peaks / 4.0, 0, 1)
    activity = 1.0 - silent_ratio
    hype = float(np.clip(0.5 * burst + 0.3 * bursts + 0.2 * activity, 0, 1))

    return AudioAnalysis(
        duration=duration,
        mean_db=round(mean_db, 2),
        median_db=round(median_db, 2),
        peak_db=round(peak_db, 2),
        peak_time=round(peak_idx * WINDOW + WINDOW / 2, 2),
        loud_peaks=loud_peaks,
        dynamic_range=round(dynamic_range, 2),
        silent_ratio=round(silent_ratio, 3),
        hype=round(hype, 3),
        envelope=[round(float(v), 1) for v in env],
        window=WINDOW,
    )


def analyze_file(path: Path, silence_db: float = -42.0) -> AudioAnalysis:
    return analyze(decode_mono(path), SAMPLE_RATE, silence_db)
