"""Run the dashboard: http://localhost:8000 (bound to this computer only)."""

from __future__ import annotations

import os
import socket
import threading
import webbrowser

from . import config
from .logs import get_logger, setup_logging

log = get_logger("server")


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host if host != "0.0.0.0" else "127.0.0.1", port))
            return True
        except OSError:
            return False


def serve(host: str = "127.0.0.1", port: int = config.DEFAULT_PORT, open_browser: bool = True) -> None:
    import uvicorn

    from .api.app import create_app

    setup_logging(config.logs_dir())
    host = os.environ.get("CLIPPILOT_HOST", host)
    port = int(os.environ.get("CLIPPILOT_PORT", port))
    url = f"http://localhost:{port}"
    if not port_free(host, port):
        log.warning("Port %d is busy - ClipPilot may already be running. Opening %s", port, url)
        if open_browser:
            webbrowser.open(url)
        return
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Listening on %s - the dashboard is reachable from other devices on your network", host)
    app = create_app()
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    log.info("ClipPilot %s running at %s (data: %s)", config.APP_VERSION, url, config.data_dir())
    uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)
