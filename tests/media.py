"""Synthetic media for tests: no network, no real Twitch clips needed."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from clipped.pipeline import ffmpeg
from clipped.pipeline.audio import write_wav
from clipped.pipeline.transcribe import Transcript, Word

SR = 16000

# (start, end, kind) - kind: silence | speech | loud
TIMELINE = [
    (0.0, 1.5, "silence"),
    (1.5, 5.0, "speech"),
    (5.0, 7.0, "silence"),  # internal dead air to be cut
    (7.0, 9.0, "speech"),
    (9.0, 10.5, "loud"),  # the hype moment
    (10.5, 12.0, "speech"),
]

WORDS = [
    (1.6, 1.9, "okay"), (1.95, 2.3, "watch"), (2.35, 2.6, "this"), (2.7, 3.0, "one"),
    (3.1, 3.4, "he's"), (3.45, 3.8, "going"), (3.85, 4.2, "for"), (4.25, 4.8, "it."),
    (7.1, 7.4, "wait"), (7.45, 7.8, "wait"), (7.9, 8.3, "wait,"), (8.4, 8.9, "no"),
    (9.0, 9.4, "NO"), (9.45, 9.9, "WAY!"), (10.0, 10.4, "clutch!"),
    (10.6, 10.9, "that"), (10.95, 11.3, "was"), (11.35, 11.9, "insane."),
]


def synth_audio(duration: float = 12.0, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(duration * SR)) / SR
    out = np.zeros_like(t, dtype=np.float32)
    for start, end, kind in TIMELINE:
        m = (t >= start) & (t < end)
        tt = t[m]
        if kind == "speech":
            syll = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * tt) ** 2  # syllable-rate modulation
            sig = 0.08 * syll * (np.sin(2 * np.pi * 220 * tt) + 0.5 * np.sin(2 * np.pi * 440 * tt))
            sig += 0.01 * rng.standard_normal(tt.size)
        elif kind == "loud":
            sig = 0.6 * (np.sin(2 * np.pi * 330 * tt) + 0.3 * rng.standard_normal(tt.size))
        else:
            sig = 0.0005 * rng.standard_normal(tt.size)
        out[m] = sig
    return np.clip(out, -1, 1).astype(np.float32)


def make_clip(path: Path, duration: float = 12.0, size: str = "1280x720", with_audio: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={duration}"]
    if with_audio:
        wav = write_wav(path.with_suffix(".wav"), synth_audio(duration))
        args += ["-i", str(wav), "-c:a", "aac", "-b:a", "128k", "-shortest"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    ffmpeg.run(args)
    return path


def transcript() -> Transcript:
    return Transcript(words=[Word(s, e, w) for s, e, w in WORDS], language="en")


def write_transcript(path: Path) -> Path:
    path.write_text(json.dumps(transcript().to_dict()), "utf-8")
    return path
