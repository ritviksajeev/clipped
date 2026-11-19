"""Licence keys and the plan this computer is on.

Plans
    free      a day key from evzero.org/clipped/free (watch ads): 24 hours, locked to
              this computer, Shorts carry a small "clipped · evzero.org" watermark
              (two Shorts a day can lose it for a few more ads)
    pro       a subscription key ($2.99/month, Razorpay): no watermark, active on one
              computer at a time, re-checked with evzero.org about once a day
    lifetime  / monthly: older offline keys (gifts, early supporters); still honoured

Everything that grants access is signed with evzero's Ed25519 private key. The app
carries only the public key below, so nothing in it, or in this repository, can
make a key, a certificate or a watermark removal.

Key format, shown to people as ``CLIP-XXXXX-XXXXX-…`` (Crockford base32 of
payload || signature, no padding):

    v1 payload, 20 bytes, big-endian: version=1, plan u8, issued u32, expires u32 (0 = never), id 10 B
    v2 payload, 28 bytes:             the same with version=2, then the computer's id, 8 B
    plan codes: 1 monthly · 2 lifetime · 3 pro · 4 day

Tokens from the server (Pro certificates, watermark removals) are
``base64url(JSON) "." base64url(Ed25519 signature of the first part)``.

The licence server (ev repo, api/_lib/clipped.js) must produce exactly these layouts.
"""

from __future__ import annotations

import base64
import json
import re
import struct
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# The only half of the key pair that ever ships. Not a secret.
PUBLIC_KEY_HEX = "96aa011f963aba7bbb99322e2b350991569858856a5ae6afa7436bee8d9707de"

PREFIX = "CLIP"
VERSION = 1
PLANS = {1: "monthly", 2: "lifetime", 3: "pro", 4: "day"}
PAYLOAD = struct.Struct(">BBII10s")  # v1, 20 bytes
PAYLOAD_V2 = struct.Struct(">BBII10s8s")  # v2, 28 bytes: locked to one computer
SIG_LEN = 64
GRACE = 3 * 24 * 3600  # an offline monthly key keeps working 3 days past its date
WATERMARK_REMOVALS = 2  # per free day key
REFRESH_AFTER = 20 * 3600  # re-check a Pro subscription with evzero.org about once a day
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: no I, L, O, U
_DECODE = {c: i for i, c in enumerate(ALPHABET)} | {"I": 1, "L": 1, "O": 0}
BUY_URL = "https://evzero.org/clipped/buy/"


