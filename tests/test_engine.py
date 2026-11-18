from datetime import timedelta

import pytest

from clippilot.engine import EngineError
from clippilot.models import CategorySettings
from tests.conftest import requires_ffmpeg
from tests.fakes import build_engine, make_clip

pytestmark = requires_ffmpeg


def setup(tmp_path, sample_clip, clips_spec, mode="manual", cat_settings=None):
    engine, db, store, twitch, yt, clock = build_engine(tmp_path, sample_clip, mode=mode)
    clips = [make_clip(i, sample_clip, now=clock(), **spec) for i, spec in enumerate(clips_spec)]
    twitch.clips = clips
    cat = db.add_category("516575", "VALORANT", settings=cat_settings or CategorySettings(max_clips_per_day=5))
    return engine, db, twitch, yt, clock, cat


def test_fetch_dedupes_and_filters(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(tmp_path, sample_clip, [{}, {"views": 3}, {"streamer": "Bad", "login": "bad"}],
                                               cat_settings=CategorySettings(min_views=50, blocklist=["bad"]))
    assert engine.fetch_due() == 1
    assert db.get_clip("Clip1")["skip_reason"].startswith("only 3 views")
    assert "blocklist" in db.get_clip("Clip2")["skip_reason"]
    # Not due again until the fetch interval passes; forced fetch adds nothing new (dedupe)
    assert engine.fetch_due() == 0
    assert engine.fetch_due(force_category=cat["id"]) == 0
    clock.advance(minutes=31)
    assert engine.fetch_due() == 0 and twitch.calls == 3


def test_manual_flow_review_approve_upload(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(tmp_path, sample_clip, [{}])
    engine.fetch_due()
    item = engine.render_step()
    assert item["status"] == "review" and item["mode"] == "manual"
    assert "TenZ" in item["title"] and "https://www.twitch.tv/tenz" in item["description"]
    assert len(item["variants"]) == 3 and item["video_path"]
    # Nothing uploads while waiting for review
    assert engine.upload_due() is None and yt.uploads == []
    db.update_item(item["id"], status="approved", approved_at=clock())
    result = engine.upload_due()
    assert result["youtube_id"] == "VID1"
    up = db.get_item(item["id"])
    assert up["status"] == "uploaded" and up["privacy_actual"] == "public"
    assert yt.uploads[0].title == item["title"]
    assert not list((tmp_path / "work").glob("*/source.*"))  # original download cleaned up
    # The same clip is never processed twice
    assert engine.render_step() is None


def test_rate_limit_and_daily_cap(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(tmp_path, sample_clip, [{}, {"streamer": "B", "login": "b"}])
    engine.fetch_due()
    a, b = engine.render_step(), engine.render_step()
    for it in (a, b):
        db.update_item(it["id"], status="approved", approved_at=clock())
    engine.upload_due()
    assert engine.upload_due() is None  # 20 min minimum gap
    with pytest.raises(EngineError):
        engine.check_rate_limit()
    nxt = engine.next_upload()
    assert nxt["reason"] == "minimum gap between uploads"
    clock.advance(minutes=21)
    assert engine.upload_due()["youtube_id"] == "VID2"


def test_auto_mode_approved_streamers_only(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(
        tmp_path, sample_clip, [{"streamer": "Unknown", "login": "unknown", "title": "first thing"},
                                {"title": "another thing entirely"}], mode="auto")
    gs = db.get_global_settings()
    gs.approved_streamers = ["tenz"]
    db.save_global_settings(gs)
    engine.fetch_due()
    first, second = engine.render_step(), engine.render_step()
    by_streamer = {i["streamer"]: i for i in (first, second)}
    assert by_streamer["Unknown"]["status"] == "review"  # safety: unapproved -> review queue
    assert any("approved list" in n for n in by_streamer["Unknown"]["analysis"]["notes"])
    assert by_streamer["TenZ"]["status"] == "ready"
    assert engine.upload_due()["youtube_id"] == "VID1"
    assert db.get_item(by_streamer["TenZ"]["id"])["status"] == "uploaded"


def test_auto_interval_quiet_hours_and_pause(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(
        tmp_path, sample_clip, [{"title": "alpha one"}, {"title": "beta two"}], mode="auto")
    gs = db.get_global_settings()
    gs.approved_streamers_only = False
    gs.schedule.upload_interval_minutes = 120
    db.save_global_settings(gs)
    engine.fetch_due()
    engine.render_step(), engine.render_step()
    assert engine.upload_due()
    nxt = engine.next_upload()
    assert nxt["reason"] == "upload interval"
    assert nxt["at"] == clock() + timedelta(minutes=120)
    # Pause until tomorrow
    gs = db.get_global_settings()
    gs.schedule.pause_until = clock() + timedelta(days=1)
    db.save_global_settings(gs)
    assert engine.next_upload()["reason"] == "paused"
    clock.advance(hours=3)
    assert engine.upload_due() is None
    assert engine.status()["state"] in ("stopped", "paused")


def test_skips_too_quiet_and_records_reason(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(tmp_path, sample_clip, [{}])
    gs = db.get_global_settings()
    gs.selection.min_mean_db = -3.0  # impossible bar
    db.save_global_settings(gs)
    engine.fetch_due()
    assert engine.render_step() == {"skipped": engine.db.get_clip("Clip0")["skip_reason"]}
    assert "too quiet" in db.get_clip("Clip0")["skip_reason"]
    assert db.get_item_by_clip("Clip0") is None


def test_similar_clip_is_skipped(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(tmp_path, sample_clip, [{}, {"title": "insane clutch number 0"}])
    gs = db.get_global_settings()
    gs.selection.similarity_threshold = 0.5
    db.save_global_settings(gs)
    engine.fetch_due()
    engine.render_step()
    result = engine.render_step()
    assert "too similar" in result["skipped"]


def test_quota_exhaustion_pauses_uploads(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(tmp_path, sample_clip, [{}])
    engine.fetch_due()
    item = engine.render_step()
    db.update_item(item["id"], status="approved", approved_at=clock())
    engine.quota.mark_exhausted()
    assert engine.upload_due() is None
    assert db.get_value("quota_paused_until")
    assert engine.next_upload()["reason"].startswith("YouTube quota")


def test_rerender_after_edit_and_reject(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(tmp_path, sample_clip, [{}])
    engine.fetch_due()
    item = engine.render_step()
    db.update_item(item["id"], hook_text="NEW HOOK", commentary="my take", needs_rerender=True)
    updated = engine.rerender_item(item["id"])
    assert updated["needs_rerender"] is False
    ass = (tmp_path / "work" / "Clip0" / "captions.ass").read_text()
    assert "NEW HOOK" in ass and "my take" in ass
    assert engine.reject_item(item["id"])["status"] == "rejected"


def test_stats_refresh_stores_snapshots(tmp_path, sample_clip):
    engine, db, twitch, yt, clock, cat = setup(tmp_path, sample_clip, [{}])
    engine.fetch_due()
    item = engine.render_step()
    db.update_item(item["id"], status="approved", approved_at=clock())
    engine.upload_due()
    clock.advance(hours=7)
    assert engine.refresh_stats_due() == 1
    stats = db.stats_for(item["id"])
    assert stats[-1]["views"] == 100 and stats[-1]["avg_view_pct"] == 70.0
    assert engine.refresh_stats_due() == 0  # not due again yet
