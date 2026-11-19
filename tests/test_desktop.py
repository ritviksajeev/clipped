"""Desktop app: window lifecycle, heartbeat, app-mode browser discovery, CLI default."""

import json
import socket
import sys
import urllib.request

import pytest
from fastapi.testclient import TestClient

from clipped import desktop
from clipped.api.app import create_app


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_session_closes_after_goodbye_but_survives_a_reload():
    clock = FakeClock()
    s = desktop.AppSession("tok", clock=clock)
    assert not s.ping("wrong")
    assert s.ping("tok") and not s.should_close()
    s.ping("tok", bye=True)  # reload: goodbye...
    clock.t += 2
    s.ping("tok")  # ...and straight back
    clock.t += 20
    assert not s.should_close()
    s.ping("tok", bye=True)  # window closed for real
    clock.t += desktop.BYE_GRACE + 1
    assert s.should_close()


def test_session_times_out_without_heartbeats_unless_away():
    clock = FakeClock()
    s = desktop.AppSession("tok", clock=clock)
    clock.t += 10_000
    assert not s.should_close()  # never seen yet: the window may still be opening
    s.ping("tok")
    clock.t += desktop.IDLE_TIMEOUT + 1
    assert s.should_close()
    s.ping("tok", away=True)  # signing in in the same window
    clock.t += desktop.IDLE_TIMEOUT * 3
    assert not s.should_close()
    clock.t += desktop.AWAY_TIMEOUT
    assert s.should_close()


def test_ping_endpoint_needs_the_launch_token(tmp_path, monkeypatch, sample_clip):
    from tests.fakes import build_engine

    engine, db, store, *_ = build_engine(tmp_path, sample_clip)
    session = desktop.AppSession("launch-token")
    app = create_app(db=db, store=store, engine=engine, allowed_hosts={"testserver"}, autostart=False,
                     app_session=session)
    with TestClient(app) as client:
        assert client.post("/app/ping?token=nope").status_code == 404
        assert client.post("/app/ping?token=launch-token").json() == {"ok": True}  # no X-Clipped needed (beacon)
        assert session.seen
        client.post("/app/ping?token=launch-token&bye=true")
        assert session.bye_at is not None
    plain = create_app(db=db, store=store, engine=engine, allowed_hosts={"testserver"}, autostart=False)
    with TestClient(plain) as client:  # `clipped serve`: no app window, endpoint is inert
        assert client.post("/app/ping?token=launch-token").status_code == 404


def test_app_window_command_is_a_chromeless_window(tmp_path):
    cmd = desktop.app_window_command("msedge.exe", "http://127.0.0.1:8000/?app=t#/", tmp_path)
    assert cmd[0] == "msedge.exe"
    assert "--app=http://127.0.0.1:8000/?app=t#/" in cmd
    assert f"--user-data-dir={tmp_path}" in cmd and "--no-first-run" in cmd