class LicenseError(ValueError):
    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class License:
    plan: str
    issued: int
    expires: int  # 0 = never
    id: str  # hex, for support and revocation
    device: str = ""  # day keys: the computer they belong to

    @property
    def tier(self) -> str:
        return "free" if self.plan == "day" else "pro"

    def expired(self, now: float) -> bool:
        if not self.expires:
            return False
        return now > self.expires + (GRACE if self.plan == "monthly" else 0)

    def to_dict(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        return {
            "plan": self.plan,
            "tier": self.tier,
            "issued": self.issued,
            "expires": self.expires or None,
            "days_left": None if not self.expires else max(0, int((self.expires - now) // 86400)),
            "hours_left": None if not self.expires else max(0, int((self.expires - now) // 3600)),
            "id": self.id[:8],
        }


def b32encode(data: bytes) -> str:
    bits = int.from_bytes(data, "big")
    n = (len(data) * 8 + 4) // 5
    bits <<= n * 5 - len(data) * 8
    return "".join(ALPHABET[(bits >> (5 * (n - 1 - i))) & 31] for i in range(n))


def b32decode(text: str, length: int) -> bytes:
    bits = 0
    for ch in text:
        if ch not in _DECODE:
            raise LicenseError("That key has characters a clipped key never uses.", "invalid_key")
        bits = (bits << 5) | _DECODE[ch]
    extra = len(text) * 5 - length * 8
    if extra < 0 or extra >= 5:
        raise LicenseError("That key is the wrong length. Paste the whole key.", "invalid_key")
    if bits & ((1 << extra) - 1):  # unused padding bits must be zero: one spelling per key
        raise LicenseError("That isn't a valid clipped key. Check you pasted all of it.", "invalid_key")
    return (bits >> extra).to_bytes(length, "big")


def format_key(raw: bytes) -> str:
    body = b32encode(raw)
    return PREFIX + "-" + "-".join(body[i:i + 5] for i in range(0, len(body), 5))


def _normalize(key: str) -> str:
    text = re.sub(r"[\s\-_]", "", (key or "").upper())
    return text[len(PREFIX):] if text.startswith(PREFIX) else text


def public_key() -> Ed25519PublicKey | None:
    try:
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))
    except ValueError:  # not configured: no key can be valid
        return None


def _raw(key: str) -> tuple[bytes, struct.Struct]:
    body = _normalize(key)
    if not body:
        raise LicenseError("Paste your licence key.", "invalid_key")
    for layout in (PAYLOAD, PAYLOAD_V2):
        size = layout.size + SIG_LEN
        if len(body) == (size * 8 + 4) // 5:
            return b32decode(body, size), layout
    raise LicenseError("That key is the wrong length. Paste the whole key.", "invalid_key")


def canonical(key: str) -> str:
    return format_key(_raw(key)[0])


def parse(key: str, verifier: Ed25519PublicKey | None = None) -> License:
    """Decode and verify a key's signature (not its dates). Raises LicenseError with a message for people."""
    raw, layout = _raw(key)
    payload, signature = raw[:layout.size], raw[layout.size:]
    verifier = verifier or public_key()
    if verifier is None:
        raise LicenseError("This build of clipped can't check licence keys.", "build")
    try:
        verifier.verify(signature, payload)
    except InvalidSignature:
        raise LicenseError("That isn't a valid clipped key. Check you pasted all of it.", "invalid_key") from None
    fields = layout.unpack(payload)
    version, plan, issued, expires, ident = fields[:5]
    device = fields[5].hex() if layout is PAYLOAD_V2 else ""
    if version != (2 if layout is PAYLOAD_V2 else 1) or plan not in PLANS:
        raise LicenseError("That key is for a different version of clipped. Update the app.", "version")
    if (PLANS[plan] == "day") != bool(device):
        raise LicenseError("That isn't a valid clipped key.", "invalid_key")
    return License(plan=PLANS[plan], issued=issued, expires=expires, id=ident.hex(), device=device)


def check(key: str, now: float | None = None, verifier: Ed25519PublicKey | None = None,
          device: str | None = None) -> License:
    """Parse and require the key to be current (and, for a day key, to be this computer's)."""
    lic = parse(key, verifier)
    now = time.time() if now is None else now
    if lic.issued > now + 2 * 86400:
        raise LicenseError("That key isn't valid yet. Check your computer's date and time.", "clock")
    if lic.plan == "day" and device is not None and lic.device != device:
        raise LicenseError("That free key belongs to another computer. Get your own free day: it only takes a few ads.",
                           "other_device")
    if lic.expired(now):
        if lic.plan == "day":
            raise LicenseError("Your free day is over. Get another, or go Pro for $2.99 a month.", "expired")
        raise LicenseError("That key has expired. Renew at evzero.org/clipped/buy.", "expired")
    return lic


def issue(private_key, plan: str, *, days: int | None = None, now: float | None = None,
          ident: bytes | None = None, device: str | None = None) -> str:
    """Make a key (needs the private key, which never ships with the app)."""
    import os

    codes = {v: k for k, v in PLANS.items()}
    if plan not in codes:
        raise ValueError(f"plan must be one of {sorted(codes)}")
    now = int(time.time() if now is None else now)
    if plan in ("monthly", "day"):
        expires = now + (days * 86400 if days else (31 * 86400 if plan == "monthly" else 86400))
    else:
        expires = now + days * 86400 if days else 0
    ident = ident or os.urandom(10)
    if plan == "day":
        if not device or not re.fullmatch(r"[0-9a-f]{16}", device):
            raise ValueError("a day key needs the computer's 16-hex-character id")
        payload = PAYLOAD_V2.pack(2, codes[plan], now, expires, ident, bytes.fromhex(device))
    else:
        payload = PAYLOAD.pack(VERSION, codes[plan], now, expires, ident)
    return format_key(payload + private_key.sign(payload))


def sign_token(private_key, data: dict) -> str:
    """Used by tests and scripts/license_admin.py; the live server does the same in JavaScript."""
    body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).rstrip(b"=")
    return body.decode() + "." + base64.urlsafe_b64encode(private_key.sign(body)).rstrip(b"=").decode()


def read_token(token: str, kind: str, verifier: Ed25519PublicKey | None = None) -> dict:
    """Verify and decode a signed server token (a Pro certificate or a watermark removal)."""
    try:
        body, sig = (token or "").strip().split(".")
        padded = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        (verifier or public_key()).verify(base64.urlsafe_b64decode(padded(sig)), body.encode())
        data = json.loads(base64.urlsafe_b64decode(padded(body)))
    except (ValueError, InvalidSignature, AttributeError, TypeError):
        raise LicenseError("That code isn't valid. Copy it again from the page.", "invalid_token") from None
    if not isinstance(data, dict) or data.get("t") != kind:
        raise LicenseError("That code is for something else.", "invalid_token")
    return data


class LicenseState:
    """The licence this install runs under, checked against a clock that only moves forward.

    Winding the computer's clock back doesn't revive an expired key: the latest time
    clipped has seen is remembered and used instead whenever it's later than the clock.
    """

    def __init__(self, store, db, clock=time.time, server=None, device=None) -> None:
        from . import device as device_mod
        from .services import license_server

        self.store = store
        self.db = db
        self.clock = clock
        self.server = server or license_server
        self._device = device or device_mod.device_id
        self._cache: tuple[float, License | None, str] | None = None

    @property
    def device(self) -> str:
        return self._device() if callable(self._device) else self._device

    def now(self) -> float:
        try:
            seen = float(self.db.get_value("license_seen_at") or 0)
        except (TypeError, ValueError):
            seen = 0.0
        now = max(self.clock(), seen)
        if now - seen > 3600:
            self.db.set_value("license_seen_at", str(int(now)))
        return now

    def _pro_ok(self, lic: License, now: float) -> str:
        """'' if this computer holds a current certificate for the Pro key, else why not."""
        cert_text = self.db.get_value("license_cert")
        if cert_text:
            try:
                cert = read_token(cert_text, "cert")
                if cert.get("k") == lic.id and cert.get("d") == self.device and float(cert.get("u", 0)) > now:
                    return ""
            except LicenseError:
                pass
        return self.db.get_value("license_problem") or \
            "clipped couldn't confirm your Pro subscription with evzero.org. Connect to the internet and reopen clipped."

    def current(self) -> tuple[License | None, str]:
        """(licence, problem). Cached for a minute; cheap enough to call on every request."""
        t = self.clock()
        if self._cache and t - self._cache[0] < 60:
            return self._cache[1], self._cache[2]
        key = self.store.get("license_key")
        lic, problem = None, ""
        if key:
            try:
                lic = check(key, now=self.now(), device=self.device)
                if lic.plan == "pro":
                    problem = self._pro_ok(lic, self.now())
                    if problem:
                        lic = None
            except LicenseError as exc:
                lic, problem = None, str(exc)
        self._cache = (t, lic, problem)
        return lic, problem

    def tier(self) -> str:
        lic, _ = self.current()
        return lic.tier if lic else "none"

    def activate(self, key: str, force: bool = False) -> License:
        lic = check(key, now=self.now(), device=self.device)
        if lic.plan == "pro":
            try:
                result = self.server.activate(canonical(key), self.device, force=force)
            except Exception as exc:  # LicenseServerError: offline, device limit, ended...
                raise LicenseError(str(exc), getattr(exc, "code", "")) from None
            cert = read_token(result.get("cert", ""), "cert")
            if cert.get("k") != lic.id or cert.get("d") != self.device:
                raise LicenseError("The licence server answered for a different key.", "mismatch")
            self.db.set_value("license_cert", result["cert"])
            self.db.set_value("license_cert_at", int(self.now()))
        self.db.set_value("license_problem", None)
        self.store.set("license_key", canonical(key))
        self._cache = None
        return lic

    def refresh(self, force: bool = False) -> None:
        """Re-check a Pro subscription about once a day (renewed, cancelled, moved to another computer)."""
        key = self.store.get("license_key")
        if not key:
            return
        try:
            lic = parse(key)
        except LicenseError:
            return
        if lic.plan != "pro":
            return
        last = float(self.db.get_value("license_cert_at") or 0)
        if not force and self.now() - last < REFRESH_AFTER:
            return
        try:
            result = self.server.activate(canonical(key), self.device)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if code in ("inactive", "unknown_key", "device_limit", "too_many_moves", "invalid_key"):
                self.db.set_value("license_problem", str(exc))
                self.db.set_value("license_cert", None)
                self._cache = None
            return  # offline: keep the current certificate until it runs out
        try:
            read_token(result.get("cert", ""), "cert")
        except LicenseError:
            return
        self.db.set_value("license_cert", result["cert"])
        self.db.set_value("license_cert_at", int(self.now()))
        self.db.set_value("license_problem", None)
        self._cache = None

    def deactivate(self) -> None:
        key = self.store.get("license_key")
        if key:
            try:
                if parse(key).plan == "pro":
                    self.server.deactivate(canonical(key), self.device)  # frees the slot for another computer
            except Exception:
                pass  # offline or invalid: still forget it here
        self.store.delete("license_key")
        for name in ("license_cert", "license_cert_at", "license_problem"):
            self.db.set_value(name, None)
        self._cache = None

    # ---- free tier: watermark removals (two per day key)
    def removals_used(self, lic: License) -> list[int]:
        return [int(n) for n in (self.db.get_value(f"wm_used:{lic.id}") or [])]

    def removals_left(self) -> int | None:
        lic, _ = self.current()
        if not lic or lic.tier != "free":
            return None
        return max(0, WATERMARK_REMOVALS - len(self.removals_used(lic)))

    def next_removal(self) -> int | None:
        lic, _ = self.current()
        if not lic or lic.tier != "free":
            return None
        used = self.removals_used(lic)
        return next((n for n in range(1, WATERMARK_REMOVALS + 1) if n not in used), None)

    def redeem_removal(self, token: str) -> int:
        """Spend a watermark-removal code from evzero.org. Returns which of today's two it was."""
        lic, problem = self.current()
        if not lic:
            raise LicenseError(problem or "Enter a licence key first.", "no_licence")
        if lic.tier != "free":
            raise LicenseError("Pro Shorts have no watermark to remove.", "pro")
        data = read_token(token, "wm")
        n = int(data.get("n") or 0)
        if data.get("k") != lic.id or data.get("d") != self.device:
            raise LicenseError("That removal code is for a different free day or computer.", "mismatch")
        if float(data.get("x") or 0) < self.now():
            raise LicenseError("That removal code has expired.", "expired")
        used = self.removals_used(lic)
        if n not in range(1, WATERMARK_REMOVALS + 1) or n in used:
            raise LicenseError("That removal has already been used.", "used")
        self.db.set_value(f"wm_used:{lic.id}", used + [n])
        return n
