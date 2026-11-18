import json

import pytest

from clipped import cli
from clipped.models import ClipInfo, HookSettings, ReframeSettings
from clipped.pipeline import ffmpeg, runner
from clipped.pipeline.transcribe import StaticTranscriber
from tests import media
from tests.conftest import requires_ffmpeg


class CountingTranscriber(StaticTranscriber):
    calls = 0

    def transcribe(self, media_path, language=""):
        CountingTranscriber.calls += 1
        return super().transcribe(media_path, language)


@requires_ffmpeg
def test_process_clip_end_to_end(tmp_path, sample_clip, transcript, small_render):
    clip = ClipInfo(id="c1", url="https://clips.twitch.tv/c1", title="huge clutch", broadcaster_name="Shroud",
                    game_name="Counter-Strike 2")
    opts = runner.ProcessOptions(render=small_render, hook=HookSettings(mode="teaser"),
                                 reframe=ReframeSettings(mode="blur"), commentary="Watch the crosshair")
    CountingTranscriber.calls = 0
    tr = CountingTranscriber(transcript)
    result = runner.process_clip(clip, tmp_path / "w", tr, opts, source=sample_clip,
                                 choose=lambda vs: len(vs) - 1)
    assert result.chosen == len(result.variants) - 1
    assert result.output.video.exists() and result.output.thumbnail.exists()
    assert "Shroud" in result.variant.title and clip.url in result.variant.description
    assert result.analysis.hype > 0.4
    ass = (tmp_path / "w" / "captions.ass").read_text()
    assert ",Hook," in ass and ",Commentary," in ass
    assert ffmpeg.probe(result.output.video).height == 640

    # Re-analysis uses the cached transcript instead of running whisper again.
    runner.analyze_clip(clip, tmp_path / "w", tr, opts)
    assert CountingTranscriber.calls == 1


@requires_ffmpeg
def test_gate_can_skip(tmp_path, sample_clip, transcript):
    def gate(analysis):
        raise runner.SkipClip("too quiet")

    with pytest.raises(runner.SkipClip):
        runner.process_clip(ClipInfo(id="c2"), tmp_path / "w", StaticTranscriber(transcript),
                            runner.ProcessOptions(), source=sample_clip, gate=gate)
    assert not (tmp_path / "w" / "short.mp4").exists()


@requires_ffmpeg
def test_cli_process_one_clip(tmp_path, sample_clip, capsys):
    tfile = media.write_transcript(tmp_path / "t.json")
    out = tmp_path / "out"
    code = cli.main(["process", str(sample_clip), "--transcript", str(tfile), "--streamer", "TenZ",
                     "--streamer-login", "tenz", "--title", "1v4", "--game", "VALORANT",
                     "--clip-url", "https://clips.twitch.tv/X", "--layout", "split", "--facecam", "top-right",
                     "--out", str(out)])
    assert code == 0
    summary = json.loads((out / "metadata.json").read_text())
    assert summary["title"].endswith("| TenZ")
    assert "https://clips.twitch.tv/X" in summary["description"]
    assert ffmpeg.probe(out / "short.mp4").width == 1080


def test_cli_rejects_missing_file(tmp_path, capsys):
    assert cli.main(["process", str(tmp_path / "missing.mp4")]) == 2


def test_cli_doctor_runs(capsys):
    cli.main(["doctor"])
    assert "ffmpeg" in capsys.readouterr().out
