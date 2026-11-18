import re

from clipped.models import CaptionStyle
from clipped.pipeline import captions
from clipped.pipeline.transcribe import Word


def test_color_conversion():
    assert captions.hex_to_ass("#FFD400") == "&H0000D4FF"
    assert captions.hex_to_ass("#112233", 0x80) == "&H80332211"
    assert captions.hex_to_ass_override("#FFD400") == "&H00D4FF&"


def test_ass_time_format():
    assert captions.ass_time(0) == "0:00:00.00"
    assert captions.ass_time(61.236) == "0:01:01.24"
    assert captions.ass_time(3725.5) == "1:02:05.50"


def test_group_pages_respects_limits_and_sentences():
    words = [Word(i * 0.3, i * 0.3 + 0.25, w) for i, w in enumerate("one two three four five. six seven".split())]
    pages = captions.group_pages(words, max_words=3, max_chars=40)
    assert [[w.text for w in p] for p in pages] == [["one", "two", "three"], ["four", "five."], ["six", "seven"]]
    long_words = [Word(0, 0.2, "supercalifragilistic"), Word(0.3, 0.5, "expialidocious")]
    assert len(captions.group_pages(long_words, max_words=3, max_chars=18)) == 2


def test_group_pages_breaks_on_pauses():
    words = [Word(0, 0.2, "a"), Word(0.3, 0.5, "b"), Word(2.0, 2.2, "c")]
    assert len(captions.group_pages(words, max_words=5, max_chars=40, max_gap=0.6)) == 2


def _dialogues(ass: str) -> list[str]:
    return [l for l in ass.splitlines() if l.startswith("Dialogue:")]


def test_one_event_per_word_with_highlight(transcript):
    style = CaptionStyle()
    ass = captions.build_ass(transcript.words, style)
    events = [l for l in _dialogues(ass) if ",Caption," in l]
    assert len(events) == len(transcript.words)
    highlight = captions.hex_to_ass_override(style.highlight_color)
    for line in events:
        assert line.count(f"\\1c{highlight}") == 1  # exactly one highlighted word
        assert "\\t(0,90," in line  # pop animation
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Inter Black" in ass


def test_uppercase_and_punctuation_cleanup(transcript):
    ass = captions.build_ass(transcript.words, CaptionStyle(uppercase=True))
    assert "OKAY" in ass and "okay" not in ass.split("[Events]")[1]
    assert "WAIT," not in ass  # trailing commas removed for a clean look
    assert "WAY!" in ass  # exclamation kept


def test_event_timing_is_contiguous_within_page():
    words = [Word(0.0, 0.3, "a"), Word(0.35, 0.6, "b"), Word(0.7, 1.0, "c")]
    ass = captions.build_ass(words, CaptionStyle(max_words=3, animation="none"))
    times = [re.findall(r"Dialogue: \d,([^,]+),([^,]+),", l)[0] for l in _dialogues(ass)]
    assert times[0][1] == times[1][0] and times[1][1] == times[2][0]
    assert times[2][1] == "0:00:01.30"  # last word holds 0.3 s


def test_hook_and_commentary_overlays():
    ass = captions.build_ass(
        [], CaptionStyle(),
        hook=captions.Overlay("wait for it 😱", 0, 2),
        commentary=captions.Overlay("My take: {this} is \\N clean", 2, 10),
    )
    lines = _dialogues(ass)
    hook = next(l for l in lines if ",Hook," in l)
    assert "WAIT FOR IT" in hook and "😱" not in hook
    assert hook.startswith("Dialogue: 3,0:00:00.00,0:00:02.00")
    comm = next(l for l in lines if ",Commentary," in l)
    assert "{this}" not in comm and "\\N" not in comm.split("}", 1)[1]


def test_position_variants():
    for pos, an in (("bottom", "\\an2"), ("middle", "\\an5"), ("top", "\\an8")):
        ass = captions.build_ass([Word(0, 1, "hi")], CaptionStyle(position=pos))
        assert an in ass
