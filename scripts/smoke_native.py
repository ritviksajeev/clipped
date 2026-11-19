"""Open clipped's real native window and check its window chrome works.

CI runs this on Windows (WebView2 + WinForms through pywebview) to cover what
can't be tested on Linux: the frameless window, the title-bar buttons through
the JS bridge, edge resizing, maximise / restore / minimise, the tray icon,
hiding to the tray while the engine runs, coming back on a second launch, and
quitting.

    python scripts/smoke_native.py

Exit code 0 = every check passed.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

HOME = tempfile.mkdtemp(prefix="clipped-smoke-")
os.environ["CLIPPED_HOME"] = HOME
os.environ.setdefault("CLIPPED_SECRETS_FILE", os.path.join(HOME, "secrets.json"))

from clipped import desktop  # noqa: E402
from clipped.api.app import create_app  # noqa: E402
from clipped.logs import setup_logging  # noqa: E402

WIN = sys.platform == "win32"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok, detail: str = "") -> bool:
    ok = bool(ok)
    results.append((name, ok, detail))
    print(f"[{'ok' if ok else 'XX'}] {name}{'  ' + detail if detail else ''}", flush=True)
    return ok


def wait(pred, timeout: float = 30, every: float = 0.25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            value = pred()
            if value:
                return value
        except Exception:
            pass
        time.sleep(every)
    return None


class Win32:
    """Read the real window's state straight from Windows (no .NET cross-thread calls)."""

    def __init__(self) -> None:
        import ctypes

        self.u = ctypes.windll.user32
        self.u.GetWindowLongW.restype = ctypes.c_long
        self.hwnd = wait(lambda: self.u.FindWindowW(None, "clipped"), 20) or 0

    def visible(self) -> bool:
        return bool(self.u.IsWindowVisible(self.hwnd))

    def maximized(self) -> bool:
        return bool(self.u.IsZoomed(self.hwnd))

    def minimized(self) -> bool:
        return bool(self.u.IsIconic(self.hwnd))

    def has_caption(self) -> bool:
        WS_CAPTION = 0x00C00000
        return (self.u.GetWindowLongW(self.hwnd, -16) & WS_CAPTION) == WS_CAPTION


def main() -> int:
    setup_logging(None)
    session = desktop.AppSession()
    app = create_app(app_session=session, autostart=False)
    port = desktop.find_port("127.0.0.1", 8765)
    server = desktop.ServerThread(app, "127.0.0.1", port)
    server.start()
    url = f"http://127.0.0.1:{port}/?app={session.token}#/"
    engine = {"running": False}

    def drive(win, bridge, tray) -> None:
        try:
            js = win.evaluate_js
            check("window loaded", win.events.loaded.wait(90))
            check("JS bridge reaches the page",
                  wait(lambda: js("!!(window.pywebview && window.pywebview.api && window.pywebview.api.window_control)"), 40))
            check("custom title bar with window buttons", wait(lambda: js("!!document.querySelector('.titlebar .win-ctl .close')"), 40))
            check("sticker rail", wait(lambda: js("document.querySelectorAll('.rail-item').length") == 7, 20))
            w32 = Win32() if WIN else None
            if w32:
                check("found the window", w32.hwnd, hex(w32.hwnd))
                check("no OS title bar (frameless)", not w32.has_caption())

            # CI screens can be as small as 1024x768; Windows caps a window near the screen size.
            screen = desktop.primary_screen(__import__("webview"))
            check("first window fits the screen", screen and win.width <= screen[0] and win.height <= screen[1],
                  f"{win.width}x{win.height} on {screen}")
            js("window.pywebview.api.resize_window(990, 700)")
            check("edge resize through the bridge", wait(lambda: abs(win.width - 990) <= 3 and abs(win.height - 700) <= 3, 10),
                  f"{win.width}x{win.height}")

            js("document.querySelector('.win-ctl button[aria-label=\"Maximise\"]').click()")
            if w32:
                check("maximise button", wait(w32.maximized, 10))
            js("document.querySelector('.win-ctl button[aria-label=\"Restore\"]').click()")
            if w32:
                check("restore button", wait(lambda: not w32.maximized(), 10))
            js("document.querySelector('.win-ctl button[aria-label=\"Minimise\"]').click()")
            if w32:
                check("minimise button", wait(w32.minimized, 10))
            win.restore()
            time.sleep(1)

            if WIN:
                check("tray icon", tray.available)
            engine["running"] = True
            js("document.querySelector('.win-ctl .close').click()")
            if w32 and tray.available:
                check("close hides to the tray while the engine runs", wait(lambda: not w32.visible(), 10))
                check("app still serving", server.alive)
                ok = desktop.ask_to_show(port)
                check("second launch brings the window back", ok and wait(w32.visible, 10))
            engine["running"] = False
            time.sleep(0.5)
            js("document.querySelector('.win-ctl .close').click()")
        except Exception as exc:  # report and fail rather than hang
            check("driver", False, repr(exc))
            os._exit(2)

    def timeout() -> None:
        print("TIMEOUT: the window never finished", flush=True)
        os._exit(3)

    watchdog = threading.Timer(240, timeout)
    watchdog.daemon = True
    watchdog.start()
    started = time.time()
    desktop.run_native(url, session, keep_running=lambda: engine["running"], on_ready=drive)
    check("close button quits", True, f"window closed after {time.time() - started:.0f}s")
    server.stop()
    failed = [r for r in results if not r[1]]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
