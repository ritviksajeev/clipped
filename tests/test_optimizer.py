import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from clipped.models import (
    CategorySettings, ClipInfo, GlobalSettings, OptimizerSettings, QuietHours, ScheduleSettings, SelectionSettings,
)
from clipped.optimizer import insights, learning, ranking, similarity, timing

NOW = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)
NY = ZoneInfo("America/New_York")
SEL = SelectionSettings()


# ----------------------------------------------------------------------------- ranking

def clip(**kw):
    base = dict(id="c", broadcaster_name="TenZ", broadcaster_login="tenz", view_count=1000, duration=25,
                created_at=NOW - timedelta(hours=2), language="en")
    base.update(kw)
    return ClipInfo(**base)


def test_trending_and_top24h_rank_differently():
    rising = clip(view_count=900, created_at=NOW - timedelta(minutes=45))   # small but exploding
    big = clip(view_count=20000, created_at=NOW - timedelta(hours=20))     # huge, but from this morning
    trending = lambda c: ranking.pre_score(c, SEL, NOW, "trending")[0]
    top = lambda c: ranking.pre_score(c, SEL, NOW, "top24h")[0]
    assert trending(rising) > trending(big)
    assert top(big) > top(rising)


def test_recent_velocity_rewards_clips_gaining_views_now():
    c = clip(view_count=3000, created_at=NOW - timedelta(hours=5))
    assert ranking.recent_velocity(2000, NOW - timedelta(minutes=30), 3000, NOW) == pytest.approx(2000)
    assert ranking.recent_velocity(2990, NOW - timedelta(minutes=5), 3000, NOW) is None  # too soon to tell
    assert ranking.recent_velocity(3100, NOW - timedelta(hours=1), 3000, NOW) == 0  # never negative
    peaked = ranking.pre_score(c, SEL, NOW, "trending", recent=0.0)[0]
    climbing = ranking.pre_score(c, SEL, NOW, "trending", recent=2000.0)[0]
    assert climbing > ranking.pre_score(c, SEL, NOW, "trending")[0] > peaked


def test_discovery_windows_and_category_override():
    sel = SelectionSettings(trending_window_hours=6)
    assert ranking.window_hours("trending", sel) == 6 and ranking.window_hours("top24h", sel) == 24
    assert ranking.discovery_mode(CategorySettings(), sel) == "trending"
    assert ranking.discovery_mode(CategorySettings(discovery="top24h"), sel) == "top24h"
    ten_hours = clip(created_at=NOW - timedelta(hours=10))
    ok, why = ranking.eligible(ten_hours, CategorySettings(), sel, NOW)
    assert not ok and "6h" in why and "trending" in why
    assert ranking.eligible(ten_hours, CategorySettings(discovery="top24h"), sel, NOW)[0]
    assert not ranking.eligible(clip(created_at=NOW - timedelta(hours=25)), CategorySettings(discovery="top24h"),
                                sel, NOW)[0]


def test_view_velocity_favours_fresh_clips():
    fresh = clip(view_count=1000, created_at=NOW - timedelta(hours=1))
    stale = clip(view_count=5000, created_at=NOW - timedelta(hours=40))
    assert ranking.view_velocity(fresh, NOW) == pytest.approx(1000)
    assert ranking.view_velocity(stale, NOW) == pytest.approx(125)
    assert ranking.pre_score(fresh, SEL, NOW)[0] > ranking.pre_score(stale, SEL, NOW)[0]


@pytest.mark.parametrize("duration,expected", [(30, 1.0), (15, 1.0), (45, 1.0), (8, 0.4), (60, 0.4), (61, 0.0),
                                               (5, 0.0)])
def test_length_score(duration, expected):
    assert ranking.length_score(duration, SEL) == pytest.approx(expected)


def test_ideal_length_beats_long_clip_with_same_views():
    assert ranking.pre_score(clip(duration=30), SEL, NOW)[0] > ranking.pre_score(clip(duration=58), SEL, NOW)[0]


@pytest.mark.parametrize("kw,cat,reason", [
    ({"broadcaster_login": "bad"}, CategorySettings(blocklist=["bad"]), "blocklist"),
    ({}, CategorySettings(allowlist=["someoneelse"]), "allowlist"),
    ({"view_count": 10}, CategorySettings(min_views=50), "views"),
    ({"created_at": NOW - timedelta(hours=72)}, CategorySettings(max_age_hours=48), "older"),
    ({"language": "de"}, CategorySettings(language="en"), "language"),
    ({"duration": 90}, CategorySettings(), "too long"),
])
def test_eligibility_filters(kw, cat, reason):
    ok, why = ranking.eligible(clip(**kw), cat, SEL, NOW)
    assert not ok and reason in why


