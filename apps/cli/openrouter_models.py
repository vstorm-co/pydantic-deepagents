"""Fetch the OpenRouter model catalogue dynamically.

Pulls the live model list from OpenRouter's public API so we never hand-maintain
it, and caches the result under ``~/.pydantic-deep/cache/`` with a TTL. The
parsing is a pure function so it can be tested without network access.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from apps.cli.config import get_global_dir

_API_URL = "https://openrouter.ai/api/v1/models"
_CACHE_TTL_SECONDS = 24 * 3600


@dataclass(frozen=True)
class OpenRouterModel:
    """A model offered by OpenRouter.

    Attributes:
        id: OpenRouter slug, e.g. ``deepseek/deepseek-v4-flash``. Prefix with
            ``openrouter:`` to use it as a pydantic-ai model string.
        name: Human-readable name.
        context_length: Max context window in tokens (0 if unknown).
        prompt_price: USD per prompt token (0.0 if unknown/free).
        completion_price: USD per completion token (0.0 if unknown/free).
    """

    id: str
    name: str
    context_length: int
    prompt_price: float
    completion_price: float

    @property
    def model_string(self) -> str:
        """pydantic-ai model string, e.g. ``openrouter:deepseek/deepseek-v4-flash``."""
        return f"openrouter:{self.id}"


def parse_models(payload: dict) -> list[OpenRouterModel]:
    """Parse an OpenRouter ``/models`` response into model records.

    Tolerates missing fields; entries without an ``id`` are skipped.
    """
    out: list[OpenRouterModel] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        pricing = item.get("pricing") or {}
        out.append(
            OpenRouterModel(
                id=model_id,
                name=str(item.get("name") or model_id),
                context_length=int(item.get("context_length") or 0),
                prompt_price=_to_float(pricing.get("prompt")),
                completion_price=_to_float(pricing.get("completion")),
            )
        )
    return out


def _to_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _cache_path() -> Path:
    return get_global_dir() / "cache" / "openrouter_models.json"


def _read_cache(max_age: int) -> list[OpenRouterModel] | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        blob = json.loads(path.read_text())
        if time.time() - float(blob.get("fetched_at", 0)) > max_age:
            return None
        return parse_models(blob.get("payload", {}))
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _write_cache(payload: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": time.time(), "payload": payload}))
    except OSError:
        pass


def cached_models() -> list[OpenRouterModel]:
    """Return cached models without any network call (any age), else empty.

    For UI that must stay responsive: read what's on disk instantly and refresh
    in the background.
    """
    return _read_cache(max_age=10**12) or []


def fetch_openrouter_models(
    *, force_refresh: bool = False, timeout: float = 10.0
) -> list[OpenRouterModel]:
    """Return the OpenRouter model list, from cache when fresh else the API.

    Network and JSON errors return the stale cache if present, else an empty
    list — this never raises, so callers can offer OpenRouter models
    opportunistically.
    """
    if not force_refresh:
        cached = _read_cache(_CACHE_TTL_SECONDS)
        if cached is not None:
            return cached

    try:
        import httpx

        resp = httpx.get(_API_URL, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        # Fall back to any cache regardless of age, else nothing.
        return _read_cache(max_age=10**12) or []

    _write_cache(payload)
    return parse_models(payload)


__all__ = ["OpenRouterModel", "cached_models", "fetch_openrouter_models", "parse_models"]
