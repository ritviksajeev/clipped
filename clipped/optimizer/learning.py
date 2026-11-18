"""Learning from the channel's own YouTube Analytics.

* ``performance`` turns raw stats into a 0..1 score per upload (rank-based,
  so one viral outlier cannot skew everything).
* ``choose_styles`` is a Thompson-sampling bandit over title styles.
* ``hour_scores`` finds the posting hours that perform best.
* ``diversity_factor`` spreads uploads across streamers and categories.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import datetime, timezone, tzinfo

from ..pipeline.metadata import STYLES

MIN_AGE_HOURS = 24.0  # stats younger than this are too noisy to learn from


def _parse(dt) -> datetime | None:
    if dt is None or isinstance(dt, datetime):
        return dt
    value = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def matured(uploads: list[dict], now: datetime | None = None) -> list[dict]:
    """Uploads that have stats and have been live long enough to judge."""
    now = now or datetime.now(timezone.utc)
    out = []
    for u in uploads:
        stats = u.get("stats")
        up = _parse(u.get("uploaded_at"))
        if not stats or not up:
            continue
        if (now - up).total_seconds() / 3600 >= MIN_AGE_HOURS:
            out.append(u)
    return out


def performance(uploads: list[dict]) -> dict[int, float]:
    """0..1 score per upload id: rank of views blended with retention rank."""
    if not uploads:
        return {}

    def ranks(values: list[float]) -> list[float]:
        """Percentile ranks in 0..1; ties share their average rank."""
        if len(values) == 1:
            return [0.5]
        order = sorted(range(len(values)), key=lambda i: values[i])
        r = [0.0] * len(values)
        n = len(values) - 1
        pos = 0
        while pos < len(order):
            end = pos
            while end + 1 < len(order) and values[order[end + 1]] == values[order[pos]]:
                end += 1
            avg = (pos + end) / 2 / n
            for k in range(pos, end + 1):
                r[order[k]] = avg
            pos = end + 1
        return r

    views = [math.log1p(u["stats"].get("views", 0) or 0) for u in uploads]
    retention = [u["stats"].get("avg_view_pct") for u in uploads]
    v_rank = ranks(views)
    if any(x is not None for x in retention):
        filled = [x if x is not None else sum(y for y in retention if y is not None) / max(
            sum(1 for y in retention if y is not None), 1) for x in retention]
        r_rank = ranks(filled)
        scores = [0.7 * v + 0.3 * r for v, r in zip(v_rank, r_rank)]
    else:
        scores = v_rank
    return {u["id"]: round(s, 4) for u, s in zip(uploads, scores)}


def style_stats(uploads: list[dict], perf: dict[int, float]) -> dict[str, dict]:
    out: dict[str, dict] = {s: {"n": 0, "sum": 0.0} for s in STYLES}
    for u in uploads:
        style = u.get("title_style")
        if style in out and u["id"] in perf:
            out[style]["n"] += 1
            out[style]["sum"] += perf[u["id"]]
    for s in out.values():
        s["mean"] = round(s["sum"] / s["n"], 3) if s["n"] else None
    return out


def choose_styles(uploads: list[dict], n: int, *, min_samples: int = 6, explore_rate: float = 0.2,
                  rng: random.Random | None = None, now: datetime | None = None) -> list[str]:
    """Order title styles: best expected performer first (Thompson sampling).

    Until there is enough data, rotate so every style gets tried.
    """
    rng = rng or random.Random()
    data = matured(uploads, now)
    perf = performance(data)
    stats = style_stats(data, perf)
    total = sum(s["n"] for s in stats.values())
    if total < min_samples or rng.random() < explore_rate:
        # Explore: least-tried styles first, random tiebreak.
        order = sorted(STYLES, key=lambda s: (stats[s]["n"], rng.random()))
        return order[:n]
    # Exploit: Thompson-sample among styles with evidence; untried styles are
    # reached through the explore branch above, not by a flat prior here.
    draws = {}
    for style, s in stats.items():
        if s["n"] >= 2:
            draws[style] = rng.betavariate(1 + s["sum"], 1 + (s["n"] - s["sum"]))
        else:
            draws[style] = -1.0 + rng.random() * 0.01
    return sorted(STYLES, key=lambda s: draws[s], reverse=True)[:n]


def hour_scores(uploads: list[dict], tz: tzinfo, *, min_samples: int = 12,
                now: datetime | None = None) -> dict[int, float] | None:
    """Smoothed 0..1 score for each local hour of day, or None without enough data."""
    data = matured(uploads, now)
    if len(data) < min_samples:
        return None
    perf = performance(data)
    sums: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)
    for u in data:
        hour = _parse(u["uploaded_at"]).astimezone(tz).hour
        sums[hour] += perf[u["id"]]
        counts[hour] += 1
    prior_mean, prior_weight = 0.5, 1.0
    raw = {h: (sums[h] + prior_mean * prior_weight) / (counts[h] + prior_weight) for h in range(24)}
    # Circular smoothing: neighbouring hours share evidence.
    smooth = {h: 0.5 * raw[h] + 0.25 * raw[(h - 1) % 24] + 0.25 * raw[(h + 1) % 24] for h in range(24)}
    lo, hi = min(smooth.values()), max(smooth.values())
    if hi - lo < 1e-9:
        return {h: 0.5 for h in range(24)}
    return {h: round((v - lo) / (hi - lo), 4) for h, v in smooth.items()}


def diversity_factor(streamer: str, category_id: int | None, recent: list[dict], *, window: int = 8,
                     penalty: float = 0.55) -> float:
    """Multiplier < 1 for streamers/categories that appeared in the last `window` uploads."""
    recent = recent[:window]
    s = (streamer or "").lower()
    same_streamer = sum(1 for r in recent if (r.get("streamer") or "").lower() == s and s)
    same_category = sum(1 for r in recent if r.get("category_id") == category_id and category_id is not None)
    return round((penalty ** same_streamer) * (math.sqrt(penalty) ** same_category), 4)
