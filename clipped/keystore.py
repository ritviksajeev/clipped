"""Secret storage in the operating system keyring.

* Windows: Credential Manager, macOS: Keychain, Linux: Secret Service/KWallet.
* When no OS keyring is available (headless Linux, Docker) we fall back to a
  JSON file in the data directory with owner-only permissions, and the UI says
  so plainly.
* Secrets are never logged, never returned by the API (only a masked hint),
  and only ever sent to the provider they belong to.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import keyring
import keyring.errors

from . import config
from .logs import get_logger, register_secret

log = get_logger("keystore")

SERVICE = "clipped"

SECRET_NAMES = {
    "twitch_client_id": "Twitch Client ID",
    "twitch_client_secret": "Twitch Client Secret",
    "google_client_id": "Google OAuth Client ID",
    "google_client_secret": "Google OAuth Client Secret",
    "youtube_refresh_token": "YouTube refresh token (set by Connect YouTube)",
    "anthropic_api_key": "Anthropic API key",
    "openai_api_key": "OpenAI API key",
    "gemini_api_key": "Google Gemini API key",
    "openrouter_api_key": "OpenRouter key (set by Connect OpenRouter)",
}


class FileSecretBackend:
    """Owner-only JSON file. Used only when the OS keyring is unavailable."""

    name = "file (OS keyring unavailable)"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, str]) -> None:
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - Windows
            pass

    def get(self, name: str) -> str | None:
        with self._lock:
            return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        with self._lock:
            data = self._read()
            data[name] = value
            self._write(data)

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._read()
            if name in data:
                del data[name]
                self._write(data)


class OSKeyringBackend:
    def __init__(self, backend=None) -> None:
        self.backend = backend or keyring.get_keyring()
        self.name = f"OS keyring ({type(self.backend).__name__})"

    def get(self, name: str) -> str | None:
        return self.backend.get_password(SERVICE, name)

    def set(self, name: str, value: str) -> None:
        self.backend.set_password(SERVICE, name, value)

    def delete(self, name: str) -> None:
        try:
            self.backend.delete_password(SERVICE, name)
        except keyring.errors.PasswordDeleteError:
            pass


def _os_keyring_usable() -> bool:
    try:
        backend = keyring.get_keyring()
    except Exception:  # pragma: no cover
        return False
    module = type(backend).__module__
    if module.startswith("keyring.backends.fail") or module.startswith("keyring.backends.null"):
        return False
    try:
        if float(getattr(backend, "priority", 1)) <= 0:
            return False
    except Exception:  # pragma: no cover
        pass
    return True


class KeyStore:
    def __init__(self, backend=None) -> None:
        if backend is not None:
            self.backend = backend
        elif os.environ.get("CLIPPED_SECRETS_FILE") or not _os_keyring_usable():
            path = Path(os.environ.get("CLIPPED_SECRETS_FILE") or (config.data_dir() / "secrets.json"))
            self.backend = FileSecretBackend(path)
        else:
            self.backend = OSKeyringBackend()

    @property
    def backend_name(self) -> str:
        return getattr(self.backend, "name", type(self.backend).__name__)

    @property
    def is_os_keyring(self) -> bool:
        return not isinstance(self.backend, FileSecretBackend)

    def get(self, name: str) -> str | None:
        self._check(name)
        env_value = os.environ.get(f"CLIPPED_{name.upper()}")
        value = env_value or self.backend.get(name)
        register_secret(value)
        return value

    def set(self, name: str, value: str) -> None:
        self._check(name)
        value = (value or "").strip()
        if not value:
            self.delete(name)
            return
        register_secret(value)
        self.backend.set(name, value)
        log.info("Saved %s to %s", SECRET_NAMES[name], self.backend_name)

    def delete(self, name: str) -> None:
        self._check(name)
        self.backend.delete(name)

    def status(self) -> dict[str, dict]:
        result = {}
        for name, label in SECRET_NAMES.items():
            value = self.get(name)
            result[name] = {
                "label": label,
                "set": bool(value),
                "hint": mask(value) if value else "",
            }
        return result

    @staticmethod
    def _check(name: str) -> None:
        if name not in SECRET_NAMES:
            raise KeyError(f"Unknown secret {name!r}")


def mask(value: str) -> str:
    if len(value) <= 8:
        return "•" * len(value)
    return "••••" + value[-4:]
