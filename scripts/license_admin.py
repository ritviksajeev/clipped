"""Issue clipped gift keys. For evzero only: needs the private signing key.

Customers never get keys from here: Pro keys come from Razorpay checkout on
evzero.org/clipped/buy and free day keys from evzero.org/clipped/free (both in
the ev repo, api/clipped/). This script is for gifts, testers and your own copy.

    python scripts/license_admin.py init  --out C:\\safe\\place\\clipped-signing-key.pem
    python scripts/license_admin.py issue --key C:\\safe\\place\\clipped-signing-key.pem --plan lifetime
    python scripts/license_admin.py issue --key ... --plan monthly            # 31 days
    python scripts/license_admin.py issue --key ... --plan monthly --days 62
    python scripts/license_admin.py show CLIP-XXXXX-...                        # decode and verify a key

Gift keys are checked offline and aren't locked to a computer, so anyone you
give one to could pass it on: keep them for people you trust, and prefer a
--plan monthly key with --days for testers, since it runs out by itself.

``init`` makes a new key pair and prints the public half, which goes in
clipped/licensing.py (PUBLIC_KEY_HEX). Doing that invalidates every key issued
with the old pair, so it is a one-time step. Never commit the private key file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clipped import licensing  # noqa: E402


def load_private(path: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        sys.exit("That file isn't an Ed25519 private key.")
    return key


def public_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def cmd_init(args) -> None:
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} already exists; refusing to overwrite a signing key.")
    key = Ed25519PrivateKey.generate()
    out.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    try:
        out.chmod(0o600)
    except OSError:
        pass
    print(f"Private key written to {out}. Keep it safe and never commit it.")
    print(f"PUBLIC_KEY_HEX = \"{public_hex(key)}\"")


def cmd_issue(args) -> None:
    key = load_private(args.key)
    if public_hex(key) != licensing.PUBLIC_KEY_HEX:
        sys.exit("This private key doesn't match the public key in clipped/licensing.py.")
    for _ in range(args.count):
        print(licensing.issue(key, args.plan, days=args.days))


def cmd_show(args) -> None:
    try:
        lic = licensing.parse(args.license)
    except licensing.LicenseError as exc:
        sys.exit(f"Invalid: {exc}")
    when = lambda t: dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "never"  # noqa: E731
    print(f"valid · {lic.plan} · issued {when(lic.issued)} · expires {when(lic.expires)} · id {lic.id}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="make a new signing key pair")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("issue", help="issue keys")
    p.add_argument("--key", required=True, help="private key file from init")
    p.add_argument("--plan", choices=["lifetime", "monthly"], required=True,
                   help="gift keys only: Pro and free day keys come from evzero.org")
    p.add_argument("--days", type=int, help="validity in days (monthly default 31; lifetime never expires)")
    p.add_argument("--count", type=int, default=1)
    p.set_defaults(fn=cmd_issue)
    p = sub.add_parser("show", help="decode and verify a key")
    p.add_argument("license")
    p.set_defaults(fn=cmd_show)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
