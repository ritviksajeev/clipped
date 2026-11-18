"""Download Twitch clips with yt-dlp (no API key needed for public clips)."""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..config import find_binary
from ..logs import get_logger
from ..models import ClipInfo

log = get_logger("download")

CLIP_URL_RE = re.compile(
    r"(?:clips\.twitch\.tv/(?:embed\?clip=)?|twitch\.tv/[^/]+/clip/)([A-Za-z0-9_-]+)"
)


def clip_id_from_url(url: str) -> str | None:
    match = CLIP_URL_RE.search(url)
    return match.group(1) if match else None


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def info_from_ytdlp(info: dict, url: str) -> ClipInfo:
    created = None
    if info.get("timestamp"):
        created = datetime.fromtimestamp(int(info["timestamp"]), tz=timezone.utc)
    uploader = info.get("creator") or info.get("uploader") or info.get("channel") or ""
    login = (info.get("uploader_id") or info.get("channel_id") or "").lower()
    if not re.fullmatch(r"[a-z0-9_]{2,25}", login or ""):
        login = ""
    return ClipInfo(
        id=info.get("id") or clip_id_from_url(url) or "clip",
        url=info.get("webpage_url") or url,
        title=info.get("title") or "",
        broadcaster_name=uploader,
        broadcaster_login=login,
        view_count=int(info.get("view_count") or 0),
        created_at=created,
        duration=float(info.get("duration") or 0),
        thumbnail_url=info.get("thumbnail") or "",
    )


def download_clip(url: str, dest_dir: Path) -> tuple[Path, ClipInfo]:
    """Download the best MP4 rendition of a clip. Returns (file, metadata)."""
    import yt_dlp  # lazy: large import

    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 3,
        "socket_timeout": 30,
        "overwrites": True,
    }
    ffmpeg_bin = find_binary("ffmpeg")
    if ffmpeg_bin:
        opts["ffmpeg_location"] = ffmpeg_bin
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    if not path.exists():
        candidates = sorted(dest_dir.glob("source.*"))
        if not candidates:
            raise RuntimeError(f"yt-dlp did not produce a file for {url}")
        path = candidates[0]
    log.info("Downloaded %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
    return path, info_from_ytdlp(info, url)


def use_local_file(path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"source{path.suffix.lower() or '.mp4'}"
    if path.resolve() != target.resolve():
        shutil.copyfile(path, target)
    return target
