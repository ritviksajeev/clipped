"""Twitch Helix API client (app access token / client-credentials flow).

Uses only the user's own Client ID + Secret. Requests go directly from the
user's machine to Twitch.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

import httpx

from ..logs import get_logger, register_secret
from ..models import ClipInfo

log = get_logger("twitch")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX = "https://api.twitch.tv/helix"


class TwitchError(RuntimeError):
    pass


class TwitchAuthError(TwitchError):
    pass


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def box_art(url: str, w: int = 144, h: int = 192) -> str:
    return url.replace("{width}", str(w)).replace("{height}", str(h)).replace("52x72", f"{w}x{h}")


class TwitchClient:
    def __init__(self, client_id: str, client_secret: str, transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> None:
        if not client_id or not client_secret:
            raise TwitchAuthError("Twitch Client ID and Secret are required (Settings → Twitch).")
        register_secret(client_secret)
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = httpx.Client(timeout=30.0, transport=transport)
        self.clock = clock
        self.sleep = sleep
        self._token: str | None = None
        self._expires_at = 0.0

    @classmethod
    def from_keystore(cls, store, **kwargs) -> "TwitchClient":
        return cls(store.get("twitch_client_id") or "", store.get("twitch_client_secret") or "", **kwargs)

    def close(self) -> None:
        self.http.close()

    # ------------------------------------------------------------------ auth
    def _access_token(self, force: bool = False) -> str:
        if self._token and not force and self.clock() < self._expires_at - 60:
            return self._token
        try:
            resp = self.http.post(TOKEN_URL, data={
                "client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "client_credentials",
            })
        except httpx.HTTPError as exc:
            raise TwitchError(f"could not reach Twitch ({type(exc).__name__})") from exc
        if resp.status_code in (400, 401, 403):
            raise TwitchAuthError("Twitch rejected the Client ID / Secret. Check them in Settings.")
        if resp.status_code >= 400:
            raise TwitchError(f"Twitch token endpoint returned {resp.status_code}")
        data = resp.json()
        self._token = data["access_token"]
        register_secret(self._token)
        self._expires_at = self.clock() + float(data.get("expires_in", 3600))
        return self._token

    def _get(self, path: str, params: dict | list | None = None) -> dict:
        for attempt in range(4):
            headers = {"Client-Id": self.client_id, "Authorization": f"Bearer {self._access_token()}"}
            try:
                resp = self.http.get(f"{HELIX}/{path}", params=params, headers=headers)
            except httpx.HTTPError as exc:
                if attempt == 3:
                    raise TwitchError(f"network error talking to Twitch ({type(exc).__name__})") from exc
                self.sleep(2 ** attempt)
                continue
            if resp.status_code == 401:
                self._token = None  # expired or revoked: get a new app token once
                if attempt == 0:
                    continue
                raise TwitchAuthError("Twitch rejected the access token")
            if resp.status_code == 429:
                reset = float(resp.headers.get("Ratelimit-Reset", self.clock() + 5))
                wait = min(max(reset - self.clock(), 1.0), 60.0)
                log.warning("Twitch rate limit reached; waiting %.0fs", wait)
                self.sleep(wait)
                continue
            if resp.status_code >= 500:
                self.sleep(2 ** attempt)
                continue
            if resp.status_code >= 400:
                raise TwitchError(f"Twitch API {path} returned {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        raise TwitchError(f"Twitch API {path} kept failing")

    # ------------------------------------------------------------------ endpoints
    def validate(self) -> bool:
        self._access_token(force=True)
        return True

    def search_categories(self, query: str, first: int = 20) -> list[dict]:
        if not query.strip():
            return self.top_categories(first)
        data = self._get("search/categories", {"query": query.strip(), "first": min(first, 100)})
        return [{"id": c["id"], "name": c["name"], "box_art_url": box_art(c.get("box_art_url", ""))}
                for c in data.get("data", [])]

    def top_categories(self, first: int = 20) -> list[dict]:
        data = self._get("games/top", {"first": min(first, 100)})
        return [{"id": c["id"], "name": c["name"], "box_art_url": box_art(c.get("box_art_url", ""))}
                for c in data.get("data", [])]

    def get_users(self, user_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        ids = [i for i in dict.fromkeys(user_ids) if i]
        for i in range(0, len(ids), 100):
            data = self._get("users", [("id", uid) for uid in ids[i:i + 100]])
            for u in data.get("data", []):
                out[u["id"]] = {"login": u.get("login", ""), "display_name": u.get("display_name", "")}
        return out

    def get_clips(self, game_id: str, started_at: datetime, ended_at: datetime | None = None,
                  max_clips: int = 100, game_name: str = "") -> list[ClipInfo]:
        """Most-viewed clips in a category within a time window (Helix sorts by views)."""
        ended_at = ended_at or datetime.now(timezone.utc)
        clips: list[ClipInfo] = []
        cursor = None
        while len(clips) < max_clips:
            params = {"game_id": game_id, "started_at": _rfc3339(started_at), "ended_at": _rfc3339(ended_at),
                      "first": min(100, max_clips - len(clips))}
            if cursor:
                params["after"] = cursor
            data = self._get("clips", params)
            for c in data.get("data", []):
                clips.append(clip_from_helix(c, game_name))
            cursor = (data.get("pagination") or {}).get("cursor")
            if not cursor or not data.get("data"):
                break
        users = self.get_users([c.broadcaster_id for c in clips])
        for c in clips:
            if c.broadcaster_id in users:
                c.broadcaster_login = users[c.broadcaster_id]["login"]
        return clips


def clip_from_helix(c: dict, game_name: str = "") -> ClipInfo:
    created = c.get("created_at")
    return ClipInfo(
        id=c["id"],
        url=c.get("url") or f"https://clips.twitch.tv/{c['id']}",
        title=c.get("title", ""),
        broadcaster_name=c.get("broadcaster_name", ""),
        broadcaster_id=c.get("broadcaster_id", ""),
        creator_name=c.get("creator_name", ""),
        game_id=c.get("game_id", ""),
        game_name=game_name,
        language=c.get("language", ""),
        view_count=int(c.get("view_count", 0)),
        created_at=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
        duration=float(c.get("duration", 0) or 0),
        video_id=c.get("video_id", "") or "",
        vod_offset=c.get("vod_offset"),
        thumbnail_url=c.get("thumbnail_url", ""),
    )
