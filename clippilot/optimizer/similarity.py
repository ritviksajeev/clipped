"""Near-duplicate detection against recent uploads (word-shingle Jaccard)."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[\w']+", re.UNICODE)
STOP = {"the", "a", "an", "and", "or", "to", "of", "is", "it", "in", "on", "i", "you", "he", "she", "they",
        "this", "that", "was", "for", "with", "my", "me", "so", "just", "be", "are", "at"}


def tokens(text: str) -> list[str]:
    return [t.replace("'", "") for t in _TOKEN.findall((text or "").lower())]


def shingles(text: str, n: int = 2) -> set[tuple[str, ...]]:
    toks = [t for t in tokens(text) if t not in STOP] or tokens(text)
    if len(toks) < n:
        return {tuple(toks)} if toks else set()
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a: dict, b: dict) -> float:
    """a/b: {"title": str, "text": transcript, "streamer": str}."""
    t_sim = jaccard(shingles(a.get("title", ""), 1), shingles(b.get("title", ""), 1))
    if a.get("text") and b.get("text"):
        x_sim = jaccard(shingles(a["text"]), shingles(b["text"]))
        score = 0.75 * x_sim + 0.25 * t_sim
    else:
        score = t_sim
    if a.get("streamer") and a.get("streamer", "").lower() == b.get("streamer", "").lower():
        score = min(1.0, score + 0.1)
    return round(score, 3)


def most_similar(candidate: dict, recent: list[dict]) -> tuple[float, dict | None]:
    best, match = 0.0, None
    for other in recent:
        s = similarity(candidate, other)
        if s > best:
            best, match = s, other
    return best, match
