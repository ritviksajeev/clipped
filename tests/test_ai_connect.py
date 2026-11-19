"""One-click AI connections: Anthropic sign-in profile, OpenRouter PKCE, local Ollama."""

import base64
import hashlib
import io
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from clipped.models import ClipInfo, MetadataSettings
from clipped.pipeline import metadata
from clipped.services import ai

CLIP = ClipInfo(id="c1", url="https://clips.twitch.tv/c1", title="insane ace", broadcaster_name="TenZ",
                broadcaster_login="tenz", game_name="VALORANT")
REPLY = {"variants": [{"style": "hype", "title": "TenZ hits the ace", "hook_text": "watch this",
                       "blurb": "unreal", "hashtags": ["#valorant"]}]}
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": json.dumps(REPLY)}]}}]}


@pytest.fixture(autouse=True)
def fresh_gemini_pauses():
    metadata.reset_gemini_pauses()  # which models are skipped is remembered per process
    yield
    metadata.reset_gemini_pauses()


# --------------------------------------------------------------------------- OpenRouter

def test_pkce_challenge_is_sha256_of_verifier():
    verifier, challenge = ai.pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected and 43 <= len(verifier) <= 128


def test_openrouter_flow_exchanges_code_with_the_same_verifier():
    flow = ai.OpenRouterConnect()
    url = flow.start("http://localhost:8000/openrouter/callback", desktop=True)
    q = parse_qs(urlparse(url).query)
    assert url.startswith(ai.OPENROUTER_AUTH_URL)
    assert q["callback_url"] == ["http://localhost:8000/openrouter/callback"]
    assert q["code_challenge_method"] == ["S256"]
    assert flow.desktop is True
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"key": "sk-or-v1-abcdef0123456789"})

    key = flow.finish("code_123", transport=httpx.MockTransport(handler))
    assert key == "sk-or-v1-abcdef0123456789"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(seen["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == q["code_challenge"][0] and seen["code"] == "code_123"
    with pytest.raises(ai.AIConnectError):  # single use
        flow.finish("code_123", transport=httpx.MockTransport(handler))


def test_openrouter_flow_rejects_expired_or_bad_codes(monkeypatch):
    flow = ai.OpenRouterConnect()
    with pytest.raises(ai.AIConnectError, match="No OpenRouter connection"):
        flow.finish("abcd")
    flow.start("http://localhost:8000/openrouter/callback")
    with pytest.raises(ai.AIConnectError, match="unexpected code"):
        flow.finish("bad code with spaces")
    flow.start("http://localhost:8000/openrouter/callback")
    real = time.time
    monkeypatch.setattr(ai.time, "time", lambda: real() + ai.PENDING_TTL + 5)
    with pytest.raises(ai.AIConnectError, match="expired"):
        flow.finish("abcd")


def test_openrouter_titles_use_the_chat_api():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        content = "Here you go:\n```json\n" + json.dumps(REPLY) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    variants = metadata.openrouter_variants("sk-or-v1-x", "", CLIP, "t", ["hype"], [],
                                            transport=httpx.MockTransport(handler))
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-or-v1-x" and seen["body"]["model"] == "openrouter/auto"
    assert variants[0].source == "openrouter" and "ace" in variants[0].title


def test_openrouter_out_of_credits_is_explained():
    transport = httpx.MockTransport(lambda r: httpx.Response(402, json={}))
    with pytest.raises(metadata.LLMError, match="credits"):
        metadata.openrouter_variants("k" * 12, "m", CLIP, "", ["hype"], [], transport=transport)


# --------------------------------------------------------------------------- Ollama

def test_ollama_detection_and_titles():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}, {"name": "qwen3:8b"}]})
        body = json.loads(request.content)
        assert body["model"] == "llama3.2:latest" and body["stream"] is False
        assert body["format"]["type"] == "object"  # structured output schema
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(REPLY)}})

    transport = httpx.MockTransport(handler)
    assert ai.ollama_status(transport=transport) == {"running": True, "models": ["llama3.2:latest", "qwen3:8b"],
                                                      "url": ai.OLLAMA_DEFAULT_URL}
    variants = metadata.ollama_variants(ai.OLLAMA_DEFAULT_URL, "", CLIP, "t", ["hype"], [], transport=transport)
    assert variants[0].source == "ollama" and calls[-1] == "/api/chat"


