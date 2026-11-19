"""End-to-end processing of a single clip.

download -> probe -> audio analysis -> transcribe -> hook/edit plan ->
title variants -> captions (ASS) -> render 9:16 -> thumbnail

Each step caches its output in the clip's work directory, so re-rendering
after an edit in the review queue skips download and transcription.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..logs import get_logger
from ..models import (
    CaptionStyle, ClipInfo, HookSettings, MetadataSettings, ReframeSettings, RenderSettings,
    SelectionSettings, WhisperSettings,
)
from . import audio, captions, download, ffmpeg, hooks, metadata, render, thumbnail
from .transcribe import Transcriber, Transcript

log = get_logger("pipeline")


class SkipClip(Exception):
    """Raised by a gate to stop processing a clip that fails quality checks."""


@dataclass
class ProcessOptions:
    captions: CaptionStyle = field(default_factory=CaptionStyle)
    reframe: ReframeSettings = field(default_factory=ReframeSettings)
    hook: HookSettings = field(default_factory=HookSettings)
    metadata: MetadataSettings = field(default_factory=MetadataSettings)
    render: RenderSettings = field(default_factory=RenderSettings)
    whisper: WhisperSettings = field(default_factory=WhisperSettings)
    selection: SelectionSettings = field(default_factory=SelectionSettings)
    category_hashtags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=lambda: list(metadata.STYLES[:3]))
    commentary: str = ""
    intro: Path | None = None
    outro: Path | None = None
    api_keys: dict = field(default_factory=dict)
    subtitles: bool = True  # burn the word-by-word captions in (hook and commentary always show)
    # Returns (metadata settings, keys) as they are now; titles are written late in a long job.
    title_settings: Callable[[], tuple[MetadataSettings, dict]] | None = None
    stage: Callable[[str], None] | None = None  # told "Downloading", "Transcribing", "Rendering"...

    def report(self, text: str) -> None:
        if self.stage:
            try:
                self.stage(text)
            except Exception:  # progress reporting must never break a render
                pass

    @property
    def all_keywords(self) -> list[str]:
        return list(dict.fromkeys([*self.selection.hype_keywords, *self.keywords]))


@dataclass
class Analysis:
    clip: ClipInfo
    source: Path
    info: ffmpeg.MediaInfo
    audio: audio.AudioAnalysis
    transcript: Transcript
    keyword_hits: list[tuple[float, str]]
    hype: float

    def summary(self) -> dict:
        return {
            "duration": round(self.info.duration, 2),
            "width": self.info.width,
            "height": self.info.height,
            "audio": self.audio.to_dict(),
            "keyword_hits": [k for _, k in self.keyword_hits][:12],
            "hype": self.hype,
            "words": len(self.transcript.words),
            "language": self.transcript.language,
        }


@dataclass
class RenderOutput:
    video: Path
    thumbnail: Path
    plan: hooks.EditPlan
    duration: float


@dataclass
class ProcessResult:
    workdir: Path
    analysis: Analysis
    variants: list[metadata.Variant]
    chosen: int
    output: RenderOutput

    @property
    def variant(self) -> metadata.Variant:
        return self.variants[self.chosen]


def acquire(clip: ClipInfo, workdir: Path, source: str | Path | None = None) -> tuple[Path, ClipInfo]:
    """Get the clip file into the work dir. `source` may be a URL or local path."""
    workdir.mkdir(parents=True, exist_ok=True)
    existing = sorted(p for p in workdir.glob("source.*") if p.suffix != ".part")
    if existing:
        return existing[0], clip
    src = str(source or clip.url)
    if src and download.is_url(src):
        path, meta = download.download_clip(src, workdir)
        merged = clip.model_copy(update={k: v for k, v in meta.model_dump().items()
                                         if v and not getattr(clip, k, None)})
        return path, merged
    if src and Path(src).exists():
        return download.use_local_file(Path(src), workdir), clip
    raise FileNotFoundError(f"No source for clip {clip.id}: {src!r}")


def analyze_clip(clip: ClipInfo, workdir: Path, transcriber: Transcriber, opts: ProcessOptions,
                 source: str | Path | None = None) -> Analysis:
    t0 = time.monotonic()
    opts.report("Downloading")
    path, clip = acquire(clip, workdir, source)
    opts.report("Analysing audio")
    info = ffmpeg.probe(path)
    if not clip.duration:
        clip = clip.model_copy(update={"duration": info.duration})
    audio_cache = workdir / "audio.json"
    if audio_cache.exists():
        data = json.loads(audio_cache.read_text("utf-8"))
        analysis = audio.AudioAnalysis(**data)
    else:
        analysis = audio.analyze_file(path, opts.hook.silence_db)
        audio_cache.write_text(json.dumps(analysis.to_dict(include_envelope=True)), "utf-8")

    transcript_cache = workdir / "transcript.json"
    if transcript_cache.exists():
        transcript = Transcript.load(transcript_cache)
    else:
        opts.report("Transcribing")
        transcript = transcriber.transcribe(path, opts.whisper.language or clip.language or "")
        transcript.save(transcript_cache)

    hits = transcript.keyword_hits(opts.all_keywords)
    kw_score = min(len(hits) / 3.0, 1.0)
    hype = round(0.7 * analysis.hype + 0.3 * kw_score, 3)
    log.info("Analyzed %s in %.1fs: hype %.2f, mean %.1f dBFS, %d words",
             clip.id, time.monotonic() - t0, hype, analysis.mean_db, len(transcript.words))
    return Analysis(clip=clip, source=path, info=info, audio=analysis, transcript=transcript,
                    keyword_hits=hits, hype=hype)


def plan_for(analysis: Analysis, opts: ProcessOptions) -> hooks.EditPlan:
    return hooks.plan_edit(analysis.info.duration, analysis.audio, analysis.transcript, opts.hook, opts.all_keywords)


def make_variants(analysis: Analysis, opts: ProcessOptions) -> list[metadata.Variant]:
    settings, keys = opts.metadata, opts.api_keys
    if opts.title_settings:
        try:
            settings, keys = opts.title_settings()
        except Exception as exc:  # fall back to what the job started with
            log.warning("Could not re-read the title settings (%s)", exc)
    return metadata.generate_variants(
        analysis.clip, analysis.transcript.text, settings, opts.styles, opts.category_hashtags,
        opts.all_keywords, keys, opts.commentary,
    )


def render_outputs(analysis: Analysis, workdir: Path, opts: ProcessOptions, hook_text: str,
                   thumb_text: str, commentary: str = "", plan: hooks.EditPlan | None = None) -> RenderOutput:
    plan = plan or plan_for(analysis, opts)
    words = plan.remap_words(analysis.transcript.words) if opts.subtitles else []
    hook_overlay = None
    if opts.hook.mode != "off" and opts.hook.hook_text and hook_text.strip():
        hook_overlay = captions.Overlay(hook_text, 0.0, min(opts.hook.hook_seconds, plan.duration))
    commentary_overlay = None
    if commentary.strip():
        start = opts.hook.hook_seconds if hook_overlay else 0.0
        commentary_overlay = captions.Overlay(commentary, start, plan.duration)
    # Captions are laid out in a fixed 1080x1920 design space; libass scales to the output size.
    ass_text = captions.build_ass(words, opts.captions, hook=hook_overlay, commentary=commentary_overlay)
    ass_path = workdir / "captions.ass"
    ass_path.write_text(ass_text, "utf-8")

    out = workdir / "short.mp4"
    tmp = workdir / "short.tmp.mp4"
    opts.report("Rendering video")
    started = time.monotonic()
    render.render_video(analysis.source, tmp, info=analysis.info, plan=plan, reframe=opts.reframe,
                        render=opts.render, ass_path=ass_path, workdir=workdir,
                        intro=opts.intro, outro=opts.outro)
    tmp.replace(out)
    out_info = ffmpeg.probe(out)
    log.info("Rendered %.0fs of video in %.0fs", out_info.duration, time.monotonic() - started)
    opts.report("Making thumbnail")

    peak = plan.map_time(plan.peak_time) or min(1.0, out_info.duration / 2)
    if opts.intro:
        peak += ffmpeg.probe(workdir / "intro_norm.mp4").duration
    thumb = thumbnail.make_thumbnail(out, min(peak, max(out_info.duration - 0.1, 0)), thumb_text,
                                     workdir / "thumbnail.jpg", opts.captions.highlight_color)
    (workdir / "plan.json").write_text(json.dumps(plan.to_dict()), "utf-8")
    return RenderOutput(video=out, thumbnail=thumb, plan=plan, duration=out_info.duration)


def process_clip(clip: ClipInfo, workdir: Path, transcriber: Transcriber, opts: ProcessOptions,
                 source: str | Path | None = None, gate: Callable[[Analysis], None] | None = None,
                 choose: Callable[[list[metadata.Variant]], int] | None = None) -> ProcessResult:
    analysis = analyze_clip(clip, workdir, transcriber, opts, source)
    if gate:
        gate(analysis)  # may raise SkipClip
    opts.report("Writing titles")
    variants = make_variants(analysis, opts)
    chosen = choose(variants) if choose else 0
    variant = variants[chosen]
    output = render_outputs(analysis, workdir, opts, variant.hook_text, variant.hook_text or variant.title,
                            opts.commentary)
    for note in output.plan.notes:
        log.info("Hook: %s", note)
    return ProcessResult(workdir=workdir, analysis=analysis, variants=variants, chosen=chosen, output=output)
