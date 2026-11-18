"""Fill a throwaway data directory with demo data (for UI development and screenshots).

    CLIPPILOT_HOME=/tmp/clippilot-demo python scripts/seed_demo.py
    CLIPPILOT_HOME=/tmp/clippilot-demo clippilot serve

Uses a synthetic test clip and fake credentials. Never point this at your
real data directory.
"""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clippilot import config  # noqa: E402
from clippilot.db import Database  # noqa: E402
from clippilot.engine import Engine  # noqa: E402
from clippilot.keystore import KeyStore  # noqa: E402
from clippilot.models import CategorySettings, ClipInfo, GlobalSettings  # noqa: E402
from clippilot.pipeline.transcribe import StaticTranscriber  # noqa: E402
from tests import media  # noqa: E402


def main() -> None:
    if "CLIPPILOT_HOME" not in os.environ:
        sys.exit("Set CLIPPILOT_HOME to a throwaway folder first.")
    os.environ.setdefault("CLIPPILOT_SECRETS_FILE", str(config.data_dir() / "secrets.json"))
    db = Database(config.db_path())
    store = KeyStore()
    for name, value in {"twitch_client_id": "demo-client-id", "twitch_client_secret": "demo-client-secret",
                        "google_client_id": "demo.apps.googleusercontent.com", "google_client_secret": "GOCSPX-demo",
                        "youtube_refresh_token": "1//demo-refresh-token-not-real"}.items():
        store.set(name, value)
    db.set_value("youtube_channel", {"id": "UCdemo", "title": "Clutch Clips Daily", "thumbnail": ""})
    gs = GlobalSettings()
    gs.approved_streamers = ["tenz", "shroud"]
    gs.selection.similarity_threshold = 1.0  # demo clips share one synthetic transcript
    db.save_global_settings(gs)

    valo = db.add_category("516575", "VALORANT", "https://static-cdn.jtvnw.net/ttv-boxart/516575-144x192.jpg",
                           CategorySettings(hashtags=["#valorant", "#valorantclips"], allowlist=["tenz"]))
    cs2 = db.add_category("32399", "Counter-Strike", "https://static-cdn.jtvnw.net/ttv-boxart/32399-144x192.jpg",
                          CategorySettings(hashtags=["#cs2"], min_views=200))

    sample = media.make_clip(config.data_dir() / "demo-source" / "clip.mp4")
    now = datetime.now(timezone.utc)
    engine = Engine(db, store, transcriber_factory=lambda g: StaticTranscriber(media.transcript()))
    demo = [
        ("DemoClip-Ace1", "TenZ", "tenz", valo, "he actually hit the 1v4 with a sheriff", 18400),
        ("DemoClip-Flick2", "shroud", "shroud", cs2, "shroud's flick through smoke", 9100),
    ]
    for cid, name, login, cat, title, views in demo:
        if db.get_item_by_clip(cid):
            continue
        clip = ClipInfo(id=cid, url=str(sample), title=title, broadcaster_name=name, broadcaster_login=login,
                        game_name=cat["name"], view_count=views, duration=12, created_at=now - timedelta(hours=3),
                        language="en")
        db.insert_clip(clip, cat["id"], 0.8, {"velocity": views / 3})
        row = db.get_clip(cid)
        row["clip"] = clip.model_copy(update={"url": f"https://clips.twitch.tv/{cid}"})
        db.update_clip(cid, data=row["clip"])
        row = db.get_clip(cid)
        # render from the local sample, but keep the public clip URL for credit
        engine.process_clip_row({**row, "clip": row["clip"].model_copy(update={"url": str(sample)})}, cat, gs)
        item = db.get_item_by_clip(cid)
        if not item:
            print(f"could not render {cid}: {db.get_clip(cid)['skip_reason']}")
            continue
        from clippilot.pipeline import metadata

        variants = [metadata.finalize(metadata.Variant.from_dict(v), row["clip"], gs.metadata, cat["settings"]["hashtags"])
                    for v in item["variants"]]
        db.update_item(item["id"], variants=[v.to_dict() for v in variants], title=variants[0].title,
                       description=variants[0].description)

    rng = random.Random(4)
    styles = ["question", "hype", "descriptive", "streamer"]
    streamers = [("TenZ", "tenz", valo), ("shroud", "shroud", cs2), ("Tarik", "tarik", valo), ("s1mple", "s1mple", cs2)]
    for i in range(18):
        cid = f"DemoHist{i}"
        if db.has_clip(cid):
            continue
        name, login, cat = streamers[i % 4]
        style = styles[i % 4]
        up = (now - timedelta(days=1 + i * 0.7)).replace(minute=0, second=0)
        up = up.replace(hour=[14, 17, 20, 23][i % 4])
        base = {"question": 21000, "hype": 9000, "descriptive": 6000, "streamer": 7000}[style]
        views = int(base * rng.uniform(0.5, 1.6) * (1.6 if up.hour == 20 else 1))
        db.insert_clip(ClipInfo(id=cid, broadcaster_name=name, broadcaster_login=login), cat["id"], status="processed")
        item = db.create_item(cid, cat["id"], mode="manual", streamer=name, streamer_login=login,
                              category_name=cat["name"])
        db.update_item(item["id"], status="uploaded", uploaded_at=up, created_at=up, title_style=style,
                       youtube_id=f"demo{i:03d}", title=f"{name}: demo upload #{i}", duration=rng.choice([14, 22, 31, 38, 52]),
                       privacy_requested="public", privacy_actual="private" if i < 2 else "public",
                       analysis={"plan": {"segments": [{"kind": "teaser"}] if i % 2 else []}})
        db.add_stats(item["id"], views=views, likes=views // 40, avg_view_pct=rng.uniform(55, 92),
                     avg_view_duration=rng.uniform(10, 28), hours_since_upload=24)
    gs.selection.similarity_threshold = GlobalSettings().selection.similarity_threshold
    db.save_global_settings(gs)
    engine.shutdown()
    print(f"Demo data ready in {config.data_dir()}")


if __name__ == "__main__":
    main()
