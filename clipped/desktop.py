"""clipped as a desktop app: its own window, no browser tab, closes cleanly.

``clipped`` (no arguments) or ``clipped app`` starts the local server in the
background and opens the dashboard in an app window:

* **app** (default on Windows and Linux): Microsoft Edge, Chrome, Brave or
  Chromium in app mode. A plain window with no address bar or tabs, using its
  own profile under the clipped data folder. Edge ships with Windows 10/11, so
  nothing extra is installed.
* **native** (default on macOS when pywebview is installed): a native window.
* **browser**: a normal browser tab, as a last resort.

Closing the window quits clipped. The page sends a heartbeat every few
seconds (with a per-launch token), and the server shuts down shortly after the
window says goodbye or stops checking in.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import config
from .logs import get_logger

log = get_logger("desktop")

WINDOW_SIZE = (1380, 900)
IDLE_TIMEOUT = 150.0  # seconds without a heartbeat before we assume the window is gone
AWAY_TIMEOUT = 15 * 60.0  # the window said it is busy elsewhere (e.g. a sign-in popup)
BYE_GRACE = 8.0  # a reload also says goodbye; wait for the page to come back


# --------------------------------------------------------------------------- heartbeat

class AppSession:
    """Tracks whether the app window is still open."""

    def __init__(self, token: str | None = None, clock=time.monotonic) -> None:
        self.token = token or secrets.token_urlsafe(18)
        self.clock = clock
        self.started = clock()
        self.last_seen: float | None = None
        self.bye_at: float | None = None
        self.away_until: float | None = None
        self._lock = threading.Lock()

    def ping(self, token: str, *, bye: bool = False, away: bool = False) -> bool:
        if not secrets.compare_digest(token or "", self.token):
            return False
        now = self.clock()
        with self._lock:
            if bye:
                self.bye_at = now
            else:
                self.last_seen, self.bye_at = now, None
                self.away_until = now + AWAY_TIMEOUT if away else None
        return True

    @property
    def seen(self) -> bool:
        return self.last_seen is not None

    def should_close(self) -> bool:
        now = self.clock()
        with self._lock:
            if self.away_until and now < self.away_until:
                return False
            if self.bye_at is not None and now - self.bye_at > BYE_GRACE:
                return True
            return self.last_seen is not None and now - self.last_seen > IDLE_TIMEOUT


# --------------------------------------------------------------------------- app-mode browsers

def _windows_candidates() -> list[Path]:
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    rel = [Path("Microsoft/Edge/Application/msedge.exe"), Path("Google/Chrome/Application/chrome.exe"),
           Path("BraveSoftware/Brave-Browser/Application/brave.exe"), Path("Chromium/Application/chrome.exe")]
    return [Path(root) / r for r in rel for root in roots if root]


MAC_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
LINUX_NAMES = ["microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable", "chromium",
               "chromium-browser", "brave-browser"]


def find_app_browser() -> str | None:
    """A Chromium-family browser that supports app windows (--app)."""
    override = os.environ.get("CLIPPED_BROWSER")
    if override:
        return override if Path(override).exists() or shutil.which(override) else None
    if sys.platform == "win32":
        for path in _windows_candidates():
            if path.is_file():
                return str(path)
        return shutil.which("msedge") or shutil.which("chrome")
    if sys.platform == "darwin":
        return next((p for p in MAC_CANDIDATES if Path(p).exists()), None)
    return next((found for name in LINUX_NAMES if (found := shutil.which(name))), None)


def app_window_command(browser: str, url: str, profile_dir: Path, size: tuple[int, int] = WINDOW_SIZE) -> list[str]:
    return [
        browser, f"--app={url}", f"--user-data-dir={profile_dir}", f"--window-size={size[0]},{size[1]}",
        "--no-first-run", "--no-default-browser-check", "--disable-features=Translate", "--class=clipped",
    ]


def native_available() -> bool:
    try:
        import webview  # noqa: F401  (pywebview)
        return True
    except Exception:
        return False


def choose_window(requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    if sys.platform == "darwin" and native_available():
        return "native"
    if find_app_browser():
        return "app"
    if native_available():
        return "native"
    return "browser"


# --------------------------------------------------------------------------- server in a thread

class ServerThread:
    def __init__(self, app, host: str, port: int) -> None:
        import uvicorn

        self.server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False))
        self.thread = threading.Thread(target=self.server.run, daemon=True, name="clipped-server")
        self.host, self.port = host, port

    def start(self, timeout: float = 30.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.started:
                return
            if not self.thread.is_alive():
                raise RuntimeError("the clipped server stopped while starting (see the log)")
            time.sleep(0.05)
        raise RuntimeError("the clipped server did not start in time")

    @property
    def alive(self) -> bool:
        return self.thread.is_alive()

    def stop(self, timeout: float = 20.0) -> None:
        self.server.should_exit = True
        self.thread.join(timeout)


def existing_instance(port: int) -> bool:
    """Is clipped itself already answering on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1.5) as resp:
            return "version" in json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False


