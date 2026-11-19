"""The background engine behind the Start/Stop button.

Two single-thread workers keep the dashboard responsive:
* ``net``:    fetch clips from Twitch, upload to YouTube, refresh analytics
* ``render``: download, transcribe and render the next best clip

Nothing runs while stopped. Manual-mode clips wait in the review queue
until approved; auto-mode clips upload on the schedule.
"""

from __future__ import annotations

import asyncio
import random
import re
import shutil
import threading
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Callable

from . import config
from .db import Database, iso, parse_dt, utcnow
from .keystore import KeyStore
from .logs import get_logger
from .models import CategorySettings, ClipInfo, GlobalSettings
from .optimizer import learning, ranking, similarity, timing
from .pipeline import metadata, runner
from .pipeline.transcribe import Transcriber, WhisperTranscriber
from .services import ai
from .services.quota import QuotaTracker
from .services.twitch import TwitchClient, TwitchError
from .services.instagram import InstagramAuthError, InstagramClient, InstagramError, build_caption
from .services.youtube import AuthError, QuotaExceeded, UploadRequest, YouTubeClient, YouTubeError

log = get_logger("engine")

PRODUCED_STATUSES = ("processing", "review", "ready", "approved", "uploading", "uploaded")
MAX_UPLOAD_ATTEMPTS = 5
STATS_REFRESH_HOURS = 6
KEEP_VIDEOS_DAYS = 14


def local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)[:80] or "clip"


class EngineError(RuntimeError):
    pass


