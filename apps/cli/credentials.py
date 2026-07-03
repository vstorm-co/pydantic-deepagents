"""Registry of every credential the CLI can set.

Single source of truth for credential metadata — the `keys` CLI command,
onboarding, and the provider picker all read from here so the list never drifts.
Covers model-provider API keys plus the other credentials the agent understands
(Vertex config, observability, cloud SDKs).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Credential:
    """Metadata for one settable credential.

    Attributes:
        env_var: Environment variable name (the storage key).
        label: Human-readable name shown in pickers and `keys list`.
        category: Grouping for display (e.g. "Model providers", "Vertex AI").
        url: Where to obtain it, if applicable.
        secret: Whether the value is sensitive and should be masked in output.
        provider_id: The `providers.py` id when this key selects a model
            provider, else "".
    """

    env_var: str
    label: str
    category: str
    url: str = ""
    secret: bool = True
    provider_id: str = ""


# Ordered so the most common model providers come first.
CREDENTIALS: tuple[Credential, ...] = (
    # ── Model providers ────────────────────────────────────────────────
    Credential(
        "OPENROUTER_API_KEY",
        "OpenRouter",
        "Model providers",
        "https://openrouter.ai/keys",
        provider_id="openrouter",
    ),
    Credential(
        "ANTHROPIC_API_KEY",
        "Anthropic (Claude)",
        "Model providers",
        "https://console.anthropic.com/settings/keys",
        provider_id="anthropic",
    ),
    Credential(
        "OPENAI_API_KEY",
        "OpenAI (GPT)",
        "Model providers",
        "https://platform.openai.com/api-keys",
        provider_id="openai",
    ),
    Credential(
        "GEMINI_API_KEY",
        "Google Gemini (AI Studio)",
        "Model providers",
        "https://aistudio.google.com/apikey",
        provider_id="google",
    ),
    Credential(
        "GOOGLE_API_KEY",
        "Google (legacy key)",
        "Model providers",
        "https://aistudio.google.com/apikey",
        provider_id="google",
    ),
    Credential(
        "GROQ_API_KEY",
        "Groq",
        "Model providers",
        "https://console.groq.com/keys",
        provider_id="groq",
    ),
    Credential(
        "MISTRAL_API_KEY",
        "Mistral",
        "Model providers",
        "https://console.mistral.ai/api-keys",
        provider_id="mistral",
    ),
    Credential(
        "DEEPSEEK_API_KEY",
        "DeepSeek",
        "Model providers",
        "https://platform.deepseek.com/api_keys",
        provider_id="deepseek",
    ),
    Credential(
        "XAI_API_KEY", "xAI (Grok)", "Model providers", "https://console.x.ai/", provider_id="xai"
    ),
    Credential(
        "CO_API_KEY",
        "Cohere",
        "Model providers",
        "https://dashboard.cohere.com/api-keys",
        provider_id="cohere",
    ),
    Credential(
        "CEREBRAS_API_KEY",
        "Cerebras",
        "Model providers",
        "https://cloud.cerebras.ai/",
        provider_id="cerebras",
    ),
    Credential(
        "TOGETHER_API_KEY",
        "Together AI",
        "Model providers",
        "https://api.together.ai/settings/api-keys",
        provider_id="together",
    ),
    Credential(
        "FIREWORKS_API_KEY",
        "Fireworks AI",
        "Model providers",
        "https://fireworks.ai/account/api-keys",
        provider_id="fireworks",
    ),
    Credential(
        "HF_TOKEN",
        "Hugging Face",
        "Model providers",
        "https://huggingface.co/settings/tokens",
        provider_id="huggingface",
    ),
    Credential(
        "MOONSHOTAI_API_KEY",
        "Moonshot (Kimi)",
        "Model providers",
        "https://platform.moonshot.ai/console/api-keys",
        provider_id="moonshotai",
    ),
    Credential(
        "HEROKU_INFERENCE_KEY",
        "Heroku Inference",
        "Model providers",
        "https://www.heroku.com/",
        provider_id="heroku",
    ),
    # ── Vertex AI (Gemini via Google Cloud) ────────────────────────────
    Credential(
        "GOOGLE_GENAI_USE_VERTEXAI", "Use Vertex AI (true/false)", "Vertex AI", secret=False
    ),
    Credential("GOOGLE_CLOUD_PROJECT", "GCP project id", "Vertex AI", secret=False),
    Credential("GOOGLE_CLOUD_LOCATION", "GCP location (e.g. global)", "Vertex AI", secret=False),
    Credential(
        "GOOGLE_APPLICATION_CREDENTIALS", "Path to service-account JSON", "Vertex AI", secret=False
    ),
    # ── Observability ──────────────────────────────────────────────────
    Credential(
        "LOGFIRE_TOKEN", "Pydantic Logfire", "Observability", "https://logfire.pydantic.dev/"
    ),
    # ── AWS Bedrock ────────────────────────────────────────────────────
    Credential("AWS_ACCESS_KEY_ID", "AWS access key id", "AWS Bedrock"),
    Credential("AWS_SECRET_ACCESS_KEY", "AWS secret access key", "AWS Bedrock"),
    Credential("AWS_DEFAULT_REGION", "AWS region", "AWS Bedrock", secret=False),
    # ── Azure OpenAI ───────────────────────────────────────────────────
    Credential("AZURE_OPENAI_API_KEY", "Azure OpenAI key", "Azure OpenAI"),
    Credential("AZURE_OPENAI_ENDPOINT", "Azure OpenAI endpoint", "Azure OpenAI", secret=False),
    Credential("OPENAI_API_VERSION", "Azure OpenAI API version", "Azure OpenAI", secret=False),
)

#: env_var → Credential, for fast lookup.
_BY_ENV: dict[str, Credential] = {c.env_var: c for c in CREDENTIALS}


def find_credential(env_var: str) -> Credential | None:
    """Return the registry entry for an env var, or None if unknown."""
    return _BY_ENV.get(env_var)


def credentials_by_category() -> dict[str, list[Credential]]:
    """Group credentials by category, preserving registry order within each."""
    grouped: dict[str, list[Credential]] = {}
    for cred in CREDENTIALS:
        grouped.setdefault(cred.category, []).append(cred)
    return grouped


def mask(value: str) -> str:
    """Mask a secret value for display (keeps a short prefix/suffix)."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"


__all__ = [
    "CREDENTIALS",
    "Credential",
    "credentials_by_category",
    "find_credential",
    "mask",
]
