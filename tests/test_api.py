import json

import pytest
from fastapi.testclient import TestClient

from clipped.api.app import create_app
from clipped.models import CategorySettings
from tests.conftest import requires_ffmpeg
from tests.fakes import build_engine, make_clip

H = {"X-Clipped": "1"}


@pytest.fixture
def env(tmp_path, monkeypatch, sample_clip):
    monkeypatch.setenv("CLIPPED_ALLOW_ANY_MEDIA", "1")
    engine, db, store, twitch, yt, clock = build_engine(tmp_path, sample_clip)
    app = create_app(db=db, store=store, engine=engine, allowed_hosts={"testserver"}, autostart=False)
    with TestClient(app) as client:
        yield client, engine, db, store, twitch, yt, clock


def test_csrf_header_and_host_guard(env):
    client, *_ = env
    assert client.post("/api/engine/stop").status_code == 403
    assert client.post("/api/engine/stop", headers=H).status_code == 200
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/status").json()["state"] == "stopped"


def test_secrets_are_write_only(env):
    client, engine, db, store, *_ = env
    r = client.put("/api/secrets/anthropic_api_key", json={"value": "sk-ant-api03-verysecretvalue"}, headers=H)
    assert r.json() == {"label": "Anthropic API key", "set": True, "hint": "••••alue"}
    body = client.get("/api/secrets").text
    assert "verysecret" not in body
    assert client.put("/api/secrets/youtube_refresh_token", json={"value": "x"}, headers=H).status_code == 404
    assert client.delete("/api/secrets/anthropic_api_key", headers=H).json()["set"] is False


def test_google_client_json_upload(env):
    client, engine, db, store, *_ = env
    payload = {"installed": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "GOCSPX-zzz"}}
    r = client.post("/api/secrets/google-client-json", json={"json_text": json.dumps(payload)}, headers=H)
    assert r.json()["client_type"] == "desktop"
    assert store.get("google_client_id") == "abc.apps.googleusercontent.com"
    bad = client.post("/api/secrets/google-client-json", json={"json_text": "{}"}, headers=H)
    assert bad.status_code == 400


def test_auto_mode_requires_one_time_acknowledgement(env):
    client, engine, db, *_ = env
    settings = client.get("/api/settings").json()["settings"]
    settings["mode"] = "auto"
    assert client.put("/api/settings", json=settings, headers=H).status_code == 409
    assert client.post("/api/settings/acknowledge-auto", headers=H).json()["auto_warning_acknowledged"]
    r = client.put("/api/settings", json=settings, headers=H)
    assert r.status_code == 200 and r.json()["settings"]["mode"] == "auto"
    assert r.json()["settings"]["approved_streamers_only"] is True  # on by default


def test_category_crud_and_auto_ack(env):
    client, *_ = env
    r = client.post("/api/categories", json={"twitch_id": "33214", "name": "Fortnite",
                                             "settings": {"mode": "auto"}}, headers=H)
    assert r.status_code == 409
    r = client.post("/api/categories", json={"twitch_id": "33214", "name": "Fortnite",
                                             "settings": {"hashtags": ["fortnite", "#fn"], "allowlist": ["@Ninja"]}},
                    headers=H)
    cat = r.json()
    assert cat["settings"]["hashtags"] == ["#fortnite", "#fn"] and cat["settings"]["allowlist"] == ["ninja"]
    upd = client.put(f"/api/categories/{cat['id']}", json={"enabled": False}, headers=H).json()
    assert upd["enabled"] is False
    assert len(client.get("/api/categories").json()) == 1
    assert client.delete(f"/api/categories/{cat['id']}", headers=H).status_code == 200


@requires_ffmpeg
def test_review_queue_edit_approve_and_upload(env, sample_clip):
    client, engine, db, store, twitch, yt, clock = env
    twitch.clips = [make_clip(0, sample_clip, now=clock())]
    db.add_category("516575", "VALORANT", settings=CategorySettings())
    engine.fetch_due()
    item = engine.render_step()

    queue = client.get("/api/items?status=review").json()
    assert [i["id"] for i in queue] == [item["id"]]
    assert queue[0]["video_url"].startswith(f"/media/items/{item['id']}/video.mp4")
    assert "video_path" not in queue[0]
    video = client.get(queue[0]["video_url"], headers={"Range": "bytes=0-99"})
    assert video.status_code == 206 and len(video.content) == 100
    assert client.get(queue[0]["thumbnail_url"]).headers["content-type"] == "image/jpeg"

    # Editing the title can't remove the credit; changing hook text flags a re-render
    r = client.patch(f"/api/items/{item['id']}", json={"title": "my custom title", "description": "no credit here",
                                                     "hook_text": "WATCH THIS"}, headers=H).json()
    assert r["title"] == "my custom title | TenZ"
    assert "https://www.twitch.tv/tenz" in r["description"] and "#Shorts" in r["description"]
    assert r["needs_rerender"] is True
    r = client.patch(f"/api/items/{item['id']}", json={"chosen": 1}, headers=H).json()
    assert r["chosen"] == 1 and r["title_style"] == item["variants"][1]["style"]

    r = client.post(f"/api/items/{item['id']}/approve", json={}, headers=H)
    assert r.json()["status"] == "approved"
    engine._pools["render"].submit(lambda: None).result()  # wait for queued re-render
    assert client.get(f"/api/items/{item['id']}").json()["needs_rerender"] is False

    assert engine.upload_due()["youtube_id"] == "VID1"
    hist = client.get("/api/history").json()
    assert hist[0]["youtube_url"] == "https://youtube.com/shorts/VID1"
    assert client.patch(f"/api/items/{item['id']}", json={"title": "x"}, headers=H).status_code == 409


