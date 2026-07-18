"""v3 R1 shell: pywebview (WebView2 on Windows) over the local FastAPI
service. Single window, native title bar, localhost only, random port,
random bearer token injected into the page bootstrap — no other local
process can drive the API (charter §4).

Launch: `run_windows.bat --web` (the Tk GUI stays the default until
the R2 parity gate passes). Imports are lazy so headless environments
(CI) can import the module without a webview backend installed."""
from __future__ import annotations

import secrets
import socket
import threading


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_shell() -> int:
    import uvicorn
    import webview   # pywebview — lazy: only the shell needs it

    from forensic_viz import config
    from .server import create_app

    config.apply_user_settings(config.load_user_settings())
    token = secrets.token_urlsafe(24)
    port = _free_port()
    app = create_app(token=token)

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()

    window = webview.create_window(
        f"Forensic Stock Viz {config.APP_VERSION}",
        url=f"http://127.0.0.1:{port}/",
        width=1360, height=900, min_size=(960, 640))
    webview.start()   # blocks until the window closes
    server.should_exit = True
    return 0


if __name__ == "__main__":   # pragma: no cover - manual launch
    raise SystemExit(run_shell())
