"""Free and Pro: day keys locked to a computer, watermark removals, Pro activation with one computer."""

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from clipped import licensing
from clipped.api.app import create_app
from clipped.db import Database
from clipped.keystore import KeyStore
from clipped.pipeline import captions
from clipped.services import license_server

pytestmark = pytest.mark.unlicensed
H = {"X-Clipped": "1"}
HERE = "0123456789abcdef"
THERE = "fedcba9876543210"

# Made by the live server's JavaScript (ev repo, api/_lib/clipped.js) with a fixed test key, so the
# app and the server are proven to agree on every byte of the formats.
SERVER = {
    "pub": "ea4a6c63e29c520abef5507b132ec5f9954776aebebe7b92421eea691446d22c",
    "day": "CLIP-0826P-JEJ01-RKZCR-0040G-20810-40G20-8104H-MASW9-NF6YZ-CM38W-9W95E-D58MS-0DNYD-39VAS-T4B8X-7M5TK-J7Y5K-4KZ9G-DRG2P-8TY03-BD77R-43P88-GP8CA-FZ2ES-PX3VD-EWG6S-9CC71-4VHEV-EH14W-44G",
    "pro": "CLIP-041PP-JEJ00-00000-00810-40G20-81040-G28CN-5DTRJ-2PGB1-GWVZ3-5VD93-2XAK5-714KH-N7CCC-YZEZW-CDSR7-7MSM0-X8W3V-YK61W-Z74ZD-GVZ8G-V1M66-P6YGR-D25SG-S26JJ-G6XSW-XP83R",
    "cert": "eyJ0IjoiY2VydCIsInYiOjEsImsiOiIwMjAyMDIwMjAyMDIwMjAyMDIwMiIsImQiOiIwMTIzNDU2Nzg5YWJjZGVmIiwicCI6InBybyIsInUiOjE5MDAwMDAwMDAsImkiOjE4MDAwMDAwMDB9.JjNb5T1TLY62qALKfLTcrqV0gCf74ar6DeoALCnrvvo19Uk_UXgLDF7GEL6jXdwGxM8D2bLy0G_84kDZXV1QDA",
    "wm": "eyJ0Ijoid20iLCJ2IjoxLCJrIjoiMDEwMTAxMDEwMTAxMDEwMTAxMDEiLCJuIjoxLCJkIjoiMDEyMzQ1Njc4OWFiY2RlZiIsIngiOjE5MDAwMDAwMDB9.wWcTjce_ot6_wos5vroOOdH6xOVdPQfoL9TAjpFnSBBjeB7OlEMIIxppawRCVSZZCN_YwhgUU1Aa2Z_uYOKNBQ"
}


@pytest.fixture
def signer(monkeypatch):
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", pub)
    return key


def test_keys_and_tokens_from_the_javascript_server_verify(monkeypatch):
    monkeypatch.setattr(licensing, "PUBLIC_KEY_HEX", SERVER["pub"])
    day = licensing.parse(SERVER["day"])
    assert (day.plan, day.device, day.expires, day.tier) == ("day", HERE, 1900000000, "free")
    pro = licensing.parse(SERVER["pro"])
    assert pro.plan == "pro" and pro.tier == "pro"
    assert licensing.read_token(SERVER["cert"], "cert")["k"] == pro.id
    assert licensing.read_token(SERVER["wm"], "wm")["n"] == 1
    with pytest.raises(licensing.LicenseError):
        licensing.read_token(SERVER["wm"], "cert")  # a token for one job can't do another
    with pytest.raises(licensing.LicenseError):
        licensing.read_token(SERVER["cert"][:-2] + "AA", "cert")


