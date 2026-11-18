import json

import httpx
import pytest

from clippilot.models import ClipInfo, MetadataSettings
from clippilot.pipeline import metadata

CLIP = ClipInfo(id="AbcClip", url="https://clips.twitch.tv/AbcClip", title="he actually hit the 1v4",
                broadcaster_name="TenZ", broadcaster_login="tenz", game_name="VALORANT", view_count=1200,
                duration=24)


def test_template_variants_cover_requested_styles():
    variants = metadata.template_variants(CLIP, "no way that was insane", ["question", "hype", "streamer"],
                                          ["#Valorant"], ["no way"])
    assert [v.style for v in variants] == ["question", "hype", "streamer"]
    assert variants[1].hook_text == "NO WAY!"
    assert all(v.source == "template" for v in variants)


@pytest.mark.parametrize("title", ["", "totally new title", "x" * 300])
def test_finalize_always_credits_streamer_and_links_clip(title):
    v = metadata.finalize(metadata.Variant("hype", title, "HOOK", "blurb"), CLIP, MetadataSettings(), ["#fps"])
    assert "TenZ" in v.title
    assert len(v.title) <= metadata.TITLE_MAX
    assert "https://www.twitch.tv/tenz" in v.description
    assert CLIP.url in v.description
    assert "#Shorts" in v.description
    assert "<" not in v.title + v.description


def test_ensure_credit_restores_removed_credit():
    title, desc = metadata.ensure_credit("my own <title>", "I deleted the credits", CLIP)
    assert title == "my own title | TenZ"
    assert "https://www.twitch.tv/tenz" in desc and CLIP.url in desc and "#Shorts" in desc


def test_ensure_credit_long_description_keeps_credit_block():
    _, desc = metadata.ensure_credit("t", "word " * 3000, CLIP)
    assert len(desc.encode()) <= 5000
    assert desc.rstrip().endswith("#Shorts")
    assert CLIP.url in desc and "https://www.twitch.tv/tenz" in desc


def test_credit_in_title_can_be_disabled():
    title, _ = metadata.ensure_credit("clean title", "", CLIP, credit_in_title=False)
    assert title == "clean title"


def test_tags_stay_under_youtube_limit():
    many = [f"#tag{i:03d}longishword" for i in range(80)]
    tags = metadata.build_tags(many, CLIP)
    assert sum(len(t) + 1 for t in tags) <= 500
    assert tags[0] == "TenZ"


def _anthropic_payload():
    return {"variants": [
        {"style": "hype", "title": "TenZ 1v4 ACE?!", "hook_text": "WATCH THE TIMER", "blurb": "Unreal.",
         "hashtags": ["#valorant", "tenz"]},
        {"style": "question", "title": "How is this legal?", "hook_text": "HOW", "blurb": "B", "hashtags": []},
    ]}


def test_anthropic_provider(monkeypatch):
    import anthropic

    calls = {}

    class Block:
        type = "text"
        text = json.dumps(_anthropic_payload())

    class Response:
        stop_reason = "end_turn"
        content = [Block()]

    class FakeBeta:
        class messages:
            @staticmethod
            def create(**kwargs):
                calls.update(kwargs)
                return Response()

    class FakeClient:
        def __init__(self, api_key, **kwargs):
            calls["api_key"] = api_key
            self.beta = FakeBeta

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    settings = MetadataSettings(provider="anthropic", variants=3)
    variants = metadata.generate_variants(CLIP, "transcript", settings, ["hype", "question", "descriptive"], [], [],
                                          {"anthropic_api_key": "sk-ant-test-123456"})
    assert calls["model"] == "claude-opus-5-5"
    assert calls["output_config"]["format"]["type"] == "json_schema"
    assert calls["output_config"]["effort"] == "low"
    assert calls["fallbacks"] == "default"
    assert [v.style for v in variants] == ["hype", "question", "descriptive"]
    assert [v.source for v in variants] == ["anthropic", "anthropic", "template"]  # missing style filled
    assert variants[0].title.endswith("TenZ 1v4 ACE?!") or "TenZ" in variants[0].title
    assert CLIP.url in variants[0].description


def test_anthropic_refusal_falls_back_to_templates(monkeypatch):
    import anthropic

    class Response:
        stop_reason = "refusal"
        content = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.beta = type("B", (), {"messages": type("M", (), {"create": staticmethod(lambda **k: Response())})})

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    variants = metadata.generate_variants(CLIP, "", MetadataSettings(provider="anthropic"), ["hype"], [], [],
                                          {"anthropic_api_key": "sk-ant-x-123456"})
    assert variants[0].source == "template"


def test_openai_provider_with_mock_transport():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers["authorization"]
        body = json.loads(request.content)
        seen["format"] = body["response_format"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(_anthropic_payload())}}]})

    variants = metadata.openai_variants("sk-openai-test", "gpt-5-mini", CLIP, "t", ["hype", "question"], [],
                                        transport=httpx.MockTransport(handler))
    assert seen["auth"] == "Bearer sk-openai-test"
    assert seen["format"] == {"type": "json_object"}
    assert [v.source for v in variants] == ["openai", "openai"]


def test_openai_bad_key_raises():
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "nope"}))
    with pytest.raises(metadata.LLMError):
        metadata.openai_variants("bad", "m", CLIP, "", ["hype"], [], transport=transport)


def test_missing_key_uses_templates():
    variants = metadata.generate_variants(CLIP, "", MetadataSettings(provider="openai"), ["hype"], [], [], {})
    assert variants[0].source == "template"
