"""Native desktop launcher.

Starts the gateway in a background thread and opens a native OS window
(pywebview) pointed at the served SPA. Pure Python — no Node/Rust runtime
needed at launch (the SPA is pre-built into ``apps/desktop/dist``).

Used by the ``pydantic-deep desktop`` CLI command. ``pywebview`` ships in the
optional ``desktop`` extra.
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request

from apps.gateway.app import create_app
from apps.gateway.auth import generate_token


def find_free_port(host: str = "127.0.0.1") -> int:
    """Return an OS-assigned free TCP port on ``host``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def wait_for_health(host: str, port: int, *, timeout: float = 10.0) -> bool:
    """Poll the gateway ``/health`` endpoint until it answers or times out."""
    deadline = time.monotonic() + timeout
    url = f"http://{host}:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)
    return False


def start_gateway_thread(host: str, port: int, token: str) -> threading.Thread:
    """Run the gateway via uvicorn in a daemon thread; return the thread."""
    import uvicorn

    app = create_app(token=token)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread


def run_desktop(
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    width: int = 1200,
    height: int = 820,
) -> int:
    """Launch the gateway and open the desktop window. Returns an exit code."""
    resolved_port = port or find_free_port(host)
    token = generate_token()
    start_gateway_thread(host, resolved_port, token)

    if not wait_for_health(host, resolved_port):
        print("Gateway failed to start.")
        return 1

    url = f"http://{host}:{resolved_port}/?token={token}"

    try:
        import webview
    except ImportError:
        print(
            "The desktop window needs pywebview.\n"
            "Install it with:  pip install 'pydantic-deep[desktop]'\n"
            f"Meanwhile the app is available at: {url}"
        )
        return 2

    window = webview.create_window(
        "pydantic·deep", url, width=width, height=height, min_size=(720, 480)
    )

    # Native menu bar (appears in the macOS top bar).
    menu = _build_menu(window, url)
    try:
        webview.start(menu=menu) if menu else webview.start()
    except TypeError:  # pragma: no cover - older pywebview without menu support
        webview.start()
    return 0


def _build_menu(window: object, url: str) -> list:  # pragma: no cover - GUI only
    """Build a small native menu; returns [] if this pywebview lacks menu support."""
    try:
        from webview.menu import Menu, MenuAction, MenuSeparator
    except Exception:
        return []

    import webbrowser

    def reload_window() -> None:
        getattr(window, "load_url", lambda _u: None)(url)

    def open_browser() -> None:
        webbrowser.open(url)

    def open_docs() -> None:
        webbrowser.open("https://github.com/vstorm-co/pydantic-deepagents")

    return [
        Menu(
            "View",
            [
                MenuAction("Reload", reload_window),
                MenuSeparator(),
                MenuAction("Open in browser", open_browser),
            ],
        ),
        Menu("Help", [MenuAction("Documentation", open_docs)]),
    ]


__all__ = [
    "find_free_port",
    "run_desktop",
    "start_gateway_thread",
    "wait_for_health",
]
