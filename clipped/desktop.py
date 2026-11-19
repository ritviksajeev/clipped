"""clipped as a desktop app: its own window, no browser tab, closes cleanly.

``clipped`` (no arguments) or ``clipped app`` starts the local server in the
background and opens the dashboard in an app window:

* **native** (default on Windows and macOS): a frameless native window
  (WebView2 / WebKit through pywebview). clipped draws its own title bar with
  minimise, maximise and close. While the engine is running, closing the
  window keeps clipped in the system tray (Windows) so uploads continue.
* **app**: Microsoft Edge, Chrome, Brave or Chromium in app mode, a plain
  window with no address bar or tabs. The fallback when no native window can
  be made, and the default on Linux.
* **browser**: a normal browser tab, as a last resort.

Outside the native window, closing the window quits clipped: the page sends a
heartbeat (with a per-launch token) and the server shuts down shortly after the
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
        self.on_show = None  # set by the native window: bring it back from the tray
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
    if sys.platform in ("win32", "darwin") and native_available():
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


def ask_to_show(port: int) -> bool:
    """Ask a running clipped to bring its (maybe tray-hidden) window back."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/app/show", method="POST", data=b"",
                                     headers={"X-Clipped": "1"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def find_port(host: str, start: int, tries: int = 20) -> int:
    from .server import port_free

    for port in range(start, start + tries):
        if port_free(host, port):
            return port
    raise RuntimeError(f"no free port between {start} and {start + tries - 1}")


# --------------------------------------------------------------------------- windows

def window_state_path() -> Path:
    return config.data_dir() / "window.json"


def load_window_state() -> dict:
    try:
        data = json.loads(window_state_path().read_text("utf-8"))
        w, h = int(data["width"]), int(data["height"])
        state = {"width": max(980, min(w, 4000)), "height": max(640, min(h, 3000))}
        if isinstance(data.get("x"), int) and isinstance(data.get("y"), int) and data["x"] > -200 and data["y"] > -50:
            state.update(x=data["x"], y=data["y"])
        return state
    except (OSError, ValueError, KeyError, TypeError):
        return {"width": WINDOW_SIZE[0], "height": WINDOW_SIZE[1]}


def save_window_state(win) -> None:
    try:
        state = {"width": int(win.width), "height": int(win.height), "x": int(win.x), "y": int(win.y)}
        window_state_path().write_text(json.dumps(state), "utf-8")
    except Exception:  # best effort: a missing size is not worth an error
        pass


class _Bridge:
    """Exposed to the page as window.pywebview.api (native window only).

    Attributes start with an underscore so pywebview does not expose them to
    the page as well.
    """

    def __init__(self, on_close) -> None:
        self._window = None
        self._maximized = False
        self._on_close = on_close

    def open_url(self, url: str) -> bool:
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)
            return True
        return False

    def window_control(self, action: str) -> bool:
        win = self._window
        if win is None:
            return False
        if action == "minimize":
            win.minimize()
        elif action == "toggle_maximize":
            if self._maximized:
                win.restore()
            else:
                win.maximize()
            self._maximized = not self._maximized
        elif action == "close":
            # Let this bridge call answer the page first: destroying the window
            # inside the call leaves pywebview waiting forever for its reply.
            timer = threading.Timer(0.05, self._on_close)
            timer.daemon = True
            timer.start()
        else:
            return False
        return True


class Tray:
    """System-tray icon (Windows), so clipped can keep uploading with its window closed."""

    def __init__(self, on_show, on_quit) -> None:
        self.icon = None
        self.notified = False
        if sys.platform != "win32":
            return
        try:
            import pystray
            from PIL import Image

            image = Image.open(config.assets_dir() / "icon.png")
            menu = pystray.Menu(
                pystray.MenuItem("Open clipped", lambda *_: on_show(), default=True),
                pystray.MenuItem("Quit clipped", lambda *_: on_quit()),
            )
            self.icon = pystray.Icon("clipped", image, "clipped", menu)
            self.icon.run_detached()
        except Exception as exc:  # no tray: closing the window simply quits
            log.info("No system tray (%s)", exc)
            self.icon = None

    @property
    def available(self) -> bool:
        return self.icon is not None

    def notify_once(self) -> None:
        if self.icon is None or self.notified:
            return
        self.notified = True
        try:
            self.icon.notify("clipped is still running, so uploads keep going. Open or quit it from the tray icon.",
                             "clipped is in the tray")
        except Exception:
            pass

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass


def run_native(url: str, session: "AppSession | None" = None, keep_running=lambda: False) -> None:
    """Frameless native window. Blocks until clipped quits."""
    import webview

    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True  # title-bar buttons click instead of dragging
    state = {"quitting": False}
    win_ref: dict = {}

    def quit_app() -> None:
        state["quitting"] = True
        tray.stop()
        win = win_ref.get("win")
        if win is not None:
            save_window_state(win)
            win.destroy()

    def show() -> None:
        win = win_ref.get("win")
        if win is not None:
            win.show()
            win.restore()

    def request_close() -> None:
        # Engine running + tray available: hide instead of quitting, like any
        # app that works in the background. Otherwise quit.
        if keep_running() and tray.available:
            win_ref["win"].hide()
            tray.notify_once()
        else:
            quit_app()

    def on_closing() -> bool:
        if state["quitting"]:
            return True
        if keep_running() and tray.available:
            threading.Thread(target=win_ref["win"].hide, daemon=True).start()
            tray.notify_once()
            return False  # cancel: stay in the tray
        state["quitting"] = True
        tray.stop()
        save_window_state(win_ref["win"])
        return True

    tray = Tray(on_show=show, on_quit=quit_app)
    bridge = _Bridge(on_close=request_close)
    geometry = load_window_state()
    win = webview.create_window(
        "clipped", url, min_size=(980, 640), frameless=True, easy_drag=False, background_color="#09090b",
        js_api=bridge, **geometry,
    )
    bridge._window = win
    win_ref["win"] = win
    win.events.closing += on_closing
    if session is not None:
        session.on_show = show
    try:
        webview.start()  # blocks until the window is destroyed
    finally:
        tray.stop()


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
        if ask_to_show(port):
            log.info("clipped is already running; brought its window to the front")
            return 0
        log.info("clipped is already running; opening another window")
        url = f"http://127.0.0.1:{port}/"
        if choose_window(window) != "browser" and open_app_window(url):
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
                run_native(url, session, keep_running=lambda: bool(app.state.engine.running))
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
        _exit_soon()
    return 0


def _exit_soon(grace: float = 5.0) -> None:
    """Safety net: once clipped has shut down, don't let a stray non-daemon
    thread (a GUI toolkit's, say) keep an invisible process alive."""
    def bail() -> None:
        import logging

        logging.shutdown()
        os._exit(0)

    timer = threading.Timer(grace, bail)
    timer.daemon = True
    timer.start()


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