def test_ollama_not_running_and_remote_urls_refused():
    def refuse(request):
        raise httpx.ConnectError("refused")

    status = ai.ollama_status(transport=httpx.MockTransport(refuse))
    assert status["running"] is False and "not running" in status["message"]
    with pytest.raises(ai.AIConnectError, match="this computer"):
        ai.ollama_models("http://evil.example:11434")
    with pytest.raises(ValueError):
        MetadataSettings(ollama_url="http://10.0.0.5:11434")
    assert MetadataSettings(ollama_url="http://localhost:11434/").ollama_url == "http://localhost:11434"


# --------------------------------------------------------------------------- Anthropic sign-in

def _write_profile(base, name="default"):
    (base / "configs").mkdir(parents=True, exist_ok=True)
    (base / "credentials").mkdir(parents=True, exist_ok=True)
    (base / "configs" / f"{name}.json").write_text(json.dumps({"authentication": {"type": "user_oauth"}}), "utf-8")
    (base / "credentials" / f"{name}.json").write_text(json.dumps({"access_token": "tok"}), "utf-8")


def test_anthropic_profile_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_PROFILE", raising=False)
    assert ai.anthropic_profile()["signed_in"] is False
    _write_profile(tmp_path, "work")
    (tmp_path / "active_config").write_text("work\n", "utf-8")
    info = ai.anthropic_profile()
    assert info["signed_in"] is True and info["profile"] == "work"
    monkeypatch.setenv("ANTHROPIC_PROFILE", "../../etc")  # never escapes the config dir
    assert ai.anthropic_profile()["profile"] == "default"


class FakeProc:
    def __init__(self, lines, code, on_exit=None):
        self.stdout = io.StringIO("".join(l + "\n" for l in lines))
        self.code, self.on_exit = code, on_exit

    def poll(self):
        return None

    def wait(self, timeout=None):
        if self.on_exit:
            self.on_exit()
        return self.code

    def kill(self):
        pass


def _wait_for(login, state):
    for _ in range(200):
        if login.snapshot()["state"] == state:
            return login.snapshot()
        time.sleep(0.01)
    raise AssertionError(login.snapshot())


def test_anthropic_login_runs_the_cli_and_reports_success(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_PROFILE", raising=False)
    monkeypatch.setattr(ai, "ant_cli", lambda: "/usr/local/bin/ant")
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc(["Opening https://console.anthropic.com/oauth/authorize?x=1 in your browser"], 0,
                        on_exit=lambda: _write_profile(tmp_path))

    login = ai.AnthropicLogin(runner=runner)
    assert login.start()["state"] == "waiting"
    done = _wait_for(login, "done")
    assert seen["cmd"] == ["/usr/local/bin/ant", "auth", "login"]
    assert done["url"] == "https://console.anthropic.com/oauth/authorize?x=1"


def test_anthropic_login_failure_and_missing_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(ai, "ant_cli", lambda: None)
    with pytest.raises(ai.AIConnectError, match="not installed"):
        ai.AnthropicLogin().start()
    monkeypatch.setattr(ai, "ant_cli", lambda: "ant")
    login = ai.AnthropicLogin(runner=lambda cmd, **kw: FakeProc(["error: access denied"], 1))
    login.start()
    assert "access denied" in _wait_for(login, "failed")["message"]


def test_signed_in_anthropic_needs_no_key(monkeypatch):
    seen = {}

    def fake(api_key, model, *a, **k):
        seen["key"] = api_key
        return [metadata.Variant(style="hype", title="From Claude", hook_text="", blurb="", source="anthropic")]

    monkeypatch.setattr(metadata, "anthropic_variants", fake)
    out = metadata.generate_variants(CLIP, "", MetadataSettings(provider="anthropic"), ["hype"], [], [],
                                     {"anthropic_signed_in": True})
    assert seen["key"] is None and out[0].source == "anthropic"
    # Not signed in and no key: free templates, no call
    seen.clear()
    out = metadata.generate_variants(CLIP, "", MetadataSettings(provider="anthropic"), ["hype"], [], [], {})
    assert not seen and out[0].source == "template"


def test_credentials_never_include_profile_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    _write_profile(tmp_path)

    class Store:
        def get(self, name):
            return None

    creds = ai.credentials(Store())
    assert creds["anthropic_signed_in"] is True and "tok" not in json.dumps(creds)


# --------------------------------------------------------------------------- Google Gemini

def test_gemini_titles_request_and_reply():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": "thinking about it", "thought": True},  # thought summaries are not the answer
            {"text": json.dumps(REPLY)},
        ]}}]})

    variants = metadata.gemini_variants("AIzaSyTestKey123", "", CLIP, "t", ["hype"], [],
                                        transport=httpx.MockTransport(handler))
    assert seen["url"] == ("https://generativelanguage.googleapis.com/v1beta/models/"
                           "gemini-flash-latest:generateContent")
    assert "AIza" not in seen["url"] and seen["key"] == "AIzaSyTestKey123"  # the key never goes in the URL
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "hook_text" in seen["body"]["systemInstruction"]["parts"][0]["text"]  # exact JSON shape spelled out
    assert variants[0].source == "gemini" and "ace" in variants[0].title