def test_eligible_clip_passes_and_allowlist_by_display_name():
    assert ranking.eligible(clip(), CategorySettings(allowlist=["tenz"]), SEL, NOW) == (True, "")
    assert ranking.eligible(clip(broadcaster_login=""), CategorySettings(allowlist=["tenz"]), SEL, NOW)[0]


def test_final_score_weights_hype_and_diversity():
    assert ranking.final_score(0.5, 1.0) > ranking.final_score(0.5, 0.2)
    assert ranking.final_score(0.5, 0.5, diversity=0.5) == pytest.approx(ranking.final_score(0.5, 0.5) / 2)


# ----------------------------------------------------------------------------- similarity

def test_similarity_detects_repeat_moments():
    a = {"title": "TenZ insane 1v4 clutch", "text": "no way he hits the one tap through smoke", "streamer": "TenZ"}
    b = {"title": "1v4 clutch by TenZ", "text": "no way he hits the one tap through smoke wow", "streamer": "TenZ"}
    c = {"title": "funny fail", "text": "i fell off the map again chat", "streamer": "Other"}
    assert similarity.similarity(a, b) > 0.6
    assert similarity.similarity(a, c) < 0.2
    score, match = similarity.most_similar(a, [c, b])
    assert match is b


# ----------------------------------------------------------------------------- learning

def upload(i, *, style="hype", views=100, pct=50.0, hour_utc=18, days_ago=3, streamer="s", cat=1):
    t = (NOW - timedelta(days=days_ago)).replace(hour=hour_utc, minute=0)
    return {"id": i, "title_style": style, "uploaded_at": t.isoformat(), "streamer": streamer, "category_id": cat,
            "category_name": f"cat{cat}", "duration": 30, "title": f"t{i}", "youtube_id": f"v{i}", "analysis": {},
            "stats": {"views": views, "avg_view_pct": pct}}


def test_performance_is_rank_based():
    ups = [upload(1, views=10), upload(2, views=1000), upload(3, views=100_000)]
    perf = learning.performance(ups)
    assert perf[1] < perf[2] < perf[3]
    assert perf[3] <= 1.0


def test_matured_ignores_fresh_uploads():
    ups = [upload(1, days_ago=0), upload(2, days_ago=2)]
    ups[0]["uploaded_at"] = (NOW - timedelta(hours=3)).isoformat()
    assert [u["id"] for u in learning.matured(ups, NOW)] == [2]


def test_choose_styles_explores_until_enough_data():
    ups = [upload(1, style="hype"), upload(2, style="hype")]
    order = learning.choose_styles(ups, 3, min_samples=6, rng=random.Random(1), now=NOW)
    assert order[0] in ("question", "descriptive", "streamer")  # least-tried first
    assert len(set(order)) == 3


def test_choose_styles_exploits_winner():
    ups = []
    for i in range(12):
        ups.append(upload(i, style="question", views=5000 + i))
        ups.append(upload(100 + i, style="hype", views=50 + i))
        ups.append(upload(200 + i, style="descriptive", views=60 + i))
    rng = random.Random(7)
    wins = sum(learning.choose_styles(ups, 3, min_samples=6, explore_rate=0.0, rng=rng, now=NOW)[0] == "question"
               for _ in range(50))
    assert wins >= 40  # Thompson sampling: strongly favours the winner, still tries the runner-up
    data = learning.matured(ups, NOW)
    stats = learning.style_stats(data, learning.performance(data))
    assert stats["question"]["mean"] > stats["descriptive"]["mean"] > stats["hype"]["mean"]


def test_hour_scores_find_best_hour():
    ups = [upload(i, hour_utc=1, views=10_000) for i in range(8)] + [upload(50 + i, hour_utc=14, views=20) for i in range(8)]
    scores = learning.hour_scores(ups, timezone.utc, min_samples=12, now=NOW)
    assert max(scores, key=scores.get) == 1
    assert scores[14] < 0.2
    assert learning.hour_scores(ups[:5], timezone.utc, min_samples=12, now=NOW) is None


