import logging
import os
import stat

import pytest

from clipped import keystore, logs


def test_redact_registered_secret_and_patterns():
    logs.register_secret("supersecretvalue123")
    text = ("token supersecretvalue123 Authorization: Bearer abcdefghijklmnop "
            "refresh_token=1//0abcdefghijklmnopqrstuvwxyz client_secret=GOCSPX-abcdef12345 sk-ant-api03-zzzzzzzzzz")
    out = logs.redact(text)
    assert "supersecretvalue123" not in out
    assert "abcdefghijklmnop" not in out
    assert "1//0abc" not in out and "GOCSPX-abc" not in out and "api03" not in out


def test_logging_pipeline_never_emits_secret():
    logs.register_secret("my-twitch-secret-xyz")
    buffer = logs.LiveLogBuffer()
    buffer.addFilter(logs.RedactingFilter())
    logger = logging.getLogger("clipped.test.redact")
    logger.addHandler(buffer)
    logger.setLevel(logging.INFO)
    try:
        logger.info("using %s", "my-twitch-secret-xyz")
        try:
            raise ValueError("boom my-twitch-secret-xyz")
        except ValueError:
            logger.exception("failed")
    finally:
        logger.removeHandler(buffer)
    joined = " ".join(r["message"] for r in buffer.tail())
    assert "my-twitch-secret-xyz" not in joined
    assert "***" in joined


class MemoryBackend:
    name = "memory"

    def __init__(self):
        self.data = {}

    def get(self, n):
        return self.data.get(n)

    def set(self, n, v):
        self.data[n] = v

    def delete(self, n):
        self.data.pop(n, None)


def test_keystore_roundtrip_and_status():
    store = keystore.KeyStore(MemoryBackend())
    store.set("twitch_client_secret", "  abcdefghijkl  ")
    assert store.get("twitch_client_secret") == "abcdefghijkl"
    status = store.status()
    assert status["twitch_client_secret"] == {"label": "Twitch Client Secret", "set": True, "hint": "••••ijkl"}
    assert status["openai_api_key"]["set"] is False
    store.set("twitch_client_secret", "")
    assert store.get("twitch_client_secret") is None
    with pytest.raises(KeyError):
        store.get("not_a_secret")


def test_file_backend_is_owner_only(tmp_path):
    store = keystore.KeyStore(keystore.FileSecretBackend(tmp_path / "s.json"))
    store.set("anthropic_api_key", "sk-ant-123456789")
    assert store.get("anthropic_api_key") == "sk-ant-123456789"
    if os.name != "nt":
        mode = stat.S_IMODE(os.stat(tmp_path / "s.json").st_mode)
        assert mode == 0o600
    assert not store.is_os_keyring


def test_env_override_for_docker(monkeypatch):
    monkeypatch.setenv("CLIPPED_TWITCH_CLIENT_ID", "envclientid")
    store = keystore.KeyStore(MemoryBackend())
    assert store.get("twitch_client_id") == "envclientid"


def test_windows_client_disconnect_noise_is_dropped():
    import logging

    from clipped.logs import ClientDisconnectFilter

    f = ClientDisconnectFilter()
    try:
        raise ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")
    except ConnectionResetError:
        import sys

        exc_info = sys.exc_info()
    noisy = logging.LogRecord("asyncio", logging.ERROR, __file__, 1,
                              "Exception in callback _ProactorBasePipeTransport._call_connection_lost()", None, exc_info)
    assert f.filter(noisy) is False
    real = logging.LogRecord("asyncio", logging.ERROR, __file__, 1, "Task exception was never retrieved", None,
                             (ValueError, ValueError("boom"), None))
    assert f.filter(real) is True  # real problems still get logged