@pytest.mark.parametrize("status,body,message", [
    (400, {"error": {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}, "rejected"),
    (403, {"error": {"status": "PERMISSION_DENIED"}}, "rejected"),
    (429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, "per-minute limit"),
    (404, {"error": {"status": "NOT_FOUND"}}, "not found"),
])
def test_gemini_errors_are_explained(status, body, message):
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json=body))
    with pytest.raises(metadata.LLMError, match=message):
        metadata.gemini_variants("AIzaSyTestKey123", "gemini-flash-latest", CLIP, "", ["hype"], [], transport=transport)


def test_gemini_blocked_prompt_and_bad_model_name():
    blocked = httpx.MockTransport(lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(metadata.LLMError, match="declined"):
        metadata.gemini_variants("k", "", CLIP, "", ["hype"], [], transport=blocked)
    with pytest.raises(metadata.LLMError, match="model name"):
        metadata.gemini_variants("k", "../../evil", CLIP, "", ["hype"], [])


def test_gemini_is_used_when_selected_and_keyed(monkeypatch):
    seen = {}

    def fake(api_key, model, *a, **k):
        seen.update(key=api_key, model=model)
        return [metadata.Variant(style="hype", title="From Gemini", hook_text="", blurb="", source="gemini")]

    monkeypatch.setattr(metadata, "gemini_variants", fake)
    out = metadata.generate_variants(CLIP, "", MetadataSettings(provider="gemini"), ["hype"], [], [],
                                     {"gemini_api_key": "AIzaKey"})
    assert seen == {"key": "AIzaKey", "model": "gemini-flash-latest"} and out[0].source == "gemini"
    seen.clear()
    out = metadata.generate_variants(CLIP, "", MetadataSettings(provider="gemini"), ["hype"], [], [], {})
    assert not seen and out[0].source == "template"  # no key: free templates


def test_gemini_retries_when_overloaded_then_succeeds():
    calls, waits = [], []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if len(calls) < 3:
            return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE",
                                                       "message": "The model is overloaded."}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(REPLY)}]}}]})

    variants = metadata.gemini_variants("AIzaSyTestKey123", "", CLIP, "t", ["hype"], [],
                                        transport=httpx.MockTransport(handler), sleep=waits.append)
    assert len(calls) == 3 and all("gemini-flash-latest" in c for c in calls)
    assert waits == list(metadata.RETRY_WAITS)
    assert variants[0].source == "gemini"


