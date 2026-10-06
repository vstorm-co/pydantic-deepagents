"""Discover the models a local inference server is serving, for the model picker.

Two listings cover the servers people run locally: the OpenAI-style
`GET {base_url}/models` that llama.cpp, LocalAI, vLLM and LM Studio all answer,
and Ollama's own `GET /api/tags`. Only names are read - enough to pick one; a
model's size or tool support is the server's business.

Discovery never raises and never waits long: a server that is down, slow, or
answers something else means "nothing discovered", and typing a model name by
hand still works.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from apps.cli.providers import OPENAI_COMPATIBLE_API_KEY_ENV, OPENAI_COMPATIBLE_PREFIX

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_TIMEOUT_SECONDS = 2.0


def _get_json(url: str, client: httpx.Client | None, headers: dict[str, str] | None = None) -> Any:
    """The JSON at `url`, through `client` when one is given (and left open)."""
    if client is None:
        with httpx.Client() as own:
            return _get_json(url, own, headers)
    response = client.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def openai_compatible_models(
    base_url: str | None, *, client: httpx.Client | None = None
) -> list[str]:
    """`openai-compatible:` model strings for what `base_url` serves, or none.

    Sends the keystore's `OPENAI_COMPATIBLE_API_KEY` when one is set, as the
    model calls do: a keyed vLLM or a remote LM Studio refuses the listing too.
    """
    if not base_url:
        return []
    headers: dict[str, str] = {}
    if api_key := os.environ.get(OPENAI_COMPATIBLE_API_KEY_ENV):
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        payload = _get_json(f"{base_url.rstrip('/')}/models", client, headers)
        ids = [item["id"] for item in payload["data"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return []
    return [
        f"{OPENAI_COMPATIBLE_PREFIX}{model_id}" for model_id in ids if isinstance(model_id, str)
    ]


def ollama_host() -> str:
    """Where Ollama listens: `OLLAMA_BASE_URL` without its `/v1`, else the default."""
    configured = os.environ.get("OLLAMA_BASE_URL", "").rstrip("/")
    return configured.removesuffix("/v1") or DEFAULT_OLLAMA_HOST


def ollama_models(*, client: httpx.Client | None = None) -> list[str]:
    """`ollama:` model strings for the models Ollama has pulled, or none."""
    try:
        payload = _get_json(f"{ollama_host()}/api/tags", client)
        names = [item["name"] for item in payload["models"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return []
    return [f"ollama:{name}" for name in names if isinstance(name, str)]


__all__ = ["DEFAULT_OLLAMA_HOST", "ollama_host", "ollama_models", "openai_compatible_models"]
