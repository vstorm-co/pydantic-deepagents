"""Provider API-key handling for the desktop app.

Keys are applied to the running process (``os.environ``) so the lazily-built
agent picks them up immediately, and persisted to ``.pydantic-deep/.env`` so
they survive a restart. Key *values* are never returned to the client — only
whether each provider is configured.
"""

from __future__ import annotations

import os
from pathlib import Path

# Provider id (pydantic-ai prefix) → environment variable name.
PROVIDER_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google-gla": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "CO_API_KEY",
}


def key_status() -> dict[str, bool]:
    """Return ``{provider: is_configured}`` without exposing any key value."""
    return {provider: bool(os.environ.get(env)) for provider, env in PROVIDER_ENV.items()}


def _env_path() -> Path:
    return Path.cwd() / ".pydantic-deep" / ".env"


def _persist(env_name: str, value: str) -> None:
    path = _env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.exists():
        lines = [
            line for line in path.read_text().splitlines() if not line.startswith(f"{env_name}=")
        ]
    lines.append(f"{env_name}={value}")
    path.write_text("\n".join(lines) + "\n")


def set_key(provider: str, key: str) -> bool:
    """Set a provider key in the process env + persist it. Returns success."""
    env_name = PROVIDER_ENV.get(provider)
    if env_name is None:
        return False
    os.environ[env_name] = key
    _persist(env_name, key)
    return True


__all__ = ["PROVIDER_ENV", "key_status", "set_key"]