def test_gemini_falls_back_to_flash_lite_when_the_model_stays_busy():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if metadata.GEMINI_FALLBACK_MODEL in request.url.path:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(REPLY)}]}}]})
        return httpx.Response(503, headers={"retry-after": "5"}, json={"error": {"status": "UNAVAILABLE"}})

    waits = []
    variants = metadata.gemini_variants("AIzaSyTestKey123", "gemini-flash-latest", CLIP, "t", ["hype"], [],
                                        transport=httpx.MockTransport(handler), sleep=waits.append)
    assert [c.rsplit("/", 1)[-1] for c in calls] == ["gemini-flash-latest:generateContent"] * 3 + \
        [f"{metadata.GEMINI_FALLBACK_MODEL}:generateContent"]
    assert waits == [max(w, 5.0) for w in metadata.RETRY_WAITS]  # Retry-After is honoured
    assert variants[0].source == "gemini"


def test_gemini_overload_that_never_clears_is_explained():
    transport = httpx.MockTransport(lambda r: httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}}))
    with pytest.raises(metadata.LLMError, match="overloaded"):
        metadata.gemini_variants("AIzaSyTestKey123", "", CLIP, "", ["hype"], [], transport=transport,
                                 sleep=lambda s: None)


def test_gemini_does_not_retry_a_real_error():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})

    with pytest.raises(metadata.LLMError, match="API error 400"):
        metadata.gemini_variants("k", "", CLIP, "", ["hype"], [], transport=httpx.MockTransport(handler),
                                 sleep=lambda s: None)
    assert len(calls) == 1


def test_dropped_connections_are_retried_but_slow_replies_are_not(monkeypatch):
    monkeypatch.setattr(metadata.time, "sleep", lambda s: None)
    calls = []

    def flaky(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("reset", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(REPLY)}}]})

    out = metadata.openai_variants("sk-test", "gpt", CLIP, "t", ["hype"], [], transport=httpx.MockTransport(flaky))
    assert len(calls) == 2 and out[0].source == "openai"

    slow_calls = []

    def slow(request):
        slow_calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(metadata.LLMError, match="didn't answer"):
        metadata.gemini_variants("k", "", CLIP, "", ["hype"], [], transport=httpx.MockTransport(slow),
                                 sleep=lambda s: None)
    assert len(slow_calls) == 2  # once on the chosen model, once on Flash-Lite; never waited out twice


def test_gemini_that_hangs_falls_back_to_flash_lite():
    def handler(request):
        if metadata.GEMINI_FALLBACK_MODEL in request.url.path:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(REPLY)}]}}]})
        raise httpx.ReadTimeout("no answer", request=request)

    variants = metadata.gemini_variants("k", "", CLIP, "t", ["hype"], [], transport=httpx.MockTransport(handler),
                                        sleep=lambda s: None)
    assert variants[0].source == "gemini"


def test_titles_use_the_keys_saved_while_the_clip_was_rendering(monkeypatch):
    from types import SimpleNamespace

    from clipped.models import MetadataSettings
    from clipped.pipeline import runner

    seen = {}

    def fake_generate(clip, text, settings, styles, hashtags, keywords, keys, commentary=""):
        seen.update(provider=settings.provider, keys=keys)
        return []

    monkeypatch.setattr(metadata, "generate_variants", fake_generate)
    analysis = SimpleNamespace(clip=CLIP, transcript=SimpleNamespace(text="t"))
    opts = runner.ProcessOptions(metadata=MetadataSettings(provider="gemini"), api_keys={})
    opts.title_settings = lambda: (MetadataSettings(provider="gemini"), {"gemini_api_key": "AIzaSaved"})
    runner.make_variants(analysis, opts)
    assert seen == {"provider": "gemini", "keys": {"gemini_api_key": "AIzaSaved"}}

    def broken():
        raise RuntimeError("db locked")

    opts.title_settings = broken  # never lose the titles over it
    runner.make_variants(analysis, opts)
    assert seen["keys"] == {}


