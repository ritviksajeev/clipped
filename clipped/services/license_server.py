"""Talks to the licence server on evzero.org (Vercel functions, ev repo: api/clipped/).

Only three things go there: the licence key, this computer's anonymous id
(see clipped.device), and a random one-time nonce while a free unlock is being
fetched. Answers that unlock anything are signed with evzero's key, so a fake
server can't hand out access.
"""

from __future__ import annotations

import os
from urllib.parse import urlencode

import httpx

SERVER = os.environ.get("CLIPPED_LICENSE_SERVER", "https://evzero.org/api/clipped").rstrip("/")
SITE = os.environ.get("CLIPPED_SITE", "https://evzero.org").rstrip("/")
OFFLINE = "Couldn't reach evzero.org to check your key. Check your internet connection and try again."


class LicenseServerError(RuntimeError):
    def __init__(self, message: str, code: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _call(method: str, path: str, *, body: dict | None = None, params: dict | None = None,
          transport: httpx.BaseTransport | None = None) -> dict:
    try:
        with httpx.Client(timeout=20.0, transport=transport, follow_redirects=True) as http:
            resp = http.request(method, f"{SERVER}/{path}/", json=body, params=params,
                                headers={"User-Agent": "clipped-app"})
    except httpx.HTTPError as exc:
        raise LicenseServerError(OFFLINE, "offline") from exc
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        raise LicenseServerError(str(data.get("error") or f"The licence server answered HTTP {resp.status_code}."),
                                 str(data.get("code") or ""), resp.status_code)
    return data if isinstance(data, dict) else {}


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