@requires_ffmpeg
def test_reject_and_upload_now_rate_limit(env, sample_clip):
    client, engine, db, store, twitch, yt, clock = env
    twitch.clips = [make_clip(0, sample_clip, now=clock()), make_clip(1, sample_clip, now=clock(), streamer="B", login="b",
                                                                      title="something else")]
    db.add_category("516575", "VALORANT", settings=CategorySettings())
    engine.fetch_due()
    a, b = engine.render_step(), engine.render_step()
    assert client.post(f"/api/items/{a['id']}/reject", headers=H).json()["status"] == "rejected"
    assert client.post(f"/api/items/{b['id']}/upload-now", headers=H).status_code == 409  # not approved
    client.post(f"/api/items/{b['id']}/approve", json={"upload_now": True}, headers=H)
    engine._pools["net"].submit(lambda: None).result()
    assert db.get_item(b["id"])["status"] == "uploaded"
    # A second immediate upload is blocked by the minimum gap
    db.update_item(a["id"], status="approved")
    r = client.post(f"/api/items/{a['id']}/upload-now", headers=H)
    assert r.status_code == 409 and "Rate limit" in r.json()["detail"]


def test_youtube_connect_requires_client(env):
    client, engine, db, store, *_ = env
    store.delete("google_client_id")
    assert client.get("/api/youtube/connect").status_code == 400
    store.set("google_client_id", "gid")
    r = client.get("/api/youtube/connect").json()
    assert r["redirect_uri"] == "http://testserver/oauth2callback"
    assert "code_challenge" in r["url"]
    bad = client.get("/oauth2callback?state=unknown&code=x", follow_redirects=False)
    assert bad.status_code == 303 and "youtube_error" in bad.headers["location"]


def test_insights_and_guides_and_spa(env):
    client, *_ = env
    ins = client.get("/api/insights").json()
    assert ins["summary"]["uploads"] == 0 and isinstance(ins["tips"], list)
    assert isinstance(client.get("/api/guides").json(), list)
    assert client.get("/").status_code == 200
    assert client.get("/api/nope").status_code == 404


def test_ai_status_and_use_provider(env, tmp_path, monkeypatch):
    client, engine, db, store, *_ = env
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    from clipped.services import ai

    monkeypatch.setattr(ai, "ollama_status", lambda url=None, transport=None: {"running": False, "models": [], "url": url})
    st = client.get("/api/ai/status").json()
    assert st["provider"] == "template"
    assert st["anthropic"]["ready"] is False and st["openrouter"]["connected"] is False
    assert client.post("/api/ai/use", json={"provider": "openrouter"}, headers=H).status_code == 400
    assert client.post("/api/ai/use", json={"provider": "nope"}, headers=H).status_code == 400
    store.set("openrouter_api_key", "sk-or-v1-0123456789abcdef")
    r = client.post("/api/ai/use", json={"provider": "openrouter"}, headers=H)
    assert r.status_code == 200 and db.get_global_settings().metadata.provider == "openrouter"
    assert "0123456789" not in client.get("/api/ai/status").text  # key never returned
    client.post("/api/ai/openrouter/disconnect", headers=H)
    assert store.get("openrouter_api_key") is None and db.get_global_settings().metadata.provider == "template"


def test_openrouter_connect_callback_saves_key(env, monkeypatch):
    client, engine, db, store, *_ = env
    from clipped.services import ai

    r = client.post("/api/ai/openrouter/connect?desktop=true", headers=H).json()
    assert "callback_url=http%3A%2F%2Flocalhost" in r["url"]
    monkeypatch.setattr(ai.OpenRouterConnect, "finish", lambda self, code, transport=None: "sk-or-v1-fromoauth1234")
    page = client.get("/openrouter/callback?code=abc123")
    assert page.status_code == 200 and "OpenRouter connected" in page.text  # desktop: a page, not the dashboard
    assert store.get("openrouter_api_key") == "sk-or-v1-fromoauth1234"
    assert db.get_global_settings().metadata.provider == "openrouter"  # switched from the free templates


def test_openrouter_callback_without_pending_flow_fails_safely(env):
    client, engine, db, store, *_ = env
    r = client.get("/openrouter/callback?code=abc123", follow_redirects=False)
    assert r.status_code == 303 and "ai_error" in r.headers["location"]
    assert store.get("openrouter_api_key") is None


def test_youtube_desktop_callback_shows_a_page(env):
    from urllib.parse import parse_qs, urlparse

    client, *_ = env
    r = client.get("/oauth2callback?state=unknown&code=x", follow_redirects=False)
    assert r.status_code == 303  # browser flow: back to the dashboard
    url = client.get("/api/youtube/connect?desktop=true").json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    page = client.get(f"/oauth2callback?state={state}&error=access_denied", follow_redirects=False)
    assert page.status_code == 400 and "YouTube not connected" in page.text and "access_denied" in page.text
