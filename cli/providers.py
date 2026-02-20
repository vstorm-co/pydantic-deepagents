"""Provider registry for the pydantic-deep CLI.

Maps pydantic-ai provider prefixes to their required environment variables
and pip extras. Used for validation, helpful error messages, and the
``pydantic-deep providers`` command.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata about a pydantic-ai model provider."""

    name: str
    env_vars: list[str]
    pip_extra: str | None
    description: str
    optional_env_vars: list[str] | None = None


PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        name="OpenAI",
        env_vars=["OPENAI_API_KEY"],
        pip_extra=None,
        description="GPT-4.1, GPT-4o, o1, o3, etc.",
        optional_env_vars=["OPENAI_BASE_URL"],
    ),
    "anthropic": ProviderInfo(
        name="Anthropic",
        env_vars=["ANTHROPIC_API_KEY"],
        pip_extra="anthropic",
        description="Claude Opus, Sonnet, Haiku",
    ),
    "google-gla": ProviderInfo(
        name="Google (Gemini API)",
        env_vars=["GOOGLE_API_KEY"],
        pip_extra="google",
        description="Gemini 2.0 Flash, Gemini 2.5 Pro, etc.",
        optional_env_vars=["GEMINI_API_KEY"],
    ),
    "google-vertex": ProviderInfo(
        name="Google (Vertex AI)",
        env_vars=["GOOGLE_API_KEY"],
        pip_extra="google",
        description="Gemini models via Vertex AI",
        optional_env_vars=["GEMINI_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"],
    ),
    "groq": ProviderInfo(
        name="Groq",
        env_vars=["GROQ_API_KEY"],
        pip_extra="groq",
        description="LLaMA, Mixtral on Groq hardware",
    ),
    "mistral": ProviderInfo(
        name="Mistral",
        env_vars=["MISTRAL_API_KEY"],
        pip_extra="mistral",
        description="Mistral Large, Codestral, etc.",
    ),
    "openrouter": ProviderInfo(
        name="OpenRouter",
        env_vars=["OPENROUTER_API_KEY"],
        pip_extra="openrouter",
        description="Aggregator — access 200+ models (OpenAI, Anthropic, Meta, etc.)",
    ),
    "deepseek": ProviderInfo(
        name="DeepSeek",
        env_vars=["DEEPSEEK_API_KEY"],
        pip_extra="openai",
        description="DeepSeek V3, DeepSeek R1",
    ),
    "xai": ProviderInfo(
        name="xAI (Grok)",
        env_vars=["XAI_API_KEY"],
        pip_extra="openai",
        description="Grok models",
    ),
    "cohere": ProviderInfo(
        name="Cohere",
        env_vars=["CO_API_KEY"],
        pip_extra="cohere",
        description="Command R+, Embed, etc.",
    ),
    "cerebras": ProviderInfo(
        name="Cerebras",
        env_vars=["CEREBRAS_API_KEY"],
        pip_extra="openai",
        description="Fast inference on Cerebras hardware",
    ),
    "bedrock": ProviderInfo(
        name="AWS Bedrock",
        env_vars=["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        pip_extra="bedrock",
        description="Claude, Titan, LLaMA via AWS",
        optional_env_vars=["AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION"],
    ),
    "azure": ProviderInfo(
        name="Azure OpenAI",
        env_vars=["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
        pip_extra="openai",
        description="OpenAI models via Azure",
        optional_env_vars=["OPENAI_API_VERSION"],
    ),
    "ollama": ProviderInfo(
        name="Ollama",
        env_vars=[],
        pip_extra="openai",
        description="Local models (LLaMA, Mistral, Phi, etc.)",
        optional_env_vars=["OLLAMA_BASE_URL"],
    ),
    "together": ProviderInfo(
        name="Together AI",
        env_vars=["TOGETHER_API_KEY"],
        pip_extra="openai",
        description="Open-source models hosted by Together",
    ),
    "fireworks": ProviderInfo(
        name="Fireworks AI",
        env_vars=["FIREWORKS_API_KEY"],
        pip_extra="openai",
        description="Fast inference for open-source models",
    ),
    "huggingface": ProviderInfo(
        name="Hugging Face",
        env_vars=["HF_TOKEN"],
        pip_extra="huggingface",
        description="HF Inference API models",
    ),
    "sambanova": ProviderInfo(
        name="SambaNova",
        env_vars=["SAMBANOVA_API_KEY"],
        pip_extra="openai",
        description="SambaNova Cloud AI",
    ),
    "github": ProviderInfo(
        name="GitHub Models",
        env_vars=["GITHUB_API_KEY"],
        pip_extra="openai",
        description="Models via GitHub Marketplace",
    ),
    "litellm": ProviderInfo(
        name="LiteLLM",
        env_vars=[],
        pip_extra="litellm",
        description="Universal proxy — route to 100+ providers",
    ),
}


def parse_model_string(model: str) -> tuple[str, str]:
    """Parse a pydantic-ai model string into (provider, model_name).

    Examples::

        >>> parse_model_string("openai:gpt-4.1")
        ('openai', 'gpt-4.1')
        >>> parse_model_string("openrouter:openai/gpt-5.2-codex")
        ('openrouter', 'openai/gpt-5.2-codex')
        >>> parse_model_string("gpt-4.1")
        ('openai', 'gpt-4.1')
    """
    if ":" in model:
        provider, model_name = model.split(":", 1)
        return provider, model_name
    return "openai", model


def get_provider(name: str) -> ProviderInfo | None:
    """Look up a provider by its prefix name."""
    return PROVIDERS.get(name)


def validate_provider_env(provider: str) -> list[str]:
    """Check if required env vars for a provider are set.

    Returns a list of missing env var names (empty = all good).
    """
    info = PROVIDERS.get(provider)
    if info is None:
        return []
    return [var for var in info.env_vars if not os.environ.get(var)]


def check_provider_extra(provider: str) -> str | None:
    """Return the pip install command if the provider extra is not available.

    Returns None if the provider is already importable.
    """
    info = PROVIDERS.get(provider)
    if info is None or info.pip_extra is None:
        return None

    try:
        __import__(f"pydantic_ai.providers.{provider}")
        return None
    except ImportError:
        return f'pip install "pydantic-ai-slim[{info.pip_extra}]"'


def format_provider_error(model: str) -> str | None:
    """Produce a helpful error message for provider issues.

    Returns None if no issues detected.
    """
    provider, _ = parse_model_string(model)
    info = PROVIDERS.get(provider)

    if info is None:
        known = ", ".join(sorted(PROVIDERS.keys()))
        return (
            f"Unknown provider '{provider}'. "
            f"Known providers: {known}\n"
            f"See: pydantic-deep providers list"
        )

    missing_vars = validate_provider_env(provider)
    if missing_vars:
        vars_str = ", ".join(missing_vars)
        hint = f"export {missing_vars[0]}=your-key-here" if len(missing_vars) == 1 else ""
        return (f"Missing environment variable(s) for {info.name}: {vars_str}\n{hint}").strip()

    install_cmd = check_provider_extra(provider)
    if install_cmd:
        return f"{info.name} provider not installed. Run:\n  {install_cmd}"

    return None


__all__ = [
    "PROVIDERS",
    "ProviderInfo",
    "check_provider_extra",
    "format_provider_error",
    "get_provider",
    "parse_model_string",
    "validate_provider_env",
]
