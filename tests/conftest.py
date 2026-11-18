from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests import media

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own data dir and never touches the real OS keyring."""
    home = tmp_path / "home"
    monkeypatch.setenv("CLIPPED_HOME", str(home))
    monkeypatch.setenv("CLIPPED_SECRETS_FILE", str(home / "secrets.json"))
    for name in list(os.environ):
        if name.startswith("CLIPPED_") and name.endswith(("_KEY", "_SECRET", "_TOKEN", "_CLIENT_ID")):
            monkeypatch.delenv(name, raising=False)
    yield home


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("media")


@pytest.fixture(scope="session")
def sample_clip(media_dir) -> Path:
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    return media.make_clip(media_dir / "clip.mp4")


@pytest.fixture(scope="session")
def silent_video(media_dir) -> Path:
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    return media.make_clip(media_dir / "noaudio.mp4", duration=4.0, with_audio=False)


@pytest.fixture
def transcript():
    return media.transcript()


@pytest.fixture
def small_render():
    from clipped.models import RenderSettings

    return RenderSettings(width=360, height=640, fps=15, crf=30, preset="ultrafast")


requires_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
