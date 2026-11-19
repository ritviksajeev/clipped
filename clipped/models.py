"""Typed settings and data models shared by the CLI, API and pipeline."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class CaptionStyle(BaseModel):
    """Burned-in captions are always on; this only controls how they look."""

    font: str = "Inter Black"
    font_size: int = Field(86, ge=36, le=160)
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFD400"
    outline_color: str = "#000000"
    outline: float = Field(7, ge=0, le=20)
    shadow: float = Field(3, ge=0, le=20)
    position: Literal["bottom", "middle", "top"] = "middle"
    vertical_offset: int = Field(0, ge=-600, le=600, description="Extra pixels down (+) or up (-)")
    uppercase: bool = True
    max_words: int = Field(3, ge=1, le=8)
    max_chars: int = Field(18, ge=6, le=40)
    animation: Literal["pop", "none"] = "pop"
    highlight_scale: int = Field(112, ge=100, le=140)
    # Safe area for the Shorts player UI (buttons on the right, title at the bottom).
    margin_left: int = 90
    margin_right: int = 140
    margin_bottom: int = 520
    margin_top: int = 300

    @field_validator("primary_color", "highlight_color", "outline_color")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not HEX_COLOR.match(value):
            raise ValueError("colors must look like #RRGGBB")
        return value.upper()


class FacecamRect(BaseModel):
    """Facecam position as fractions of the source frame (0..1)."""

    x: float = Field(0.0, ge=0, le=1)
    y: float = Field(0.0, ge=0, le=1)
    w: float = Field(0.25, gt=0, le=1)
    h: float = Field(0.3, gt=0, le=1)


FACECAM_PRESETS: dict[str, FacecamRect] = {
    "top-left": FacecamRect(x=0.0, y=0.0, w=0.26, h=0.32),
    "top-right": FacecamRect(x=0.74, y=0.0, w=0.26, h=0.32),
    "bottom-left": FacecamRect(x=0.0, y=0.68, w=0.26, h=0.32),
    "bottom-right": FacecamRect(x=0.74, y=0.68, w=0.26, h=0.32),
}


class ReframeSettings(BaseModel):
    mode: Literal["blur", "split", "crop"] = "blur"
    zoom: float = Field(1.12, ge=1.0, le=2.0, description="Foreground zoom in blur mode")
    facecam: Optional[FacecamRect] = None
    facecam_height: float = Field(0.36, ge=0.2, le=0.6, description="Share of the 9:16 frame for the facecam")
    gameplay_focus_x: float = Field(0.5, ge=0, le=1)


class HookSettings(BaseModel):
    mode: Literal["teaser", "trim", "off"] = "teaser"
    hook_text: bool = True
    hook_seconds: float = Field(2.0, ge=0.5, le=5)
    teaser_seconds: float = Field(1.8, ge=0.8, le=4)
    trim_dead_air: bool = True
    max_silence: float = Field(0.9, ge=0.3, le=5)
    keep_silence: float = Field(0.25, ge=0.05, le=1)
    silence_db: float = Field(-42.0, ge=-80, le=-10)
    max_output_seconds: float = Field(59.0, ge=10, le=180)


class MetadataSettings(BaseModel):
    provider: Literal["template", "anthropic", "gemini", "openai", "openrouter", "ollama"] = "template"
    anthropic_model: str = "claude-opus-5-5"
    openai_model: str = "gpt-5-mini"
    gemini_model: str = "gemini-flash-latest"  # Google's alias for its current Flash model
    openrouter_model: str = "openrouter/auto"  # lets OpenRouter pick; any id from openrouter.ai/models works
    ollama_model: str = ""  # empty = first installed model
    ollama_url: str = "http://127.0.0.1:11434"
    variants: int = Field(3, ge=1, le=3)
    credit_in_title: bool = True
    default_hashtags: list[str] = Field(default_factory=lambda: ["#Shorts", "#Twitch", "#Gaming"])
    description_footer: str = ""

    @field_validator("ollama_url")
    @classmethod
    def _local_only(cls, value: str) -> str:
        value = value.strip().rstrip("/") or "http://127.0.0.1:11434"
        if not re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", value):
            raise ValueError("Ollama must run on this computer, e.g. http://127.0.0.1:11434")
        return value


class WhisperSettings(BaseModel):
    model_size: Literal["tiny", "base", "small", "medium", "large-v3", "distil-large-v3"] = "base"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    compute_type: str = "auto"
    language: str = ""  # empty = auto-detect


class RenderSettings(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    crf: int = Field(20, ge=14, le=32)
    preset: str = "veryfast"
    loudnorm: bool = True
    intro_path: str = ""
    outro_path: str = ""


class QuietHours(BaseModel):
    enabled: bool = False
    start: str = "00:00"
    end: str = "07:00"

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", value):
            raise ValueError("use HH:MM (24h)")
        return value


class ScheduleSettings(BaseModel):
    upload_interval_minutes: int = Field(120, ge=10, le=10080)
    max_uploads_per_day: int = Field(4, ge=1, le=50)
    min_gap_minutes: int = Field(20, ge=5, le=1440, description="Hard floor between any two uploads")
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    pause_until: Optional[datetime] = None
    fetch_interval_minutes: int = Field(30, ge=5, le=1440)
    render_ahead: int = Field(3, ge=1, le=20, description="Rendered clips to keep ready")
    review_queue_size: int = Field(20, ge=1, le=200, description="Rendered clips to keep waiting for review")


class SelectionSettings(BaseModel):
    # trending: clips from the last few hours that are gaining views fastest right now.
    # top24h: the most-viewed clips created in the last 24 hours.
    discovery: Literal["trending", "top24h"] = "trending"
    trending_window_hours: int = Field(6, ge=1, le=24, description="How recent a trending clip must be")
    min_seconds: float = 8.0
    ideal_min_seconds: float = 15.0
    ideal_max_seconds: float = 45.0
    max_seconds: float = 60.0
    min_mean_db: float = -38.0
    similarity_threshold: float = Field(0.55, ge=0.1, le=1.0)
    recent_window: int = Field(30, ge=5, le=500, description="Recent uploads to compare against")
    hype_keywords: list[str] = Field(
        default_factory=lambda: [
            "no way", "oh my god", "omg", "let's go", "lets go", "what", "insane", "clutch",
            "ace", "holy", "bro", "wtf", "crazy", "unbelievable", "yes", "noo", "gg", "wow",
        ]
    )


class OptimizerSettings(BaseModel):
    enabled: bool = True
    min_samples_for_styles: int = Field(6, ge=2, le=100)
    min_samples_for_timing: int = Field(12, ge=4, le=500)
    explore_rate: float = Field(0.2, ge=0, le=1)
    timing_flex_ratio: float = Field(0.5, ge=0, le=1)
    timing_flex_max_minutes: int = Field(180, ge=0, le=720)
    diversity_window: int = Field(8, ge=1, le=100)
    diversity_penalty: float = Field(0.55, ge=0.05, le=1.0)


class YouTubeSettings(BaseModel):
    privacy_status: Literal["public", "unlisted", "private"] = "public"
    made_for_kids: bool = False
    category_id: str = "20"  # Gaming
    set_thumbnail: bool = True
    contains_synthetic_media: bool = False


class GlobalSettings(BaseModel):
    mode: Literal["manual", "auto"] = "manual"
    auto_warning_acknowledged_at: Optional[datetime] = None
    approved_streamers_only: bool = True
    approved_streamers: list[str] = Field(default_factory=list)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)
    selection: SelectionSettings = Field(default_factory=SelectionSettings)
    optimizer: OptimizerSettings = Field(default_factory=OptimizerSettings)
    captions: CaptionStyle = Field(default_factory=CaptionStyle)
    reframe: ReframeSettings = Field(default_factory=ReframeSettings)
    hook: HookSettings = Field(default_factory=HookSettings)
    metadata: MetadataSettings = Field(default_factory=MetadataSettings)
    whisper: WhisperSettings = Field(default_factory=WhisperSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    youtube: YouTubeSettings = Field(default_factory=YouTubeSettings)
    commentary_default: str = ""

    @field_validator("approved_streamers")
    @classmethod
    def _norm_streamers(cls, value: list[str]) -> list[str]:
        return normalize_logins(value)


class CategorySettings(BaseModel):
    min_views: int = Field(50, ge=0)
    discovery: Literal["inherit", "trending", "top24h"] = "inherit"
    max_age_hours: int = Field(48, ge=1, le=24 * 30)  # superseded by `discovery`; kept so old settings load
    language: str = ""  # ISO 639-1, empty = any
    max_clips_per_day: int = Field(3, ge=0, le=50)  # automatic uploads per day; manual approvals always go up
    allowlist: list[str] = Field(default_factory=list)
    blocklist: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    mode: Literal["inherit", "manual", "auto"] = "inherit"
    keywords: list[str] = Field(default_factory=list)
    reframe: Optional[ReframeSettings] = None
    facecams: dict[str, FacecamRect] = Field(default_factory=dict, description="Per-streamer facecam rects")
    intro_path: str = ""
    outro_path: str = ""

    @field_validator("allowlist", "blocklist")
    @classmethod
    def _norm(cls, value: list[str]) -> list[str]:
        return normalize_logins(value)

    @field_validator("hashtags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return normalize_hashtags(value)


class ClipInfo(BaseModel):
    """A Twitch clip (from Helix, yt-dlp metadata, or a local file)."""

    id: str
    url: str = ""
    title: str = ""
    broadcaster_name: str = ""
    broadcaster_login: str = ""
    broadcaster_id: str = ""
    creator_name: str = ""
    game_id: str = ""
    game_name: str = ""
    language: str = ""
    view_count: int = 0
    created_at: Optional[datetime] = None
    duration: float = 0.0
    video_id: str = ""
    vod_offset: Optional[int] = None
    thumbnail_url: str = ""

    @property
    def channel_url(self) -> str:
        login = self.broadcaster_login or _ascii_login(self.broadcaster_name)
        return f"https://www.twitch.tv/{login}" if login else ""

    @property
    def streamer(self) -> str:
        return self.broadcaster_name or self.broadcaster_login or "the streamer"

    def age_hours(self, now: datetime | None = None) -> float:
        if not self.created_at:
            return 24.0
        now = now or datetime.now(timezone.utc)
        created = self.created_at if self.created_at.tzinfo else self.created_at.replace(tzinfo=timezone.utc)
        return max((now - created).total_seconds() / 3600.0, 0.0)


def _ascii_login(name: str) -> str:
    login = name.strip().lower()
    return login if re.fullmatch(r"[a-z0-9_]{2,25}", login) else ""


def normalize_logins(values: list[str]) -> list[str]:
    seen: list[str] = []
    for raw in values:
        value = raw.strip().lower().lstrip("@")
        value = re.sub(r"^https?://(www\.)?twitch\.tv/", "", value).strip("/")
        if value and value not in seen:
            seen.append(value)
    return seen


def normalize_hashtags(values: list[str]) -> list[str]:
    seen: list[str] = []
    for raw in values:
        for token in re.split(r"[\s,]+", raw.strip()):
            token = re.sub(r"[^\w]", "", token.lstrip("#"), flags=re.UNICODE)
            if token:
                tag = "#" + token
                if tag.lower() not in [s.lower() for s in seen]:
                    seen.append(tag)
    return seen
