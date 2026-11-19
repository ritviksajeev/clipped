"""Instagram Reels: the four-step publish, errors in plain words, and the engine posting to it."""

import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from clipped.api.app import create_app
from clipped.models import CategorySettings
from clipped.services import instagram as ig
from tests.conftest import requires_ffmpeg
from tests.fakes import build_engine, make_clip

H = {"X-Clipped": "1"}


class FakeGraph:
    """Just enough of graph.instagram.com and rupload.facebook.com."""

    def __init__(self, processing_polls=1, fail=None):
        self.calls = []
        self.uploaded = b""
        self.polls = processing_polls
        self.fail = fail or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, request.url.host, path))
        if path in self.fail:
            return httpx.Response(400, json={"error": self.fail[path]})
        if request.url.host == "rupload.facebook.com":
            assert request.headers["authorization"] == "OAuth TOKEN"
            assert request.headers["offset"] == "0" and int(request.headers["file_size"]) > 0
            self.uploaded = request.content
            return httpx.Response(200, json={"success": True})
        if path == "/me":
            assert request.url.params["access_token"] == "TOKEN"
            return httpx.Response(200, json={"user_id": "1789", "username": "clipsdaily", "account_type": "BUSINESS"})
        if path == "/refresh_access_token":
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": 5184000})
        if path == "/1789/media":
            form = parse_qs(request.content.decode())
            assert form["media_type"] == ["REELS"] and form["upload_type"] == ["resumable"]
            self.caption = form["caption"][0]
            return httpx.Response(200, json={"id": "C55", "uri": "https://rupload.facebook.com/ig-api-upload/v21.0/C55"})
        if path == "/C55":
            self.polls -= 1
            return httpx.Response(200, json={"status_code": "IN_PROGRESS" if self.polls >= 0 else "FINISHED"})
        if path == "/1789/media_publish":
            assert parse_qs(request.content.decode())["creation_id"] == ["C55"]
            return httpx.Response(200, json={"id": "M77"})
        if path == "/M77":
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/abc/"})
        return httpx.Response(404, json={"error": {"message": "unknown"}})


def test_caption_keeps_credit_and_respects_limits():
    tags = " ".join(f"#t{i}" for i in range(40))
    cap = ig.build_caption("Title", "credit line\n" + tags)
    assert cap.startswith("Title\n\ncredit line") and cap.count("#") == 30
    assert len(ig.build_caption("x", "y" * 5000)) == 2200


def test_publish_reel_runs_the_four_steps(tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"\x00\x01" * 1000)
    graph = FakeGraph(processing_polls=2)
    client = ig.InstagramClient("TOKEN", transport=httpx.MockTransport(graph), sleep=lambda s: None)
    steps = []
    reel = client.publish_reel("1789", video, "caption here", progress=steps.append)
    assert reel.media_id == "M77" and reel.permalink == "https://www.instagram.com/reel/abc/"
    assert graph.uploaded == video.read_bytes() and graph.caption == "caption here"
    assert [c[2] for c in graph.calls] == ["/1789/media", "/ig-api-upload/v21.0/C55", "/C55", "/C55", "/C55",
                                           "/1789/media_publish", "/M77"]
    assert steps[0] < steps[-1] == 1.0


@pytest.mark.parametrize("err,kind,words", [
    ({"code": 190, "message": "Session has expired"}, ig.InstagramAuthError, "Paste a new token"),
    ({"code": 10, "message": "Application does not have permission"}, ig.InstagramAuthError, "content_publish"),
    ({"code": 4, "error_subcode": 2207042, "message": "limit"}, ig.InstagramError, "posting limit"),
])
def test_errors_are_explained(tmp_path, err, kind, words):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    graph = FakeGraph(fail={"/1789/media": err})
    client = ig.InstagramClient("TOKEN", transport=httpx.MockTransport(graph), sleep=lambda s: None)
    with pytest.raises(kind, match=words) as info:
        client.publish_reel("1789", video, "c")
    assert "TOKEN" not in str(info.value)  # the token never ends up in a message or the log