def test_diversity_factor_penalises_repeats():
    recent = [{"streamer": "tenz", "category_id": 1}, {"streamer": "tenz", "category_id": 1},
              {"streamer": "shroud", "category_id": 2}]
    assert learning.diversity_factor("newguy", 3, recent) == 1.0
    assert learning.diversity_factor("tenz", 1, recent) < learning.diversity_factor("shroud", 2, recent) < 1.0
    assert learning.diversity_factor("tenz", 1, recent, window=0) == 1.0


# ----------------------------------------------------------------------------- timing

def slot(now=NOW, kind="auto", last_any=None, last_auto=None, uploads=0, hours=None, **sched):
    schedule = ScheduleSettings(**sched)
    return timing.next_slot(now, kind=kind, schedule=schedule, tz=NY, last_any=last_any, last_auto=last_auto,
                            uploads_on_day=lambda t: uploads, hour_scores=hours, optimizer=OptimizerSettings())


def test_ready_now_without_history():
    s = slot()
    assert s.at == NOW and s.reason == "ready now"


def test_min_gap_applies_to_manual_and_auto():
    s = slot(kind="manual", last_any=NOW - timedelta(minutes=5), min_gap_minutes=20)
    assert s.at == NOW + timedelta(minutes=15) and "minimum gap" in s.reason


def test_interval_applies_to_auto_only():
    last = NOW - timedelta(minutes=30)
    assert slot(kind="auto", last_any=last, last_auto=last, upload_interval_minutes=120).at == NOW + timedelta(minutes=90)
    assert slot(kind="manual", last_any=last, last_auto=last, upload_interval_minutes=120).at == NOW


def test_pause_until():
    until = NOW + timedelta(hours=5)
    s = slot(pause_until=until)
    assert s.at == until and s.reason == "paused"


def test_daily_cap_moves_to_next_local_day():
    today = NOW.astimezone(NY).date()
    s = timing.next_slot(NOW, kind="auto", schedule=ScheduleSettings(max_uploads_per_day=4), tz=NY, last_any=None,
                         last_auto=None, uploads_on_day=lambda t: 4 if t.astimezone(NY).date() == today else 0)
    local = s.at.astimezone(NY)
    assert local.date() == NOW.astimezone(NY).date() + timedelta(days=1) and local.hour == 0
    assert s.reason == "daily upload limit reached"


def test_quiet_hours_spanning_midnight():
    quiet = QuietHours(enabled=True, start="23:00", end="07:00")
    late = datetime(2026, 11, 19, 4, 30, tzinfo=timezone.utc)  # 23:30 in New York
    assert timing.in_quiet_hours(late, quiet, NY)
    s = slot(now=late, quiet_hours=quiet)
    assert s.at.astimezone(NY).hour == 7 and s.reason == "quiet hours"
    assert not timing.in_quiet_hours(NOW, quiet, NY)  # 13:00 New York


def test_best_hour_shift_is_bounded_and_never_earlier():
    last = NOW - timedelta(minutes=120)
    # NOW is 13:00 New York; make 15:00 the clear best hour.
    hours = {h: 0.1 for h in range(24)}
    hours[15] = 1.0
    s = slot(last_any=last, last_auto=last, upload_interval_minutes=240, hours=hours)
    base = last + timedelta(minutes=240)  # 15:00 local already? base is 15:00 UTC = 10:00 NY
    assert s.at >= base
    assert s.at.astimezone(NY).hour == 12 or s.shifted_minutes <= 120  # flex = min(240*0.5, 180)
    assert s.shifted_minutes <= 120


def test_best_hour_shift_moves_toward_peak():
    hours = {h: 0.0 for h in range(24)}
    hours[14] = 1.0  # 14:00 New York, one hour after NOW
    s = slot(hours=hours, upload_interval_minutes=240)
    assert s.at.astimezone(NY).hour == 14 and 0 < s.shifted_minutes <= 120
    assert "best-performing hour" in s.reason


# ----------------------------------------------------------------------------- insights

def test_insights_summarise_what_works():
    ups = [upload(i, style="question", views=5000, hour_utc=1, streamer="A", cat=1) for i in range(7)]
    ups += [upload(20 + i, style="hype", views=500, hour_utc=14, streamer="B", cat=2) for i in range(7)]
    gs = GlobalSettings()
    data = insights.build(ups, timezone.utc, gs, now=NOW)
    assert data["summary"]["uploads"] == 14 and data["summary"]["avg_retention"] == 50.0
    assert data["by_style"][0]["key"] == "question"
    assert any("Title style “question”" in t for t in data["tips"])
    assert data["learning_active"] == {"styles": True, "timing": True}
    assert len(data["by_hour"]) == 24 and data["top"][0]["style"] == "question"
