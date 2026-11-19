"""SQLite storage for settings, categories, clips, the review/upload queue,
upload history, analytics snapshots and API quota usage."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import CategorySettings, ClipInfo, GlobalSettings

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    twitch_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    box_art_url TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    settings TEXT NOT NULL DEFAULT '{}',
    last_fetch_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    category_id INTEGER,
    data TEXT NOT NULL,
    broadcaster_login TEXT NOT NULL DEFAULT '',
    broadcaster_name TEXT NOT NULL DEFAULT '',
    view_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    duration REAL NOT NULL DEFAULT 0,
    video_id TEXT NOT NULL DEFAULT '',
    vod_offset INTEGER,
    fetched_at TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    score_detail TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'new',
    skip_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS clips_status ON clips(status, score DESC);
CREATE INDEX IF NOT EXISTS clips_video ON clips(video_id);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id TEXT NOT NULL UNIQUE,
    category_id INTEGER,
    category_name TEXT NOT NULL DEFAULT '',
    streamer TEXT NOT NULL DEFAULT '',
    streamer_login TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'manual',
    workdir TEXT NOT NULL DEFAULT '',
    video_path TEXT NOT NULL DEFAULT '',
    thumbnail_path TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL DEFAULT 0,
    hype REAL NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    analysis TEXT NOT NULL DEFAULT '{}',
    variants TEXT NOT NULL DEFAULT '[]',
    chosen INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    hook_text TEXT NOT NULL DEFAULT '',
    thumbnail_text TEXT NOT NULL DEFAULT '',
    commentary TEXT NOT NULL DEFAULT '',
    title_style TEXT NOT NULL DEFAULT '',
    needs_rerender INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT,
    uploaded_at TEXT,
    youtube_id TEXT NOT NULL DEFAULT '',
    instagram_id TEXT NOT NULL DEFAULT '',
    instagram_url TEXT NOT NULL DEFAULT '',
    posted_manually INTEGER NOT NULL DEFAULT 0,
    privacy_requested TEXT NOT NULL DEFAULT '',
    privacy_actual TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS items_status ON items(status);

CREATE TABLE IF NOT EXISTS stats (
    item_id INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    hours_since_upload REAL NOT NULL DEFAULT 0,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    avg_view_pct REAL,
    avg_view_duration REAL,
    PRIMARY KEY (item_id, fetched_at)
);

CREATE TABLE IF NOT EXISTS quota (day TEXT PRIMARY KEY, units INTEGER NOT NULL DEFAULT 0);
"""

# Columns added after the first release, created on older databases at start-up.
ADDED_ITEM_COLUMNS = {
    "instagram_id": "TEXT NOT NULL DEFAULT ''",
    "instagram_url": "TEXT NOT NULL DEFAULT ''",
    "posted_manually": "INTEGER NOT NULL DEFAULT 0",
}