class FakeServer:
    """The licence server, in-process: one computer per Pro key."""

    def __init__(self, signer):
        self.signer = signer
        self.devices = {}
        self.status = "active"
        self.offline = False

    def activate(self, key, device, force=False):
        if self.offline:
            raise license_server.LicenseServerError(license_server.OFFLINE, "offline")
        lic = licensing.parse(key)
        if self.status != "active":
            raise license_server.LicenseServerError("Your Pro subscription has ended.", "inactive", 402)
        held = self.devices.get(lic.id)
        if held and held != device and not force:
            raise license_server.LicenseServerError("This key is in use on another computer.", "device_limit", 409)
        self.devices[lic.id] = device
        cert = licensing.sign_token(self.signer, {"t": "cert", "k": lic.id, "d": device, "p": "pro",
                                                  "u": time.time() + 7 * 86400})
        return {"cert": cert, "plan": "pro"}

    def deactivate(self, key, device):
        self.devices.pop(licensing.parse(key).id, None)
        return {"ok": True}


@pytest.fixture
def state(tmp_path, isolated_home, signer):
    isolated_home.mkdir(parents=True, exist_ok=True)
    server = FakeServer(signer)
    st = licensing.LicenseState(KeyStore(), Database(tmp_path / "db.sqlite"), server=server, device=HERE)
    return st, server


def test_a_free_day_key_works_only_here_and_only_for_a_day(state, signer):
    st, _ = state
    key = licensing.issue(signer, "day", device=HERE)
    assert st.activate(key).tier == "free"
    assert st.tier() == "free"
    with pytest.raises(licensing.LicenseError, match="another computer"):
        st.activate(licensing.issue(signer, "day", device=THERE))
    old = licensing.issue(signer, "day", device=HERE, now=time.time() - 2 * 86400)
    with pytest.raises(licensing.LicenseError, match="free day is over"):
        st.activate(old)


def test_two_watermark_removals_per_free_day(state, signer):
    st, _ = state
    key = licensing.issue(signer, "day", device=HERE)
    lic = st.activate(key)
    tok = lambda n, k=lic.id, d=HERE: licensing.sign_token(signer, {"t": "wm", "k": k, "n": n, "d": d, "x": time.time() + 3600})  # noqa: E731
    assert st.removals_left() == 2 and st.next_removal() == 1
    assert st.redeem_removal(tok(1)) == 1
    with pytest.raises(licensing.LicenseError, match="already been used"):
        st.redeem_removal(tok(1))
    assert st.next_removal() == 2
    with pytest.raises(licensing.LicenseError, match="different free day"):
        st.redeem_removal(tok(2, k="00" * 10))
    with pytest.raises(licensing.LicenseError, match="different free day"):
        st.redeem_removal(tok(2, d=THERE))
    assert st.redeem_removal(tok(2)) == 2
    assert st.removals_left() == 0 and st.next_removal() is None
    with pytest.raises(licensing.LicenseError, match="already been used"):
        st.redeem_removal(tok(3))


def test_pro_is_one_computer_rechecked_daily_and_ends_with_the_subscription(state, signer, tmp_path):
    st, server = state
    key = licensing.issue(signer, "pro")
    assert st.activate(key).tier == "pro"
    assert st.current()[0] is not None
    # Another computer can't use it at the same time…
    other = licensing.LicenseState(KeyStore(), Database(tmp_path / "other.sqlite"), server=server, device=THERE)
    with pytest.raises(licensing.LicenseError) as err:
        other.activate(key)
    assert err.value.code == "device_limit"
    # …unless it moves the key, which signs the first one out at its next check
    other.activate(key, force=True)
    st.refresh(force=True)
    lic, problem = st.current()
    assert lic is None and "another computer" in problem
    # Offline: the last certificate keeps working until it runs out
    server.offline = True
    other.refresh(force=True)
    assert other.current()[0] is not None
    # Cancelled: locked at the next successful check
    server.offline, server.status = False, "cancelled"
    other.refresh(force=True)
    assert other.current()[0] is None and "ended" in other.current()[1]


def test_a_certificate_for_another_computer_or_key_is_ignored(state, signer):
    st, _ = state
    key = licensing.issue(signer, "pro")
    lic = st.activate(key)
    st.db.set_value("license_cert", licensing.sign_token(signer, {"t": "cert", "k": lic.id, "d": THERE, "u": time.time() + 999}))
    st._cache = None
    assert st.current()[0] is None
    st.db.set_value("license_cert", licensing.sign_token(signer, {"t": "cert", "k": "11" * 10, "d": HERE, "u": time.time() + 999}))
    st._cache = None
    assert st.current()[0] is None


