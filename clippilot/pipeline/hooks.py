"""Hook planning: find the strongest moment, trim dead air, build an edit list.

The result is an :class:`EditPlan` - an ordered list of source-time segments
that the renderer concatenates. Word timestamps are remapped through the same
plan so captions stay in sync after cuts and the optional teaser.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from ..models import HookSettings
from .audio import AudioAnalysis, smooth
from .transcribe import Transcript, Word


@dataclass
class Segment:
    start: float
    end: float
    kind: str = "main"  # "teaser" or "main"

    @property
    def length(self) -> float:
        return max(self.end - self.start, 0.0)


@dataclass
class EditPlan:
    segments: list[Segment]
    source_duration: float
    peak_time: float
    removed_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return sum(s.length for s in self.segments)

    @property
    def has_teaser(self) -> bool:
        return any(s.kind == "teaser" for s in self.segments)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["duration"] = round(self.duration, 3)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "EditPlan":
        return cls(
            segments=[Segment(**s) for s in data["segments"]],
            source_duration=data["source_duration"],
            peak_time=data["peak_time"],
            removed_seconds=data.get("removed_seconds", 0.0),
            notes=list(data.get("notes", [])),
        )

    def map_time(self, t: float, prefer: str = "main") -> float | None:
        """Map a source time to the output timeline (first match of `prefer` kind)."""
        offset = 0.0
        fallback = None
        for seg in self.segments:
            if seg.start <= t <= seg.end:
                out = offset + (t - seg.start)
                if seg.kind == prefer:
                    return out
                fallback = out if fallback is None else fallback
            offset += seg.length
        return fallback

    def remap_words(self, words: list[Word]) -> list[Word]:
        out: list[Word] = []
        offset = 0.0
        for seg in self.segments:
            for w in words:
                s, e = max(w.start, seg.start), min(w.end, seg.end)
                length = max(w.end - w.start, 1e-3)
                if e - s <= 0 or (e - s) / length < 0.5:
                    continue
                out.append(Word(round(offset + s - seg.start, 3), round(offset + e - seg.start, 3), w.text, w.probability))
            offset += seg.length
        return out


def activity_mask(analysis: AudioAnalysis | None, transcript: Transcript | None, duration: float,
                  silence_db: float, window: float = 0.1) -> np.ndarray:
    bins = max(int(np.ceil(duration / window)), 1)
    active = np.zeros(bins, dtype=bool)
    if analysis is not None and analysis.envelope:
        env = analysis.env[:bins]
        active[: env.size] |= env > silence_db
    elif analysis is None:
        active[:] = True
    if transcript:
        for w in transcript.words:
            a, b = int(w.start / window), int(np.ceil(w.end / window))
            active[max(a, 0): min(b, bins)] = True
    return active


def hype_curve(analysis: AudioAnalysis | None, transcript: Transcript | None, keywords: list[str],
               duration: float, window: float = 0.1) -> np.ndarray:
    bins = max(int(np.ceil(duration / window)), 1)
    curve = np.zeros(bins, dtype=np.float32)
    if analysis is not None and analysis.envelope:
        env = analysis.env[:bins]
        curve[: env.size] = smooth(env - float(np.median(env)), 5)
    if transcript and keywords:
        for t, _ in transcript.keyword_hits(keywords):
            a = int(t / window)
            curve[max(a - 3, 0): min(a + 8, bins)] += 6.0
    return curve


def _runs(mask: np.ndarray, value: bool) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, v in enumerate(mask):
        if v == value and start is None:
            start = i
        elif v != value and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


def plan_edit(duration: float, analysis: AudioAnalysis | None, transcript: Transcript | None,
              settings: HookSettings, keywords: list[str] | None = None, window: float = 0.1) -> EditPlan:
    keywords = keywords or []
    notes: list[str] = []
    duration = max(duration, 0.1)
    curve = hype_curve(analysis, transcript, keywords, duration, window)
    keep = [Segment(0.0, duration)]

    if settings.mode != "off" and settings.trim_dead_air:
        active = activity_mask(analysis, transcript, duration, settings.silence_db, window)
        idx = np.flatnonzero(active)
        if idx.size:
            start = max(idx[0] * window - 0.15, 0.0)
            end = min((idx[-1] + 1) * window + 0.35, duration)
            start = min(start, duration * 0.3)
            if end - start < min(3.0, duration):
                start, end = 0.0, duration
            if start > 0.2:
                notes.append(f"trimmed {start:.1f}s of dead air at the start")
            if duration - end > 0.2:
                notes.append(f"trimmed {duration - end:.1f}s at the end")
            keep = []
            cursor = start
            for a, b in _runs(active, False):
                s, e = a * window, b * window
                if s <= start or e >= end or (e - s) <= settings.max_silence:
                    continue
                half = settings.keep_silence / 2
                keep.append(Segment(cursor, s + half))
                cursor = e - half
            keep.append(Segment(cursor, end))
            internal = len(keep) - 1
            if internal:
                notes.append(f"cut {internal} silent gap(s)")

    def kept_peak() -> float:
        best_t, best_v = keep[0].start, -1e9
        for seg in keep:
            a, b = int(seg.start / window), max(int(seg.end / window), int(seg.start / window) + 1)
            part = curve[a:b]
            if part.size:
                i = int(np.argmax(part))
                if part[i] > best_v:
                    best_v, best_t = float(part[i]), (a + i) * window + window / 2
        return min(best_t, duration)

    peak = kept_peak()

    # Enforce the maximum output length with a window around the peak
    # (build-up first, payoff at ~65%).
    total = sum(s.length for s in keep)
    limit = settings.max_output_seconds - (settings.teaser_seconds if settings.mode == "teaser" else 0)
    if total > limit:
        w0 = max(min(peak - 0.65 * limit, duration - limit), 0.0)
        w1 = w0 + limit
        keep = [Segment(max(s.start, w0), min(s.end, w1)) for s in keep if s.end > w0 and s.start < w1]
        notes.append(f"limited to {limit:.0f}s around the peak")
        total = sum(s.length for s in keep)

    segments = list(keep)
    if settings.mode == "teaser" and total >= 8.0:
        out_peak = 0.0
        offset = 0.0
        for seg in keep:
            if seg.start <= peak <= seg.end:
                out_peak = offset + peak - seg.start
            offset += seg.length
        if out_peak > 0.35 * total:
            t_len = settings.teaser_seconds
            t0 = max(peak - 0.6 * t_len, 0.0)
            t1 = min(t0 + t_len, duration)
            segments.insert(0, Segment(t0, t1, "teaser"))
            notes.append(f"opens with a {t1 - t0:.1f}s flash-forward to the peak at {peak:.1f}s")

    removed = duration - sum(s.length for s in segments if s.kind == "main")
    return EditPlan(
        segments=[Segment(round(s.start, 3), round(s.end, 3), s.kind) for s in segments if s.length > 0.05],
        source_duration=round(duration, 3),
        peak_time=round(peak, 2),
        removed_seconds=round(max(removed, 0.0), 2),
        notes=notes,
    )
