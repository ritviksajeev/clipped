"""Paths and environment discovery.

Everything clipped stores lives under one per-user data directory on the
user's own machine. Nothing is ever sent to a clipped server (there is none).
"""

from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "clipped"
APP_VERSION = "0.1.1"
DEFAULT_PORT = 8000


def _bundle_root() -> Path:
    """Root of bundled resources (PyInstaller sets sys._MEIPASS)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def package_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "clipped"
    return Path(__file__).resolve().parent


def assets_dir() -> Path:
    return package_dir() / "assets"


def fonts_dir() -> Path:
    return assets_dir() / "fonts"


def web_dir() -> Path:
    """Built React dashboard. Populated by `npm run build` in frontend/."""
    return package_dir() / "web"


def data_dir() -> Path:
    override = os.environ.get("CLIPPED_HOME")
    base = Path(override).expanduser() if override else Path(user_data_dir(APP_NAME, appauthor=False))
    base.mkdir(parents=True, exist_ok=True)
    return base


def sub_dir(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "clipped.sqlite3"


def work_dir() -> Path:
    return sub_dir("work")


def media_dir() -> Path:
    return sub_dir("media")


def logs_dir() -> Path:
    return sub_dir("logs")


def models_dir() -> Path:
    return sub_dir("models")


def uploads_dir() -> Path:
    """User-supplied assets such as intro/outro videos."""
    return sub_dir("user-assets")


def _candidate_bin_dirs() -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get("CLIPPED_BIN_DIR")
    if env:
        dirs.append(Path(env))
    dirs.append(_bundle_root() / "bin")
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent / "bin")
    return dirs


@lru_cache(maxsize=None)
def find_binary(name: str) -> str | None:
    """Locate ffmpeg/ffprobe: explicit env var, bundled bin/, then PATH."""
    env = os.environ.get(f"CLIPPED_{name.upper()}")
    if env and Path(env).exists():
        return env
    exe = name + (".exe" if os.name == "nt" else "")
    for directory in _candidate_bin_dirs():
        candidate = directory / exe
        if candidate.exists():
            return str(candidate)
    if sys.platform == "darwin":
        # Homebrew's ffmpeg-full (the build with libass) is keg-only: not on PATH.
        for prefix in ("/opt/homebrew", "/usr/local"):
            candidate = Path(prefix) / "opt" / "ffmpeg-full" / "bin" / exe
            if candidate.exists():
                return str(candidate)
    return shutil.which(name)


def require_binary(name: str) -> str:
    path = find_binary(name)
    if not path:
        raise RuntimeError(
            f"{name} was not found. Install ffmpeg (https://ffmpeg.org/download.html) "
            f"or set CLIPPED_{name.upper()} to its full path."
        )
    return path