def test_the_watermark_is_drawn_on_free_shorts():
    from clipped.models import CaptionStyle

    ass = captions.build_ass([], CaptionStyle(), watermark="clipped · evzero.org", duration=12.5)
    assert "Style: Watermark" in ass and ",Watermark,,0,0,0,,clipped · evzero.org" in ass
    assert ",Watermark," not in captions.build_ass([], CaptionStyle()).split("[Events]")[1]


def test_free_day_through_the_app_api(tmp_path, isolated_home, signer, monkeypatch):
    isolated_home.mkdir(parents=True, exist_ok=True)
    from clipped import device

    monkeypatch.setattr(device, "device_id", lambda: HERE)
    handed = {}
    monkeypatch.setattr(license_server, "server", lambda transport=None: "https://licence.test/clipped")
    monkeypatch.setattr(license_server, "pickup", lambda nonce: handed.get(nonce))
    app = create_app(db=Database(tmp_path / "db.sqlite"), store=KeyStore(), allowed_hosts={"testserver"}, autostart=False)
    with TestClient(app) as c:
        assert c.get("/api/license").json()["tier"] == "none"
        start = c.post("/api/license/free", headers=H).json()
        assert f"d={HERE}" in start["url"] and start["nonce"] in start["url"]
        assert c.get(f"/api/license/free/{start['nonce']}").json() == {"pending": True}
        handed[start["nonce"]] = {"kind": "day", "value": licensing.issue(signer, "day", device=HERE)}
        done = c.get(f"/api/license/free/{start['nonce']}").json()
        assert done["done"] and done["tier"] == "free" and done["removals_left"] == 2
        # Before free days are switched on, the app says so instead of opening a dead page
        def not_live(transport=None):
            raise license_server.LicenseServerError(license_server.NOT_LIVE, "not_live")
        monkeypatch.setattr(license_server, "server", not_live)
        r = c.post("/api/license/free", headers=H)
        assert r.status_code == 503 and "aren't switched on yet" in r.json()["detail"]
        assert c.get("/api/status").status_code == 200
        # a Pro key that's in use elsewhere comes back as 409 with a code the UI can act on
        def busy(key, device, force=False):
            raise license_server.LicenseServerError("This key is in use on another computer.", "device_limit", 409)
        monkeypatch.setattr(license_server, "activate", busy)
        r = c.post("/api/license", json={"key": licensing.issue(signer, "pro")}, headers=H)
        assert r.status_code == 409 and r.json()["code"] == "device_limit"


@pytest.mark.ffmpeg
def test_free_plan_shorts_carry_the_watermark_until_removed_or_pro(tmp_path, sample_clip):
    from clipped.models import CategorySettings
    from tests.fakes import build_engine, make_clip

    engine, db, store, twitch, yt, clock = build_engine(tmp_path, sample_clip)
    engine.tier_of = lambda: "free"
    twitch.clips = [make_clip(0, sample_clip, now=clock())]
    db.add_category("516575", "VALORANT", settings=CategorySettings())
    engine.fetch_due()
    item = engine.render_step()
    ass = tmp_path / "work" / item["clip_id"] / "captions.ass"
    assert "evzero.org" in ass.read_text("utf-8") and item["analysis"]["watermarked"] is True
    # A removal (after the ads) re-renders this one Short clean
    db.update_item(item["id"], analysis={**item["analysis"], "watermark": False}, needs_rerender=True)
    done = engine.rerender_item(item["id"])
    assert "evzero.org" not in ass.read_text("utf-8") and done["analysis"]["watermarked"] is False
    # Upgrading to Pro: anything rendered on the free plan is re-rendered clean before it uploads
    db.update_item(item["id"], analysis={**done["analysis"], "watermark": True})
    engine.rerender_item(item["id"])
    assert "evzero.org" in ass.read_text("utf-8")
    engine.tier_of = lambda: "pro"
    db.update_item(item["id"], status="approved", approved_at=clock())
    assert engine.upload_item(item["id"])["youtube_id"]
    assert "evzero.org" not in ass.read_text("utf-8")