def _quota_429(per: str, limit: str, delay: str = "") -> httpx.Response:
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
        "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
        "quotaId": f"GenerateRequestsPer{per}PerProjectPerModel-FreeTier", "quotaValue": limit}]}]
    if delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    return httpx.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": details}})


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def test_daily_quota_moves_to_flash_lite_and_stops_asking_flash():
    calls, clock = [], Clock()

    def handler(request):
        calls.append(request.url.path.rsplit("/", 1)[-1].split(":")[0])
        if metadata.GEMINI_FALLBACK_MODEL in request.url.path:
            return httpx.Response(200, json=GEMINI_OK)
        return _quota_429("Day", "20", "40s")

    run = lambda: metadata.gemini_variants("AIzaKeyOne", "", CLIP, "t", ["hype"], [],  # noqa: E731
                                           transport=httpx.MockTransport(handler), sleep=lambda s: None, now=clock)
    assert run()[0].source == "gemini"
    assert calls == ["gemini-flash-latest", metadata.GEMINI_FALLBACK_MODEL]  # a quota error isn't retried
    notices = metadata.gemini_notices("AIzaKeyOne", now=clock())
    assert len(notices) == 1 and "free daily quota (20 requests a day)" in notices[0]

    calls.clear()
    clock.t += 3600
    run()
    assert calls == [metadata.GEMINI_FALLBACK_MODEL]  # Flash is left alone until Google resets it
    assert metadata.gemini_notices("AIzaOtherKey", now=clock()) == []  # another key isn't affected

    calls.clear()
    clock.t += 24 * 3600  # past midnight Pacific
    run()
    assert calls == ["gemini-flash-latest", metadata.GEMINI_FALLBACK_MODEL]


def test_when_every_model_is_out_of_quota_no_time_is_wasted():
    calls, clock = [], Clock()

    def handler(request):
        calls.append(1)
        return _quota_429("Day", "20")

    def run():
        return metadata.gemini_variants("AIzaKeyTwo", "", CLIP, "t", ["hype"], [],
                                        transport=httpx.MockTransport(handler), sleep=lambda s: None, now=clock)

    with pytest.raises(metadata.LLMError, match="free daily quota"):
        run()
    assert len(calls) == 2
    with pytest.raises(metadata.LLMError, match="free daily quota"):
        run()
    assert len(calls) == 2  # both paused: not a single request for the next clip


def test_a_model_without_free_quota_and_a_per_minute_limit():
    clock = Clock()
    transport = httpx.MockTransport(lambda r: _quota_429("Day", "0") if "flash-latest" in r.url.path
                                    else _quota_429("Minute", "10", "17s"))
    with pytest.raises(metadata.LLMError) as err:
        metadata.gemini_variants("AIzaKeyThree", "", CLIP, "t", ["hype"], [], transport=transport,
                                 sleep=lambda s: None, now=clock)
    assert "isn't included in your key's free tier" in str(err.value)
    assert "per-minute limit" in str(err.value)
    clock.t += 18  # the per-minute pause is over, the free-tier one is not
    notices = metadata.gemini_notices("AIzaKeyThree", now=clock())
    assert len(notices) == 1 and "free tier" in notices[0]


def test_an_overloaded_model_is_skipped_for_a_few_minutes():
    calls, clock = [], Clock()

    def handler(request):
        calls.append(request.url.path)
        if metadata.GEMINI_FALLBACK_MODEL in request.url.path:
            return httpx.Response(200, json=GEMINI_OK)
        return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})

    def run():
        return metadata.gemini_variants("AIzaKeyFour", "", CLIP, "t", ["hype"], [],
                                        transport=httpx.MockTransport(handler), sleep=lambda s: None, now=clock)

    run()
    assert len(calls) == 4  # three tries on Flash, then Flash-Lite
    calls.clear()
    clock.t += 60
    run()
    assert len(calls) == 1 and metadata.GEMINI_FALLBACK_MODEL in calls[0]
    calls.clear()
    clock.t += metadata.BUSY_PAUSE
    run()
    assert len(calls) == 4  # tried again once the pause is over
