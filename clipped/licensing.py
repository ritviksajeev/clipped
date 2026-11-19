"""Licence keys.

A key is a small record (plan, issue date, expiry, a random id) signed with
evzero's Ed25519 private key. The app carries only the public key below, so
nothing in the app, or in this repository, lets anyone make a key: forging one
means breaking Ed25519. Keys are checked offline; nothing is sent anywhere.

Key format (v1), shown to people as ``CLIP-XXXXX-XXXXX-…``:

    Crockford base32 (no padding) of  payload || signature

    payload, 20 bytes, big-endian:
        version   u8   = 1
        plan      u8   1 monthly · 2 lifetime
        issued    u32  unix seconds
        expires   u32  unix seconds, 0 = never
        id        10 random bytes
    signature 64 bytes  Ed25519 over the payload

Anything that issues keys (``scripts/license_admin.py``, or the checkout webhook
on evzero.org later) must produce exactly this layout.
"""

from __future__ import annotations

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
PLANS = {1: "monthly", 2: "lifetime"}
PAYLOAD = struct.Struct(">BBII10s")  # 20 bytes
SIG_LEN = 64
GRACE = 3 * 24 * 3600  # a monthly key keeps working 3 days past its date while the renewal arrives
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: no I, L, O, U
_DECODE = {c: i for i, c in enumerate(ALPHABET)} | {"I": 1, "L": 1, "O": 0}
BUY_URL = "https://evzero.org/clipped/buy/"


class LicenseError(ValueError):
    pass


@dataclass(frozen=True)
class License:
    plan: str
    issued: int
    expires: int  # 0 = never
    id: str  # hex, for support and revocation

    def expired(self, now: float) -> bool:
        return bool(self.expires) and now > self.expires + GRACE

    def to_dict(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        return {
            "plan": self.plan,
            "issued": self.issued,
            "expires": self.expires or None,
            "days_left": None if not self.expires else max(0, int((self.expires - now) // 86400)),
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
            raise LicenseError("That key has characters a clipped key never uses.")
        bits = (bits << 5) | _DECODE[ch]
    extra = len(text) * 5 - length * 8
    if extra < 0 or extra >= 5:
        raise LicenseError("That key is the wrong length. Paste the whole key.")
    if bits & ((1 << extra) - 1):  # unused padding bits must be zero: one spelling per key
        raise LicenseError("That isn't a valid clipped key. Check you pasted all of it.")
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


def parse(key: str, verifier: Ed25519PublicKey | None = None) -> License:
    """Decode and verify a key. Raises LicenseError with a message for people."""
    body = _normalize(key)
    if not body:
        raise LicenseError("Paste your licence key.")
    raw = b32decode(body, PAYLOAD.size + SIG_LEN)
    payload, signature = raw[:PAYLOAD.size], raw[PAYLOAD.size:]
    verifier = verifier or public_key()
    if verifier is None:
        raise LicenseError("This build of clipped can't check licence keys.")
    try:
        verifier.verify(signature, payload)
    except InvalidSignature:
        raise LicenseError("That isn't a valid clipped key. Check you pasted all of it.") from None
    version, plan, issued, expires, ident = PAYLOAD.unpack(payload)
    if version != VERSION or plan not in PLANS:
        raise LicenseError("That key is for a different version of clipped.")
    return License(plan=PLANS[plan], issued=issued, expires=expires, id=ident.hex())


def check(key: str, now: float | None = None, verifier: Ed25519PublicKey | None = None) -> License:
    """Parse and require the key to be current."""
    lic = parse(key, verifier)
    now = time.time() if now is None else now
    if lic.issued > now + 2 * 86400:
        raise LicenseError("That key isn't valid yet. Check your computer's date and time.")
    if lic.expired(now):
        raise LicenseError("That key has expired. Renew your monthly plan or get a lifetime key.")
    return lic


def issue(private_key, plan: str, *, days: int | None = None, now: float | None = None,
          ident: bytes | None = None) -> str:
    """Make a key (needs the private key, which never ships with the app)."""
    import os

    codes = {v: k for k, v in PLANS.items()}
    if plan not in codes:
        raise ValueError(f"plan must be one of {sorted(codes)}")
    now = int(time.time() if now is None else now)
    if plan == "monthly":
        expires = now + (days or 31) * 86400
    else:
        expires = now + days * 86400 if days else 0
    payload = PAYLOAD.pack(VERSION, codes[plan], now, expires, ident or os.urandom(10))
    return format_key(payload + private_key.sign(payload))


class LicenseState:
    """The licence this install is running under, checked against a clock that only moves forward.

    Winding the computer's clock back doesn't revive an expired monthly key: the latest time
    clipped has seen is remembered and used instead whenever it's later than the clock.
    """

    def __init__(self, store, db, clock=time.time) -> None:
        self.store = store
        self.db = db
        self.clock = clock
        self._cache: tuple[float, License | None, str] | None = None

    def now(self) -> float:
        seen = 0.0
        try:
            seen = float(self.db.get_value("license_seen_at") or 0)
        except (TypeError, ValueError):
            seen = 0.0
        now = max(self.clock(), seen)
        if now - seen > 3600:
            self.db.set_value("license_seen_at", str(int(now)))
        return now

    def current(self) -> tuple[License | None, str]:
        """(licence, problem). Cached for a minute; cheap enough to call on every request."""
        t = self.clock()
        if self._cache and t - self._cache[0] < 60:
            return self._cache[1], self._cache[2]
        key = self.store.get("license_key")
        lic, problem = None, ""
        if key:
            try:
                lic = check(key, now=self.now())
            except LicenseError as exc:
                problem = str(exc)
        self._cache = (t, lic, problem)
        return lic, problem

    def activate(self, key: str) -> License:
        lic = check(key, now=self.now())
        self.store.set("license_key", format_key(b32decode(_normalize(key), PAYLOAD.size + SIG_LEN)))
        self._cache = None
        return lic

    def deactivate(self) -> None:
        self.store.delete("license_key")
        self._cache = None
