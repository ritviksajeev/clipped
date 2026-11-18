from datetime import datetime, timedelta, timezone

import httpx
import pytest

from clippilot.services.twitch import TwitchAuthError, TwitchClient, TwitchError


def helix_clip(i, views=100, **kw):
    return {"id": f"clip{i}", "url": f"https://clips.twitch.tv/clip{i}", "broadcaster_id": f"b{i % 2}",
            "broadcaster_name": f"Streamer{i % 2}", "creator_name": "c", "video_id": "v", "game_id": "g",
            "language": "en", "title": f"title {i}", "view_count": views, "created_at": "2026-11-18T10:00:00Z",
            "thumbnail_url": "", "duration": 25.0, "vod_offset": 100 * i, **kw}


class FakeTwitch:
    def __init__(self):
        self.tokens = 0
        self.requests = []
        self.fail_once_401 = False
        self.rate_limit_once = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "id.twitch.tv":
            form = dict(x.split("=") for x in request.content.decode().split("&"))
            if form["client_secret"] != "secret123":
                return httpx.Response(400, json={"message": "invalid client secret"})
            self.tokens += 1
            return httpx.Response(200, json={"access_token": f"tok{self.tokens}", "expires_in": 3600})
        assert request.headers["Client-Id"] == "cid"
        if self.fail_once_401:
            self.fail_once_401 = False
            return httpx.Response(401, json={"message": "invalid token"})
        if self.rate_limit_once:
            self.rate_limit_once = False
            return httpx.Response(429, headers={"Ratelimit-Reset": "0"})
        path = request.url.path
        if path.endswith("/search/categories"):
            return httpx.Response(200, json={"data": [
                {"id": "516575", "name": "VALORANT", "box_art_url": "https://x/{width}x{height}.jpg"}]})
        if path.endswith("/clips"):
            after = request.url.params.get("after")
            if after is None:
                return httpx.Response(200, json={"data": [helix_clip(i) for i in range(3)],
                                                 "pagination": {"cursor": "page2"}})
            return httpx.Response(200, json={"data": [helix_clip(i) for i in range(3, 5)], "pagination": {}})
        if path.endswith("/users"):
            ids = request.url.params.get_list("id")
            return httpx.Response(200, json={"data": [{"id": i, "login": f"login_{i}", "display_name": i} for i in ids]})
        return httpx.Response(404)


def client(fake, secret="secret123"):
    return TwitchClient("cid", secret, transport=httpx.MockTransport(fake), sleep=lambda s: None)


def test_search_categories_and_box_art():
    fake = FakeTwitch()
    result = client(fake).search_categories("valo")
    assert result == [{"id": "516575", "name": "VALORANT", "box_art_url": "https://x/144x192.jpg"}]
    assert fake.requests[-1].headers["Authorization"] == "Bearer tok1"


def test_get_clips_paginates_and_resolves_logins():
    fake = FakeTwitch()
    now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    clips = client(fake).get_clips("516575", now - timedelta(hours=48), now, max_clips=10, game_name="VALORANT")
    assert [c.id for c in clips] == [f"clip{i}" for i in range(5)]
    assert clips[0].broadcaster_login == "login_b0" and clips[1].broadcaster_login == "login_b1"
    assert clips[0].game_name == "VALORANT" and clips[0].created_at.tzinfo is not None
    clip_req = next(r for r in fake.requests if r.url.path.endswith("/clips"))
    assert clip_req.url.params["started_at"] == "2026-11-16T12:00:00Z"


def test_token_refresh_on_401_and_rate_limit_retry():
    fake = FakeTwitch()
    tw = client(fake)
    tw.search_categories("x")
    fake.fail_once_401 = True
    tw.search_categories("x")
    assert fake.tokens == 2
    fake.rate_limit_once = True
    assert tw.search_categories("x")


def test_bad_credentials():
    with pytest.raises(TwitchAuthError):
        client(FakeTwitch(), secret="wrong").validate()
    with pytest.raises(TwitchAuthError):
        TwitchClient("", "")


def test_server_errors_eventually_raise():
    tw = TwitchClient("cid", "secret123", sleep=lambda s: None, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"access_token": "t", "expires_in": 10})
        if r.url.host == "id.twitch.tv" else httpx.Response(503)))
    with pytest.raises(TwitchError):
        tw.search_categories("x")
