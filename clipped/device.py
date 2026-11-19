"""A stable, anonymous id for this computer (16 hex characters).

Free day keys and Pro keys are locked to one computer with it. It's a one-way
hash of the id the operating system already keeps for the machine (Windows'
MachineGuid, the Mac's hardware UUID, Linux's machine-id), so the real id never
leaves the computer and the value means nothing outside clipped.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import subprocess
import sys
from functools import lru_cache

from . import config
from .proc import hidden

SALT = b"clipped-device-v1:"


def _windows_guid() -> str:
    import winreg

    flags = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, flags) as key:
        return str(winreg.QueryValueEx(key, "MachineGuid")[0])


def _mac_uuid() -> str:
    out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True,
                         timeout=5, **hidden()).stdout
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
    return match.group(1) if match else ""


def _linux_id() -> str:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = open(path, encoding="utf-8").read().strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def _system_id() -> str:
    try:
        if sys.platform == "win32":
            return _windows_guid()
        if sys.platform == "darwin":
            return _mac_uuid()
        return _linux_id()
    except Exception:  # unreadable: fall back to an id of our own
        return ""


def _saved_id() -> str:
    """A random id kept in the data folder, for systems that won't tell us theirs."""
    path = config.data_dir() / "device-id"
    try:
        value = path.read_text("utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{32}", value):
            return value
    except OSError:
        pass
    value = secrets.token_hex(16)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, "utf-8")
    except OSError:
        pass
    return value


@lru_cache(maxsize=1)
def device_id() -> str:
    raw = _system_id() or _saved_id()
    return hashlib.sha256(SALT + raw.encode("utf-8")).hexdigest()[:16]
