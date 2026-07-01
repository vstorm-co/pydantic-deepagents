"""Single source of truth for CLI model-provider metadata (C14).

Onboarding, the `/provider` command, and the no-key auto-fallback in `app.py`
all need the same provider list, default models, and key URLs. Keeping one
table here stops the three copies from drifting.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    """Static metadata for a model provider offered in the CLI.

    Attributes:
        id: Short provider identifier (also the model-name prefix).
        name: Human-readable label shown in the picker.
        env_var: API-key environment variable; empty for keyless providers.
        key_url: Where to obtain a key; empty for keyless providers.
        default_model: Model selected when this provider is chosen; empty when
            there is no single sensible default.
    """

    id: str
    name: str
    env_var: str
    key_url: str
    default_model: str


PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo(
        "openrouter",
        "OpenRouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/keys",
        "openrouter:anthropic/claude-sonnet-4",
    ),
    ProviderInfo(
        "anthropic",
        "Anthropic (Claude)",
        "ANTHROPIC_API_KEY",
        "https://console.anthropic.com/",
        "anthropic:claude-sonnet-4-6",
    ),
    ProviderInfo(
        "openai",
        "OpenAI (GPT)",
        "OPENAI_API_KEY",
        "https://platform.openai.com/api-keys",
        "openai:gpt-4.1",
    ),
    ProviderInfo(
        "google",
        "Google (Gemini)",
        "GOOGLE_API_KEY",
        "https://aistudio.google.com/apikey",
        "google-gla:gemini-2.5-pro",
    ),
    ProviderInfo("ollama", "Ollama (local, free)", "", "", "ollama:llama3.3"),
)

#: Provider id → default model, derived from :data:`PROVIDERS`.
PROVIDER_DEFAULT_MODELS: dict[str, str] = {p.id: p.default_model for p in PROVIDERS}
