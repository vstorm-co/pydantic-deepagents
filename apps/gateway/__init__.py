"""HTTP + WebSocket gateway for pydantic-deep.

Exposes the agent as a local, token-authenticated REST + WebSocket service so a
desktop shell (Tauri/Electron) or any web frontend can drive the *same* agent
core the CLI and ACP adapter use — via the shared `pydantic_deep.session`
streaming layer.

Run with:  ``python -m apps.gateway``  (installs the ``gateway`` extra).
"""

from __future__ import annotations

from apps.gateway.session_manager import GatewaySession, SessionManager

__all__ = ["GatewaySession", "SessionManager"]
