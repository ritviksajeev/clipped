"""YouTube Data API v3 + YouTube Analytics API, using the user's own OAuth client.

* OAuth 2.0 for installed apps with PKCE and a loopback redirect to the
  local dashboard (http://localhost:8000/oauth2callback).
* Resumable uploads that survive network hiccups.
* Exponential backoff with jitter on 5xx / rate limits; a clean
  :class:`QuotaExceeded` when the daily quota is gone.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import httpx

from ..logs import get_logger, register_secret
from .quota import QuotaTracker

log = get_logger("youtube")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CHUNK = 8 * 1024 * 1024  # must be a multiple of 256 KiB
RETRYABLE_STATUS = {500, 502, 503, 504, 429}
RETRYABLE_REASONS = {"backendError", "rateLimitExceeded", "userRateLimitExceeded", "internalError"}
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"}


class YouTubeError(RuntimeError):
    def __init__(self, message: str, reason: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.reason = reason
        self.status = status


class AuthError(YouTubeError):
    """Refresh token missing/revoked/expired: the user must reconnect YouTube."""


class QuotaExceeded(YouTubeError):
    pass


def _error_reason(resp: httpx.Response) -> tuple[str, str]:
    try:
        err = resp.json().get("error", {})
    except ValueError:
        return "", resp.text[:200]
    if isinstance(err, str):  # OAuth endpoints: {"error": "invalid_grant", ...}
        return err, resp.json().get("error_description", err)
    reasons = [e.get("reason", "") for e in err.get("errors", []) if isinstance(e, dict)]
    return (reasons[0] if reasons else err.get("status", "")), err.get("message", "")


# --------------------------------------------------------------------------- OAuth

@dataclass
class PendingAuth:
    state: str
    verifier: str
    redirect_uri: str
    created: float = field(default_factory=time.time)


class OAuthFlow:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not client_id or not client_secret:
            raise AuthError("Add your Google OAuth Client ID and Secret first (Settings → YouTube).")
        register_secret(client_secret)
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.transport = transport

    def start(self) -> tuple[str, PendingAuth]:
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", PendingAuth(state, verifier, self.redirect_uri)

    def exchange(self, code: str, pending: PendingAuth) -> dict:
        with httpx.Client(timeout=30.0, transport=self.transport) as http:
            resp = http.post(TOKEN_URL, data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": pending.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": pending.verifier,
            })
        if resp.status_code >= 400:
            reason, message = _error_reason(resp)
            raise AuthError(f"Google refused the sign-in ({reason}): {message}", reason, resp.status_code)
        tokens = resp.json()
        if not tokens.get("refresh_token"):
            raise AuthError("Google did not return a refresh token. Remove ClipPilot's access at "
                            "myaccount.google.com/permissions and connect again.")
        register_secret(tokens.get("refresh_token"))
        register_secret(tokens.get("access_token"))
        return tokens


# --------------------------------------------------------------------------- API client

@dataclass
class UploadRequest:
    video_path: Path
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    privacy_status: str = "public"
    made_for_kids: bool = False
    category_id: str = "20"
    thumbnail_path: Path | None = None
    contains_synthetic_media: bool = False
    default_language: str = ""


@dataclass
class UploadResult:
    video_id: str
    privacy_status: str
    upload_status: str
    thumbnail_set: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://youtube.com/shorts/{self.video_id}"


class YouTubeClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 transport: httpx.BaseTransport | None = None, quota: QuotaTracker | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int = 5) -> None:
        if not refresh_token:
            raise AuthError("YouTube is not connected (Settings → Connect YouTube).")
        if not client_id or not client_secret:
            raise AuthError("Google OAuth Client ID/Secret missing (Settings → YouTube).")
        for value in (client_secret, refresh_token):
            register_secret(value)
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.http = httpx.Client(timeout=httpx.Timeout(60.0, write=300.0), transport=transport)
        self.quota = quota
        self.sleep = sleep
        self.max_retries = max_retries
        self._access: str | None = None
        self._access_exp = 0.0

    @classmethod
    def from_keystore(cls, store, quota: QuotaTracker | None = None, **kwargs) -> "YouTubeClient":
        return cls(store.get("google_client_id") or "", store.get("google_client_secret") or "",
                   store.get("youtube_refresh_token") or "", quota=quota, **kwargs)

    def close(self) -> None:
        self.http.close()

    # ------------------------------------------------------------------ auth
    def access_token(self, force: bool = False) -> str:
        if self._access and not force and time.time() < self._access_exp - 60:
            return self._access
        try:
            resp = self.http.post(TOKEN_URL, data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": self.refresh_token, "grant_type": "refresh_token",
            })
        except httpx.HTTPError as exc:
            raise YouTubeError(f"could not reach Google ({type(exc).__name__})", "network") from exc
        if resp.status_code >= 400:
            reason, message = _error_reason(resp)
            if reason in ("invalid_client", "unauthorized_client"):
                raise AuthError("Google rejected the OAuth client ID/secret. Check Settings → YouTube, then reconnect.",
                                reason, resp.status_code)
            if reason == "invalid_grant":
                raise AuthError(
                    "YouTube access expired or was revoked. Reconnect YouTube in Settings. "
                    "(Apps in Google 'Testing' mode lose access after 7 days - see the setup guide.)",
                    reason, resp.status_code)
            raise YouTubeError(f"token refresh failed ({reason}): {message}", reason, resp.status_code)
        data = resp.json()
        self._access = data["access_token"]
        register_secret(self._access)
        self._access_exp = time.time() + float(data.get("expires_in", 3600))
        return self._access

    def _backoff(self, attempt: int) -> None:
        delay = min(2 ** attempt + random.random(), 64)
        log.warning("YouTube API busy; retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, self.max_retries)
        self.sleep(delay)

    def request(self, method: str, url: str, *, quota_op: str | None = None, headers: dict | None = None,
                **kwargs) -> httpx.Response:
        if quota_op and self.quota and not self.quota.can_spend(quota_op):
            raise QuotaExceeded(f"Local quota budget exhausted for today ({quota_op})", "quotaExceeded", 403)
        for attempt in range(self.max_retries + 1):
            all_headers = {"Authorization": f"Bearer {self.access_token()}", **(headers or {})}
            try:
                resp = self.http.request(method, url, headers=all_headers, **kwargs)
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    raise YouTubeError(f"network error ({type(exc).__name__})", "network") from exc
                self._backoff(attempt)
                continue
            if resp.status_code == 401 and attempt == 0:
                self.access_token(force=True)
                continue
            if resp.status_code < 400:
                if quota_op and self.quota:
                    self.quota.spend(quota_op)
                return resp
            reason, message = _error_reason(resp)
            if reason in QUOTA_REASONS:
                if self.quota and reason != "uploadLimitExceeded":
                    self.quota.mark_exhausted()
                raise QuotaExceeded(f"YouTube {reason}: {message}", reason, resp.status_code)
            if (resp.status_code in RETRYABLE_STATUS or reason in RETRYABLE_REASONS) and attempt < self.max_retries:
                self._backoff(attempt)
                continue
            if resp.status_code == 401:
                raise AuthError(f"YouTube rejected the credentials: {message}", reason, 401)
            raise YouTubeError(f"YouTube API error {resp.status_code} ({reason}): {message}", reason, resp.status_code)
        raise YouTubeError("YouTube API kept failing", "retries", 0)

    # ------------------------------------------------------------------ endpoints
    def channel(self) -> dict:
        resp = self.request("GET", f"{API}/channels", params={"part": "snippet", "mine": "true"},
                            quota_op="channels.list")
        items = resp.json().get("items", [])
        if not items:
            raise YouTubeError("This Google account has no YouTube channel yet. Create one at youtube.com first.",
                               "noChannel")
        snip = items[0].get("snippet", {})
        thumb = (snip.get("thumbnails", {}).get("default") or {}).get("url", "")
        return {"id": items[0]["id"], "title": snip.get("title", ""), "thumbnail": thumb}

    def upload(self, req: UploadRequest, progress: Callable[[float], None] | None = None) -> UploadResult:
        path = Path(req.video_path)
        size = path.stat().st_size
        body = {
            "snippet": {
                "title": req.title,
                "description": req.description,
                "tags": req.tags,
                "categoryId": req.category_id,
            },
            "status": {
                "privacyStatus": req.privacy_status,
                "selfDeclaredMadeForKids": req.made_for_kids,
                "containsSyntheticMedia": req.contains_synthetic_media,
                "embeddable": True,
            },
        }
        if req.default_language:
            body["snippet"]["defaultLanguage"] = req.default_language
        init = self.request(
            "POST", f"{UPLOAD_API}/videos", quota_op="videos.insert",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={"Content-Type": "application/json; charset=UTF-8",
                     "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
            content=json.dumps(body).encode("utf-8"),
        )
        session = init.headers.get("Location")
        if not session:
            raise YouTubeError("YouTube did not return an upload session", "noSession", init.status_code)
        video = self._send_file(session, path, size, progress)
        result = UploadResult(
            video_id=video["id"],
            privacy_status=video.get("status", {}).get("privacyStatus", req.privacy_status),
            upload_status=video.get("status", {}).get("uploadStatus", ""),
        )
        log.info("Uploaded %s → %s", path.name, result.url)
        if req.thumbnail_path and Path(req.thumbnail_path).exists():
            try:
                self.set_thumbnail(result.video_id, Path(req.thumbnail_path))
                result.thumbnail_set = True
            except QuotaExceeded:
                result.warnings.append("Thumbnail skipped: quota exhausted")
            except YouTubeError as exc:
                msg = ("Custom thumbnails need a phone-verified YouTube channel"
                       if exc.status == 403 else f"Thumbnail not set: {exc}")
                result.warnings.append(msg)
                log.warning(msg)
        try:
            actual = self.video_status([result.video_id]).get(result.video_id, {})
            if actual.get("privacyStatus"):
                result.privacy_status = actual["privacyStatus"]
        except YouTubeError:
            pass
        if req.privacy_status != "private" and result.privacy_status == "private":
            result.warnings.append(
                "YouTube set this video to private. Uploads from Google Cloud projects that have not passed "
                "the YouTube API audit are locked to private - see the setup guide (API audit).")
        return result

    def _send_file(self, session: str, path: Path, size: int, progress: Callable[[float], None] | None) -> dict:
        offset = 0
        failures = 0
        with path.open("rb") as fh:
            while True:
                fh.seek(offset)
                chunk = fh.read(CHUNK)
                end = offset + len(chunk) - 1
                headers = {"Authorization": f"Bearer {self.access_token()}", "Content-Type": "video/mp4",
                           "Content-Range": f"bytes {offset}-{end}/{size}" if chunk else f"bytes */{size}"}
                try:
                    resp = self.http.put(session, content=chunk, headers=headers)
                except httpx.HTTPError:
                    failures += 1
                    if failures > self.max_retries:
                        raise YouTubeError("upload interrupted too many times", "network")
                    self._backoff(failures)
                    offset = self._query_offset(session, size)
                    continue
                if resp.status_code in (200, 201):
                    if progress:
                        progress(1.0)
                    return resp.json()
                if resp.status_code == 308:
                    rng = resp.headers.get("Range")
                    offset = int(rng.split("-")[-1]) + 1 if rng else 0
                    failures = 0
                    if progress:
                        progress(offset / size)
                    continue
                if resp.status_code == 401:
                    self.access_token(force=True)
                    continue
                reason, message = _error_reason(resp)
                if reason in QUOTA_REASONS:
                    raise QuotaExceeded(f"YouTube {reason}: {message}", reason, resp.status_code)
                if resp.status_code in RETRYABLE_STATUS and failures < self.max_retries:
                    failures += 1
                    self._backoff(failures)
                    offset = self._query_offset(session, size)
                    continue
                raise YouTubeError(f"upload failed {resp.status_code} ({reason}): {message}", reason, resp.status_code)

    def _query_offset(self, session: str, size: int) -> int:
        try:
            resp = self.http.put(session, content=b"", headers={
                "Authorization": f"Bearer {self.access_token()}", "Content-Range": f"bytes */{size}"})
        except httpx.HTTPError:
            return 0
        if resp.status_code == 308 and resp.headers.get("Range"):
            return int(resp.headers["Range"].split("-")[-1]) + 1
        return 0

    def set_thumbnail(self, video_id: str, image: Path) -> None:
        self.request("POST", f"{UPLOAD_API}/thumbnails/set", quota_op="thumbnails.set",
                     params={"videoId": video_id, "uploadType": "media"},
                     headers={"Content-Type": "image/jpeg"}, content=image.read_bytes())

    def video_status(self, video_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(video_ids), 50):
            resp = self.request("GET", f"{API}/videos", quota_op="videos.list",
                                params={"part": "status,statistics", "id": ",".join(video_ids[i:i + 50])})
            for v in resp.json().get("items", []):
                stats = v.get("statistics", {})
                out[v["id"]] = {
                    "privacyStatus": v.get("status", {}).get("privacyStatus", ""),
                    "uploadStatus": v.get("status", {}).get("uploadStatus", ""),
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                }
        return out

    def analytics(self, video_ids: list[str], start: date, end: date) -> dict[str, dict]:
        """Retention metrics per video (YouTube Analytics API; separate quota)."""
        out: dict[str, dict] = {}
        for i in range(0, len(video_ids), 200):
            ids = video_ids[i:i + 200]
            resp = self.request("GET", ANALYTICS_API, params={
                "ids": "channel==MINE",
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "metrics": "views,averageViewDuration,averageViewPercentage,likes",
                "dimensions": "video",
                "filters": "video==" + ",".join(ids),
                "maxResults": len(ids),
            })
            data = resp.json()
            cols = [h["name"] for h in data.get("columnHeaders", [])]
            for row in data.get("rows", []) or []:
                rec = dict(zip(cols, row))
                out[rec["video"]] = {
                    "views": int(rec.get("views", 0)),
                    "avg_view_duration": float(rec.get("averageViewDuration", 0)),
                    "avg_view_pct": float(rec.get("averageViewPercentage", 0)),
                    "likes": int(rec.get("likes", 0)),
                }
        return out

    def revoke(self) -> None:
        try:
            self.http.post(REVOKE_URL, data={"token": self.refresh_token})
        except httpx.HTTPError:
            pass
