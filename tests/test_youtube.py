import json
import urllib.parse
from datetime import date

import httpx
import pytest

from clipped.db import Database
from clipped.services import youtube
from clipped.services.quota import QuotaTracker
from clipped.services.youtube import (
    AuthError, OAuthFlow, PendingAuth, QuotaExceeded, UploadRequest, YouTubeClient, YouTubeError,
)


class FakeGoogle:
    """Minimal fake of Google's token, resumable upload, thumbnails and videos endpoints."""

    def __init__(self, size_hint=0):
        self.received = bytearray()
        self.init_body = None
        self.thumbnail_status = 200
        self.final_privacy = "public"
        self.fail_put_once = False
        self.server_errors = 0
        self.quota_error = False
        self.refresh_error = None
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        url = request.url
        if url.host == "oauth2.googleapis.com":
            form = urllib.parse.parse_qs(request.content.decode())
            if self.refresh_error:
                return httpx.Response(400, json={"error": self.refresh_error, "error_description": "Token expired"})
            if form["grant_type"] == ["authorization_code"]:
                assert form["code_verifier"][0]
                return httpx.Response(200, json={"access_token": "ya29.access", "refresh_token": "1//refresh-token-xyz",
                                                 "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "ya29.fresh", "expires_in": 3600})
        if url.path == "/upload/youtube/v3/videos" and request.method == "POST":
            if self.quota_error:
                return httpx.Response(403, json={"error": {"code": 403, "message": "quota",
                                                           "errors": [{"reason": "quotaExceeded"}]}})
            if self.server_errors:
                self.server_errors -= 1
                return httpx.Response(503, json={"error": {"code": 503, "message": "busy",
                                                           "errors": [{"reason": "backendError"}]}})
            self.init_body = json.loads(request.content)
            self.total = int(request.headers["X-Upload-Content-Length"])
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/session/abc"})
        if url.path == "/upload/session/abc":
            rng = request.headers["Content-Range"]
            if rng.startswith("bytes */"):
                if not self.received:
                    return httpx.Response(308)
                return httpx.Response(308, headers={"Range": f"bytes=0-{len(self.received) - 1}"})
            if self.fail_put_once and self.received:
                self.fail_put_once = False
                raise httpx.ConnectError("connection reset")
            start = int(rng.split(" ")[1].split("-")[0])
            assert start == len(self.received)
            self.received += request.content
            if len(self.received) < self.total:
                return httpx.Response(308, headers={"Range": f"bytes=0-{len(self.received) - 1}"})
            return httpx.Response(200, json={"id": "VID123", "status": {"privacyStatus": "public",
                                                                        "uploadStatus": "uploaded"}})
        if url.path == "/upload/youtube/v3/thumbnails/set":
            return httpx.Response(self.thumbnail_status, json={"error": {"code": 403, "message": "nope",
                                                                         "errors": [{"reason": "forbidden"}]}}
                                  if self.thumbnail_status >= 400 else {"items": []})
        if url.path == "/youtube/v3/videos":
            return httpx.Response(200, json={"items": [{"id": "VID123", "status": {"privacyStatus": self.final_privacy},
                                                        "statistics": {"viewCount": "42", "likeCount": "3"}}]})
        if url.path == "/youtube/v3/channels":
            return httpx.Response(200, json={"items": [{"id": "UC1", "snippet": {"title": "My Clips", "thumbnails": {}}}]})
        if url.host == "youtubeanalytics.googleapis.com":
            return httpx.Response(200, json={
                "columnHeaders": [{"name": "video"}, {"name": "views"}, {"name": "averageViewDuration"},
                                  {"name": "averageViewPercentage"}, {"name": "likes"}],
                "rows": [["VID123", 40, 18.5, 77.2, 3]]})
        return httpx.Response(404, json={"error": {"code": 404, "message": "nf", "errors": []}})


def make_client(fake, tmp_path=None, quota=None):
    return YouTubeClient("cid.apps.googleusercontent.com", "GOCSPX-secret", "1//refresh-token-xyz",
                         transport=httpx.MockTransport(fake), quota=quota, sleep=lambda s: None)


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "short.mp4"
    path.write_bytes(bytes(range(256)) * 2400)  # 614,400 bytes
    return path


@pytest.fixture(autouse=True)
def small_chunks(monkeypatch):
    monkeypatch.setattr(youtube, "CHUNK", 256 * 1024)


def test_oauth_start_uses_pkce_and_offline_access():
    flow = OAuthFlow("cid", "secret", "http://localhost:8000/oauth2callback")
    url, pending = flow.start()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    assert q["redirect_uri"] == ["http://localhost:8000/oauth2callback"]
    assert "youtube.upload" in q["scope"][0] and "yt-analytics.readonly" in q["scope"][0]
    assert q["state"] == [pending.state]


def test_oauth_exchange():
    fake = FakeGoogle()
    flow = OAuthFlow("cid", "secret", "http://localhost:8000/oauth2callback", transport=httpx.MockTransport(fake))
    tokens = flow.exchange("code123", PendingAuth("s", "verifier", "http://localhost:8000/oauth2callback"))
    assert tokens["refresh_token"] == "1//refresh-token-xyz"


def test_resumable_upload_in_chunks_with_thumbnail(video, tmp_path):
    fake = FakeGoogle()
    db = Database(tmp_path / "q.sqlite3")
    quota = QuotaTracker(db)
    progress = []
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"\xff\xd8jpeg")
    result = make_client(fake, quota=quota).upload(UploadRequest(
        video_path=video, title="t | TenZ", description="d", tags=["a"], thumbnail_path=thumb,
    ), progress=progress.append)
    assert result.video_id == "VID123" and result.url == "https://youtube.com/shorts/VID123"
    assert bytes(fake.received) == video.read_bytes()
    assert progress[-1] == 1.0 and len(progress) >= 3
    assert fake.init_body["status"]["selfDeclaredMadeForKids"] is False
    assert fake.init_body["snippet"]["categoryId"] == "20"
    assert result.thumbnail_set
    assert quota.used() == 1600 + 50 + 1


def test_upload_resumes_after_network_drop(video):
    fake = FakeGoogle()
    fake.fail_put_once = True
    result = make_client(fake).upload(UploadRequest(video_path=video, title="t", description="d"))
    assert result.video_id == "VID123"
    assert bytes(fake.received) == video.read_bytes()


def test_backoff_on_server_errors(video):
    fake = FakeGoogle()
    fake.server_errors = 2
    assert make_client(fake).upload(UploadRequest(video_path=video, title="t", description="d")).video_id == "VID123"


def test_quota_exceeded_marks_day_exhausted(video, tmp_path):
    fake = FakeGoogle()
    fake.quota_error = True
    quota = QuotaTracker(Database(tmp_path / "q.sqlite3"))
    with pytest.raises(QuotaExceeded):
        make_client(fake, quota=quota).upload(UploadRequest(video_path=video, title="t", description="d"))
    assert quota.remaining() == 0
    # local budget check stops the next attempt before any network call
    fake.calls.clear()
    with pytest.raises(QuotaExceeded):
        make_client(fake, quota=quota).upload(UploadRequest(video_path=video, title="t", description="d"))
    assert not any(path.endswith("/videos") for _, path in fake.calls)


def test_private_lock_and_thumbnail_warnings(video, tmp_path):
    fake = FakeGoogle()
    fake.final_privacy = "private"
    fake.thumbnail_status = 403
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"x")
    result = make_client(fake).upload(UploadRequest(video_path=video, title="t", description="d",
                                                    thumbnail_path=thumb))
    assert result.privacy_status == "private"
    assert any("audit" in w for w in result.warnings)
    assert any("phone-verified" in w for w in result.warnings)


def test_revoked_refresh_token_is_auth_error(video):
    fake = FakeGoogle()
    fake.refresh_error = "invalid_grant"
    with pytest.raises(AuthError) as exc:
        make_client(fake).channel()
    assert "Reconnect" in str(exc.value)


def test_stats_and_analytics():
    fake = FakeGoogle()
    yt = make_client(fake)
    assert yt.video_status(["VID123"])["VID123"]["views"] == 42
    a = yt.analytics(["VID123"], date(2026, 11, 1), date(2026, 11, 18))
    assert a["VID123"]["avg_view_pct"] == 77.2
    assert yt.channel()["title"] == "My Clips"


def test_client_requires_connection():
    with pytest.raises(AuthError):
        YouTubeClient("cid", "secret", "")
