"""Token authentication for the loopback gateway.

The gateway binds to 127.0.0.1 and additionally requires a bearer token,
generated at launch and handed to the desktop shell out-of-band. This blocks
other local processes from driving the agent.
"""

from __future__ import annotations

import secrets

_BEARER_PREFIX = "Bearer "


def generate_token() -> str:
    """Return a fresh, URL-safe session token."""
    return secrets.token_urlsafe(32)


def extract_bearer(authorization: str | None) -> str:
    """Pull the raw token out of an ``Authorization: Bearer <t>`` header."""
    if not authorization:
        return ""
    if authorization.startswith(_BEARER_PREFIX):
        return authorization[len(_BEARER_PREFIX) :].strip()
    return authorization.strip()


def token_valid(provided: str | None, expected: str) -> bool:
    """Constant-time comparison of a provided token against the expected one."""
    return bool(expected) and secrets.compare_digest(provided or "", expected)


__all__ = ["extract_bearer", "generate_token", "token_valid"]