def test_find_app_browser_prefers_edge_on_windows(tmp_path, monkeypatch):
    edge = tmp_path / "x86" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_text("", "utf-8")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("CLIPPED_BROWSER", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "x86"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert desktop.find_app_browser() == str(edge)
    monkeypatch.setenv("CLIPPED_BROWSER", str(tmp_path / "missing.exe"))
    assert desktop.find_app_browser() is None


def test_choose_window_falls_back(monkeypatch):
    monkeypatch.setattr(desktop, "native_available", lambda: False)
    monkeypatch.setattr(desktop, "find_app_browser", lambda: None)
    assert desktop.choose_window() == "browser"
    monkeypatch.setattr(desktop, "find_app_browser", lambda: "/usr/bin/chromium")
    assert desktop.choose_window() == "app"
    assert desktop.choose_window("browser") == "browser"


class FakeProc:
    def __init__(self, exit_after=None, clock=None):
        self.exit_after, self.clock = exit_after, clock

    def poll(self):
        if self.exit_after is not None and self.clock() >= self.exit_after:
            return 0
        return None


class FakeServer:
    alive = True


def test_wait_for_close_when_the_browser_process_ends():
    clock = FakeClock()
    s = desktop.AppSession("tok", clock=clock)
    proc = FakeProc(exit_after=clock.t + 30, clock=clock)

    def sleep(_):
        clock.t += 1

    assert desktop.wait_for_close(s, FakeServer(), proc, sleep=sleep) == "window closed"
    assert clock.t >= 1030


def test_wait_for_close_does_not_wait_for_heartbeat_timeout_when_window_process_ends():
    clock = FakeClock()
    s = desktop.AppSession("tok", clock=clock)
    proc = FakeProc(exit_after=clock.t + 30, clock=clock)

    def sleep(_):
        clock.t += 1
        if clock.t < 1030:
            s.ping("tok")  # the page was checking in until the window closed

    assert desktop.wait_for_close(s, FakeServer(), proc, sleep=sleep) == "window closed"
    assert clock.t <= 1032


def test_wait_for_close_handoff_relies_on_heartbeat():
    """Browser exits at once (handed off to a running instance): keep going while pings arrive."""
    clock = FakeClock()
    s = desktop.AppSession("tok", clock=clock)
    proc = FakeProc(exit_after=clock.t + 0.5, clock=clock)
    ticks = {"n": 0}

    def sleep(_):
        clock.t += 1
        ticks["n"] += 1
        if ticks["n"] < 60:
            s.ping("tok")
        elif ticks["n"] == 60:
            s.ping("tok", bye=True)

    assert desktop.wait_for_close(s, FakeServer(), proc, sleep=sleep) == "window closed"
    assert ticks["n"] >= 60 + desktop.BYE_GRACE


def test_server_thread_starts_and_stops(tmp_path, sample_clip):
    from tests.fakes import build_engine

    engine, db, store, *_ = build_engine(tmp_path, sample_clip)
    app = create_app(db=db, store=store, engine=engine, autostart=False)
    port = desktop.find_port("127.0.0.1", 18765)
    server = desktop.ServerThread(app, "127.0.0.1", port)
    server.start()
    try:
        assert desktop.existing_instance(port)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
            assert json.loads(resp.read())["state"] == "stopped"
        # The port is taken now, so the next free one is chosen
        assert desktop.find_port("127.0.0.1", port) != port
    finally:
        server.stop()
    assert not server.alive
    assert not desktop.existing_instance(port)


def test_existing_instance_ignores_other_programs():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        assert not desktop.existing_instance(sock.getsockname()[1])
    finally:
        sock.close()


def test_no_command_opens_the_app(monkeypatch):
    from clipped import cli

    called = {}
    monkeypatch.setattr(desktop, "run_app", lambda port, window: called.update(port=port, window=window) or 0)
    assert cli.main([]) == 0
    assert called == {"port": 8000, "window": "auto"}


def test_linux_shortcut_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    made = desktop.create_shortcuts()
    text = made[0].read_text("utf-8")
    assert made[0].name == "clipped.desktop"
    assert "-m clipped app" in text and "Terminal=false" in text and "icon.png" in text


class FakeWin:
    def __init__(self):
        self.calls = []
        self.width, self.height, self.x, self.y = 1300, 820, 40, 60

    def __getattr__(self, name):
        return lambda *a: self.calls.append(name)


def test_window_controls_from_the_title_bar():
    import time as _time

    closed = []
    bridge = desktop._Bridge(on_close=lambda: closed.append(True))
    assert bridge.window_control("minimize") is False  # no window yet
    win = FakeWin()
    bridge._window = win
    assert bridge.window_control("minimize") and bridge.window_control("toggle_maximize")
    assert bridge.window_control("toggle_maximize")
    assert win.calls == ["minimize", "maximize", "restore"]
    assert bridge.window_control("explode") is False
    assert bridge.window_control("close") is True
    assert closed == []  # deferred so the bridge call can answer the page first
    _time.sleep(0.2)
    assert closed == [True]
    # pywebview exposes public attributes to the page; the window must stay private
    assert not [k for k in vars(bridge) if not k.startswith("_")]
    assert bridge.open_url("file:///etc/passwd") is False


def test_window_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop.config, "data_dir", lambda: tmp_path)
    assert desktop.load_window_state() == {"width": desktop.WINDOW_SIZE[0], "height": desktop.WINDOW_SIZE[1]}
    desktop.save_window_state(FakeWin())
    assert desktop.load_window_state() == {"width": 1300, "height": 820, "x": 40, "y": 60}
    (tmp_path / "window.json").write_text('{"width": 200, "height": 99999, "x": -5000, "y": 3}', "utf-8")
    state = desktop.load_window_state()
    assert state["width"] == 980 and state["height"] == 3000 and "x" not in state  # clamped, off-screen dropped


