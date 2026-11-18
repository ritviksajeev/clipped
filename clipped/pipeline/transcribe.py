"""Local speech-to-text with word timestamps (faster-whisper).

The whisper model is downloaded once from Hugging Face into the clipped data
directory on first use, then everything runs offline on the user's machine.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from ..logs import get_logger

log = get_logger("transcribe")


@dataclass
class Word:
    start: float
    end: float
    text: str
    probability: float = 1.0


@dataclass
class Transcript:
    words: list[Word] = field(default_factory=list)
    language: str = ""

    @property
    def text(self) -> str:
        return " ".join(w.text.strip() for w in self.words).strip()

    def to_dict(self) -> dict:
        return {"language": self.language, "words": [asdict(w) for w in self.words]}

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        words = [Word(float(w["start"]), float(w["end"]), str(w["text"]), float(w.get("probability", 1.0)))
                 for w in data.get("words", [])]
        return cls(words=clean_words(words), language=data.get("language", ""))

    def save(self, path: Path) -> Path:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), "utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        return cls.from_dict(json.loads(path.read_text("utf-8")))

    def keyword_hits(self, keywords: list[str]) -> list[tuple[float, str]]:
        """Times where any keyword/phrase is spoken."""
        hits: list[tuple[float, str]] = []
        tokens = [normalize_token(w.text) for w in self.words]
        for kw in keywords:
            parts = [normalize_token(p) for p in kw.split() if normalize_token(p)]
            if not parts:
                continue
            for i in range(len(tokens) - len(parts) + 1):
                if tokens[i : i + len(parts)] == parts:
                    hits.append((self.words[i].start, kw))
        hits.sort()
        return hits


def normalize_token(text: str) -> str:
    return re.sub(r"[^\w']", "", text.lower(), flags=re.UNICODE).replace("'", "")


def clean_words(words: list[Word]) -> list[Word]:
    """Drop empty tokens, enforce monotonic non-overlapping timings."""
    out: list[Word] = []
    for w in sorted(words, key=lambda x: (x.start, x.end)):
        text = w.text.strip()
        if not text:
            continue
        start = max(float(w.start), 0.0)
        if out:
            start = max(start, out[-1].start + 0.02)
            if out[-1].end > start:
                out[-1].end = start  # previous word ends where this one starts
        end = max(float(w.end), start + 0.05)
        out.append(Word(round(start, 3), round(end, 3), text, w.probability))
    return out


class Transcriber(Protocol):
    def transcribe(self, media_path: Path, language: str = "") -> Transcript: ...


class WhisperTranscriber:
    """faster-whisper wrapper. The model is loaded lazily and cached per process."""

    _models: dict[tuple, object] = {}
    _lock = threading.Lock()

    def __init__(self, model_size: str = "base", device: str = "auto", compute_type: str = "auto",
                 download_root: Path | None = None) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root

    def _model(self):
        key = (self.model_size, self.device, self.compute_type, str(self.download_root))
        with self._lock:
            if key not in self._models:
                from faster_whisper import WhisperModel  # heavy import, keep lazy

                compute = self.compute_type
                if compute == "auto":
                    compute = "default"
                log.info("Loading whisper model '%s' (first run downloads it once)", self.model_size)
                self._models[key] = WhisperModel(
                    self.model_size, device=self.device, compute_type=compute,
                    download_root=str(self.download_root) if self.download_root else None,
                )
            return self._models[key]

    def transcribe(self, media_path: Path, language: str = "") -> Transcript:
        model = self._model()
        segments, info = model.transcribe(
            str(media_path),
            language=language or None,
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        words: list[Word] = []
        for segment in segments:
            for w in segment.words or []:
                words.append(Word(float(w.start), float(w.end), w.word, float(getattr(w, "probability", 1.0))))
        transcript = Transcript(words=clean_words(words), language=getattr(info, "language", "") or language)
        log.info("Transcribed %d words (%s)", len(transcript.words), transcript.language or "?")
        return transcript


class StaticTranscriber:
    """Returns a fixed transcript. Used by tests and `--transcript file.json`."""

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript

    def transcribe(self, media_path: Path, language: str = "") -> Transcript:
        return self.transcript
