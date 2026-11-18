import pytest

from clippilot.models import HookSettings
from clippilot.pipeline import audio, hooks
from clippilot.pipeline.transcribe import Word
from tests import media

KEYWORDS = ["no way", "clutch", "insane"]


@pytest.fixture
def analysis():
    return audio.analyze(media.synth_audio())


def test_trim_cut_and_teaser(analysis, transcript):
    plan = hooks.plan_edit(12.0, analysis, transcript, HookSettings(mode="teaser"), KEYWORDS)
    teaser, *main = plan.segments
    assert teaser.kind == "teaser"
    assert teaser.start <= plan.peak_time <= teaser.end
    assert 9.0 <= plan.peak_time <= 10.6
    # leading 1.5 s of silence trimmed (keeps a short lead-in)
    assert 1.2 <= main[0].start <= 1.5
    # the 2 s internal gap (5.0-7.0) was cut down to ~keep_silence
    assert len(main) == 2
    gap_kept = (main[1].start - main[0].end)
    assert gap_kept > 1.5
    assert plan.duration < 12.0
    assert any("flash-forward" in n for n in plan.notes)


def test_trim_mode_has_no_teaser(analysis, transcript):
    plan = hooks.plan_edit(12.0, analysis, transcript, HookSettings(mode="trim"), KEYWORDS)
    assert not plan.has_teaser
    assert plan.segments[0].start > 1.0


def test_off_mode_keeps_everything(analysis, transcript):
    plan = hooks.plan_edit(12.0, analysis, transcript, HookSettings(mode="off"), KEYWORDS)
    assert len(plan.segments) == 1
    assert plan.segments[0].start == 0 and plan.segments[0].end == 12.0


def test_no_teaser_when_peak_is_early(transcript):
    import numpy as np

    sr = audio.SAMPLE_RATE
    samples = media.synth_audio()
    samples[: 2 * sr] = 0.7 * np.sin(2 * np.pi * 300 * np.arange(2 * sr) / sr)  # loudest at start
    samples[int(9 * sr): int(10.5 * sr)] *= 0.1
    plan = hooks.plan_edit(12.0, audio.analyze(samples), transcript, HookSettings(mode="teaser"), [])
    assert not plan.has_teaser


def test_max_output_window_contains_peak(analysis, transcript):
    settings = HookSettings(mode="trim", max_output_seconds=10, trim_dead_air=False)
    plan = hooks.plan_edit(12.0, analysis, transcript, settings, KEYWORDS)
    assert plan.duration <= 10.01
    assert plan.segments[0].start <= plan.peak_time <= plan.segments[-1].end


def test_remap_words_follows_cuts(analysis, transcript):
    plan = hooks.plan_edit(12.0, analysis, transcript, HookSettings(mode="teaser"), KEYWORDS)
    remapped = plan.remap_words(transcript.words)
    teaser_len = plan.segments[0].length
    main0 = plan.segments[1]
    # first word "okay" at 1.6 s source -> teaser_len + (1.6 - main0.start) output
    okay = next(w for w in remapped if w.text == "okay")
    assert okay.start == pytest.approx(teaser_len + 1.6 - main0.start, abs=0.01)
    # words are in output order and inside the output duration
    assert all(a.start <= b.start for a, b in zip(remapped, remapped[1:]))
    assert remapped[-1].end <= plan.duration + 0.01
    # words after the cut gap moved earlier by the removed silence
    wait = next(w for w in remapped if w.text == "wait")
    assert wait.start < 7.1


def test_map_time_and_serialization(analysis, transcript):
    plan = hooks.plan_edit(12.0, analysis, transcript, HookSettings(mode="teaser"), KEYWORDS)
    out = plan.map_time(plan.peak_time)
    assert out is not None and out > plan.segments[0].length
    assert plan.map_time(plan.peak_time, prefer="teaser") < plan.segments[0].length
    clone = hooks.EditPlan.from_dict(plan.to_dict())
    assert clone.duration == pytest.approx(plan.duration)


def test_plan_without_audio_analysis_uses_words():
    words = [Word(2.0, 2.5, "hi"), Word(2.6, 3.0, "there")]
    from clippilot.pipeline.transcribe import Transcript

    plan = hooks.plan_edit(10.0, None, Transcript(words=words), HookSettings(mode="trim"), [])
    assert plan.duration == pytest.approx(10.0)  # no analysis -> treated as fully active
