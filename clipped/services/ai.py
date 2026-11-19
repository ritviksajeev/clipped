"""Connect an AI model for titles without copy-pasting API keys.

Three ways in, all optional (the free template generator always works):

* **Anthropic**: sign in with the Anthropic CLI (``ant auth login``). It opens
  the browser, the user approves, and the CLI saves a login profile that the
  official ``anthropic`` SDK reads by itself (and refreshes) — clipped never
  sees or stores a key. This is an Anthropic Console (API) account; Claude.ai
  Pro/Max chat subscriptions cannot be used by other apps.
* **OpenRouter**: OAuth PKCE. The user approves clipped on openrouter.ai and we
  receive a key scoped to them, saved in the OS keyring like every other
  secret. One account covers Claude, GPT, Gemini, Llama and free models.
* **Ollama**: a model running locally. No account, no key, no cost.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

import httpx

from ..logs import get_logger
from ..proc import hidden

log = get_logger("ai")

OPENROUTER_AUTH_URL = "https://openrouter.ai/auth"
OPENROUTER_KEYS_URL = "https://openrouter.ai/api/v1/auth/keys"
OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434"
ANT_RELEASES_URL = "https://github.com/anthropics/anthropic-cli/releases"
PENDING_TTL = 15 * 60  # seconds an OpenRouter approval may take


class AIConnectError(RuntimeError):
    pass


# --------------------------------------------------------------------------- Anthropic sign-in

def anthropic_config_dir() -> Path:
    """Where the Anthropic CLI and SDKs keep login profiles."""
    env = os.environ.get("ANTHROPIC_CONFIG_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return (Path(appdata) if appdata else Path.home() / "AppData" / "Roaming") / "Anthropic"
    return Path.home() / ".config" / "anthropic"


def _active_profile(base: Path) -> str:
    name = os.environ.get("ANTHROPIC_PROFILE", "").strip()
    if not name:
        try:
            name = (base / "active_config").read_text("utf-8").strip()
        except OSError:
            name = ""
    name = name or "default"
    return name if re.fullmatch(r"[\w.-]+", name) and not name.startswith(".") else "default"


def ant_cli() -> str | None:
    """Path to the Anthropic CLI, if installed."""
    found = shutil.which("ant")
    if found:
        return found
    if sys.platform == "win32":  # common install spots that may not be on PATH yet
        for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles")):
            if base:
                for cand in (Path(base) / "Programs" / "ant" / "ant.exe", Path(base) / "ant" / "ant.exe"):
                    if cand.is_file():
                        return str(cand)
    return None


def anthropic_profile() -> dict:
    """Whether an Anthropic login profile exists (never reads the token itself)."""
    base = anthropic_config_dir()
    profile = _active_profile(base)
    signed_in = (base / "configs" / f"{profile}.json").is_file() and \
        (base / "credentials" / f"{profile}.json").is_file()
    return {"signed_in": signed_in, "profile": profile, "cli": bool(ant_cli()), "install_url": ANT_RELEASES_URL}


def anthropic_env_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def credentials(store) -> dict:
    """What the title generator may use. Values are secrets: never log this dict."""
    return {
        "anthropic_api_key": store.get("anthropic_api_key"),
        "openai_api_key": store.get("openai_api_key"),
        "openrouter_api_key": store.get("openrouter_api_key"),
        "gemini_api_key": store.get("gemini_api_key"),
        "anthropic_signed_in": anthropic_profile()["signed_in"] or anthropic_env_key(),
    }


@dataclass
class LoginState:
    state: str = "idle"  # idle | waiting | done | failed
    message: str = ""
    url: str = ""  # the approval page, in case the browser did not open by itself
    started_at: float = 0.0


class AnthropicLogin:
    """Runs ``ant auth login`` in the background and reports progress."""

    URL_RE = re.compile(r"https://\S+")

    def __init__(self, runner=None) -> None:
        self._lock = threading.Lock()
        self.status = LoginState()
        self._proc: subprocess.Popen | None = None
        self._runner = runner or subprocess.Popen

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self.status.state, "message": self.status.message, "url": self.status.url}

    def start(self) -> dict:
        cli = ant_cli()
        if not cli:
            raise AIConnectError("The Anthropic CLI (ant) is not installed. Install it, then click again.")
        with self._lock:
            if self.status.state == "waiting" and self._proc and self._proc.poll() is None:
                return {"state": "waiting", "message": self.status.message, "url": self.status.url}
            self.status = LoginState("waiting", "Approve clipped in the browser window that just opened.",
                                     started_at=time.time())
            self._proc = self._runner([cli, "auth", "login"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                      **hidden())
        threading.Thread(target=self._watch, args=(self._proc,), daemon=True, name="ant-login").start()
        return self.snapshot()

    def _watch(self, proc) -> None:
        tail: list[str] = []
        try:
            for line in proc.stdout or []:
                line = line.strip()
                if not line:
                    continue
                tail = (tail + [line])[-6:]
                match = self.URL_RE.search(line)
                if match:
                    with self._lock:
                        self.status.url = match.group(0).rstrip(".,)")
            code = proc.wait(timeout=15 * 60)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = -1
            tail.append("timed out waiting for approval")
        with self._lock:
            if code == 0 and anthropic_profile()["signed_in"]:
                self.status.state, self.status.message = "done", "Signed in to Anthropic."
                log.info("Anthropic sign-in complete")
            else:
                # The CLI output never carries the token itself, but keep only a short tail.
                self.status.state = "failed"
                self.status.message = "Sign-in did not finish" + (f": {tail[-1][:200]}" if tail else ".")
                log.warning("Anthropic sign-in failed (exit %s)", code)


# --------------------------------------------------------------------------- OpenRouter OAuth PKCE

def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@dataclass
class OpenRouterConnect:
    """One pending approval at a time; the verifier never leaves this process."""

    _pending: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, callback_url: str, desktop: bool = False) -> str:
        verifier, challenge = pkce_pair()
        with self._lock:
            self._pending = {"verifier": verifier, "at": time.time(), "callback": callback_url, "desktop": desktop}
        query = urlencode({"callback_url": callback_url, "code_challenge": challenge,
                           "code_challenge_method": "S256"})
        return f"{OPENROUTER_AUTH_URL}?{query}"

    @property
    def desktop(self) -> bool:
        with self._lock:
            return bool(self._pending.get("desktop"))

    def finish(self, code: str, transport: httpx.BaseTransport | None = None) -> str:
        with self._lock:
            pending, self._pending = self._pending, {}
        if not pending or time.time() - pending["at"] > PENDING_TTL:
            raise AIConnectError("No OpenRouter connection was in progress (or it expired). Click Connect again.")
        if not re.fullmatch(r"[\w\-.~]{4,512}", code or ""):
            raise AIConnectError("OpenRouter returned an unexpected code.")
        try:
            with httpx.Client(timeout=30.0, transport=transport) as http:
                resp = http.post(OPENROUTER_KEYS_URL, json={"code": code, "code_verifier": pending["verifier"],
                                                            "code_challenge_method": "S256"})
        except httpx.HTTPError as exc:
            raise AIConnectError("Could not reach OpenRouter.") from exc
        if resp.status_code >= 400:
            raise AIConnectError(f"OpenRouter refused the connection (HTTP {resp.status_code}).")
        try:
            key = resp.json()["key"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AIConnectError("OpenRouter returned an unexpected response.") from exc
        if not isinstance(key, str) or len(key) < 10:
            raise AIConnectError("OpenRouter returned an empty key.")
        return key


# --------------------------------------------------------------------------- Ollama

def ollama_models(base_url: str = OLLAMA_DEFAULT_URL, transport: httpx.BaseTransport | None = None) -> list[str]:
    """Installed local models, or raises AIConnectError if Ollama is not running."""
    url = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")
    if not re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", url):
        raise AIConnectError("Ollama must run on this computer (localhost).")
    try:
        with httpx.Client(timeout=3.0, transport=transport) as http:
            resp = http.get(f"{url}/api/tags")
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AIConnectError("Ollama is not running on this computer.") from exc
    return [m.get("name") or m.get("model") for m in data.get("models", []) if m.get("name") or m.get("model")]


def ollama_status(base_url: str = OLLAMA_DEFAULT_URL, transport: httpx.BaseTransport | None = None) -> dict:
    try:
        models = ollama_models(base_url, transport)
        return {"running": True, "models": models, "url": base_url}
    except AIConnectError as exc:
        return {"running": False, "models": [], "url": base_url, "message": str(exc)}


def json_from_text(text: str) -> dict:
    """Parse a JSON object out of a model reply that may wrap it in prose or fences."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])
