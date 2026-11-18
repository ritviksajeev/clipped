"""Thumbnail: a frame from the strongest moment with big title text on top."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import fonts_dir
from . import ffmpeg
from .captions import clean_text

MAX_BYTES = 2 * 1024 * 1024  # YouTube custom thumbnail limit


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("Inter-Black.otf", "Inter-ExtraBold.otf"):
        path = fonts_dir() / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def compose(frame_path: Path, text: str, out_path: Path, accent: str = "#FFD400",
            size: tuple[int, int] = (1080, 1920)) -> Path:
    img = Image.open(frame_path).convert("RGB")
    if img.size != size:
        img = img.resize(size, Image.LANCZOS)
    W, H = img.size
    text = clean_text(text, uppercase=True)

    # Darken the top third so text pops on any background.
    shade = Image.new("L", (1, H))
    for y in range(H):
        shade.putpixel((0, y), int(200 * max(0.0, 1 - y / (H * 0.45))))
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.composite(overlay, img, shade.resize((W, H)))

    draw = ImageDraw.Draw(img)
    font_size = 120
    while font_size > 60:
        font = _font(font_size)
        lines = wrap(draw, text, font, W - 140)
        if len(lines) <= 3:
            break
        font_size -= 8
    lines = lines[:3]
    y = int(H * 0.09)
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=font)
        x = (W - width) / 2
        fill = accent if i == len(lines) - 1 and len(lines) > 1 else "#FFFFFF"
        draw.text((x + 6, y + 8), line, font=font, fill="#000000")
        draw.text((x, y), line, font=font, fill=fill, stroke_width=8, stroke_fill="#000000")
        y += int(font_size * 1.12)

    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))
    quality = 90
    while True:
        img.save(out_path, "JPEG", quality=quality, optimize=True, progressive=True)
        if out_path.stat().st_size <= MAX_BYTES or quality <= 50:
            break
        quality -= 10
    return out_path


def make_thumbnail(video: Path, at_seconds: float, text: str, out_path: Path, accent: str = "#FFD400") -> Path:
    frame = out_path.with_name(out_path.stem + "_frame.jpg")
    ffmpeg.extract_frame(video, at_seconds, frame)
    try:
        return compose(frame, text, out_path, accent)
    finally:
        frame.unlink(missing_ok=True)
