"""Download static ffmpeg + ffprobe builds (with libass) into packaging/bin.

Used by the release workflow before running PyInstaller. Sources:
* Windows / Linux x64: BtbN FFmpeg-Builds (GPL, includes libass)
* macOS arm64 / x64:   Martin Riedl's static builds (include libass)

The script verifies that the downloaded ffmpeg has the `ass` filter and
fails the build otherwise, so a release can never ship without captions.
"""

from __future__ import annotations

import io
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "packaging" / "bin"

BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
RIEDL = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/{tool}.zip"


def fetch(url: str) -> bytes:
    print(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "clipped-build"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def extract(names: dict[str, str], data: bytes, kind: str) -> None:
    """names: archive basename -> output filename."""
    if kind == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                base = Path(info.filename).name
                if base in names:
                    (BIN / names[base]).write_bytes(zf.read(info))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tf:
            for member in tf.getmembers():
                base = Path(member.name).name
                if base in names and member.isfile():
                    (BIN / names[base]).write_bytes(tf.extractfile(member).read())


def main() -> int:
    BIN.mkdir(parents=True, exist_ok=True)
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows":
        data = fetch(f"{BTBN}/ffmpeg-master-latest-win64-gpl.zip")
        extract({"ffmpeg.exe": "ffmpeg.exe", "ffprobe.exe": "ffprobe.exe"}, data, "zip")
        exe = BIN / "ffmpeg.exe"
    elif system == "Linux":
        arch = "linuxarm64" if machine in ("aarch64", "arm64") else "linux64"
        data = fetch(f"{BTBN}/ffmpeg-master-latest-{arch}-gpl.tar.xz")
        extract({"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}, data, "tar")
        exe = BIN / "ffmpeg"
    elif system == "Darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
        for tool in ("ffmpeg", "ffprobe"):
            extract({tool: tool}, fetch(RIEDL.format(arch=arch, tool=tool)), "zip")
        exe = BIN / "ffmpeg"
    else:
        print(f"unsupported platform {system}")
        return 1

    for path in BIN.iterdir():
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    filters = subprocess.run([str(exe), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    if not any(line.split()[1:2] == ["ass"] for line in filters.splitlines() if line.strip()):
        print("ERROR: downloaded ffmpeg has no libass (ass filter); captions would not work")
        return 1
    version = subprocess.run([str(exe), "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    print(f"ok: {version}")
    print("files:", ", ".join(sorted(p.name for p in BIN.iterdir())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
