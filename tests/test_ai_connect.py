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
