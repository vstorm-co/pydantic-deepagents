"""Single-operator authentication for DeepResearch's HTTP and WebSocket API."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os

from starlette.requests import HTTPConnection
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_COOKIE = "deepresearch_session"
_CHALLENGE = {"WWW-Authenticate": 'Basic realm="DeepResearch", charset="UTF-8"'}
_READ_ONLY = {"GET", "HEAD", "OPTIONS"}


def operator_password() -> str:
    """Require an operator credential before the app can start."""
    password = os.environ.get("DEEPRESEARCH_PASSWORD")
    if not password:
        raise RuntimeError("Set DEEPRESEARCH_PASSWORD to start DeepResearch.")
    return password


def _valid_basic(header: str, password: bytes) -> bool:
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        credentials = base64.b64decode(encoded, validate=True)
    except binascii.Error:
        return False
    return hmac.compare_digest(credentials, b"deepresearch:" + password)


class OperatorAccess:
    """Protect all routes and check the origin of browser mutations."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        conn = HTTPConnection(scope)
        origin = conn.headers.get("origin")
        url = conn.url
        secure = url.scheme in {"https", "wss"}
        scheme = "https" if secure else "http"
        same_origin = origin is None or origin == f"{scheme}://{url.netloc}"
        origin_required = kind == "websocket" or scope["method"] not in _READ_ONLY

        configured_password = os.getenv("DEEPRESEARCH_PASSWORD")
        if not configured_password:
            await self._deny(kind, scope, receive, send, 503, "Operator access is not configured")
            return

        password = configured_password.encode("utf-8")
        cookie = hmac.new(password, b"deepresearch-browser-v1", hashlib.sha256).hexdigest()
        authorization = conn.headers.get("authorization", "")
        basic = _valid_basic(authorization, password)
        browser = hmac.compare_digest(
            conn.cookies.get(_COOKIE, "").encode("utf-8"), cookie.encode()
        )
        if origin_required and (not same_origin or (origin is None and browser and not basic)):
            await self._deny(kind, scope, receive, send, 403, "Origin not allowed")
            return
        if not (basic or browser):
            await self._deny(kind, scope, receive, send, 401, "Authentication required")
            return

        async def send_authenticated(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    ((b"cache-control", b"no-store"), (b"x-frame-options", b"SAMEORIGIN"))
                )
                if basic and not browser and scope["path"] == "/":
                    response = PlainTextResponse("")
                    response.set_cookie(
                        _COOKIE, cookie, httponly=True, secure=secure, samesite="strict"
                    )
                    headers.extend(
                        (key, value) for key, value in response.raw_headers if key == b"set-cookie"
                    )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_authenticated)

    @staticmethod
    async def _deny(
        kind: str, scope: Scope, receive: Receive, send: Send, status: int, detail: str
    ) -> None:
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = PlainTextResponse(
            detail, status_code=status, headers=_CHALLENGE if status == 401 else None
        )
        await response(scope, receive, send)
