"""Clip selection: eligibility filters and scoring.

Two phases:
1. ``pre_score`` from Twitch metadata only (view velocity + ideal length),
   used to decide which clips are worth downloading at all.
2. ``final_score`` after download, adding audio/transcript hype and the
   diversity factor so no single streamer or category dominates.
"""

from __future__ import annotations

import math
from datetime import datetime

from ..models import CategorySettings, ClipInfo, SelectionSettings

VELOCITY_CAP = 2000.0  # views/hour that counts as "maximum hot"


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


def pre_score(clip: ClipInfo, sel: SelectionSettings, now: datetime | None = None) -> tuple[float, dict]:
    vel = view_velocity(clip, now)
    vs = velocity_score(vel)
    ls = length_score(clip.duration, sel)
    score = round(0.65 * vs + 0.35 * ls, 4)
    return score, {"velocity": round(vel, 1), "velocity_score": round(vs, 3), "length_score": round(ls, 3)}


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
    if clip.age_hours(now) > cat.max_age_hours:
        return False, f"older than {cat.max_age_hours}h"
    if cat.language and clip.language and not clip.language.lower().startswith(cat.language.lower()):
        return False, f"language {clip.language} (wanted {cat.language})"
    if clip.duration and clip.duration > sel.max_seconds:
        return False, f"too long ({clip.duration:.0f}s > {sel.max_seconds:.0f}s)"
    if clip.duration and clip.duration < sel.min_seconds:
        return False, f"too short ({clip.duration:.0f}s)"
    return True, ""
