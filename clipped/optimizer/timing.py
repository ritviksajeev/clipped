"""When should the next upload happen?

Rules, applied in order:
1. Never earlier than ``min_gap`` after *any* upload (anti-spam floor).
2. Auto uploads: never earlier than the chosen interval after the last auto upload.
3. Respect "pause until".
4. Respect the daily cap (local calendar day).
5. Skip quiet hours.
6. With enough analytics, shift later (within a bounded window) toward the
   channel's best-performing hours - never earlier than the interval allows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo
from typing import Callable

from ..models import OptimizerSettings, QuietHours, ScheduleSettings


@dataclass
class Slot:
    at: datetime
    reason: str
    shifted_minutes: int = 0


def _hm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def in_quiet_hours(t: datetime, quiet: QuietHours, tz: tzinfo) -> bool:
    if not quiet.enabled:
        return False
    local = t.astimezone(tz).time()
    start, end = _hm(quiet.start), _hm(quiet.end)
    if start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


def end_of_quiet(t: datetime, quiet: QuietHours, tz: tzinfo) -> datetime:
    local = t.astimezone(tz)
    end = _hm(quiet.end)
    candidate = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(t.tzinfo)


def next_local_midnight(t: datetime, tz: tzinfo) -> datetime:
    local = t.astimezone(tz)
    midnight = datetime.combine(local.date() + timedelta(days=1), time(0, 1), tzinfo=tz)
    return midnight.astimezone(t.tzinfo)


def next_slot(
    now: datetime,
    *,
    kind: str,
    schedule: ScheduleSettings,
    tz: tzinfo,
    last_any: datetime | None,
    last_auto: datetime | None,
    uploads_on_day: Callable[[datetime], int],
    hour_scores: dict[int, float] | None = None,
    optimizer: OptimizerSettings | None = None,
) -> Slot:
    at, reason = now, "ready now"
    if last_any and last_any + timedelta(minutes=schedule.min_gap_minutes) > at:
        at, reason = last_any + timedelta(minutes=schedule.min_gap_minutes), "minimum gap between uploads"
    interval = timedelta(minutes=schedule.upload_interval_minutes)
    if kind == "auto" and last_auto and last_auto + interval > at:
        at, reason = last_auto + interval, "upload interval"
    if schedule.pause_until:
        pause = schedule.pause_until if schedule.pause_until.tzinfo else schedule.pause_until.replace(tzinfo=tz)
        if pause > at:
            at, reason = pause, "paused"

    shifted = 0
    for _ in range(14):  # converge: daily cap and quiet hours can push each other
        moved = False
        if uploads_on_day(at) >= schedule.max_uploads_per_day:
            at, reason, moved = (next_local_midnight(at, tz), f"your daily cap of {schedule.max_uploads_per_day} "
                                 "uploads is reached (Settings → Mode & schedule)", True)
        if in_quiet_hours(at, schedule.quiet_hours, tz):
            at, reason, moved = end_of_quiet(at, schedule.quiet_hours, tz), "quiet hours", True
        if not moved:
            break

    if kind == "auto" and hour_scores and optimizer and optimizer.enabled:
        flex = min(schedule.upload_interval_minutes * optimizer.timing_flex_ratio, optimizer.timing_flex_max_minutes)
        best_t, best_v = at, hour_scores.get(at.astimezone(tz).hour, 0.5)
        step = 15
        for minutes in range(step, int(flex) + 1, step):
            t = at + timedelta(minutes=minutes)
            if in_quiet_hours(t, schedule.quiet_hours, tz):
                continue
            if t.astimezone(tz).date() != at.astimezone(tz).date() and uploads_on_day(t) >= schedule.max_uploads_per_day:
                continue
            # Small penalty for waiting so ties resolve toward sooner.
            v = hour_scores.get(t.astimezone(tz).hour, 0.5) - 0.02 * (minutes / 60)
            if v > best_v + 0.05:
                best_t, best_v = t, v
        if best_t != at:
            shifted = int((best_t - at).total_seconds() // 60)
            at, reason = best_t, f"shifted {shifted} min toward a best-performing hour"
    return Slot(at=at, reason=reason, shifted_minutes=shifted)
