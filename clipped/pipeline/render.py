"""Reframe to 9:16, apply the edit plan, burn captions, add intro/outro.

All geometry is computed in Python from ffprobe output so the generated
filtergraph has no runtime expressions - easy to unit test and identical on
Windows, macOS and Linux.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ..config import fonts_dir
from ..logs import get_logger
from ..models import ReframeSettings, RenderSettings
from . import ffmpeg
from .ffmpeg import MediaInfo, escape_filter_path
from .hooks import EditPlan

log = get_logger("render")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def even(value: float) -> int:
    v = int(round(value))
    return v - (v % 2)


def _fit_crop(src_w: int, src_h: int, target_aspect: float, focus_x: float = 0.5, focus_y: float = 0.5) -> tuple[int, int, int, int]:
    """Largest crop of the source with the target aspect ratio, centred on focus."""
    if src_w / src_h > target_aspect:
        h = even(src_h)
        w = even(min(src_h * target_aspect, src_w))
    else:
        w = even(src_w)
        h = even(min(src_w / target_aspect, src_h))
    x = even(min(max(focus_x * src_w - w / 2, 0), src_w - w))
    y = even(min(max(focus_y * src_h - h / 2, 0), src_h - h))
    return w, h, x, y


def reframe_filter(src: str, info: MediaInfo, rs: ReframeSettings, W: int, H: int, out: str) -> str:
    sw, sh = info.width, info.height
    mode = rs.mode
    if mode == "split" and rs.facecam is None:
        log.warning("Split layout needs a facecam position; falling back to blurred background")
        mode = "blur"
    if mode == "crop" and sw / sh < W / H:
        mode = "blur"  # source already narrower than 9:16

    if mode == "crop":
        w, h, x, y = _fit_crop(sw, sh, W / H, rs.gameplay_focus_x)
        return f"[{src}]crop={w}:{h}:{x}:{y},scale={W}:{H}:flags=lanczos,setsar=1[{out}]"

    if mode == "split":
        cam = rs.facecam
        cam_h = even(H * rs.facecam_height)
        game_h = H - cam_h
        cw = even(max(cam.w * sw, 16))
        ch = even(max(cam.h * sh, 16))
        cx = even(min(cam.x * sw, sw - cw))
        cy = even(min(cam.y * sh, sh - ch))
        gw, gh, gx, gy = _fit_crop(sw, sh, W / game_h, rs.gameplay_focus_x)
        return (
            f"[{src}]split=2[{out}_c][{out}_g];"
            f"[{out}_c]crop={cw}:{ch}:{cx}:{cy},scale={W}:{cam_h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W}:{cam_h},setsar=1[{out}_cam];"
            f"[{out}_g]crop={gw}:{gh}:{gx}:{gy},scale={W}:{game_h}:flags=lanczos,setsar=1[{out}_game];"
            f"[{out}_cam][{out}_game]vstack=inputs=2[{out}]"
        )

    # Blurred-background fill: zoomed foreground centred over a blurred copy.
    aspect = sw / sh
    fg_w = even(W * rs.zoom)
    fg_h = even(fg_w / aspect)
    if fg_h > H:
        fg_h = even(H)
        fg_w = even(H * aspect)
    crop_w, crop_h = min(fg_w, W), min(fg_h, H)
    bw, bh = max(even(W / 4), 2), max(even(H / 4), 2)
    return (
        f"[{src}]split=2[{out}_bs][{out}_fs];"
        f"[{out}_bs]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
        f"boxblur=10:3,scale={W}:{H},eq=brightness=-0.07:saturation=1.15,setsar=1[{out}_bg];"
        f"[{out}_fs]scale={fg_w}:{fg_h}:flags=lanczos,crop={crop_w}:{crop_h},setsar=1[{out}_fg];"
        f"[{out}_bg][{out}_fg]overlay=x={(W - crop_w) // 2}:y={(H - crop_h) // 2}[{out}]"
    )


@dataclass
class GraphInputs:
    has_audio: bool
    intro: bool = False
    outro: bool = False


def build_filtergraph(plan: EditPlan, info: MediaInfo, rs: ReframeSettings, render: RenderSettings,
                      ass_file: str | None, fonts: Path | None, inputs: GraphInputs) -> str:
    W, H, fps = render.width, render.height, render.fps
    segs = plan.segments
    k = len(segs)
    audio_src = "0:a" if inputs.has_audio else "1:a"
    parts: list[str] = []

    v_labels = [f"vs{i}" for i in range(k)]
    a_labels = [f"as{i}" for i in range(k)]
    vsplit = f"split={k}" + "".join(f"[{l}]" for l in v_labels) if k > 1 else f"null[{v_labels[0]}]"
    asplit = f"asplit={k}" + "".join(f"[{l}]" for l in a_labels) if k > 1 else f"anull[{a_labels[0]}]"
    parts.append(f"[0:v]fps={fps},setsar=1,{vsplit}")
    parts.append(f"[{audio_src}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{asplit}")
    concat_in = ""
    for i, seg in enumerate(segs):
        parts.append(f"[{v_labels[i]}]trim=start={seg.start:.3f}:end={seg.end:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[{a_labels[i]}]atrim=start={seg.start:.3f}:end={seg.end:.3f},asetpts=PTS-STARTPTS[a{i}]")
        concat_in += f"[v{i}][a{i}]"
    parts.append(f"{concat_in}concat=n={k}:v=1:a=1[vcat][acat]")

    parts.append(reframe_filter("vcat", info, rs, W, H, "vr"))
    if ass_file:
        fontsdir = f":fontsdir={escape_filter_path(fonts)}" if fonts else ""
        parts.append(f"[vr]ass=filename={escape_filter_path(ass_file)}{fontsdir},format=yuv420p[vmain]")
    else:
        parts.append("[vr]format=yuv420p[vmain]")

    audio_chain = "loudnorm=I=-14:TP=-1.5:LRA=11," if render.loudnorm else ""
    parts.append(f"[acat]{audio_chain}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[amain]")

    if inputs.intro or inputs.outro:
        idx = 2
        seq = ""
        if inputs.intro:
            seq += f"[{idx}:v][{idx}:a]"
            idx += 1
        seq += "[vmain][amain]"
        if inputs.outro:
            seq += f"[{idx}:v][{idx}:a]"
        n = 1 + int(inputs.intro) + int(inputs.outro)
        parts.append(f"{seq}concat=n={n}:v=1:a=1[vout][aout]")
    else:
        parts.append("[vmain]null[vout]")
        parts.append("[amain]anull[aout]")
    return ";".join(parts)


def normalize_bumper(path: Path, out_path: Path, render: RenderSettings, image_seconds: float = 2.0) -> Path:
    """Convert an intro/outro (video or still image) to the output format."""
    W, H, fps = render.width, render.height, render.fps
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
          f"fps={fps},setsar=1,format=yuv420p")
    if path.suffix.lower() in IMAGE_EXTS:
        args = ["-loop", "1", "-t", f"{image_seconds}", "-i", str(path),
                "-f", "lavfi", "-t", f"{image_seconds}", "-i", "anullsrc=r=48000:cl=stereo",
                "-vf", vf, "-map", "0:v", "-map", "1:a"]
    else:
        info = ffmpeg.probe(path)
        if info.has_audio:
            args = ["-i", str(path), "-vf", vf, "-map", "0:v", "-map", "0:a"]
        else:
            args = ["-i", str(path), "-f", "lavfi", "-t", f"{info.duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                    "-vf", vf, "-map", "0:v", "-map", "1:a"]
    args += ["-c:v", "libx264", "-preset", render.preset, "-crf", str(render.crf),
             "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-shortest", str(out_path)]
    ffmpeg.run(args)
    return out_path


def render_video(source: Path, out_path: Path, *, info: MediaInfo, plan: EditPlan, reframe: ReframeSettings,
                 render: RenderSettings, ass_path: Path | None, workdir: Path,
                 intro: Path | None = None, outro: Path | None = None) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    ass_name = None
    if ass_path is not None:
        local = workdir / "captions.ass"
        if ass_path.resolve() != local.resolve():
            shutil.copyfile(ass_path, local)
        ass_name = "captions.ass"  # relative to cwd=workdir: no path escaping issues

    args = ["-i", str(source)]
    if not info.has_audio:
        args += ["-f", "lavfi", "-t", f"{info.duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    else:
        args += ["-f", "lavfi", "-t", "0.1", "-i", "anullsrc=r=48000:cl=stereo"]  # keeps input indexes stable
    bumpers = []
    if intro:
        bumpers.append(normalize_bumper(intro, workdir / "intro_norm.mp4", render))
    if outro:
        bumpers.append(normalize_bumper(outro, workdir / "outro_norm.mp4", render))
    for b in bumpers:
        args += ["-i", str(b)]

    graph = build_filtergraph(plan, info, reframe, render, ass_name, fonts_dir(),
                              GraphInputs(has_audio=info.has_audio, intro=bool(intro), outro=bool(outro)))
    (workdir / "filtergraph.txt").write_text(graph, "utf-8")
    args += [
        "-filter_complex", graph,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", render.preset, "-crf", str(render.crf), "-pix_fmt", "yuv420p",
        "-r", str(render.fps), "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart", str(out_path.resolve()),
    ]
    log.info("Rendering %s (%.1fs, %s layout)", out_path.name, plan.duration, reframe.mode)
    ffmpeg.run(args, cwd=workdir)
    return out_path
