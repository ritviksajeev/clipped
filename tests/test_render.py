import pytest

from clipped.models import FACECAM_PRESETS, CaptionStyle, HookSettings, ReframeSettings
from clipped.pipeline import audio, captions, ffmpeg, hooks, render
from clipped.pipeline.ffmpeg import MediaInfo
from tests.conftest import requires_ffmpeg

LANDSCAPE = MediaInfo(duration=12, width=1920, height=1080, fps=30, has_audio=True)
PORTRAIT = MediaInfo(duration=12, width=1080, height=1920, fps=30, has_audio=True)


def test_fit_crop_geometry():
    w, h, x, y = render._fit_crop(1920, 1080, 9 / 16)
    assert (h, w) == (1080, 608) and x == 656 and y == 0
    w, h, x, y = render._fit_crop(1920, 1080, 9 / 16, focus_x=0.0)
    assert x == 0
    w, h, x, y = render._fit_crop(1920, 1080, 9 / 16, focus_x=1.0)
    assert x + w == 1920


def test_blur_filter_centres_zoomed_foreground():
    graph = render.reframe_filter("in", LANDSCAPE, ReframeSettings(mode="blur", zoom=1.0), 1080, 1920, "out")
    assert "boxblur" in graph and "scale=1080:608" in graph
    assert "overlay=x=0:y=656" in graph  # (1920-608)/2
    zoomed = render.reframe_filter("in", LANDSCAPE, ReframeSettings(mode="blur", zoom=1.2), 1080, 1920, "out")
    assert "crop=1080:" in zoomed


def test_split_filter_stacks_facecam_over_gameplay():
    rs = ReframeSettings(mode="split", facecam=FACECAM_PRESETS["top-right"], facecam_height=0.35)
    graph = render.reframe_filter("in", LANDSCAPE, rs, 1080, 1920, "out")
    assert "vstack=inputs=2" in graph
    assert "scale=1080:672" in graph and "scale=1080:1248" in graph  # 0.35*1920 even, remainder
    assert "crop=498:346:1420:0" in graph  # top-right quarter of 1920x1080


def test_split_without_facecam_falls_back_to_blur():
    graph = render.reframe_filter("in", LANDSCAPE, ReframeSettings(mode="split"), 1080, 1920, "out")
    assert "boxblur" in graph and "vstack" not in graph


def test_crop_mode_and_portrait_source():
    graph = render.reframe_filter("in", LANDSCAPE, ReframeSettings(mode="crop"), 1080, 1920, "out")
    assert graph.startswith("[in]crop=608:1080:656:0")
    graph = render.reframe_filter("in", PORTRAIT, ReframeSettings(mode="crop"), 1080, 1920, "out")
    assert "crop=1080:1920" in graph or "scale=1080:1920" in graph


def test_escape_filter_path_handles_windows_and_spaces():
    assert ffmpeg.escape_filter_path("C:\\Users\\Me\\My Fonts") == "'C\\:/Users/Me/My Fonts'"
    assert ffmpeg.escape_filter_path("captions.ass") == "'captions.ass'"


def test_filtergraph_has_one_trim_per_segment():
    plan = hooks.EditPlan([hooks.Segment(9, 11, "teaser"), hooks.Segment(1, 5), hooks.Segment(6, 12)], 12, 10)
    from clipped.models import RenderSettings

    graph = render.build_filtergraph(plan, LANDSCAPE, ReframeSettings(), RenderSettings(), "captions.ass", None,
                                     render.GraphInputs(has_audio=True, intro=True, outro=True))
    assert graph.count("trim=start=") == 6  # 3 video + 3 audio
    assert "concat=n=3:v=1:a=1[vcat][acat]" in graph
    assert "ass=filename='captions.ass'" in graph
    assert "[2:v][2:a][vmain][amain][3:v][3:a]concat=n=3" in graph
    assert "loudnorm" in graph


@requires_ffmpeg
@pytest.mark.parametrize("mode", ["blur", "split", "crop"])
def test_render_layouts(tmp_path, sample_clip, transcript, small_render, mode):
    info = ffmpeg.probe(sample_clip)
    analysis = audio.analyze_file(sample_clip)
    plan = hooks.plan_edit(info.duration, analysis, transcript, HookSettings(mode="teaser"), ["no way"])
    ass = tmp_path / "captions.ass"
    ass.write_text(captions.build_ass(plan.remap_words(transcript.words), CaptionStyle(),
                                      hook=captions.Overlay("no way", 0, 2)), "utf-8")
    rs = ReframeSettings(mode=mode, facecam=FACECAM_PRESETS["top-left"] if mode == "split" else None)
    out = render.render_video(sample_clip, tmp_path / "out.mp4", info=info, plan=plan, reframe=rs,
                              render=small_render, ass_path=ass, workdir=tmp_path / "work")
    result = ffmpeg.probe(out)
    assert (result.width, result.height) == (360, 640)
    assert result.has_audio
    assert result.duration == pytest.approx(plan.duration, abs=0.25)


@requires_ffmpeg
def test_render_without_source_audio_and_with_bumpers(tmp_path, silent_video, small_render):
    from PIL import Image

    info = ffmpeg.probe(silent_video)
    plan = hooks.EditPlan([hooks.Segment(0, info.duration)], info.duration, 1.0)
    intro = tmp_path / "intro.png"
    Image.new("RGB", (640, 360), "purple").save(intro)
    out = render.render_video(silent_video, tmp_path / "out.mp4", info=info, plan=plan, reframe=ReframeSettings(),
                              render=small_render, ass_path=None, workdir=tmp_path / "w",
                              intro=intro, outro=silent_video)
    result = ffmpeg.probe(out)
    assert result.has_audio
    assert result.duration == pytest.approx(2.0 + info.duration * 2, abs=0.3)