def test_second_launch_brings_the_window_back(tmp_path, sample_clip):
    from tests.fakes import build_engine

    engine, db, store, *_ = build_engine(tmp_path, sample_clip)
    session = desktop.AppSession("tok")
    shown = []
    app = create_app(db=db, store=store, engine=engine, allowed_hosts={"testserver"}, autostart=False,
                     app_session=session)
    with TestClient(app) as client:
        assert client.post("/api/app/show", headers={"X-Clipped": "1"}).status_code == 404  # no native window
        session.on_show = lambda: shown.append(True)
        assert client.post("/api/app/show").status_code == 403  # cross-site guard still applies
        assert client.post("/api/app/show", headers={"X-Clipped": "1"}).json() == {"shown": True}
    assert shown == [True]


def test_native_window_is_preferred_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop, "native_available", lambda: True)
    monkeypatch.setattr(desktop, "find_app_browser", lambda: "msedge.exe")
    assert desktop.choose_window() == "native"
    monkeypatch.setattr(desktop, "native_available", lambda: False)
    assert desktop.choose_window() == "app"  # e.g. pywebview failed to install: Edge app window


def test_edge_resize_is_clamped_and_off_when_maximised():
    bridge = desktop._Bridge(on_close=lambda: None)
    assert bridge.resize_window(1200, 800) is False  # no window yet
    win = FakeWin()
    sizes = []
    win.resize = lambda w, h: sizes.append((w, h))
    bridge._window = win
    assert bridge.resize_window(1200.6, 800) and sizes[-1] == (1200, 800)
    assert bridge.resize_window(10, 10) and sizes[-1] == desktop.MIN_SIZE
    assert bridge.resize_window("wide", 3) is False
    bridge.window_control("toggle_maximize")
    assert bridge.window_state() == {"maximized": True}
    assert bridge.resize_window(1300, 900) is False and len(sizes) == 2


def test_first_window_fits_small_screens():
    big = {"width": 1380, "height": 900, "x": 2400, "y": 40}
    assert desktop.fit_to_screen(big, None) == big
    small = desktop.fit_to_screen(big, (1366, 768))
    assert small == {"width": 1326, "height": 708}  # fits, and the off-screen position is dropped
    tiny = desktop.fit_to_screen({"width": 1380, "height": 900}, (1024, 600))
    assert tiny["width"] == 984 and tiny["height"] == 600  # never below the minimum unless the screen is smaller
    assert desktop.fit_to_screen({"width": 1200, "height": 800, "x": 10, "y": 10}, (1920, 1080))["x"] == 10


def test_typing_clipped_in_command_prompt_hands_off_to_a_windowless_app(tmp_path, monkeypatch, capsys):
    from clipped import cli

    (tmp_path / "python.exe").write_text("", "utf-8")
    (tmp_path / "pythonw.exe").write_text("", "utf-8")
    started = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            started.append((cmd, kw))

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.delenv("CLIPPED_STAY_IN_CONSOLE", raising=False)
    import subprocess as sp

    monkeypatch.setattr(sp, "Popen", FakePopen)
    monkeypatch.setattr(desktop, "existing_instance", lambda port: port == 8001)
    monkeypatch.setattr(desktop, "run_app", lambda **kw: (_ for _ in ()).throw(AssertionError("should hand off")))
    assert cli.main([]) == 0
    cmd, kw = started[0]
    assert cmd == [str(tmp_path / "pythonw.exe"), "-m", "clipped", "app"]
    assert kw["creationflags"] & 0x8  # detached: no console
    assert "You can close this window" in capsys.readouterr().out
    # `clipped app` stays in the console (for logs), and shortcuts (no console) never hand off
    assert cli._hand_off_to_window(["app"]) is False
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    assert cli._hand_off_to_window([]) is False
