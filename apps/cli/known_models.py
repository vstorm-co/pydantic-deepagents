"""Provider → model catalogue sourced from pydantic-ai's own ``KnownModelName``.

Reading the installed pydantic-ai's list means the model picker never drifts
from what ``infer_model`` actually accepts, and it stays current every time
pydantic-ai is upgraded — no hand-maintained model strings.
"""

from __future__ import annotations

import os
import typing

#: pydantic-ai provider prefix → the API-key env var that enables it.
#: Env-var names are the ones each provider actually reads (verified against the
#: pydantic-ai provider modules). Ordered by rough popularity for display.
PROVIDER_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "google-cloud": "GOOGLE_CLOUD_PROJECT",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "CO_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "moonshotai": "MOONSHOTAI_API_KEY",
    "huggingface": "HF_TOKEN",
    "heroku": "HEROKU_INFERENCE_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
}

#: Human-readable section labels.
PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google (Gemini API)",
    "google-cloud": "Google (Vertex AI)",
    "xai": "xAI (Grok)",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "mistral": "Mistral",
    "cohere": "Cohere",
    "cerebras": "Cerebras",
    "moonshotai": "Moonshot (Kimi)",
    "huggingface": "Hugging Face",
    "heroku": "Heroku",
    "bedrock": "AWS Bedrock",
}

# Substrings marking non-chat models (audio/embedding/safety) we hide from the
# picker — they can't drive the agent.
_NON_CHAT = (
    "whisper",
    "tts",
    "embed",
    "guard",
    "moderation",
    "safeguard",
    "playai",
    "rerank",
    "transcribe",
    "realtime",
    "-audio",
    "-image",
    "dall-e",
    "-search-",
)


def _is_chat(model_name: str) -> bool:
    lo = model_name.lower()
    return not any(s in lo for s in _NON_CHAT)


def chat_models_by_provider() -> dict[str, list[str]]:
    """Map each known provider prefix to its chat model strings (``provider:model``).

    Skips gateway/alias prefixes and non-chat models. Never raises — returns an
    empty dict if pydantic-ai's list can't be read.
    """
    try:
        from pydantic_ai.models import KnownModelName

        kn = getattr(KnownModelName, "__value__", KnownModelName)
        names = typing.get_args(kn)
    except Exception:
        return {}

    out: dict[str, list[str]] = {}
    for full in names:
        if not isinstance(full, str) or ":" not in full:
            continue
        prefix, name = full.split(":", 1)
        if prefix not in PROVIDER_ENV or not _is_chat(name):
            continue
        out.setdefault(prefix, []).append(full)
    return out


def provider_sections() -> list[tuple[str, str, bool, list[str]]]:
    """Ordered ``(prefix, label, has_key, models)`` for every known chat provider.

    Providers whose key is set come first (in popularity order), then the rest.
    Empty providers are dropped.
    """
    catalogue = chat_models_by_provider()
    keyed: list[tuple[str, str, bool, list[str]]] = []
    unkeyed: list[tuple[str, str, bool, list[str]]] = []
    for prefix, env_var in PROVIDER_ENV.items():
        models = catalogue.get(prefix)
        if not models:
            continue
        label = PROVIDER_LABELS.get(prefix, prefix)
        has_key = bool(os.environ.get(env_var))
        (keyed if has_key else unkeyed).append((prefix, label, has_key, models))
    return keyed + unkeyed


__all__ = [
    "PROVIDER_ENV",
    "PROVIDER_LABELS",
    "chat_models_by_provider",
    "provider_sections",
]