class Engine:
    def __init__(self, db: Database, store: KeyStore, *,
                 twitch_factory: Callable[[], TwitchClient] | None = None,
                 youtube_factory: Callable[[], YouTubeClient] | None = None,
                 transcriber_factory: Callable[[GlobalSettings], Transcriber] | None = None,
                 instagram_factory: Callable[[], InstagramClient] | None = None,
                 clock: Callable[[], datetime] = utcnow, tz: tzinfo | None = None,
                 work_root: Path | None = None) -> None:
        self.db = db
        self.store = store
        self.clock = clock
        self.tz = tz or local_tz()
        self.quota = QuotaTracker(db, clock=clock)
        self.work_root = work_root or config.work_dir()
        self._twitch_factory = twitch_factory or (lambda: TwitchClient.from_keystore(self.store))
        self._youtube_factory = youtube_factory or (lambda: YouTubeClient.from_keystore(self.store, quota=self.quota))
        self._instagram_factory = instagram_factory or (lambda: InstagramClient(self.store.get("instagram_access_token")))
        self.instagram_problem = ""
        self.tier_of: Callable[[], str] = lambda: "pro"  # set by the app from the licence: "free" adds the watermark
        self._transcriber_factory = transcriber_factory or self._default_transcriber
        self._transcriber: tuple[tuple, Transcriber] | None = None
        self.running = False
        self.activity = {"net": "idle", "render": "idle"}
        self.last_error = ""
        self.auth_problem = ""
        self.upload_progress: dict[int, float] = {}
        self._pools = {"net": ThreadPoolExecutor(1, "clipped-net"), "render": ThreadPoolExecutor(1, "clipped-render")}
        self._futures: dict[str, Future | None] = {"net": None, "render": None}
        self._loop_task: asyncio.Task | None = None
        self._lock = threading.RLock()
        self._rerenders_queued: set[int] = set()  # one waiting re-render per item
        self.tick_seconds = 10.0
        self.rng = random.Random()

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self.running = True
            self.db.set_value("engine_running", True)
        log.info("Engine started")
        self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        with self._lock:
            self.running = False
            self.db.set_value("engine_running", False)
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None
        log.info("Engine stopped (work already in progress will finish)")

    async def _loop(self) -> None:
        while self.running:
            try:
                self.tick()
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("Engine tick failed: %s", exc)
            await asyncio.sleep(self.tick_seconds)

    def tick(self) -> None:
        """Hand the next unit of work to each idle worker."""
        self._submit("net", self.network_step)
        self._submit("render", self.render_step)

    def _submit(self, pool: str, fn: Callable, *args) -> Future | None:
        with self._lock:
            fut = self._futures.get(pool)
            if fut is not None and not fut.done():
                return None
            self._futures[pool] = self._pools[pool].submit(self._guard, pool, fn, *args)
            return self._futures[pool]

    def run_now(self, pool: str, fn: Callable, *args) -> Future:
        """Queue a user-triggered job (runs after the current job on that worker)."""
        return self._pools[pool].submit(self._guard, pool, fn, *args)

    def _guard(self, pool: str, fn: Callable, *args):
        try:
            return fn(*args)
        except Exception as exc:
            self.last_error = str(exc)
            log.exception("%s worker error: %s", pool, exc)
            raise
        finally:
            self.activity[pool] = "idle"

    def shutdown(self) -> None:
        self.running = False
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ helpers
    def settings(self) -> GlobalSettings:
        return self.db.get_global_settings()

    def effective_mode(self, category: dict | None, gs: GlobalSettings) -> str:
        if category:
            mode = category["settings"].get("mode", "inherit")
            if mode in ("manual", "auto"):
                return mode
        return gs.mode

    def is_approved_streamer(self, login: str, name: str, category: dict | None, gs: GlobalSettings) -> bool:
        allowed = set(gs.approved_streamers)
        if category:
            allowed |= set(category["settings"].get("allowlist", []))
        return login.lower() in allowed or name.lower() in allowed

    def _default_transcriber(self, gs: GlobalSettings) -> Transcriber:
        key = (gs.whisper.model_size, gs.whisper.device, gs.whisper.compute_type)
        if not self._transcriber or self._transcriber[0] != key:
            self._transcriber = (key, WhisperTranscriber(*key, download_root=config.models_dir()))
        return self._transcriber[1]

    def workdir_for(self, clip_id: str) -> Path:
        return self.work_root / safe_name(clip_id)

    def twitch_ready(self) -> bool:
        return bool(self.store.get("twitch_client_id") and self.store.get("twitch_client_secret"))

    def youtube_ready(self) -> bool:
        return bool(self.store.get("youtube_refresh_token") and self.store.get("google_client_id")
                    and self.store.get("google_client_secret")) and not self.auth_problem

    def instagram_ready(self, gs: GlobalSettings | None = None) -> bool:
        gs = gs or self.settings()
        return bool(gs.instagram.enabled and self.store.get("instagram_access_token")
                    and self.db.get_value("instagram_user_id")) and not self.instagram_problem

    def publish_ready(self) -> bool:
        """Somewhere to post: YouTube, Instagram or both. Without either, Shorts are downloaded by hand."""
        return self.youtube_ready() or self.instagram_ready()

    def recent_for_diversity(self, window: int) -> list[dict]:
        rows = self.db.list_items(["uploaded"], limit=window, order="uploaded_at DESC")
        pending = self.db.list_items(["approved", "ready", "uploading"], limit=window)
        return [{"streamer": r["streamer_login"] or r["streamer"], "category_id": r["category_id"]}
                for r in pending + rows]

    def uploads_on_day(self, t: datetime) -> int:
        local = t.astimezone(self.tz)
        start = datetime.combine(local.date(), datetime.min.time(), tzinfo=self.tz).astimezone(timezone.utc)
        end = start + timedelta(days=1)
        row = self.db.one("SELECT COUNT(*) AS n FROM items WHERE uploaded_at>=? AND uploaded_at<?", (iso(start), iso(end)))
        return int(row["n"])

    # ------------------------------------------------------------------ network worker
    def network_step(self) -> None:
        self.fetch_due()
        self.refresh_instagram_token_due()
        self.upload_due()
        self.refresh_stats_due()

    def fetch_due(self, force_category: int | None = None) -> int:
        if not self.twitch_ready():
            return 0
        gs = self.settings()
        now = self.clock()
        added = 0
        categories = self.db.list_categories(enabled_only=force_category is None)
        due = []
        for cat in categories:
            if force_category is not None and cat["id"] != force_category:
                continue
            last = parse_dt(cat["last_fetch_at"])
            if force_category is not None or not last or now - last >= timedelta(minutes=gs.schedule.fetch_interval_minutes):
                due.append(cat)
        if not due:
            return 0
        try:
            twitch = self._twitch_factory()
        except TwitchError as exc:
            self.last_error = str(exc)
            log.error("Twitch: %s", exc)
            return 0
        try:
            for cat in due:
                self.activity["net"] = f"Fetching clips: {cat['name']}"
                added += self._fetch_category(twitch, cat, gs, now)
        finally:
            twitch.close()
        return added

    def _fetch_category(self, twitch: TwitchClient, cat: dict, gs: GlobalSettings, now: datetime) -> int:
        cs = CategorySettings.model_validate(cat["settings"])
        mode = ranking.discovery_mode(cs, gs.selection)
        hours = ranking.window_hours(mode, gs.selection)
        try:
            # Helix returns the most-viewed clips created inside the window.
            clips = twitch.get_clips(cat["twitch_id"], now - timedelta(hours=hours), now,
                                     max_clips=100, game_name=cat["name"])
        except TwitchError as exc:
            log.error("Fetching %s failed: %s", cat["name"], exc)
            self.last_error = str(exc)
            return 0
        new = skipped = refreshed = 0
        reasons: Counter[str] = Counter()
        for clip in clips:
            existing = self.db.get_clip(clip.id)
            if existing:
                # Never process the same clip twice, but keep queued candidates'
                # view counts current so "trending" reflects what is rising now.
                refreshed += self._refresh_candidate(existing, clip, cs, gs, mode, now)
                continue
            ok, reason = ranking.eligible(clip, cs, gs.selection, now)
            dup = self.db.near_duplicate(clip) if ok else None
            if dup:
                ok, reason = False, f"same moment as clip {dup}"
            score, detail = ranking.pre_score(clip, gs.selection, now, mode)
            detail["seen_at"] = iso(now)
            if self.db.insert_clip(clip, cat["id"], score, detail, "new" if ok else "skipped", reason):
                new += ok
                skipped += not ok
                if not ok:
                    reasons[ranking.reason_group(reason, cs)] += 1
        self.db.mark_fetched(cat["id"], now)
        why = f" ({', '.join(f'{n} {label}' for label, n in reasons.most_common(3))})" if reasons else ""
        log.info("%s (%s, last %gh): %d new clip(s), %d filtered out%s, %d updated", cat["name"],
                 ranking.DISCOVERY_LABELS[mode], hours, new, skipped, why, refreshed)
        return new

    def _refresh_candidate(self, row: dict, clip: ClipInfo, cs: CategorySettings, gs: GlobalSettings,
                           mode: str, now: datetime) -> int:
        status = row["status"]
        # A clip skipped only for having too few views gets another chance as it grows.
        retry = status == "skipped" and row["skip_reason"].startswith("only ")
        if status != "new" and not retry:
            return 0
        old: ClipInfo = row["clip"]
        detail = row["score_detail"] or {}
        seen_at = parse_dt(detail.get("seen_at") or row["fetched_at"])
        recent = ranking.recent_velocity(old.view_count, seen_at, clip.view_count, now)
        if recent is None:
            recent = detail.get("recent_velocity")
            seen_at_out = detail.get("seen_at") or row["fetched_at"]
        else:
            seen_at_out = iso(now)
        clip.game_name = clip.game_name or old.game_name
        clip.broadcaster_login = clip.broadcaster_login or old.broadcaster_login
        score, new_detail = ranking.pre_score(clip, gs.selection, now, mode, recent)
        new_detail["seen_at"] = seen_at_out
        fields: dict = {"data": clip, "view_count": clip.view_count, "score": score, "score_detail": new_detail}
        if retry:
            ok, reason = ranking.eligible(clip, cs, gs.selection, now)
            if ok and self.db.near_duplicate(clip):
                ok = False
            if not ok:
                if reason == row["skip_reason"]:
                    fields = {"data": clip, "view_count": clip.view_count, "score_detail": new_detail}
                else:
                    fields.update(skip_reason=reason)
            else:
                fields.update(status="new", skip_reason="")
        self.db.update_clip(clip.id, **fields)
        return 1

    # ------------------------------------------------------------------ uploads
    def upload_candidates(self) -> tuple[list[dict], list[dict]]:
        now_iso = iso(self.clock())
        approved = [i for i in self.db.list_items(["approved"], order="approved_at ASC")
                    if not i["next_attempt_at"] or i["next_attempt_at"] <= now_iso]
        ready = [i for i in self.db.list_items(["ready"], order="score DESC")
                 if not i["next_attempt_at"] or i["next_attempt_at"] <= now_iso]
        return approved, ready

    def _category_upload_limit_reached(self, category_id: int | None) -> bool:
        """Has this category had its automatic uploads for the last 24 hours?
        (Clips you approved yourself are never held back by it.)"""
        if category_id is None:
            return False
        cat = self.db.get_category(category_id)
        if not cat:
            return False
        limit = CategorySettings.model_validate(cat["settings"]).max_clips_per_day
        done = self.db.count_items(category_id=category_id, statuses=["uploaded", "uploading"],
                                   uploaded_since=self.clock() - timedelta(hours=24))
        return done >= limit

    def next_upload(self, gs: GlobalSettings | None = None) -> dict | None:
        """The next scheduled upload (item + slot), for the countdown and the worker."""
        gs = gs or self.settings()
        approved, ready = self.upload_candidates()
        if approved:
            item, kind = approved[0], "manual"
        elif ready := [i for i in ready if not self._category_upload_limit_reached(i["category_id"])]:
            window = gs.optimizer.diversity_window
            recent = self.recent_for_diversity(window)
            item = max(ready, key=lambda i: i["score"] * learning.diversity_factor(
                i["streamer_login"] or i["streamer"], i["category_id"], recent, window=window,
                penalty=gs.optimizer.diversity_penalty))
            kind = "auto"
        else:
            return None
        hours = None
        if kind == "auto" and gs.optimizer.enabled:
            hours = learning.hour_scores(self.db.uploads_with_stats(), self.tz,
                                         min_samples=gs.optimizer.min_samples_for_timing, now=self.clock())
        slot = timing.next_slot(
            self.clock(), kind=kind, schedule=gs.schedule, tz=self.tz,
            last_any=self.db.last_upload_at(), last_auto=self.db.last_upload_at("auto"),
            uploads_on_day=self.uploads_on_day, hour_scores=hours, optimizer=gs.optimizer,
        )
        quota_pause = self.db.get_value("quota_paused_until")
        if quota_pause and parse_dt(quota_pause) > slot.at:
            slot = timing.Slot(parse_dt(quota_pause), "YouTube quota exhausted until the daily reset")
        return {"item": item, "kind": kind, "at": slot.at, "reason": slot.reason}

    def upload_due(self) -> dict | None:
        if not self.publish_ready():
            return None
        nxt = self.next_upload()
        if not nxt or nxt["at"] > self.clock():
            return None
        return self.upload_item(nxt["item"]["id"])

    def check_manual_upload(self) -> None:
        """Upload now is the user's own call, so clipped's pacing (the daily cap and the
        minimum gap) doesn't apply; those only space out scheduled uploads. YouTube's
        quota still does, because YouTube enforces it whatever we do."""
        if not self.publish_ready():
            raise EngineError("Connect YouTube or Instagram first, or download the Short and post it yourself.")
        if self.youtube_ready() and not self.instagram_ready() and not self.quota.can_spend("videos.insert"):
            reset = self.quota.reset_at().astimezone(self.tz).strftime("%H:%M")
            raise EngineError(f"YouTube's upload quota for today is used up. It resets at {reset}.")

    def upload_item(self, item_id: int) -> dict | None:
        """Post an approved Short to every connected platform (YouTube, Instagram or both)."""
        gs = self.settings()
        item = self.db.get_item(item_id)
        if not item or item["status"] not in ("approved", "ready"):
            raise EngineError("Only approved or ready clips can be uploaded")
        to_youtube = self.youtube_ready() and not item["youtube_id"]
        to_instagram = self.instagram_ready(gs) and not item["instagram_id"]
        if not to_youtube and not to_instagram:
            raise EngineError("Connect YouTube or Instagram first, or download the Short from Review and post it yourself.")
        if item["needs_rerender"] or ((item.get("analysis") or {}).get("watermarked") and self.tier_of() != "free"):
            self.rerender_item(item_id)  # also drops a free-plan watermark once you're on Pro
            item = self.db.get_item(item_id)
        if to_youtube and not self.quota.can_spend("videos.insert"):
            self.db.set_value("quota_paused_until", iso(self.quota.reset_at()))
            log.warning("YouTube quota for today is used up; uploads resume after %s", self.quota.reset_at())
            if not to_instagram:
                return None
            to_youtube = False  # Instagram can still go now; YouTube follows after the reset
        clip_row = self.db.get_clip(item["clip_id"])
        clip = clip_row["clip"] if clip_row else ClipInfo(id=item["clip_id"], broadcaster_name=item["streamer"])
        title, description = metadata.ensure_credit(item["title"], item["description"], clip,
                                                    gs.metadata.credit_in_title)
        previous = item["status"]
        self.db.update_item(item_id, status="uploading", title=title, description=description)
        self.activity["net"] = f"Uploading: {title[:60]}"
        self.upload_progress[item_id] = 0.0
        result = None
        try:
            if to_youtube:
                result = self._upload_youtube(item, gs, clip, title, description, previous)
                if result is None and not to_instagram:
                    return None  # already put back with a retry time or marked failed
            reel, ig_error = None, ""
            if to_instagram:
                reel, ig_error = self._upload_instagram(item, gs, title, description)
                if reel is None and result is None:
                    self._retry_later(item, previous, ig_error)
                    return None
        finally:
            self.upload_progress.pop(item_id, None)

        now = self.clock()
        fields = {"status": "uploaded", "uploaded_at": now, "next_attempt_at": None}
        warnings = list(result.warnings) if result else []
        if result:
            fields.update(youtube_id=result.video_id, privacy_requested=gs.youtube.privacy_status,
                          privacy_actual=result.privacy_status)
            self.db.set_value("quota_paused_until", None)
            log.info("Published %s (%s)", result.url, result.privacy_status)
        if reel:
            fields.update(instagram_id=reel.media_id, instagram_url=reel.permalink)
            log.info("Posted to Instagram: %s", reel.permalink or reel.media_id)
        if ig_error:
            warnings.append(f"Instagram: {ig_error}")
        fields["error"] = "; ".join(warnings)
        self.db.update_item(item_id, **fields)
        for warning in warnings:
            log.warning("%s", warning)
        if item["workdir"]:
            for path in Path(item["workdir"]).glob("source.*"):
                path.unlink(missing_ok=True)  # keep the rendered Short, drop the original download
        return {"youtube_id": result.video_id if result else "", "url": result.url if result else "",
                "privacy": result.privacy_status if result else "", "warnings": warnings,
                "instagram_id": reel.media_id if reel else "", "instagram_url": reel.permalink if reel else ""}

    def _retry_later(self, item: dict, previous: str, error: str, permanent: bool = False) -> None:
        attempts = item["attempts"] + 1
        if permanent or attempts >= MAX_UPLOAD_ATTEMPTS:
            self.db.update_item(item["id"], status="failed", error=error, attempts=attempts)
            log.error("Upload failed permanently: %s", error)
        else:
            retry_at = self.clock() + timedelta(minutes=5 * 2 ** (attempts - 1))
            self.db.update_item(item["id"], status=previous, error=error, attempts=attempts, next_attempt_at=retry_at)
            log.warning("Upload failed (%s); retrying at %s", error, retry_at.astimezone(self.tz).strftime("%H:%M"))

    def _upload_youtube(self, item: dict, gs: GlobalSettings, clip: ClipInfo, title: str, description: str,
                        previous: str):
        item_id = item["id"]
        try:
            yt = self._youtube_factory()
            try:
                return yt.upload(UploadRequest(
                    video_path=Path(item["video_path"]), title=title, description=description, tags=item["tags"],
                    privacy_status=gs.youtube.privacy_status, made_for_kids=gs.youtube.made_for_kids,
                    category_id=gs.youtube.category_id,
                    thumbnail_path=Path(item["thumbnail_path"]) if gs.youtube.set_thumbnail and item["thumbnail_path"] else None,
                    contains_synthetic_media=gs.youtube.contains_synthetic_media,
                    default_language=(clip.language or "")[:2],
                ), progress=lambda p: self.upload_progress.__setitem__(item_id, p * 0.5 if self.instagram_ready() else p))
            finally:
                yt.close()
        except QuotaExceeded as exc:
            self.db.update_item(item_id, status=previous)
            self.db.set_value("quota_paused_until", iso(self.quota.reset_at()))
            log.warning("%s - uploads paused until the quota resets (%s)", exc, self.quota.reset_at())
        except AuthError as exc:
            self.db.update_item(item_id, status=previous)
            self.auth_problem = str(exc)
            log.error("YouTube auth problem: %s", exc)
        except (YouTubeError, OSError) as exc:
            self._retry_later(item, previous, str(exc),
                              permanent=isinstance(exc, YouTubeError) and exc.status in (400, 403, 404))
        return None

    def _upload_instagram(self, item: dict, gs: GlobalSettings, title: str, description: str):
        """(reel, error). An auth problem stops Instagram posting until a new token is saved."""
        item_id = item["id"]
        offset = (item.get("analysis") or {}).get("thumbnail_at")
        try:
            ig = self._instagram_factory()
            try:
                reel = ig.publish_reel(
                    str(self.db.get_value("instagram_user_id")), Path(item["video_path"]), build_caption(title, description),
                    share_to_feed=gs.instagram.share_to_feed, thumb_offset_ms=int(offset * 1000) if offset else None,
                    progress=lambda p: self.upload_progress.__setitem__(item_id, 0.5 + p * 0.5 if self.youtube_ready() else p))
            finally:
                ig.close()
            return reel, ""
        except InstagramAuthError as exc:
            self.instagram_problem = str(exc)
            log.error("Instagram: %s", exc)
            return None, str(exc)
        except (InstagramError, OSError) as exc:
            return None, str(exc)

    def refresh_instagram_token_due(self) -> None:
        """Long-lived Instagram tokens last 60 days; swap for a fresh one when under 20 are left."""
        token = self.store.get("instagram_access_token")
        if not token:
            return
        expires = parse_dt(self.db.get_value("instagram_token_expires_at"))
        checked = parse_dt(self.db.get_value("instagram_token_checked_at"))
        now = self.clock()
        if checked and now - checked < timedelta(hours=24):
            return
        self.db.set_value("instagram_token_checked_at", iso(now))
        if expires and expires - now > timedelta(days=20):
            return
        try:
            ig = InstagramClient(token)
            try:
                fresh, seconds = ig.refresh()
            finally:
                ig.close()
        except InstagramAuthError as exc:
            self.instagram_problem = str(exc)
            log.error("Instagram: %s", exc)
            return
        except InstagramError as exc:
            log.warning("Couldn't refresh the Instagram token yet (%s); trying again tomorrow", exc)
            return
        self.store.set("instagram_access_token", fresh)
        if seconds:
            self.db.set_value("instagram_token_expires_at", iso(now + timedelta(seconds=seconds)))
        log.info("Refreshed the Instagram access token")

    def mark_posted(self, item_id: int) -> dict:
        """The user downloaded the Short and posted it themselves."""
        item = self.db.get_item(item_id)
        if not item or item["status"] not in ("review", "approved", "ready", "failed"):
            raise EngineError("Only Shorts waiting to go up can be marked as posted")
        log.info("Marked “%s” as posted by hand", item["title"][:60])
        return self.db.update_item(item_id, status="uploaded", uploaded_at=self.clock(), posted_manually=True,
                                   approved_at=item["approved_at"] or self.clock(), error="", next_attempt_at=None)

    # ------------------------------------------------------------------ analytics
    def refresh_stats_due(self, force: bool = False) -> int:
        if not self.youtube_ready():
            return 0
        last = parse_dt(self.db.get_value("stats_refreshed_at"))
        if not force and last and self.clock() - last < timedelta(hours=STATS_REFRESH_HOURS):
            return 0
        uploads = [u for u in self.db.uploads_with_stats(since_days=30) if u["youtube_id"]]
        self.db.set_value("stats_refreshed_at", iso(self.clock()))
        self._cleanup_old_videos()
        if not uploads:
            return 0
        self.activity["net"] = "Refreshing YouTube stats"
        ids = [u["youtube_id"] for u in uploads]
        yt = self._youtube_factory()
        try:
            basic = yt.video_status(ids)
            retention: dict[str, dict] = {}
            try:
                first = min(parse_dt(u["uploaded_at"]) for u in uploads).astimezone(self.tz).date()
                retention = yt.analytics(ids, first, self.clock().astimezone(self.tz).date())
            except (YouTubeError, ValueError) as exc:
                log.warning("YouTube Analytics unavailable (%s) - is the YouTube Analytics API enabled?", exc)
        except QuotaExceeded as exc:
            log.warning("Skipping stats refresh: %s", exc)
            return 0
        except AuthError as exc:
            self.auth_problem = str(exc)
            return 0
        finally:
            yt.close()
        now = self.clock()
        for u in uploads:
            b = basic.get(u["youtube_id"])
            if not b:
                continue
            r = retention.get(u["youtube_id"], {})
            hours = (now - parse_dt(u["uploaded_at"])).total_seconds() / 3600
            self.db.add_stats(u["id"], views=b["views"], likes=b["likes"], comments=b["comments"],
                              avg_view_pct=r.get("avg_view_pct"), avg_view_duration=r.get("avg_view_duration"),
                              hours_since_upload=round(hours, 1), when=now)
            if b.get("privacyStatus") and b["privacyStatus"] != u["privacy_actual"]:
                self.db.update_item(u["id"], privacy_actual=b["privacyStatus"])
        log.info("Refreshed stats for %d upload(s)", len(uploads))
        return len(uploads)

    def _cleanup_old_videos(self) -> None:
        cutoff = iso(self.clock() - timedelta(days=KEEP_VIDEOS_DAYS))
        for row in self.db.query("SELECT id, workdir FROM items WHERE status IN ('uploaded','rejected') "
                                 "AND updated_at < ? AND workdir <> ''", (cutoff,)):
            shutil.rmtree(row["workdir"], ignore_errors=True)
            self.db.update_item(row["id"], workdir="", video_path="", thumbnail_path="")

    # ------------------------------------------------------------------ render worker
    def render_step(self) -> dict | None:
        gs = self.settings()
        cats = {c["id"]: c for c in self.db.list_categories(enabled_only=True)}
        if not cats:
            return None
        pending_review = self.db.count_items(statuses=["review"])
        pending_ready = self.db.count_items(statuses=["ready", "approved"])
        since = self.clock() - timedelta(hours=24)
        now = self.clock()
        window = gs.optimizer.diversity_window
        recent = self.recent_for_diversity(window)
        best, best_score = None, -1.0
        for row in self.db.candidate_clips(limit=300):
            cat = cats.get(row["category_id"])
            if not cat:
                continue
            cs = CategorySettings.model_validate(cat["settings"])
            clip: ClipInfo = row["clip"]
            disc = ranking.discovery_mode(cs, gs.selection)
            if clip.age_hours(now) > ranking.expiry_hours(disc, gs.selection):
                self.db.update_clip(clip.id, status="skipped",
                                    skip_reason=f"no longer {ranking.DISCOVERY_LABELS[disc]}")
                continue
            # Re-score live: a trending clip's views/hour falls as it ages, so a
            # score computed at fetch time goes stale.
            row["score"], _ = ranking.pre_score(clip, gs.selection, now, disc,
                                                (row["score_detail"] or {}).get("recent_velocity"))
            mode = self.effective_mode(cat, gs)
            # Manual mode keeps the review queue topped up; the per-category daily
            # limit is about uploads, so it doesn't stop clips being rendered for you
            # to choose from.
            if mode == "manual" and pending_review >= gs.schedule.review_queue_size:
                continue
            if mode == "auto":
                if pending_ready >= gs.schedule.render_ahead:
                    continue
                # Auto renders are headed for upload: stop once the category has
                # produced today's allowance. Failed or rejected clips don't count.
                if self.db.count_items(category_id=cat["id"], since=since,
                                       statuses=PRODUCED_STATUSES) >= cs.max_clips_per_day:
                    continue
            factor = learning.diversity_factor(clip.broadcaster_login or clip.broadcaster_name, cat["id"], recent,
                                               window=window, penalty=gs.optimizer.diversity_penalty)
            if row["score"] * factor > best_score:
                best, best_score = (row, cat), row["score"] * factor
        if not best:
            return None
        row, cat = best
        return self.process_clip_row(row, cat, gs)

    def build_options(self, gs: GlobalSettings, cat: dict | None, styles: list[str]) -> runner.ProcessOptions:
        cs = CategorySettings.model_validate(cat["settings"]) if cat else CategorySettings()
        reframe = (cs.reframe or gs.reframe).model_copy()
        intro = cs.intro_path or gs.render.intro_path
        outro = cs.outro_path or gs.render.outro_path
        return runner.ProcessOptions(
            captions=gs.captions, reframe=reframe, hook=gs.hook, metadata=gs.metadata, render=gs.render,
            whisper=gs.whisper, selection=gs.selection, category_hashtags=cs.hashtags, keywords=cs.keywords,
            styles=styles, commentary=gs.commentary_default,
            intro=Path(intro) if intro and Path(intro).exists() else None,
            outro=Path(outro) if outro and Path(outro).exists() else None,
            api_keys=ai.credentials(self.store),
            watermark=self.tier_of() == "free",
            # read again just before titles are written, so a key saved mid-render counts
            title_settings=lambda: (self.settings().metadata, ai.credentials(self.store)),
        )

    def process_clip_row(self, row: dict, cat: dict | None, gs: GlobalSettings, force_manual: bool = False) -> dict | None:
        clip: ClipInfo = row["clip"]
        mode = "manual" if force_manual else self.effective_mode(cat, gs)
        note = ""
        if mode == "auto" and gs.approved_streamers_only and not self.is_approved_streamer(
                clip.broadcaster_login, clip.broadcaster_name, cat, gs):
            mode, note = "manual", "Sent to review: streamer is not on your approved list (Auto mode safety)"
        cs = CategorySettings.model_validate(cat["settings"]) if cat else CategorySettings()
        facecam = cs.facecams.get((clip.broadcaster_login or clip.broadcaster_name).lower())
        styles = learning.choose_styles(self.db.uploads_with_stats(), gs.metadata.variants,
                                        min_samples=gs.optimizer.min_samples_for_styles,
                                        explore_rate=gs.optimizer.explore_rate if gs.optimizer.enabled else 1.0,
                                        rng=self.rng, now=self.clock())
        opts = self.build_options(gs, cat, styles)
        if facecam:
            opts.reframe = opts.reframe.model_copy(update={"mode": "split", "facecam": facecam})
        item = self.db.create_item(clip.id, cat["id"] if cat else None, mode=mode, streamer=clip.broadcaster_name,
                                   streamer_login=clip.broadcaster_login, category_name=cat["name"] if cat else "")
        self.db.update_clip(clip.id, status="processing")
        workdir = self.workdir_for(clip.id)
        self.activity["render"] = f"Processing: {clip.broadcaster_name} - {clip.title[:50]}"
        log.info("Processing clip %s (%s, %s mode)", clip.id, clip.broadcaster_name, mode)

        recent = [{"title": u["title"], "text": u["analysis"].get("text", ""), "streamer": u["streamer"]}
                  for u in self.db.list_items(["uploaded", "approved", "ready", "review"], limit=gs.selection.recent_window)
                  if u["id"] != item["id"]]

        def gate(analysis: runner.Analysis) -> None:
            if analysis.info.duration > gs.selection.max_seconds + 0.5:
                raise runner.SkipClip(f"too long ({analysis.info.duration:.0f}s)")
            if analysis.audio.mean_db < gs.selection.min_mean_db:
                raise runner.SkipClip(f"too quiet ({analysis.audio.mean_db:.0f} dBFS)")
            score, match = similarity.most_similar(
                {"title": clip.title, "text": analysis.transcript.text, "streamer": clip.broadcaster_name}, recent)
            if match and score >= gs.selection.similarity_threshold:
                raise runner.SkipClip(f"too similar ({score:.0%}) to “{match['title'][:50]}”")

        who = clip.broadcaster_name or clip.id
        opts.stage = lambda text: self.activity.__setitem__("render", f"{text}: {who}")
        try:
            transcriber = self._transcriber_factory(gs)
            result = runner.process_clip(clip, workdir, transcriber, opts, gate=gate)
        except runner.SkipClip as exc:
            self.db.delete_item(item["id"])
            self.db.update_clip(clip.id, status="skipped", skip_reason=str(exc))
            shutil.rmtree(workdir, ignore_errors=True)
            log.info("Skipped %s: %s", clip.id, exc)
            return {"skipped": str(exc)}
        except Exception as exc:
            self.db.update_item(item["id"], status="failed", error=str(exc)[:2000], workdir=str(workdir))
            self.db.update_clip(clip.id, status="failed", skip_reason=str(exc)[:300])
            log.error("Processing %s failed: %s", clip.id, exc)
            return {"failed": str(exc)}

        v = result.variant
        summary = result.analysis.summary()
        summary["text"] = result.analysis.transcript.text[:1500]
        summary["plan"] = result.output.plan.to_dict()
        summary["notes"] = result.output.plan.notes + ([note] if note else [])
        summary["watermarked"] = opts.watermark
        score = ranking.final_score(row["score"], result.analysis.hype)
        status = "ready" if mode == "auto" else "review"
        updated = self.db.update_item(
            item["id"], status=status, mode=mode, workdir=str(workdir), video_path=str(result.output.video),
            thumbnail_path=str(result.output.thumbnail), duration=result.output.duration,
            hype=result.analysis.hype, score=score, analysis=summary,
            variants=[x.to_dict() for x in result.variants], chosen=result.chosen, title=v.title,
            description=v.description, tags=v.tags, hook_text=v.hook_text, thumbnail_text=v.hook_text or v.title,
            commentary=opts.commentary, title_style=v.style, error="",
        )
        self.db.update_clip(clip.id, status="processed")
        if note:
            log.info(note)
        log.info("Ready for %s: “%s”", "upload" if status == "ready" else "review", v.title)
        return updated

    # ------------------------------------------------------------------ user actions
    def add_clip_by_url(self, url: str, category_id: int | None) -> dict:
        from .pipeline.download import clip_id_from_url

        clip_id = clip_id_from_url(url)
        if not clip_id:
            raise EngineError("That doesn't look like a Twitch clip URL")
        if self.db.get_item_by_clip(clip_id):
            raise EngineError("This clip was already processed")
        cat = self.db.get_category(category_id) if category_id else None
        clip = ClipInfo(id=clip_id, url=url, game_name=cat["name"] if cat else "")
        if self.twitch_ready():
            try:
                tw = self._twitch_factory()
                data = tw._get("clips", {"id": clip_id}).get("data", [])
                if data:
                    from .services.twitch import clip_from_helix

                    clip = clip_from_helix(data[0], cat["name"] if cat else "")
                    users = tw.get_users([clip.broadcaster_id])
                    clip.broadcaster_login = users.get(clip.broadcaster_id, {}).get("login", "")
                tw.close()
            except TwitchError as exc:
                log.warning("Could not look up clip on Twitch (%s); yt-dlp metadata will be used", exc)
        self.db.insert_clip(clip, category_id, 1.0, {"manual": True})
        row = self.db.get_clip(clip_id)
        return row

    def process_manual_clip(self, clip_id: str) -> dict | None:
        row = self.db.get_clip(clip_id)
        cat = self.db.get_category(row["category_id"]) if row and row["category_id"] else None
        return self.process_clip_row(row, cat, self.settings(), force_manual=True)

    def queue_rerender(self, item_id: int, only_if_needed: bool = False) -> bool:
        """Queue a re-render on the render worker, at most one waiting per item.

        Clicking Re-render and then Approve, or clicking twice, must not render the
        same Short twice: on a busy worker those jobs used to pile up and run minutes
        later. ``only_if_needed`` (used by Approve) skips the work if, by the time the
        job runs, an earlier re-render already brought the video up to date.
        """
        with self._lock:
            if item_id in self._rerenders_queued:
                return False
            self._rerenders_queued.add(item_id)
        self.run_now("render", self._run_queued_rerender, item_id, only_if_needed)
        return True

    def _run_queued_rerender(self, item_id: int, only_if_needed: bool) -> dict | None:
        with self._lock:
            self._rerenders_queued.discard(item_id)  # edits made from here on may queue another
        item = self.db.get_item(item_id)
        if not item or item["status"] in ("uploading", "uploaded", "rejected"):
            return item
        if only_if_needed and not item["needs_rerender"]:
            return item
        return self.rerender_item(item_id)

    def rerender_item(self, item_id: int) -> dict:
        gs = self.settings()
        item = self.db.get_item(item_id)
        if not item:
            raise EngineError("Item not found")
        cat = self.db.get_category(item["category_id"]) if item["category_id"] else None
        clip_row = self.db.get_clip(item["clip_id"])
        clip = clip_row["clip"] if clip_row else ClipInfo(id=item["clip_id"])
        opts = self.build_options(gs, cat, [item["title_style"] or "hype"])
        cs = CategorySettings.model_validate(cat["settings"]) if cat else CategorySettings()
        facecam = cs.facecams.get((clip.broadcaster_login or clip.broadcaster_name).lower())
        if facecam:
            opts.reframe = opts.reframe.model_copy(update={"mode": "split", "facecam": facecam})
        opts.subtitles = item.get("analysis", {}).get("subtitles") is not False  # switched off in review
        opts.watermark = opts.watermark and item.get("analysis", {}).get("watermark") is not False  # removed after ads
        if item.get("analysis", {}).get("reframe_override"):
            from .models import ReframeSettings

            opts.reframe = ReframeSettings.model_validate(item["analysis"]["reframe_override"])
        self.activity["render"] = f"Re-rendering: {item['title'][:50]}"
        workdir = Path(item["workdir"]) if item["workdir"] else self.workdir_for(item["clip_id"])
        analysis = runner.analyze_clip(clip, workdir, self._transcriber_factory(gs), opts)
        out = runner.render_outputs(analysis, workdir, opts, item["hook_text"], item["thumbnail_text"] or item["hook_text"]
                                    or item["title"], item["commentary"])
        log.info("Re-rendered “%s”", item["title"][:60])
        analysis_now = dict(item.get("analysis") or {})
        analysis_now["watermarked"] = opts.watermark
        return self.db.update_item(item_id, video_path=str(out.video), thumbnail_path=str(out.thumbnail),
                                   duration=out.duration, needs_rerender=False, workdir=str(workdir),
                                   analysis=analysis_now)

    def reject_item(self, item_id: int) -> dict:
        item = self.db.get_item(item_id)
        if not item:
            raise EngineError("Item not found")
        if item["workdir"]:
            for path in Path(item["workdir"]).glob("source.*"):
                path.unlink(missing_ok=True)
        return self.db.update_item(item_id, status="rejected")

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        gs = self.settings()
        nxt = self.next_upload(gs) if self.publish_ready() else None
        now = self.clock()
        paused = gs.schedule.pause_until and gs.schedule.pause_until.astimezone(timezone.utc) > now
        quiet = timing.in_quiet_hours(now, gs.schedule.quiet_hours, self.tz)
        if not self.running:
            state = "stopped"
        elif paused:
            state = "paused"
        elif any(a != "idle" for a in self.activity.values()):
            state = "working"
        else:
            state = "idle"
        return {
            "running": self.running,
            "state": state,
            "activity": dict(self.activity),
            "mode": gs.mode,
            "next_upload": {
                "at": iso(nxt["at"]),
                "in_seconds": max(int((nxt["at"] - now).total_seconds()), 0),
                "reason": nxt["reason"],
                "kind": nxt["kind"],
                "item_id": nxt["item"]["id"],
                "title": nxt["item"]["title"],
            } if nxt else None,
            "paused_until": iso(gs.schedule.pause_until) if paused else None,
            "quiet_hours_now": quiet,
            "quota": self.quota.snapshot(),
            "quota_paused_until": self.db.get_value("quota_paused_until"),
            "twitch_configured": self.twitch_ready(),
            "youtube_connected": bool(self.store.get("youtube_refresh_token")),
            "youtube_channel": self.db.get_value("youtube_channel"),
            "instagram_connected": bool(self.store.get("instagram_access_token") and self.db.get_value("instagram_user_id")),
            "instagram_user": self.db.get_value("instagram_username"),
            "instagram_problem": self.instagram_problem,
            "download_only": not self.publish_ready(),
            "auth_problem": self.auth_problem,
            "last_error": self.last_error,
            "uploads_today": self.uploads_on_day(now),
            "max_uploads_per_day": gs.schedule.max_uploads_per_day,
            "items": self.db.item_counts(),
            "clips": self.db.clip_counts(),
            "upload_progress": {str(k): round(v, 3) for k, v in self.upload_progress.items()},
            "secret_storage": self.store.backend_name,
            "secret_storage_is_os": self.store.is_os_keyring,
            "server_time": iso(now),
        }
