"""Messages from outside the terminal into a live TUI session.

`DeepApp.inject_external_message()` is the in-process API: a Slack thread, a Jira
comment, a CI monitor or an n8n workflow submits text into the running session,
named by its `source`. While a run is active the message is queued - steering
before the next model request, or a follow-up when the run would otherwise stop
- and an idle session starts a turn with it. The integration owns its transport,
authentication with its own service, polling and deduplication; this module only
delivers.

`pydantic-deep tui --listen` also serves that API over loopback HTTP, for an
integration that runs as its own process. The session writes where it listens,
and a bearer token, to `.pydantic-deep/session-endpoint.json`, readable by the
owner only:

    POST /messages
    Authorization: Bearer <token>
    {"text": "please also check MR 123", "source": "slack", "mode": "auto"}

It answers `202 {"delivery": "steered" | "queued" | "started"}`, `409` with the
reason when the session cannot take the message, `400` for a malformed body and
`401` without the token.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from apps.cli.debug_log import get_logger

ExternalMode = Literal["auto", "steer", "follow_up"]
"""How a message is delivered while a run is active. `auto` is a follow-up, as
plain text typed mid-run is; while idle every mode starts a turn."""

Delivery = Literal["steered", "queued", "started"]
"""What happened to an accepted message."""

ENDPOINT_FILE = "session-endpoint.json"
"""Where a listening session publishes its URL and token, in `.pydantic-deep/`."""

_MAX_BODY_BYTES = 64 * 1024


class ExternalMessageRefused(Exception):
    """The session cannot take the message now; `message` says why.

    Raised rather than dropped, so the integration can tell whoever sent it.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ExternalMessage(BaseModel):
    """The body of `POST /messages`."""

    text: str = Field(min_length=1, max_length=32_000)
    source: str = Field(pattern=r"^[\w.:-]{1,32}$")
    mode: ExternalMode = "auto"
    metadata: dict[str, str] = Field(default_factory=dict)


Inject = Callable[[ExternalMessage], Delivery]
"""Delivers one message from the server's thread and returns what happened."""


class SessionEndpoint:
    """A loopback HTTP server that hands authenticated messages to a session.

    Requests are served on a background thread; `inject` is responsible for
    crossing into the app's event loop.
    """

    def __init__(self, inject: Inject, state_dir: Path) -> None:
        self._inject = inject
        self._file = state_dir / ENDPOINT_FILE
        self._token = secrets.token_urlsafe(32)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="session-endpoint", daemon=True
        )

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}/messages"

    def start(self) -> None:
        """Publish the URL and token for integrations to read, then serve.

        The socket is already bound, so a request sent the moment the file
        appears waits in the backlog rather than being refused.

        Raises:
            OSError: The file could not be written; nothing is left listening.
        """
        try:
            self._publish()
        except OSError:
            self._server.server_close()
            raise
        self._thread.start()
        get_logger().info(f"session endpoint listening on {self.url}")

    def _publish(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        # Written private before it holds the token, then moved into place, so
        # the token is never readable by anyone else - even for a moment.
        staging = self._file.with_suffix(f".{os.getpid()}.tmp")
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump({"url": self.url, "token": self._token, "pid": os.getpid()}, fh)
        os.replace(staging, self._file)

    def stop(self) -> None:
        """Stop serving and withdraw the file, unless a newer session replaced it."""
        self._server.shutdown()
        self._server.server_close()
        try:
            published = json.loads(self._file.read_text())
        except (OSError, ValueError):
            return
        if isinstance(published, dict) and published.get("token") == self._token:
            self._file.unlink(missing_ok=True)

    def authorized(self, header: str | None) -> bool:
        scheme, _, token = (header or "").partition(" ")
        return scheme.lower() == "bearer" and secrets.compare_digest(token, self._token)

    def deliver(self, message: ExternalMessage) -> Delivery:
        return self._inject(message)


def _handler_for(endpoint: SessionEndpoint) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/messages":
                self._reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            if not endpoint.authorized(self.headers.get("Authorization")):
                self._reply(HTTPStatus.UNAUTHORIZED, {"error": "missing or wrong token"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._reply(HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
                return
            if length > _MAX_BODY_BYTES:
                self._reply(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
                return
            try:
                message = ExternalMessage.model_validate_json(self.rfile.read(length))
            except ValidationError as exc:
                self._reply(HTTPStatus.BAD_REQUEST, {"error": exc.errors(include_url=False)})
                return
            try:
                delivery = endpoint.deliver(message)
            except ExternalMessageRefused as exc:
                self._reply(HTTPStatus.CONFLICT, {"error": exc.message})
                return
            except Exception:
                # The stdlib would print the traceback over the TUI and drop the
                # connection; the sender gets a 500 and the log the traceback.
                get_logger().error("session endpoint: delivery failed", exc_info=True)
                self._reply(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "the session failed to take the message; see its log"},
                )
                return
            self._reply(HTTPStatus.ACCEPTED, {"delivery": delivery})

        def _reply(self, status: HTTPStatus, body: dict[str, Any]) -> None:
            payload = json.dumps(body, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            # The default writes to stderr, which paints over the live TUI.
            get_logger().info(f"session endpoint: {format % args}")

    return _Handler


__all__ = [
    "ENDPOINT_FILE",
    "Delivery",
    "ExternalMessage",
    "ExternalMessageRefused",
    "ExternalMode",
    "SessionEndpoint",
]
