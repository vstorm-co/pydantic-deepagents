"""Model catalogue helpers for the gateway.

A curated, provider-grouped catalogue surfaced in the model picker. Users can
always type any pydantic-ai model string ("provider:name") via the Custom tab.
"""

from __future__ import annotations

from typing import Any

# (provider id, display label, [model strings]). Provider id matches the
# pydantic-ai provider prefix so the picker can group by it.
_CATALOGUE: list[tuple[str, str, list[str]]] = [
    (
        "anthropic",
        "Anthropic",
        [
            "anthropic:claude-opus-4-8",
            "anthropic:claude-opus-4-6",
            "anthropic:claude-sonnet-4-6",
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-3-5-haiku-latest",
        ],
    ),
    (
        "openai",
        "OpenAI",
        [
            "openai:gpt-4.1",
            "openai:gpt-4.1-mini",
            "openai:gpt-4o",
            "openai:gpt-4o-mini",
            "openai:o3",
            "openai:o3-mini",
            "openai:o1",
        ],
    ),
    (
        "google-gla",
        "Google",
        [
            "google-gla:gemini-2.5-pro",
            "google-gla:gemini-2.5-flash",
            "google-gla:gemini-2.0-flash",
        ],
    ),
    (
        "openrouter",
        "OpenRouter",
        [
            "openrouter:anthropic/claude-opus-4.8",
            "openrouter:anthropic/claude-sonnet-4.5",
            "openrouter:google/gemini-2.5-pro",
            "openrouter:openai/gpt-oss-120b:free",
            "openrouter:openai/gpt-oss-20b:free",
            "openrouter:google/gemma-4-31b:free",
            "openrouter:google/gemma-4-26b-a4b:free",
            "openrouter:nvidia/nemotron-3-ultra:free",
            "openrouter:deepseek/deepseek-chat",
            "openrouter:x-ai/grok-4",
            "openrouter:meta-llama/llama-4-maverick",
            "openrouter:qwen/qwen3-max",
        ],
    ),
    (
        "ollama",
        "Ollama (local)",
        [
            "ollama:llama3.3",
            "ollama:qwen2.5",
            "ollama:gemma3",
        ],
    ),
]


def _config_models() -> list[str]:
    try:
        from apps.cli.config import load_config

        cfg = load_config()
        return [m for m in (cfg.model, cfg.fallback_model) if m]
    except Exception:
        return []


def model_catalogue() -> list[dict[str, Any]]:
    """Provider-grouped catalogue, with any configured models pinned at the top."""
    groups: list[dict[str, Any]] = []
    known = {m for _, _, models in _CATALOGUE for m in models}

    configured = [m for m in _config_models() if m not in known]
    if configured:
        groups.append({"id": "recent", "label": "Configured", "models": configured})

    for provider_id, label, models in _CATALOGUE:
        groups.append({"id": provider_id, "label": label, "models": models})
    return groups


def common_models() -> list[str]:
    """Flat list of all catalogue models (configured pinned first)."""
    out: list[str] = list(_config_models())
    for _, _, models in _CATALOGUE:
        out.extend(models)
    return list(dict.fromkeys(out))  # dedupe, preserve order


def default_model() -> str:
    """The configured model, or the first catalogue entry as a fallback."""
    configured = _config_models()
    return configured[0] if configured else _CATALOGUE[0][2][0]


__all__ = ["common_models", "default_model", "model_catalogue"]
