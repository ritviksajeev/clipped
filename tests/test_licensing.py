"""Licence keys: only keys signed with evzero's private key open the app."""

import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from clipped import licensing
from clipped.api.app import create_app
from clipped.db import Database
from clipped.keystore import KeyStore

pytestmark = pytest.mark.unlicensed
H = {"X-Clipped": "1"}
NOW = 1_800_000_000


@pytest.fixture
def signer(monkeypatch):
    """A throwaway key pair standing in for evzero's (whose private half isn't in the repo)."""
    key = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", pub)
    return key


def test_shipped_public_key_is_configured():
    assert len(licensing.PUBLIC_KEY_HEX) == 64 and licensing.public_key() is not None


def test_keys_are_long_and_round_trip(signer):
    key = licensing.issue(signer, "lifetime", now=NOW)
    assert key.startswith("CLIP-") and len(key.replace("-", "")) > 130
    lic = licensing.check(key, now=NOW + 10 * 365 * 86400)
    assert lic.plan == "lifetime" and lic.expires == 0
    # Spaces, lower case and a missing prefix are forgiven when pasting
    assert licensing.parse(key.lower().replace("-", " ")).id == lic.id
    assert licensing.parse(key.split("-", 1)[1]).id == lic.id


def test_forged_tampered_and_garbage_keys_are_rejected(signer):
    key = licensing.issue(signer, "lifetime", now=NOW)
    for pos in (-1, -2, 20, 60):  # any changed character, including the padding at the end
        ch = key[pos]
        for other in "0123456789ABCDEFGHJKMNPQRSTVWXYZ":
            if other == ch:
                continue
            tampered = key[:pos] + other + (key[pos + 1:] if pos != -1 else "")
            with pytest.raises(licensing.LicenseError):
                licensing.parse(tampered)
    forger = Ed25519PrivateKey.generate()  # someone else's key pair can't make a working key
    with pytest.raises(licensing.LicenseError, match="isn't a valid"):
        licensing.parse(licensing.issue(forger, "lifetime", now=NOW))
    for junk in ("", "hello", "CLIP-12345", key[:60]):
        with pytest.raises(licensing.LicenseError):
            licensing.parse(junk)


def test_monthly_keys_expire_after_a_short_grace(signer):
    key = licensing.issue(signer, "monthly", now=NOW)
    lic = licensing.check(key, now=NOW + 30 * 86400)
    assert lic.to_dict(NOW + 30 * 86400)["days_left"] == 1
    licensing.check(key, now=NOW + 33 * 86400)  # inside the 3-day grace
    with pytest.raises(licensing.LicenseError, match="expired"):
        licensing.check(key, now=NOW + 35 * 86400)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def client(tmp_path, signer):
    db = Database(tmp_path / "db.sqlite")
    store = KeyStore()
    app = create_app(db=db, store=store, allowed_hosts={"testserver"}, autostart=False)
    with TestClient(app) as c:
        yield c, app, db, store


def test_api_is_locked_until_a_valid_key_is_entered(client, signer):
    c, app, db, store = client
    assert c.get("/api/license").json()["licensed"] is False
    r = c.get("/api/status")
    assert r.status_code == 402 and r.json()["license_required"] is True
    assert c.post("/api/engine/start", headers=H).status_code == 402
    assert c.post("/api/license", json={"key": "CLIP-NOPE"}, headers=H).status_code == 400
    # The secrets API can't be used to slip a key in, and doesn't list it
    assert c.put("/api/secrets/license_key", json={"value": "x"}, headers=H).status_code == 402
    key = licensing.issue(signer, "monthly")
    r = c.post("/api/license", json={"key": key.lower()}, headers=H).json()
    assert r["licensed"] is True and r["license"]["plan"] == "monthly"
    assert store.get("license_key") == key  # stored in its canonical form
    assert c.get("/api/status").status_code == 200
    assert "license_key" not in c.get("/api/secrets").json()["secrets"]
    assert c.put("/api/secrets/license_key", json={"value": "x"}, headers=H).status_code == 404
    assert c.delete("/api/license", headers=H).json()["licensed"] is False
    assert c.get("/api/status").status_code == 402


def test_winding_the_clock_back_does_not_revive_an_expired_key(tmp_path, isolated_home, signer):
    isolated_home.mkdir(parents=True, exist_ok=True)
    db = Database(tmp_path / "db.sqlite")
    store = KeyStore()
    clock = Clock(NOW)
    state = licensing.LicenseState(store, db, clock=clock)
    state.activate(licensing.issue(signer, "monthly", now=NOW))
    clock.t = NOW + 40 * 86400
    state._cache = None
    assert state.current()[0] is None and "expired" in state.current()[1]
    clock.t = NOW + 5 * 86400  # someone sets the date back
    state._cache = None
    assert state.current()[0] is None
