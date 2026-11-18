"""Logging with secret redaction and a live in-memory buffer for the dashboard.

Secrets are registered with :func:`register_secret` whenever they are read from
the keyring, and every log record is scrubbed before it reaches any handler,
so a stray ``log.info(token)`` can never write a key to disk or the UI.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import logging.handlers
import re
import threading
import time
from typing import Any

_SECRETS: set[str] = set()
_SECRETS_LOCK = threading.Lock()

# Generic patterns that look like credentials even if we never registered them.
_PATTERNS = [
    (re.compile(r"(?i)(authorization:\s*(?:bearer|oauth)\s+)[^\s'\"]+"), r"\1***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]{8,}"), r"\1***"),
    (re.compile(r"(?i)((?:access|refresh|id)_token[\"']?\s*[:=]\s*[\"']?)[^\s&\"',}]+"), r"\1***"),
    (re.compile(r"(?i)(client_secret[\"']?\s*[:=]\s*[\"']?)[^\s&\"',}]+"), r"\1***"),
    (re.compile(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\s&\"',}]+"), r"\1***"),
    (re.compile(r"(?i)([?&](?:code|key)=)[^\s&\"']+"), r"\1***"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-***"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "sk-***"),
    (re.compile(r"ya29\.[A-Za-z0-9_\-]{10,}"), "ya29.***"),
    (re.compile(r"1//[A-Za-z0-9_\-]{20,}"), "1//***"),
    (re.compile(r"GOCSPX-[A-Za-z0-9_\-]{6,}"), "GOCSPX-***"),
]


def register_secret(value: str | None) -> None:
    if value and len(value) >= 6:
        with _SECRETS_LOCK:
            _SECRETS.add(value)


def redact(text: str) -> str:
    if not text:
        return text
    with _SECRETS_LOCK:
        secrets = sorted(_SECRETS, key=len, reverse=True)
    for secret in secrets:
        if secret in text:
            text = text.replace(secret, "***")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            record.exc_text = redact(
                logging.Formatter().formatException(record.exc_info)
            )
            record.exc_info = None
            del exc
        return True


class LiveLogBuffer(logging.Handler):
    """Keeps the most recent log lines and fans new ones out to SSE listeners."""

    def __init__(self, capacity: int = 1500) -> None:
        super().__init__()
        self.records: collections.deque[dict[str, Any]] = collections.deque(maxlen=capacity)
        self._listeners: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "seq": 0,
            "ts": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_text:
            entry["message"] += "\n" + redact(record.exc_text)
        with self._lock:
            self._seq += 1
            entry["seq"] = self._seq
            self.records.append(entry)
            listeners = list(self._listeners)
        for loop, queue in listeners:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, entry)
            except RuntimeError:
                pass

    def tail(self, limit: int = 300) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.records)[-limit:]

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._listeners.append((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._listeners = [(l, q) for (l, q) in self._listeners if q is not queue]


live_buffer = LiveLogBuffer()
_configured = False


def setup_logging(log_dir=None, level: int = logging.INFO, console: bool = True) -> None:
    global _configured
    root = logging.getLogger()
    if _configured:
        return
    _configured = True
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    redactor = RedactingFilter()

    handlers: list[logging.Handler] = [live_buffer]
    if console:
        handlers.append(logging.StreamHandler())
    if log_dir is not None:
        handlers.append(
            logging.handlers.RotatingFileHandler(
                str(log_dir / "clipped.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8"
            )
        )
    for handler in handlers:
        handler.addFilter(redactor)
        handler.setFormatter(fmt)
        root.addHandler(handler)
    for noisy in ("httpx", "httpcore", "urllib3", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"clipped.{name}")