ITEM_JSON_FIELDS = {"analysis", "variants", "tags"}
ACTIVE_ITEM_STATES = ("processing", "review", "ready", "approved", "uploading")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            have = {r[1] for r in self.conn.execute("PRAGMA table_info(items)")}
            for column, decl in ADDED_ITEM_COLUMNS.items():
                if column not in have:  # databases made by an older version
                    self.conn.execute(f"ALTER TABLE items ADD COLUMN {column} {decl}")
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.conn.commit()

    # ------------------------------------------------------------------ helpers
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ------------------------------------------------------------------ settings
    def get_value(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_value(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value, default=str)))

    def get_global_settings(self) -> GlobalSettings:
        data = self.get_value("global", None)
        return GlobalSettings.model_validate(data) if data else GlobalSettings()

    def save_global_settings(self, settings: GlobalSettings) -> None:
        self.set_value("global", settings.model_dump(mode="json"))

    # ------------------------------------------------------------------ categories
    def _category(self, row: dict | None) -> dict | None:
        if not row:
            return None
        row["enabled"] = bool(row["enabled"])
        row["settings"] = CategorySettings.model_validate(json.loads(row["settings"] or "{}")).model_dump(mode="json")
        return row

    def list_categories(self, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM categories" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY name COLLATE NOCASE"
        return [self._category(r) for r in self.query(sql)]

    def get_category(self, category_id: int) -> dict | None:
        return self._category(self.one("SELECT * FROM categories WHERE id=?", (category_id,)))

    def add_category(self, twitch_id: str, name: str, box_art_url: str = "",
                     settings: CategorySettings | None = None) -> dict:
        existing = self.one("SELECT id FROM categories WHERE twitch_id=?", (twitch_id,))
        if existing:
            return self.get_category(existing["id"])
        cur = self.execute(
            "INSERT INTO categories(twitch_id, name, box_art_url, settings, created_at) VALUES(?,?,?,?,?)",
            (twitch_id, name, box_art_url, (settings or CategorySettings()).model_dump_json(), iso(utcnow())),
        )
        return self.get_category(cur.lastrowid)

    def update_category(self, category_id: int, *, enabled: bool | None = None,
                        settings: CategorySettings | None = None) -> dict | None:
        if enabled is not None:
            self.execute("UPDATE categories SET enabled=? WHERE id=?", (int(enabled), category_id))
        if settings is not None:
            self.execute("UPDATE categories SET settings=? WHERE id=?", (settings.model_dump_json(), category_id))
        return self.get_category(category_id)

    def delete_category(self, category_id: int) -> None:
        self.execute("DELETE FROM categories WHERE id=?", (category_id,))

    def mark_fetched(self, category_id: int, when: datetime | None = None) -> None:
        self.execute("UPDATE categories SET last_fetch_at=? WHERE id=?", (iso(when or utcnow()), category_id))

    # ------------------------------------------------------------------ clips (dedupe)
    def has_clip(self, clip_id: str) -> bool:
        return self.one("SELECT 1 AS x FROM clips WHERE id=?", (clip_id,)) is not None

    def near_duplicate(self, clip: ClipInfo, window_seconds: int = 25) -> str | None:
        """Another clip of the same moment (same VOD, overlapping offset)."""
        if not clip.video_id or clip.vod_offset is None:
            return None
        row = self.one(
            "SELECT id FROM clips WHERE video_id=? AND id<>? AND vod_offset IS NOT NULL "
            "AND ABS(vod_offset - ?) < ? LIMIT 1",
            (clip.video_id, clip.id, clip.vod_offset, window_seconds),
        )
        return row["id"] if row else None

    def insert_clip(self, clip: ClipInfo, category_id: int | None, score: float = 0.0,
                    detail: dict | None = None, status: str = "new", skip_reason: str = "") -> bool:
        """Insert a newly discovered clip. Returns False if it was seen before."""
        cur = self.execute(
            "INSERT OR IGNORE INTO clips(id, category_id, data, broadcaster_login, broadcaster_name, view_count, "
            "created_at, duration, video_id, vod_offset, fetched_at, score, score_detail, status, skip_reason) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (clip.id, category_id, clip.model_dump_json(), clip.broadcaster_login, clip.broadcaster_name,
             clip.view_count, iso(clip.created_at), clip.duration, clip.video_id, clip.vod_offset,
             iso(utcnow()), score, json.dumps(detail or {}), status, skip_reason),
        )
        return cur.rowcount > 0

    def update_clip(self, clip_id: str, **fields: Any) -> None:
        if "score_detail" in fields:
            fields["score_detail"] = json.dumps(fields["score_detail"])
        if "data" in fields and isinstance(fields["data"], ClipInfo):
            fields["data"] = fields["data"].model_dump_json()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE clips SET {cols} WHERE id=?", (*fields.values(), clip_id))

    def get_clip(self, clip_id: str) -> dict | None:
        row = self.one("SELECT * FROM clips WHERE id=?", (clip_id,))
        if row:
            row["clip"] = ClipInfo.model_validate_json(row.pop("data"))
            row["score_detail"] = json.loads(row["score_detail"] or "{}")
        return row

    def candidate_clips(self, limit: int = 200) -> list[dict]:
        rows = self.query("SELECT * FROM clips WHERE status='new' ORDER BY score DESC LIMIT ?", (limit,))
        for row in rows:
            row["clip"] = ClipInfo.model_validate_json(row.pop("data"))
            row["score_detail"] = json.loads(row["score_detail"] or "{}")
        return rows

    def clip_counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self.query("SELECT status, COUNT(*) AS n FROM clips GROUP BY status")}

    # ------------------------------------------------------------------ items
    def _item(self, row: dict | None) -> dict | None:
        if not row:
            return None
        for key in ITEM_JSON_FIELDS:
            row[key] = json.loads(row[key] or ("[]" if key != "analysis" else "{}"))
        row["needs_rerender"] = bool(row["needs_rerender"])
        row["posted_manually"] = bool(row.get("posted_manually"))
        return row

    def create_item(self, clip_id: str, category_id: int | None, *, mode: str, streamer: str = "",
                    streamer_login: str = "", category_name: str = "", status: str = "processing") -> dict:
        now = iso(utcnow())
        cur = self.execute(
            "INSERT INTO items(clip_id, category_id, category_name, streamer, streamer_login, status, mode, "
            "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (clip_id, category_id, category_name, streamer, streamer_login, status, mode, now, now),
        )
        return self.get_item(cur.lastrowid)

    def get_item(self, item_id: int) -> dict | None:
        return self._item(self.one("SELECT * FROM items WHERE id=?", (item_id,)))

    def get_item_by_clip(self, clip_id: str) -> dict | None:
        return self._item(self.one("SELECT * FROM items WHERE clip_id=?", (clip_id,)))

    def update_item(self, item_id: int, **fields: Any) -> dict | None:
        for key in ITEM_JSON_FIELDS & fields.keys():
            fields[key] = json.dumps(fields[key], ensure_ascii=False)
        for key, value in list(fields.items()):
            if isinstance(value, datetime):
                fields[key] = iso(value)
            elif isinstance(value, bool):
                fields[key] = int(value)
        fields["updated_at"] = iso(utcnow())
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE items SET {cols} WHERE id=?", (*fields.values(), item_id))
        return self.get_item(item_id)

    def delete_item(self, item_id: int) -> None:
        self.execute("DELETE FROM stats WHERE item_id=?", (item_id,))
        self.execute("DELETE FROM items WHERE id=?", (item_id,))

    def list_items(self, statuses: Iterable[str] | None = None, limit: int = 200, offset: int = 0,
                   order: str = "created_at DESC") -> list[dict]:
        sql, params = "SELECT * FROM items", []
        if statuses:
            statuses = list(statuses)
            sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
            params += statuses
        sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
        return [self._item(r) for r in self.query(sql, (*params, limit, offset))]

    def item_counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self.query("SELECT status, COUNT(*) AS n FROM items GROUP BY status")}

    def count_items(self, *, statuses: Iterable[str] | None = None, category_id: int | None = None,
                    since: datetime | None = None, uploaded_since: datetime | None = None,
                    mode: str | None = None) -> int:
        sql, params = "SELECT COUNT(*) AS n FROM items WHERE 1=1", []
        if statuses:
            statuses = list(statuses)
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            params += statuses
        if category_id is not None:
            sql += " AND category_id=?"
            params.append(category_id)
        if since is not None:
            sql += " AND created_at>=?"
            params.append(iso(since))
        if uploaded_since is not None:
            sql += " AND uploaded_at>=?"
            params.append(iso(uploaded_since))
        if mode is not None:
            sql += " AND mode=?"
            params.append(mode)
        return int(self.one(sql, params)["n"])

    def last_upload_at(self, mode: str | None = None) -> datetime | None:
        sql = "SELECT MAX(uploaded_at) AS t FROM items WHERE uploaded_at IS NOT NULL"
        params: list = []
        if mode:
            sql += " AND mode=?"
            params.append(mode)
        return parse_dt(self.one(sql, params)["t"])

    def recent_uploads(self, limit: int = 30) -> list[dict]:
        return self.list_items(["uploaded"], limit=limit, order="uploaded_at DESC")

    def reset_stuck_items(self) -> int:
        """After a crash/restart, items mid-processing go back to the pool."""
        rows = self.query("SELECT id, clip_id, status, approved_at FROM items WHERE status IN ('processing', 'uploading')")
        for row in rows:
            if row["status"] == "processing":
                self.execute("UPDATE clips SET status='new' WHERE id=?", (row["clip_id"],))
                self.delete_item(row["id"])
            else:
                self.update_item(row["id"], status="approved" if row.get("approved_at") else "ready")
        return len(rows)

    # ------------------------------------------------------------------ stats
    def add_stats(self, item_id: int, *, views: int, likes: int = 0, comments: int = 0,
                  avg_view_pct: float | None = None, avg_view_duration: float | None = None,
                  hours_since_upload: float = 0.0, when: datetime | None = None) -> None:
        self.execute(
            "INSERT OR REPLACE INTO stats(item_id, fetched_at, hours_since_upload, views, likes, comments, "
            "avg_view_pct, avg_view_duration) VALUES(?,?,?,?,?,?,?,?)",
            (item_id, iso(when or utcnow()), hours_since_upload, views, likes, comments, avg_view_pct,
             avg_view_duration),
        )

    def latest_stats(self) -> dict[int, dict]:
        rows = self.query(
            "SELECT s.* FROM stats s JOIN (SELECT item_id, MAX(fetched_at) AS m FROM stats GROUP BY item_id) x "
            "ON s.item_id=x.item_id AND s.fetched_at=x.m"
        )
        return {r["item_id"]: r for r in rows}

    def stats_for(self, item_id: int) -> list[dict]:
        return self.query("SELECT * FROM stats WHERE item_id=? ORDER BY fetched_at", (item_id,))

    def uploads_with_stats(self, since_days: int = 90) -> list[dict]:
        since = iso(utcnow() - timedelta(days=since_days))
        items = self.query("SELECT * FROM items WHERE status='uploaded' AND uploaded_at>=? ORDER BY uploaded_at DESC",
                           (since,))
        latest = self.latest_stats()
        out = []
        for row in items:
            row = self._item(row)
            row["stats"] = latest.get(row["id"])
            out.append(row)
        return out

    def daily_activity(self, days: int, tz) -> list[dict]:
        """Per local day, oldest first: Shorts made, Shorts uploaded and the views they've had since."""
        today = utcnow().astimezone(tz).date()
        start_day = today - timedelta(days=days - 1)
        start = iso(datetime.combine(start_day, datetime.min.time(), tzinfo=tz))
        out = {start_day + timedelta(days=i): {"made": 0, "uploaded": 0, "views": 0} for i in range(days)}
        local = lambda v: parse_dt(v).astimezone(tz).date()  # noqa: E731
        for row in self.query("SELECT created_at FROM items WHERE created_at>=? AND status NOT IN "
                              "('failed', 'processing')", (start,)):
            day = local(row["created_at"])
            if day in out:
                out[day]["made"] += 1
        latest = self.latest_stats()
        for row in self.query("SELECT id, uploaded_at FROM items WHERE uploaded_at>=?", (start,)):
            day = local(row["uploaded_at"])
            if day in out:
                out[day]["uploaded"] += 1
                out[day]["views"] += int((latest.get(row["id"]) or {}).get("views") or 0)
        return [{"day": d.isoformat(), **v} for d, v in out.items()]

    # ------------------------------------------------------------------ quota
    def add_quota(self, day: str, units: int) -> int:
        self.execute("INSERT INTO quota(day, units) VALUES(?, ?) ON CONFLICT(day) DO UPDATE SET units=units+?",
                     (day, units, units))
        return self.quota_used(day)

    def quota_used(self, day: str) -> int:
        row = self.one("SELECT units FROM quota WHERE day=?", (day,))
        return int(row["units"]) if row else 0
