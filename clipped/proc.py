"""Run helper programs (ffmpeg, ffprobe, PowerShell, a browser) without a
console window flashing up on Windows.

When clipped runs as a desktop app it has no console of its own, and Windows
then opens a fresh console window for every console program it starts. Pass
``**hidden()`` to every subprocess call.
"""

from __future__ import annotations

import subprocess
import sys


def hidden() -> dict:
    if sys.platform != "win32":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0  # SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": info}