def test_processing_error_is_reported(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    class Broken(FakeGraph):
        def __call__(self, request):
            if request.url.path == "/C55":
                return httpx.Response(200, json={"status_code": "ERROR", "status": "Unsupported video format"})
            return super().__call__(request)

    client = ig.InstagramClient("TOKEN", transport=httpx.MockTransport(Broken()), sleep=lambda s: None)
    with pytest.raises(ig.InstagramError, match="Unsupported video format"):
        client.publish_reel("1789", video, "c")


@requires_ffmpeg
def test_engine_posts_to_instagram_only_and_api_connects(tmp_path, sample_clip):
    graph = FakeGraph()
    factory = lambda token=None: ig.InstagramClient(token or "TOKEN", transport=httpx.MockTransport(graph),  # noqa: E731
                                                    sleep=lambda s: None)
    engine, db, store, twitch, yt, clock = build_engine(tmp_path, sample_clip)
    store.delete("youtube_refresh_token")  # Instagram only
    engine._instagram_factory = factory
    twitch.clips = [make_clip(0, sample_clip, now=clock())]
    db.add_category("516575", "VALORANT", settings=CategorySettings())
    app = create_app(db=db, store=store, engine=engine, allowed_hosts={"testserver"}, autostart=False,
                     instagram_factory=factory)
    with TestClient(app) as c:
        assert c.get("/api/status").json()["download_only"] is True
        r = c.post("/api/instagram/connect", json={"value": " TOKEN "}, headers=H)
        assert r.status_code == 200 and r.json()["username"] == "clipsdaily"
        st = c.get("/api/status").json()
        assert st["instagram_connected"] and not st["download_only"]

        engine.fetch_due()
        item = engine.render_step()
        c.post(f"/api/items/{item['id']}/approve", json={}, headers=H)
        out = engine.upload_item(item["id"])
        assert out["instagram_id"] == "M77" and out["youtube_id"] == ""
        done = db.get_item(item["id"])
        assert done["status"] == "uploaded" and done["instagram_url"].endswith("/reel/abc/")
        assert "TenZ" in graph.caption  # the streamer credit travels with the Reel

        assert c.post("/api/instagram/disconnect", headers=H).json()["connected"] is False


@requires_ffmpeg
def test_download_and_mark_posted_need_no_platform(tmp_path, sample_clip, monkeypatch):
    monkeypatch.setenv("CLIPPED_ALLOW_ANY_MEDIA", "1")  # the test's work folder is outside the data dir
    engine, db, store, twitch, yt, clock = build_engine(tmp_path, sample_clip)
    store.delete("youtube_refresh_token")
    twitch.clips = [make_clip(0, sample_clip, now=clock())]
    db.add_category("516575", "VALORANT", settings=CategorySettings())
    engine.fetch_due()
    item = engine.render_step()
    app = create_app(db=db, store=store, engine=engine, allowed_hosts={"testserver"}, autostart=False)
    with TestClient(app) as c:
        r = c.get(f"/api/items/{item['id']}/download")
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        assert 'attachment' in r.headers["content-disposition"] and ".mp4" in r.headers["content-disposition"]
        assert len(r.content) > 1000
        r = c.post(f"/api/items/{item['id']}/approve", json={"upload_now": True}, headers=H)
        assert r.status_code == 409 and "download" in r.json()["detail"]  # nowhere to upload: say what to do
        posted = c.post(f"/api/items/{item['id']}/posted", headers=H).json()
        assert posted["status"] == "uploaded" and posted["posted_manually"] is True
        assert engine.uploads_on_day(clock()) == 1


def test_download_names_are_safe():
    from clipped.api.app import download_name

    assert download_name('Did "TenZ" really? <yes> / no') == "Did TenZ really yes no.mp4"
    assert download_name("") == "clipped short.mp4"
    assert download_name("a" * 200).endswith(".mp4") and len(download_name("a" * 200)) <= 84
