"""Post Shorts to Instagram as Reels, with Instagram's official API.

Needs an Instagram professional account (Business or Creator) and an access
token from a Meta developer app ("Instagram API with Instagram login"). The
token is pasted once in Settings and kept in the OS keychain like every other
secret; clipped refreshes it before its 60 days run out.

A Reel is published in four steps:

1. create a REELS media container set up for a resumable upload;
2. upload the video file to the address Instagram returns;
3. wait while Instagram processes it (status FINISHED);
4. publish the container, then read back its permalink.

Tokens only ever go to graph.instagram.com / rupload.facebook.com and are never
written to the log (errors are reported without URLs).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from ..logs import get_logger

log = get_logger("instagram")

GRAPH = "https://graph.instagram.com"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"
CAPTION_MAX = 2200
HASHTAGS_MAX = 30
PROCESS_TIMEOUT = 15 * 60  # seconds Instagram may take to process a Reel
POLL_EVERY = 5.0


class InstagramError(RuntimeError):
    pass


class InstagramAuthError(InstagramError):
    """The token is invalid, expired or missing a permission: paste a new one."""


@dataclass
class ReelResult:
    media_id: str
    permalink: str


def build_caption(title: str, description: str) -> str:
    """Title, then the description (with its streamer credit and links), within Instagram's limits."""
    text = f"{title.strip()}\n\n{description.strip()}".strip()
    count = 0

    def keep(match: re.Match) -> str:
        nonlocal count
        count += 1
        return match.group(0) if count <= HASHTAGS_MAX else ""

    text = re.sub(r"(?<!\S)#\w+", keep, text)  # Instagram rejects captions with more than 30 hashtags
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+(\n|$)", r"\1", text).strip()
    return text if len(text) <= CAPTION_MAX else text[:CAPTION_MAX - 1].rstrip() + "…"


def _error(resp: httpx.Response, doing: str) -> InstagramError:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    code, sub = err.get("code"), err.get("error_subcode")
    message = (err.get("error_user_msg") or err.get("message") or f"HTTP {resp.status_code}").strip()
    if code == 190 or resp.status_code == 401:
        return InstagramAuthError(f"Instagram rejected the access token while {doing} ({message}). "
                                  "Paste a new token in Settings → Connections.")
    if code in (10, 200) or (code == 100 and "permission" in message.lower()):
        return InstagramAuthError(f"The token is missing a permission ({message}). It needs "
                                  "instagram_business_basic and instagram_business_content_publish.")
    if sub == 2207042 or code in (4, 17, 32, 613):
        return InstagramError(f"Instagram's posting limit was reached while {doing} ({message}). Try again later.")
    return InstagramError(f"Instagram error while {doing}: {message}")


class InstagramClient:
    def __init__(self, token: str, *, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        if not token:
            raise InstagramAuthError("No Instagram access token saved.")
        self.token = token
        self.http = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), transport=transport)
        self.sleep = sleep
        self.clock = clock

    def close(self) -> None:
        self.http.close()

    def _get(self, path: str, params: dict, doing: str) -> dict:
        try:
            resp = self.http.get(f"{GRAPH}/{path}", params={**params, "access_token": self.token})
        except httpx.HTTPError as exc:
            raise InstagramError(f"Couldn't reach Instagram while {doing}.") from exc
        if resp.status_code >= 400:
            raise _error(resp, doing)
        return resp.json()

    def _post(self, path: str, data: dict, doing: str) -> dict:
        try:
            resp = self.http.post(f"{GRAPH}/{path}", data={**data, "access_token": self.token})
        except httpx.HTTPError as exc:
            raise InstagramError(f"Couldn't reach Instagram while {doing}.") from exc
        if resp.status_code >= 400:
            raise _error(resp, doing)
        return resp.json()

    def me(self) -> dict:
        """The account the token belongs to: {"user_id", "username", "account_type"}."""
        data = self._get("me", {"fields": "user_id,username,account_type"}, "checking the account")
        if not data.get("user_id"):
            raise InstagramError("Instagram didn't say which account this token is for.")
        return data

    def refresh(self) -> tuple[str, int]:
        """Swap the long-lived token for a fresh 60-day one. Returns (token, seconds until it expires)."""
        data = self._get("refresh_access_token", {"grant_type": "ig_refresh_token"}, "refreshing the token")
        token = data.get("access_token")
        if not token:
            raise InstagramError("Instagram didn't return a refreshed token.")
        self.token = token
        return token, int(data.get("expires_in") or 0)

    def publish_reel(self, user_id: str, video: Path, caption: str, *, share_to_feed: bool = True,
                     thumb_offset_ms: int | None = None, progress: Callable[[float], None] | None = None) -> ReelResult:
        data = {"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                "share_to_feed": "true" if share_to_feed else "false"}
        if thumb_offset_ms is not None:
            data["thumb_offset"] = str(max(0, int(thumb_offset_ms)))
        container = self._post(f"{user_id}/media", data, "creating the Reel")
        cid = container.get("id")
        if not cid:
            raise InstagramError("Instagram didn't create a Reel container.")
        upload_url = container.get("uri") or f"{RUPLOAD}/{cid}"
        size = video.stat().st_size
        if progress:
            progress(0.05)
        try:
            with video.open("rb") as fh:
                resp = self.http.post(upload_url, content=fh, timeout=httpx.Timeout(600.0, connect=15.0),
                                      headers={"Authorization": f"OAuth {self.token}", "offset": "0",
                                               "file_size": str(size), "Content-Type": "application/octet-stream"})
        except httpx.HTTPError as exc:
            raise InstagramError("The video upload to Instagram was interrupted.") from exc
        if resp.status_code >= 400:
            raise _error(resp, "uploading the video")
        if progress:
            progress(0.6)

        started = self.clock()
        while True:
            state = self._get(cid, {"fields": "status_code,status"}, "waiting for Instagram to process the video")
            code = (state.get("status_code") or "").upper()
            if code in ("FINISHED", "PUBLISHED"):
                break
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Instagram couldn't process the video ({state.get('status') or code}).")
            if self.clock() - started > PROCESS_TIMEOUT:
                raise InstagramError("Instagram took too long to process the video; it will be retried.")
            self.sleep(POLL_EVERY)
        if progress:
            progress(0.9)

        published = self._post(f"{user_id}/media_publish", {"creation_id": cid}, "publishing the Reel")
        media_id = published.get("id")
        if not media_id:
            raise InstagramError("Instagram didn't confirm the Reel was published.")
        permalink = ""
        try:
            permalink = self._get(media_id, {"fields": "permalink"}, "reading the Reel's link").get("permalink", "")
        except InstagramError as exc:
            log.warning("Reel published, but its link couldn't be read: %s", exc)
        if progress:
            progress(1.0)
        return ReelResult(media_id=media_id, permalink=permalink)
