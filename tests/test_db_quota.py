from datetime import datetime, timedelta, timezone

from clippilot.db import Database
from clippilot.models import CategorySettings, ClipInfo, GlobalSettings
from clippilot.services.quota import QuotaTracker


def make_db(tmp_path):
    return Database(tmp_path / "t.sqlite3")


def test_settings_roundtrip(tmp_path):
    db = make_db(tmp_path)
    assert db.get_global_settings().mode == "manual"
    gs = GlobalSettings(mode="auto", approved_streamers=["@TenZ", "https://twitch.tv/Shroud"])
    db.save_global_settings(gs)
    loaded = db.get_global_settings()
    assert loaded.mode == "auto" and loaded.approved_streamers == ["tenz", "shroud"]


def test_clip_dedupe_never_twice(tmp_path):
    db = make_db(tmp_path)
    clip = ClipInfo(id="A", broadcaster_name="X", video_id="v1", vod_offset=100)
    assert db.insert_clip(clip, None) is True
    assert db.insert_clip(clip, None) is False
    assert db.has_clip("A")
    same_moment = ClipInfo(id="B", video_id="v1", vod_offset=110)
    other_moment = ClipInfo(id="C", video_id="v1", vod_offset=400)
    assert db.near_duplicate(same_moment) == "A"
    assert db.near_duplicate(other_moment) is None


def test_items_lifecycle_and_counts(tmp_path):
    db = make_db(tmp_path)
    cat = db.add_category("123", "VALORANT", settings=CategorySettings(hashtags=["valorant", "#fps"]))
    assert cat["settings"]["hashtags"] == ["#valorant", "#fps"]
    assert db.add_category("123", "dup")["id"] == cat["id"]
    db.insert_clip(ClipInfo(id="A"), cat["id"])
    item = db.create_item("A", cat["id"], mode="manual", streamer="TenZ")
    assert item["status"] == "processing" and item["variants"] == []
    db.update_item(item["id"], status="review", variants=[{"style": "hype"}], tags=["a"], needs_rerender=True)
    got = db.get_item(item["id"])
    assert got["variants"][0]["style"] == "hype" and got["needs_rerender"] is True
    assert db.item_counts() == {"review": 1}
    assert db.count_items(category_id=cat["id"], since=datetime.now(timezone.utc) - timedelta(hours=1)) == 1
    now = datetime.now(timezone.utc)
    db.update_item(item["id"], status="uploaded", uploaded_at=now, mode="auto")
    assert db.last_upload_at("auto").replace(microsecond=0) == now.replace(microsecond=0)
    db.add_stats(item["id"], views=10)
    db.add_stats(item["id"], views=50, when=now + timedelta(hours=1))
    assert db.latest_stats()[item["id"]]["views"] == 50
    assert db.uploads_with_stats()[0]["stats"]["views"] == 50


def test_reset_stuck_items(tmp_path):
    db = make_db(tmp_path)
    db.insert_clip(ClipInfo(id="A"), None)
    db.insert_clip(ClipInfo(id="B"), None)
    a = db.create_item("A", None, mode="manual")
    b = db.create_item("B", None, mode="auto")
    db.update_item(b["id"], status="uploading", approved_at=datetime.now(timezone.utc))
    assert db.reset_stuck_items() == 2
    assert db.get_item(a["id"]) is None and db.get_clip("A")["status"] == "new"
    assert db.get_item(b["id"])["status"] == "approved"


def test_quota_tracker_pacific_day(tmp_path):
    db = make_db(tmp_path)
    # 07:30 UTC on Nov 18 is still Nov 17 in California
    clock = lambda: datetime(2026, 11, 18, 7, 30, tzinfo=timezone.utc)
    q = QuotaTracker(db, clock=clock)
    assert q.day() == "2026-11-17"
    assert q.reset_at() == datetime(2026, 11, 18, 8, 5, tzinfo=timezone.utc)
    assert q.uploads_left() == 6
    for _ in range(6):
        q.spend("videos.insert")
    assert not q.can_spend("videos.insert") and q.remaining() == 400
    q.mark_exhausted()
    assert q.remaining() == 0
    later = QuotaTracker(db, clock=lambda: datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc))
    assert later.remaining() == 10_000
