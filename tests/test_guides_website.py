import importlib.util
import re
from pathlib import Path

import pytest

from clipped import config

ROOT = Path(__file__).resolve().parent.parent
GUIDE_SLUGS = {"quick-start", "twitch", "youtube", "instagram", "ai-titles", "ffmpeg", "safety", "troubleshooting"}


def test_bundled_guides_exist_and_cross_links_resolve():
    guides = {p.stem.split("-", 1)[-1]: p.read_text("utf-8") for p in (config.assets_dir() / "guides").glob("*.md")}
    assert GUIDE_SLUGS <= set(guides)
    for text in guides.values():
        for slug in re.findall(r"#/guides/([a-z0-9-]+)", text):
            assert slug in guides, f"broken guide link #/guides/{slug}"


def test_youtube_guide_covers_the_hard_parts():
    text = (config.assets_dir() / "guides" / "03-youtube.md").read_text("utf-8")
    for needle in ("YouTube Data API v3", "YouTube Analytics API", "Desktop app", "Test users", "7 days",
                   "yt_api_form", "10,000", "unverified"):
        assert needle in text


@pytest.mark.skipif(importlib.util.find_spec("markdown") is None, reason="markdown not installed")
def test_build_website_renders_every_guide(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("build_website", ROOT / "scripts" / "build_website.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OUT", tmp_path)
    written = {p.name for p in mod.build()}
    assert {f"{s}.html" for s in GUIDE_SLUGS} | {"index.html"} == written
    html = (tmp_path / "quick-start.html").read_text("utf-8")
    assert 'href="twitch.html"' in html and "#/" not in html
    assert 'target="_blank" rel="noopener"' in html


def test_website_download_links_match_release_artifacts():
    index = (ROOT / "website" / "index.html").read_text("utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")
    for artifact in re.findall(r"releases/latest/download/([\w.-]+)", index):
        assert artifact in workflow
