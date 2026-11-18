from datetime import timezone
from pathlib import Path

import pytest
from PIL import Image

from clippilot.pipeline import download, thumbnail
from tests.conftest import requires_ffmpeg


def test_compose_thumbnail(tmp_path):
    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (540, 960), (30, 120, 200)).save(frame)
    out = thumbnail.compose(frame, "he actually hit the craziest 1v4 you have ever seen 😱", tmp_path / "t.jpg")
    img = Image.open(out)
    assert img.size == (1080, 1920) and img.format == "JPEG"
    assert out.stat().st_size < thumbnail.MAX_BYTES
    # text drawn near the top: top band differs from the plain background
    assert img.crop((0, 150, 1080, 400)).getextrema() != ((30, 30), (120, 120), (200, 200))


@requires_ffmpeg
def test_make_thumbnail_from_video(tmp_path, sample_clip):
    out = thumbnail.make_thumbnail(sample_clip, 3.0, "NO WAY", tmp_path / "thumb.jpg")
    assert out.exists() and not (tmp_path / "thumb_frame.jpg").exists()


@pytest.mark.parametrize("url,expected", [
    ("https://clips.twitch.tv/FunnyClipName-AbC123xyz", "FunnyClipName-AbC123xyz"),
    ("https://www.twitch.tv/tenz/clip/BraveClip-xyz_9?filter=clips", "BraveClip-xyz_9"),
    ("https://clips.twitch.tv/embed?clip=EmbedClip-1&parent=x", "EmbedClip-1"),
    ("https://youtube.com/watch?v=x", None),
])
def test_clip_id_from_url(url, expected):
    assert download.clip_id_from_url(url) == expected


def test_info_from_ytdlp_maps_fields():
    clip = download.info_from_ytdlp({
        "id": "Clip1", "title": "wow", "creator": "TenZ", "uploader_id": "TenZ", "view_count": 55,
        "timestamp": 1700000000, "duration": 29.5, "webpage_url": "https://clips.twitch.tv/Clip1",
    }, "https://clips.twitch.tv/Clip1")
    assert clip.broadcaster_name == "TenZ" and clip.broadcaster_login == "tenz"
    assert clip.view_count == 55 and clip.duration == 29.5
    assert clip.created_at.tzinfo == timezone.utc
    assert clip.channel_url == "https://www.twitch.tv/tenz"


def test_download_clip_uses_yt_dlp(tmp_path, monkeypatch):
    import yt_dlp

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            Path(self.opts["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"\0" * 1000)
            return {"id": "C1", "ext": "mp4", "title": "t", "uploader": "Streamer"}

        def prepare_filename(self, info):
            return self.opts["outtmpl"].replace("%(ext)s", info["ext"])

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    path, clip = download.download_clip("https://clips.twitch.tv/C1", tmp_path)
    assert path.name == "source.mp4" and clip.broadcaster_name == "Streamer"


def test_use_local_file(tmp_path):
    src = tmp_path / "in.MOV"
    src.write_bytes(b"x")
    assert download.use_local_file(src, tmp_path / "w").name == "source.mov"
