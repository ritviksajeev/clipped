import random
from datetime import timedelta

from clippilot.db import iso
from clippilot.models import CategorySettings
from tests.conftest import requires_ffmpeg
from tests.fakes import build_engine, make_clip

pytestmark = requires_ffmpeg


def seed_history(db, clock, n=14, *, style_views=None, hour_bias=None, streamer="dominant", cat_id=None):
    """Insert past uploads with stats, as if the channel had been running."""
    style_views = style_views or {"question": 9000, "hype": 300, "descriptive": 400}
    styles = list(style_views)
    for i in range(n):
        style = styles[i % len(styles)]
        cid = f"hist{i}"
        from clippilot.models import ClipInfo

        db.insert_clip(ClipInfo(id=cid, broadcaster_name=streamer), cat_id, status="processed")
        item = db.create_item(cid, cat_id, mode="auto", streamer=streamer, streamer_login=streamer)
        up = clock() - timedelta(days=2 + i)
        if hour_bias is not None:
            up = up.replace(hour=hour_bias if i % 2 == 0 else (hour_bias + 12) % 24)
        views = style_views[style] + i
        if hour_bias is not None:
            views = 20000 if up.hour == hour_bias else 50
        db.update_item(item["id"], status="uploaded", uploaded_at=up, created_at=up, title_style=style, youtube_id=f"y{i}",
                       title=f"history title {i}", analysis={"text": f"unrelated words {i}"})
        db.add_stats(item["id"], views=views, avg_view_pct=60.0, when=clock() - timedelta(hours=1))


def test_auto_mode_prefers_learned_title_style(tmp_path, sample_clip):
    engine, db, store, twitch, yt, clock = build_engine(tmp_path, sample_clip, mode="auto")
    gs = db.get_global_settings()
    gs.approved_streamers_only = False
    gs.optimizer.explore_rate = 0.0
    db.save_global_settings(gs)
    cat = db.add_category("516575", "VALORANT", settings=CategorySettings(max_clips_per_day=10))
    seed_history(db, clock, n=30, cat_id=cat["id"])
    engine.rng = random.Random(1234)
    twitch.clips = [make_clip(0, sample_clip, now=clock(), streamer="Fresh", login="fresh")]
    engine.fetch_due()
    item = engine.render_step()
    assert item["status"] == "ready"
    assert item["title_style"] == "question"  # the style that performs best on this channel
    assert item["variants"][0]["style"] == "question"


def test_diversity_prefers_new_streamer(tmp_path, sample_clip):
    engine, db, store, twitch, yt, clock = build_engine(tmp_path, sample_clip, mode="auto")
    gs = db.get_global_settings()
    gs.approved_streamers_only = False
    db.save_global_settings(gs)
    cat = db.add_category("516575", "VALORANT", settings=CategorySettings(max_clips_per_day=10))
    seed_history(db, clock, n=6, streamer="dominant", cat_id=cat["id"])
    # The dominant streamer's clip has more views, but they've filled the recent feed.
    twitch.clips = [
        make_clip(0, sample_clip, now=clock(), streamer="dominant", login="dominant", views=9000, title="aaa bbb"),
        make_clip(1, sample_clip, now=clock(), streamer="newcomer", login="newcomer", views=4000, title="ccc ddd"),
    ]
    engine.fetch_due()
    first = engine.render_step()
    assert first["streamer"] == "newcomer"


def test_schedule_shifts_toward_learned_best_hour(tmp_path, sample_clip):
    engine, db, store, twitch, yt, clock = build_engine(tmp_path, sample_clip, mode="auto")
    gs = db.get_global_settings()
    gs.approved_streamers_only = False
    gs.schedule.upload_interval_minutes = 240
    db.save_global_settings(gs)
    cat = db.add_category("516575", "VALORANT", settings=CategorySettings(max_clips_per_day=10))
    # clock is 18:00 UTC = 13:00 New York. Make 15:00 New York (20:00 UTC) the channel's best hour.
    seed_history(db, clock, n=14, hour_bias=20, cat_id=cat["id"])
    db.update_item(db.list_items(["uploaded"], limit=1, order="uploaded_at DESC")[0]["id"],
                   uploaded_at=clock() - timedelta(minutes=240))
    twitch.clips = [make_clip(0, sample_clip, now=clock(), streamer="x", login="x")]
    engine.fetch_due()
    engine.render_step()
    nxt = engine.next_upload()
    assert nxt["kind"] == "auto"
    assert nxt["at"] > clock()
    assert "best-performing hour" in nxt["reason"]
    assert (nxt["at"] - clock()) <= timedelta(minutes=120)  # bounded by the flex window
    # Status exposes a countdown for the dashboard
    status = engine.status()
    assert status["next_upload"]["in_seconds"] > 0 and status["next_upload"]["reason"] == nxt["reason"]
