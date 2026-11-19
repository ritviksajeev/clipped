"""Command line interface.

    clipped process <clip-url-or-file>   # one clip end to end (no API keys needed)
    clipped serve                        # dashboard at http://localhost:8000
    clipped doctor                       # check ffmpeg, libass, keyring, whisper
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .logs import get_logger, setup_logging
from .models import FACECAM_PRESETS, ClipInfo, FacecamRect, GlobalSettings

log = get_logger("cli")


def _facecam(value: str | None) -> FacecamRect | None:
    if not value:
        return None
    if value in FACECAM_PRESETS:
        return FACECAM_PRESETS[value]
    try:
        x, y, w, h = (float(v) for v in value.split(","))
    except ValueError:
        raise SystemExit("--facecam must be a preset (top-left, top-right, bottom-left, bottom-right) or x,y,w,h")
    return FacecamRect(x=x, y=y, w=w, h=h)


def load_global_settings() -> GlobalSettings:
    """Use the dashboard's saved settings when they exist, else defaults."""
    if config.db_path().exists():
        try:
            from .db import Database

            return Database(config.db_path()).get_global_settings()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Could not read saved settings (%s); using defaults", exc)
    return GlobalSettings()


def cmd_process(args: argparse.Namespace) -> int:
    from .keystore import KeyStore
    from .pipeline import download, runner
    from .pipeline.transcribe import StaticTranscriber, Transcript, WhisperTranscriber

    settings = load_global_settings()
    source = args.source
    clip_id = download.clip_id_from_url(source) if download.is_url(source) else Path(source).stem
    clip = ClipInfo(
        id=clip_id or "clip",
        url=args.clip_url or (source if download.is_url(source) else ""),
        title=args.title or "",
        broadcaster_name=args.streamer or "",
        broadcaster_login=(args.streamer_login or "").lower(),
        game_name=args.game or "",
    )
    if not download.is_url(source) and not Path(source).exists():
        print(f"error: {source} does not exist", file=sys.stderr)
        return 2

    reframe = settings.reframe.model_copy()
    if args.layout:
        reframe.mode = args.layout
    if args.facecam:
        reframe.facecam = _facecam(args.facecam)
    hook = settings.hook.model_copy(update={"mode": args.hook} if args.hook else {})
    captions = settings.captions.model_copy()
    if args.caption_position:
        captions.position = args.caption_position
    if args.font_size:
        captions.font_size = args.font_size
    if args.highlight_color:
        captions.highlight_color = args.highlight_color.upper()
    meta = settings.metadata.model_copy(update={"provider": args.provider} if args.provider else {})
    whisper = settings.whisper.model_copy(update={"model_size": args.whisper_model} if args.whisper_model else {})

    api_keys = {}
    if meta.provider != "template":
        from .services import ai

        api_keys = ai.credentials(KeyStore())

    styles = [args.style] + [s for s in ("hype", "question", "descriptive", "streamer") if s != args.style] \
        if args.style else ["hype", "question", "descriptive"]
    opts = runner.ProcessOptions(
        captions=captions, reframe=reframe, hook=hook, metadata=meta, render=settings.render,
        whisper=whisper, selection=settings.selection, category_hashtags=args.hashtag or [],
        styles=styles, commentary=args.commentary or "", api_keys=api_keys,
        intro=Path(args.intro) if args.intro else None, outro=Path(args.outro) if args.outro else None,
    )

    if args.transcript:
        transcriber = StaticTranscriber(Transcript.load(Path(args.transcript)))
    else:
        transcriber = WhisperTranscriber(whisper.model_size, whisper.device, whisper.compute_type, config.models_dir())

    out_dir = Path(args.out) if args.out else Path.cwd() / "clipped-output" / clip.id
    result = runner.process_clip(clip, out_dir, transcriber, opts, source=source)
    v = result.variant
    summary = {
        "video": str(result.output.video),
        "thumbnail": str(result.output.thumbnail),
        "duration": round(result.output.duration, 2),
        "hype": result.analysis.hype,
        "edits": result.output.plan.notes,
        "title": v.title,
        "hook_text": v.hook_text,
        "description": v.description,
        "tags": v.tags,
        "variants": [{"style": x.style, "title": x.title, "hook_text": x.hook_text, "source": x.source}
                     for x in result.variants],
    }
    (out_dir / "metadata.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), "utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.upload:
        from .services.youtube import YouTubeClient, UploadRequest

        yt = YouTubeClient.from_keystore(KeyStore())
        privacy = args.privacy or settings.youtube.privacy_status
        res = yt.upload(UploadRequest(
            video_path=result.output.video, title=v.title, description=v.description, tags=v.tags,
            privacy_status=privacy, made_for_kids=settings.youtube.made_for_kids,
            category_id=settings.youtube.category_id, thumbnail_path=result.output.thumbnail,
        ))
        print(json.dumps({"youtube_id": res.video_id, "url": res.url, "privacy": res.privacy_status}, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .keystore import KeyStore
    from .pipeline import ffmpeg

    checks = []
    ff = config.find_binary("ffmpeg")
    fp = config.find_binary("ffprobe")
    checks.append(("ffmpeg", bool(ff), ff or "not found"))
    checks.append(("ffprobe", bool(fp), fp or "not found"))
    checks.append(("libass (captions)", bool(ff) and ffmpeg.has_libass(), "ffmpeg must be built with libass"))
    store = KeyStore()
    checks.append(("secret storage", True, store.backend_name))
    try:
        import faster_whisper  # noqa: F401

        checks.append(("faster-whisper", True, "installed"))
    except Exception as exc:  # pragma: no cover
        checks.append(("faster-whisper", False, str(exc)))
    checks.append(("data directory", True, str(config.data_dir())))
    ok = True
    for name, passed, detail in checks:
        ok &= passed
        print(f"[{'ok' if passed else 'XX'}] {name}: {detail}")
    return 0 if ok else 1


def cmd_app(args: argparse.Namespace) -> int:
    from .desktop import run_app

    return run_app(port=args.port, window=args.window)


def cmd_shortcut(args: argparse.Namespace) -> int:
    from .desktop import create_shortcuts

    made = create_shortcuts()
    if not made:
        print("Shortcuts are made for Windows and Linux. On macOS, drag the clipped app to Applications.")
        return 1
    for path in made:
        print(f"Created {path}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    serve(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clipped", description="Twitch clips to captioned YouTube Shorts")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("process", help="process one clip end to end")
    p.add_argument("source", help="Twitch clip URL or a local video file")
    p.add_argument("--out", help="output folder (default ./clipped-output/<clip>)")
    p.add_argument("--title", help="clip title (for local files)")
    p.add_argument("--streamer", help="streamer display name (for local files)")
    p.add_argument("--streamer-login", help="streamer login, used for the channel link")
    p.add_argument("--game", help="game / category name")
    p.add_argument("--clip-url", help="original clip URL to credit (for local files)")
    p.add_argument("--transcript", help="use this transcript JSON instead of running whisper")
    p.add_argument("--whisper-model", choices=["tiny", "base", "small", "medium", "large-v3", "distil-large-v3"])
    p.add_argument("--layout", choices=["blur", "split", "crop"])
    p.add_argument("--facecam", help="preset (top-left|top-right|bottom-left|bottom-right) or x,y,w,h fractions")
    p.add_argument("--hook", choices=["teaser", "trim", "off"])
    p.add_argument("--caption-position", choices=["bottom", "middle", "top"])
    p.add_argument("--font-size", type=int)
    p.add_argument("--highlight-color", help="#RRGGBB")
    p.add_argument("--provider", choices=["template", "anthropic", "gemini", "openai", "openrouter", "ollama"])
    p.add_argument("--style", choices=["hype", "question", "descriptive", "streamer"], help="preferred title style")
    p.add_argument("--hashtag", action="append", help="extra hashtag (repeatable)")
    p.add_argument("--commentary", help="commentary text shown on screen and added to the description")
    p.add_argument("--intro", help="intro video or image")
    p.add_argument("--outro", help="outro video or image")
    p.add_argument("--upload", action="store_true", help="upload to YouTube after rendering (needs Connect YouTube)")
    p.add_argument("--privacy", choices=["public", "unlisted", "private"])
    p.set_defaults(func=cmd_process)

    d = sub.add_parser("doctor", help="check that everything needed is installed")
    d.set_defaults(func=cmd_doctor)

    a = sub.add_parser("app", help="open clipped in its own window (the default)")
    a.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    a.add_argument("--window", choices=["auto", "app", "native", "browser"], default="auto",
                   help="app = Edge/Chrome app window, native = pywebview, browser = a normal tab")
    a.set_defaults(func=cmd_app)

    sc = sub.add_parser("shortcut", help="add clipped to the Desktop and Start Menu")
    sc.set_defaults(func=cmd_shortcut)

    s = sub.add_parser("serve", help="run the dashboard in your browser (no app window)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=cmd_serve)
    return parser


def _ensure_streams() -> None:
    """Started without a console (desktop shortcut, windowed build) there is no
    stdout/stderr; progress bars in libraries would crash writing to None."""
    import os

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _windowless_command() -> list[str] | None:
    """How to start this same clipped as a windowless desktop app (Windows)."""
    from pathlib import Path

    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        app = exe.with_name("clipped.exe")
        return [str(app)] if exe.name.lower() != "clipped.exe" and app.exists() else None
    pythonw = exe.with_name("pythonw.exe")
    return [str(pythonw), "-m", "clipped", "app"] if pythonw.exists() else None


def _hand_off_to_window(argv: list[str]) -> bool:
    """`clipped` typed in Command Prompt: start the app without a console and
    give the prompt back, instead of tying the app to this window (closing it
    would quit clipped). `clipped app` still runs here, with its log."""
    import os
    import subprocess
    import time

    if sys.platform != "win32" or argv or os.environ.get("CLIPPED_STAY_IN_CONSOLE"):
        return False
    try:
        interactive = sys.stdout.isatty()
    except (AttributeError, ValueError):
        interactive = False
    command = _windowless_command() if interactive else None
    if not command:
        return False
    detached = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(command, creationflags=detached, close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Opening clipped in its own window...", flush=True)
    from .desktop import existing_instance

    ports = range(config.DEFAULT_PORT, config.DEFAULT_PORT + 20)
    for _ in range(60):
        if any(existing_instance(p) for p in ports):
            print("clipped is running. You can close this window.", flush=True)
            return True
        time.sleep(0.5)
    print("clipped did not open. Run `clipped app` to see what went wrong.", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    _ensure_streams()
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        if _hand_off_to_window(argv):
            return 0
        args = parser.parse_args([*argv, "app"])  # no command: open the app window
    setup_logging(config.logs_dir(), level=10 if args.verbose else 20)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
