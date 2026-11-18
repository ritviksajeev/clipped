"""YouTube Data API quota ledger.

The default quota is 10,000 units per day, resetting at midnight Pacific
Time. An upload (videos.insert) costs 1,600 units, so a fresh project can
upload about six videos a day. We track spend locally so the scheduler can
stop *before* hitting the wall, and pause until the reset when YouTube says
the quota is exhausted.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")

COSTS = {
    "videos.insert": 1600,
    "thumbnails.set": 50,
    "videos.list": 1,
    "channels.list": 1,
}
DEFAULT_DAILY_LIMIT = 10_000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QuotaTracker:
    def __init__(self, db, daily_limit: int | None = None, clock: Callable[[], datetime] = utcnow) -> None:
        self.db = db
        self._limit = daily_limit
        self.clock = clock

    @property
    def daily_limit(self) -> int:
        if self._limit is not None:
            return self._limit
        return int(self.db.get_value("youtube_daily_quota", DEFAULT_DAILY_LIMIT))

    def day(self) -> str:
        return self.clock().astimezone(PACIFIC).date().isoformat()

    def used(self) -> int:
        return self.db.quota_used(self.day())

    def remaining(self) -> int:
        if self.db.get_value("quota_exhausted_day") == self.day():
            return 0
        return max(self.daily_limit - self.used(), 0)

    def can_spend(self, op: str, count: int = 1) -> bool:
        return self.remaining() >= COSTS.get(op, 1) * count

    def spend(self, op: str, count: int = 1) -> int:
        return self.db.add_quota(self.day(), COSTS.get(op, 1) * count)

    def mark_exhausted(self) -> None:
        self.db.set_value("quota_exhausted_day", self.day())

    def reset_at(self) -> datetime:
        local = self.clock().astimezone(PACIFIC)
        nxt = datetime.combine(local.date() + timedelta(days=1), time(0, 5), tzinfo=PACIFIC)
        return nxt.astimezone(timezone.utc)

    def uploads_left(self) -> int:
        per_upload = COSTS["videos.insert"] + COSTS["thumbnails.set"] + COSTS["videos.list"]
        return self.remaining() // per_upload

    def snapshot(self) -> dict:
        return {
            "day": self.day(),
            "used": self.used(),
            "limit": self.daily_limit,
            "remaining": self.remaining(),
            "uploads_left": self.uploads_left(),
            "resets_at": self.reset_at().isoformat(timespec="seconds"),
        }
