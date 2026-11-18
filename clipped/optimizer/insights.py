"""The "what's working" dashboard: aggregate upload performance by every
lever the optimiser controls, and say in plain words what the data shows."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, tzinfo

from ..models import GlobalSettings
from . import learning

LENGTH_BUCKETS = [(0, 15, "<15s"), (15, 30, "15-30s"), (30, 45, "30-45s"), (45, 60, "45-60s"), (60, 1e9, "60s+")]


def _bucket(duration: float) -> str:
    for lo, hi, label in LENGTH_BUCKETS:
        if lo <= duration < hi:
            return label
    return "?"


def _group(uploads: list[dict], perf: dict[int, float], key) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for u in uploads:
        k = key(u)
        if k is not None and k != "":
            groups[str(k)].append(u)
    rows = []
    for k, items in groups.items():
        views = [i["stats"]["views"] for i in items]
        ret = [i["stats"]["avg_view_pct"] for i in items if i["stats"].get("avg_view_pct") is not None]
        perfs = [perf[i["id"]] for i in items if i["id"] in perf]
        rows.append({
            "key": k,
            "n": len(items),
            "avg_views": round(sum(views) / len(views), 1),
            "avg_retention": round(sum(ret) / len(ret), 1) if ret else None,
            "score": round(sum(perfs) / len(perfs), 3) if perfs else None,
        })
    rows.sort(key=lambda r: (r["score"] if r["score"] is not None else -1, r["avg_views"]), reverse=True)
    return rows


def _tip(rows: list[dict], label: str, min_n: int = 3) -> str | None:
    solid = [r for r in rows if r["n"] >= min_n]
    if len(solid) < 2:
        return None
    best, worst = solid[0], solid[-1]
    if worst["avg_views"] <= 0 or best["avg_views"] <= worst["avg_views"] * 1.15:
        return None
    ratio = best["avg_views"] / worst["avg_views"]
    return (f"{label} “{best['key']}” averages {ratio:.1f}× the views of “{worst['key']}” "
            f"({best['n']} vs {worst['n']} uploads).")


def build(uploads: list[dict], tz: tzinfo, gs: GlobalSettings, now: datetime | None = None) -> dict:
    with_stats = [u for u in uploads if u.get("stats")]
    mature = learning.matured(with_stats, now)
    perf = learning.performance(mature)
    by_style = _group(mature, perf, lambda u: u.get("title_style"))
    by_category = _group(mature, perf, lambda u: u.get("category_name"))
    by_streamer = _group(mature, perf, lambda u: u.get("streamer"))[:12]
    by_length = _group(mature, perf, lambda u: _bucket(u.get("duration") or 0))
    by_hook = _group(mature, perf, lambda u: "flash-forward" if any(
        s.get("kind") == "teaser" for s in (u.get("analysis", {}).get("plan", {}) or {}).get("segments", []))
        else "straight cut")
    by_hour_rows = {r["key"]: r for r in _group(
        mature, perf, lambda u: learning._parse(u["uploaded_at"]).astimezone(tz).hour)}
    hours = learning.hour_scores(uploads, tz, min_samples=gs.optimizer.min_samples_for_timing, now=now)
    by_hour = []
    for h in range(24):
        row = by_hour_rows.get(str(h), {"n": 0, "avg_views": 0, "avg_retention": None, "score": None})
        by_hour.append({"hour": h, **{k: v for k, v in row.items() if k != "key"},
                        "learned_score": hours.get(h) if hours else None})

    style_stats = learning.style_stats(mature, perf)
    total_views = sum(u["stats"]["views"] for u in with_stats)
    retention = [u["stats"]["avg_view_pct"] for u in with_stats if u["stats"].get("avg_view_pct") is not None]
    top = sorted(mature, key=lambda u: perf.get(u["id"], 0), reverse=True)[:5]

    tips = [t for t in (
        _tip(by_style, "Title style"), _tip(by_length, "Length"), _tip(by_hook, "Hook"),
        _tip(by_category, "Category"), _tip(by_streamer, "Streamer"),
    ) if t]
    if hours:
        best_hours = sorted(hours, key=hours.get, reverse=True)[:3]
        tips.append("Best posting hours so far: " + ", ".join(f"{h:02d}:00" for h in sorted(best_hours))
                    + " - auto mode leans the schedule toward them.")
    need_styles = max(gs.optimizer.min_samples_for_styles - len(mature), 0)
    need_timing = max(gs.optimizer.min_samples_for_timing - len(mature), 0)
    if need_styles:
        tips.append(f"{need_styles} more upload(s) with 24h+ of stats before title styles are optimised.")
    if need_timing:
        tips.append(f"{need_timing} more upload(s) with 24h+ of stats before posting times are optimised.")

    return {
        "summary": {
            "uploads": len(uploads),
            "with_stats": len(with_stats),
            "matured": len(mature),
            "total_views": total_views,
            "avg_views": round(total_views / len(with_stats), 1) if with_stats else 0,
            "avg_retention": round(sum(retention) / len(retention), 1) if retention else None,
        },
        "by_style": by_style,
        "style_learning": {k: v for k, v in style_stats.items()},
        "by_category": by_category,
        "by_streamer": by_streamer,
        "by_length": by_length,
        "by_hook": by_hook,
        "by_hour": by_hour,
        "top": [{"id": u["id"], "title": u["title"], "youtube_id": u["youtube_id"], "views": u["stats"]["views"],
                 "avg_view_pct": u["stats"].get("avg_view_pct"), "style": u.get("title_style"),
                 "score": perf.get(u["id"])} for u in top],
        "tips": tips,
        "learning_active": {"styles": need_styles == 0, "timing": hours is not None},
    }
