"""Talks to the clipped licence server (ev repo: api/clipped/, or api/_lib/serve.js).

Only three things go there: the licence key, this computer's anonymous id
(see clipped.device), and a random one-time nonce while a free unlock is being
fetched. Answers that unlock anything are signed with evzero's key, so a fake
server can't hand out access.

The server can live on any host: the app asks evzero.org/clipped/api.json where
it is (and remembers the answer for a few hours), so it can move without an app
update. CLIPPED_LICENSE_SERVER skips the lookup (tests, local runs).
"""

from __future__ import annotations

import os
import re
import threading
import time
from urllib.parse import urlencode

import httpx

SITE = os.environ.get("CLIPPED_SITE", "https://evzero.org").rstrip("/")
OVERRIDE = os.environ.get("CLIPPED_LICENSE_SERVER", "").rstrip("/")
LOOKUP_TTL = 6 * 3600
OFFLINE = "Couldn't reach evzero.org to check your key. Check your internet connection and try again."
NOT_LIVE = "Free days and Pro aren't switched on yet. Check evzero.org/clipped for news, or use a key you already have."
HEADERS = {"User-Agent": "clipped-app"}
_VALID = re.compile(r"^(https://[A-Za-z0-9.-]+(:\d+)?|http://(127\.0\.0\.1|localhost)(:\d+)?)(/[A-Za-z0-9._~/-]*)?$")

_lock = threading.Lock()
_found: tuple[float, str] | None = None  # (when, base url) from api.json


class LicenseServerError(RuntimeError):
    def __init__(self, message: str, code: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def server(transport: httpx.BaseTransport | None = None) -> str:
    """The licence server's base URL, e.g. https://api.example.org/clipped."""
    global _found
    if OVERRIDE:
        return OVERRIDE
    with _lock:
        if _found and time.monotonic() - _found[0] < LOOKUP_TTL:
            return _found[1]
        last = _found
    try:
        with httpx.Client(timeout=10.0, transport=transport, follow_redirects=True) as http:
            resp = http.get(f"{SITE}/clipped/api.json", headers=HEADERS)
        api = str(resp.json().get("api") or "").strip().rstrip("/") if resp.status_code == 200 else ""
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        if last:  # keep using the last good answer while evzero.org is unreachable
            return last[1]
        raise LicenseServerError(OFFLINE, "offline") from exc
    if not api or not _VALID.match(api):
        raise LicenseServerError(NOT_LIVE, "not_live")
    with _lock:
        _found = (time.monotonic(), api)
    return api


def forget() -> None:
    """Ask api.json again next time (tests, or after the server answered from a stale address)."""
    global _found
    with _lock:
        _found = None


def _call(method: str, path: str, *, body: dict | None = None, params: dict | None = None,
          transport: httpx.BaseTransport | None = None) -> dict:
    base = server(transport)
    try:
        with httpx.Client(timeout=20.0, transport=transport, follow_redirects=True) as http:
            resp = http.request(method, f"{base}/{path}/", json=body, params=params, headers=HEADERS)
    except httpx.HTTPError as exc:
        raise LicenseServerError(OFFLINE, "offline") from exc
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if resp.status_code >= 400:
        if resp.status_code == 404 and not data.get("code"):
            forget()  # moved? look it up again next time
        raise LicenseServerError(str(data.get("error") or f"The licence server answered HTTP {resp.status_code}."),
                                 str(data.get("code") or ""), resp.status_code)
    return data


def activate(key: str, device: str, force: bool = False, transport=None) -> dict:
    return _call("POST", "activate", body={"key": key, "device": device, "force": force}, transport=transport)


def deactivate(key: str, device: str, transport=None) -> dict:
    return _call("POST", "deactivate", body={"key": key, "device": device}, transport=transport)


def pickup(nonce: str, transport=None) -> dict | None:
    data = _call("GET", "pickup", params={"nonce": nonce}, transport=transport)
    return None if data.get("pending") else data


def free_url(device: str, nonce: str, mode: str = "day", key_id: str = "", n: int = 0) -> str:
    """The page on evzero.org where the ads are watched."""
    query = {"d": device, "nonce": nonce, "mode": mode}
    if mode == "wm":
        query.update(k=key_id, n=str(n))
    return f"{SITE}/clipped/free/?{urlencode(query)}"


def buy_url() -> str:
    return f"{SITE}/clipped/buy/"
