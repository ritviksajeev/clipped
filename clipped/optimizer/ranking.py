"""Clip selection: eligibility filters and scoring.

Two discovery modes decide which clips are candidates at all:

* ``trending``: clips from the last few hours ranked by how fast they are
  gaining views right now (views/hour since creation, blended with the views
  gained between two fetches once we have seen a clip twice).
* ``top24h``: the most-viewed clips created in the last 24 hours.

Two scoring phases:
1. ``pre_score`` from Twitch metadata only (popularity for the mode + ideal
   length), used to decide which clips are worth downloading at all.
2. ``final_score`` after download, adding audio/transcript hype and the
   diversity factor so no single streamer or category dominates.
"""

from __future__ import annotations

import math
from datetime import datetime

from ..models import CategorySettings, ClipInfo, SelectionSettings

VELOCITY_CAP = 2000.0  # views/hour that counts as "maximum hot"
VIEWS_CAP = 25000.0  # total views that count as "maximum popular" (top-24h mode)
TOP24H_HOURS = 24.0
DISCOVERY_LABELS = {"trending": "trending now", "top24h": "top of the last 24h"}


def discovery_mode(cat: CategorySettings, sel: SelectionSettings) -> str:
    return sel.discovery if cat.discovery == "inherit" else cat.discovery


def window_hours(mode: str, sel: SelectionSettings) -> float:
    """How far back to look for clips."""
    return TOP24H_HOURS if mode == "top24h" else float(sel.trending_window_hours)


def expiry_hours(mode: str, sel: SelectionSettings) -> float:
    """A queued candidate older than this no longer fits its mode and is dropped."""
    return window_hours(mode, sel) * (1.25 if mode == "top24h" else 1.5)


def view_velocity(clip: ClipInfo, now: datetime | None = None) -> float:
    return clip.view_count / max(clip.age_hours(now), 0.5)


def velocity_score(velocity: float) -> float:
    return min(math.log10(1 + velocity) / math.log10(1 + VELOCITY_CAP), 1.0)


def length_score(duration: float, sel: SelectionSettings) -> float:
    if duration <= 0:
        return 0.5  # unknown length: neutral
    if duration < sel.min_seconds or duration > sel.max_seconds:
        return 0.0
    if sel.ideal_min_seconds <= duration <= sel.ideal_max_seconds:
        return 1.0
    if duration < sel.ideal_min_seconds:
        return 0.4 + 0.6 * (duration - sel.min_seconds) / max(sel.ideal_min_seconds - sel.min_seconds, 1e-6)
    return 0.4 + 0.6 * (sel.max_seconds - duration) / max(sel.max_seconds - sel.ideal_max_seconds, 1e-6)


def popularity_score(views: int) -> float:
    return min(math.log10(1 + max(views, 0)) / math.log10(1 + VIEWS_CAP), 1.0)


def recent_velocity(prev_views: int, prev_at: datetime | None, views: int, now: datetime) -> float | None:
    """Views gained per hour between two observations of the same clip."""
    if prev_at is None:
        return None
    hours = (now - prev_at).total_seconds() / 3600.0
    if hours < 0.2:  # too close together to say anything
        return None
    return max(views - prev_views, 0) / hours


def pre_score(clip: ClipInfo, sel: SelectionSettings, now: datetime | None = None, mode: str = "trending",
              recent: float | None = None) -> tuple[float, dict]:
    avg = view_velocity(clip, now)
    # Lifetime views/hour flatters a clip that peaked hours ago; once we have seen
    # it twice, weight the views it is gaining right now more heavily.
    vel = avg if recent is None else 0.4 * avg + 0.6 * recent
    vs = velocity_score(vel)
    ls = length_score(clip.duration, sel)
    pop = popularity_score(clip.view_count)
    if mode == "top24h":
        score = 0.75 * pop + 0.25 * ls
    else:
        score = 0.65 * vs + 0.35 * ls
    detail = {"mode": mode, "views": clip.view_count, "velocity": round(vel, 1), "velocity_score": round(vs, 3),
              "popularity": round(pop, 3), "length_score": round(ls, 3)}
    if recent is not None:
        detail["recent_velocity"] = round(recent, 1)
    return round(score, 4), detail


def final_score(pre: float, hype: float, diversity: float = 1.0) -> float:
    return round((0.55 * pre + 0.45 * hype) * diversity, 4)


def eligible(clip: ClipInfo, cat: CategorySettings, sel: SelectionSettings,
             now: datetime | None = None) -> tuple[bool, str]:
    login = (clip.broadcaster_login or clip.broadcaster_name).lower()
    name = clip.broadcaster_name.lower()
    if login in cat.blocklist or name in cat.blocklist:
        return False, "streamer is on the blocklist"
    if cat.allowlist and login not in cat.allowlist and name not in cat.allowlist:
        return False, "streamer is not on this category's allowlist"
    if clip.view_count < cat.min_views:
        return False, f"only {clip.view_count} views (min {cat.min_views})"
    mode = discovery_mode(cat, sel)
    window = window_hours(mode, sel)
    if clip.age_hours(now) > window:
        return False, f"older than {window:g}h ({DISCOVERY_LABELS[mode]})"
    if cat.language and clip.language and not clip.language.lower().startswith(cat.language.lower()):
        return False, f"language {clip.language} (wanted {cat.language})"
    if clip.duration and clip.duration > sel.max_seconds:
        return False, f"too long ({clip.duration:.0f}s > {sel.max_seconds:.0f}s)"
    if clip.duration and clip.duration < sel.min_seconds:
        return False, f"too short ({clip.duration:.0f}s)"
    return True, ""