def find_port(host: str, start: int, tries: int = 20) -> int:
    from .server import port_free

    for port in range(start, start + tries):
        if port_free(host, port):
            return port
    raise RuntimeError(f"no free port between {start} and {start + tries - 1}")


# --------------------------------------------------------------------------- windows

class _Bridge:
    """Exposed to the page as window.pywebview.api (native window only)."""

    def open_url(self, url: str) -> bool:
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)
            return True
        return False


def run_native(url: str) -> None:
    import webview

    webview.create_window("clipped", url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], min_size=(900, 640),
                          background_color="#09090b", js_api=_Bridge())
    webview.start()  # blocks until the window is closed


def open_app_window(url: str) -> subprocess.Popen | None:
    browser = find_app_browser()
    if not browser:
        return None
    profile = config.data_dir() / "app-window"
    profile.mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log.info("Opening the clipped window")
    return subprocess.Popen(app_window_command(browser, url, profile), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


def wait_for_close(session: AppSession, server: ServerThread, proc: subprocess.Popen | None,
                   sleep=time.sleep, first_ping_timeout: float = 180.0) -> str:
    """Block until the window is gone. Returns why."""
    started = session.clock()
    exited_at: float | None = None
    while True:
        now = session.clock()
        if not server.alive:
            return "server stopped"
        if proc is not None and exited_at is None and proc.poll() is not None:
            exited_at = now
        if exited_at is not None and exited_at - started > 5:
            return "window closed"  # the window's own browser process ended
        # A quick exit means the browser handed the window to an instance that was
        # already running; from then on the heartbeat decides.
        if session.should_close():
            return "window closed"
        if exited_at is not None and not session.seen and now - started > first_ping_timeout:
            return "window never opened"
        sleep(0.5)


def run_app(port: int = config.DEFAULT_PORT, window: str = "auto", host: str = "127.0.0.1") -> int:
    from .api.app import create_app

    port = int(os.environ.get("CLIPPED_PORT", port))
    if existing_instance(port):
        log.info("clipped is already running; opening another window")
        url = f"http://127.0.0.1:{port}/"
        if choose_window(window) == "app" and open_app_window(url):
            return 0
        webbrowser.open(url)
        return 0
    port = find_port(host, port)
    session = AppSession()
    app = create_app(app_session=session)
    server = ServerThread(app, host, port)
    server.start()
    base = f"http://127.0.0.1:{port}"
    log.info("clipped %s running at %s (data: %s)", config.APP_VERSION, base, config.data_dir())
    mode = choose_window(window)
    url = f"{base}/?app={session.token}#/"
    try:
        if mode == "native":
            try:
                run_native(url)
                return 0
            except Exception as exc:  # no GUI backend available: fall back
                log.warning("Native window unavailable (%s); using an app window", exc)
                mode = "app" if find_app_browser() else "browser"
        proc = open_app_window(url) if mode == "app" else None
        if proc is None:
            log.info("Opening clipped in your browser. Close the tab to quit (or press Ctrl+C here).")
            webbrowser.open(url)
        reason = wait_for_close(session, server, proc)
        log.info("Shutting down: %s", reason)
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        server.stop()
    return 0


# --------------------------------------------------------------------------- shortcuts

def launch_command() -> tuple[str, list[str]]:
    """How a shortcut should start the app without a console window."""
    if getattr(sys, "frozen", False):
        return sys.executable, []
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if sys.platform == "win32" and pythonw.exists():
        exe = pythonw
    return str(exe), ["-m", "clipped", "app"]


def icon_path(ext: str) -> Path:
    return config.assets_dir() / f"icon.{ext}"


def create_shortcuts() -> list[Path]:
    """Desktop + Start Menu shortcuts (Windows) or an app-menu entry (Linux)."""
    target, args = launch_command()
    made: list[Path] = []
    if sys.platform == "win32":
        places = [Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop",
                  Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"]
        for folder in places:
            if not folder.is_dir():
                continue
            lnk = folder / "clipped.lnk"
            ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:CL_LNK);"
                  "$s.TargetPath=$env:CL_TARGET;$s.Arguments=$env:CL_ARGS;$s.IconLocation=$env:CL_ICON;"
                  "$s.WorkingDirectory=$env:USERPROFILE;$s.Description='clipped: Twitch clips to Shorts';$s.Save()")
            env = {**os.environ, "CL_LNK": str(lnk), "CL_TARGET": target,
                   "CL_ARGS": subprocess.list2cmdline(args), "CL_ICON": str(icon_path("ico"))}
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env, check=True,
                           capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            made.append(lnk)
    elif sys.platform.startswith("linux"):
        apps = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        entry = apps / "clipped.desktop"
        exec_line = " ".join(subprocess.list2cmdline([part]) for part in [target, *args])
        entry.write_text("[Desktop Entry]\nType=Application\nName=clipped\nComment=Twitch clips to YouTube Shorts\n"
                         f"Exec={exec_line}\nIcon={icon_path('png')}\nTerminal=false\nCategories=AudioVideo;Video;\n"
                         "StartupWMClass=clipped\n", "utf-8")
        made.append(entry)
    return made
