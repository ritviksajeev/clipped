"""Fake Twitch/YouTube services and a ready-to-use engine for tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from clipped.db import Database
from clipped.engine import Engine
from clipped.keystore import FileSecretBackend, KeyStore
from clipped.models import ClipInfo, GlobalSettings, RenderSettings
from clipped.pipeline.transcribe import StaticTranscriber
from clipped.services.youtube import UploadResult
from tests import media


class Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


class FakeTwitchService:
    def __init__(self, clips: list[ClipInfo]):
        self.clips = clips
        self.calls = 0

    def get_clips(self, game_id, started_at, ended_at=None, max_clips=100, game_name=""):
        self.calls += 1
        return [c.model_copy(update={"game_name": game_name}) for c in self.clips]

    def get_users(self, ids):
        return {}

    def _get(self, path, params=None):
        return {"data": []}

    def close(self):
        pass


class FakeYouTubeService:
    def __init__(self):
        self.uploads = []
        self.privacy = None
        self.views = {}

    def upload(self, req, progress=None):
        self.uploads.append(req)
        if progress:
            progress(1.0)
        vid = f"VID{len(self.uploads)}"
        return UploadResult(vid, self.privacy or req.privacy_status, "uploaded", thumbnail_set=True)

    def video_status(self, ids):
        return {i: {"privacyStatus": "public", "views": self.views.get(i, 100), "likes": 1, "comments": 0} for i in ids}

    def analytics(self, ids, start, end):
        return {i: {"views": self.views.get(i, 100), "avg_view_pct": 70.0, "avg_view_duration": 15.0} for i in ids}

    def close(self):
        pass


def make_clip(i: int, sample: Path, *, streamer="TenZ", login="tenz", views=5000, hours_old=2.0,
              now: datetime | None = None, title=None) -> ClipInfo:
    now = now or datetime.now(timezone.utc)
    return ClipInfo(id=f"Clip{i}", url=str(sample), title=title or f"insane clutch number {i}",
                    broadcaster_name=streamer, broadcaster_login=login, view_count=views, duration=12.0,
                    created_at=now - timedelta(hours=hours_old), language="en", video_id=f"vod{i}", vod_offset=1000 * i)


def build_engine(tmp_path: Path, sample: Path, clips: list[ClipInfo] | None = None, *, mode="manual",
                 start: datetime | None = None, transcript=None):
    db = Database(tmp_path / "db.sqlite3")
    store = KeyStore(FileSecretBackend(tmp_path / "secrets.json"))
    for name, value in {"twitch_client_id": "cid", "twitch_client_secret": "csecret",
                        "google_client_id": "gid", "google_client_secret": "gsecret",
                        "youtube_refresh_token": "1//refresh"}.items():
        store.set(name, value)
    gs = GlobalSettings(mode=mode, render=RenderSettings(width=360, height=640, fps=15, crf=30, preset="ultrafast"))
    gs.selection.similarity_threshold = 0.95
    if mode == "auto":
        gs.auto_warning_acknowledged_at = datetime.now(timezone.utc)
    db.save_global_settings(gs)
    clock = Clock(start or datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc))
    twitch = FakeTwitchService(clips or [])
    yt = FakeYouTubeService()
    engine = Engine(db, store, twitch_factory=lambda: twitch, youtube_factory=lambda: yt,
                    transcriber_factory=lambda gs: StaticTranscriber(transcript or media.transcript()),
                    clock=clock, tz=ZoneInfo("America/New_York"), work_root=tmp_path / "work")
    return engine, db, store, twitch, yt, clock
