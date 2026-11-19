import json
from pathlib import Path

import numpy as np
import pytest

from clipped.pipeline import audio
from clipped.pipeline.transcribe import (
    StaticTranscriber, Transcript, WhisperTranscriber, Word, clean_words, normalize_token,
)
from tests import media
from tests.conftest import requires_ffmpeg


def test_envelope_db_levels():
    sr = audio.SAMPLE_RATE
    loud = 0.5 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr)
    quiet = np.zeros(sr, dtype=np.float32)
    env = audio.envelope_db(np.concatenate([quiet, loud]).astype(np.float32))
    assert env.size == 20
    assert env[:10].max() <= audio.FLOOR_DB + 1
    assert -12 < env[10:].mean() < -6  # 0.5 amplitude sine is about -9 dBFS RMS


def test_analyze_finds_the_loud_burst():
    result = audio.analyze(media.synth_audio())
    assert 9.0 <= result.peak_time <= 10.5
    assert result.loud_peaks >= 1
    assert 0.1 < result.silent_ratio < 0.5
    assert result.hype > 0.5


def test_flat_audio_scores_lower_hype_than_bursty_audio():
    sr = audio.SAMPLE_RATE
    t = np.arange(12 * sr) / sr
    flat = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    assert audio.analyze(flat).hype < audio.analyze(media.synth_audio()).hype


def test_analyze_empty_audio():
    result = audio.analyze(np.zeros(0, dtype=np.float32))
    assert result.hype == 0 and result.silent_ratio == 1.0


@requires_ffmpeg
def test_analyze_file_decodes_real_media(sample_clip):
    result = audio.analyze_file(sample_clip)
    assert abs(result.duration - 12.0) < 0.2
    assert 9.0 <= result.peak_time <= 10.6


@requires_ffmpeg
def test_decode_video_without_audio_returns_empty(silent_video):
    assert audio.decode_mono(silent_video).size == 0


def test_clean_words_monotonic_and_non_overlapping():
    words = clean_words([Word(1.0, 1.5, " b"), Word(0.5, 1.2, "a"), Word(2.0, 2.0, "c"), Word(3, 3.2, "  ")])
    assert [w.text for w in words] == ["a", "b", "c"]
    for prev, cur in zip(words, words[1:]):
        assert prev.end <= cur.start
    assert words[-1].end > words[-1].start


def test_transcript_roundtrip_and_keywords(tmp_path, transcript):
    path = transcript.save(tmp_path / "t.json")
    loaded = Transcript.load(path)
    assert loaded.text == transcript.text
    hits = loaded.keyword_hits(["no way", "clutch", "insane", "missing"])
    assert [k for _, k in hits] == ["no way", "clutch", "insane"]
    assert hits[0][0] == pytest.approx(9.0)
    assert normalize_token("He's!") == "hes"


def test_static_transcriber(transcript):
    assert StaticTranscriber(transcript).transcribe(Path("x.mp4")) is transcript


def test_whisper_transcriber_maps_word_timestamps(monkeypatch):
    class W:  # faster-whisper word
        def __init__(self, s, e, t):
            self.start, self.end, self.word, self.probability = s, e, t, 0.9

    class Seg:
        words = [W(0.0, 0.4, " Hello"), W(0.5, 0.9, " chat")]

    class Info:
        language = "en"

    class FakeModel:
        def __init__(self, *a, **k):
            self.kwargs = k

        def transcribe(self, audio_in, **kwargs):
            # Must receive decoded samples, never a path: a path makes faster-whisper
            # decode through PyAV, which breaks on PyAV 19 ('metadata_errors').
            assert isinstance(audio_in, np.ndarray) and audio_in.dtype == np.float32
            assert kwargs["word_timestamps"] is True
            return iter([Seg()]), Info()

    import faster_whisper

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    monkeypatch.setattr(audio, "decode_mono", lambda path, sr=16000: np.zeros(sr * 2, dtype=np.float32))
    WhisperTranscriber._models.clear()
    result = WhisperTranscriber("tiny").transcribe(Path("clip.mp4"))
    assert [w.text for w in result.words] == ["Hello", "chat"]
    assert result.language == "en"
    WhisperTranscriber._models.clear()


def test_whisper_transcriber_never_uses_pyav(monkeypatch, sample_clip):
    """Real media through the real decode path; faster-whisper's own PyAV decoder must not run."""
    import faster_whisper
    import faster_whisper.audio as fw_audio
    import faster_whisper.transcribe as fw_transcribe

    def boom(*a, **k):
        raise AssertionError("faster-whisper's PyAV decoder was used")

    monkeypatch.setattr(fw_audio, "decode_audio", boom)
    monkeypatch.setattr(fw_transcribe, "decode_audio", boom)
    seen = {}

    class FakeModel:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, audio_in, **kwargs):
            seen["samples"] = audio_in
            return iter([]), type("Info", (), {"language": "en"})()

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    WhisperTranscriber._models.clear()
    WhisperTranscriber("tiny").transcribe(sample_clip)
    WhisperTranscriber._models.clear()
    assert seen["samples"].size > 16000  # seconds of 16 kHz mono audio


def test_whisper_transcriber_handles_video_without_audio(monkeypatch, silent_video):
    import faster_whisper

    class FakeModel:
        def __init__(self, *a, **k):
            raise AssertionError("model should not load for a clip with no audio")

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    WhisperTranscriber._models.clear()
    assert WhisperTranscriber("tiny").transcribe(silent_video).words == []


def test_audio_cache_roundtrip():
    result = audio.analyze(media.synth_audio())
    clone = audio.AudioAnalysis(**json.loads(json.dumps(result.to_dict(include_envelope=True))))
    assert clone.peak_time == result.peak_time and len(clone.envelope) == len(result.envelope)
