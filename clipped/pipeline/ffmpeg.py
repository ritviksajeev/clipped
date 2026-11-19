"""Thin, testable wrappers around the ffmpeg / ffprobe binaries."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import require_binary
from ..logs import get_logger

log = get_logger("ffmpeg")


class FFmpegError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 16 / 9


def run(args: list[str], cwd: Path | None = None, timeout: float | None = 1800) -> subprocess.CompletedProcess:
    cmd = [require_binary("ffmpeg"), "-hide_banner", "-nostdin", "-y", *args]
    log.debug("ffmpeg %s", " ".join(args))
    proc = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-25:])
        raise FFmpegError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
    return proc


def probe(path: Path) -> MediaInfo:
    cmd = [
        require_binary("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path.name}: {proc.stderr.strip()[-500:]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise FFmpegError(f"{path.name} has no video stream")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    fps = _parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1")
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    rotation = _rotation(video)
    if rotation in (90, 270):
        width, height = height, width
    return MediaInfo(duration=duration, width=width, height=height, fps=fps, has_audio=has_audio)


def _parse_rate(rate: str) -> float:
    try:
        num, _, den = rate.partition("/")
        value = float(num) / float(den or 1)
        return value if value > 0 else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0


def _rotation(stream: dict) -> int:
    try:
        rot = int(stream.get("tags", {}).get("rotate", 0))
    except ValueError:
        rot = 0
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            try:
                rot = int(side["rotation"])
            except (TypeError, ValueError):
                pass
    return abs(rot) % 360


def escape_filter_path(path: Path | str) -> str:
    """Escape a filesystem path for use as a quoted filter option value.

    Works for Windows drive letters (``C:``), spaces and quotes.
    """
    text = Path(path).as_posix() if not isinstance(path, str) else path.replace("\\", "/")
    text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\\\\\''")
    return f"'{text}'"


def has_libass() -> bool:
    try:
        proc = subprocess.run(
            [require_binary("ffmpeg"), "-hide_banner", "-filters"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except Exception:
        return False
    return any(line.split()[1:2] == ["ass"] for line in proc.stdout.splitlines() if line.strip())


def extract_frame(video: Path, at_seconds: float, out_path: Path) -> Path:
    run(["-ss", f"{max(at_seconds, 0):.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out_path)])
    return out_path
