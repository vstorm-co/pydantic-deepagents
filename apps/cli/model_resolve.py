"""Turn a CLI model string into something pydantic-ai accepts.

Almost every model string the CLI carries is a plain pydantic-ai identifier that
`infer_model()` understands. One is not: `openai-compatible:<name>` is a
CLI-only sentinel for a local OpenAI-wire-format server (llama.cpp, LM Studio,
vLLM, …) whose endpoint URL can't fit in a model string and lives in
`config.base_url` instead. Handing that sentinel straight to pydantic-ai raises
`ValueError: Unknown provider: openai-compatible`.

So every place that turns the CLI's model string into a pydantic-ai model goes
through :func:`resolve_cli_model` — the agent factory, the reminder generator,
the goal evaluator and `/improve`. Keeping the knowledge here rather than at
each call site is the point: a new consumer that forgets the prefix is a bug
that only shows up for local-endpoint users.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from apps.cli.config import CliConfig, load_config
from apps.cli.providers import OPENAI_COMPATIBLE_API_KEY_ENV, OPENAI_COMPATIBLE_PREFIX

if TYPE_CHECKING:
    from pydantic_ai.models import Model
    from pydantic_ai.models.openai import OpenAIChatModel

#: Stand-in key for endpoints that don't check one. `OpenAIProvider` requires
#: *some* key and would otherwise fall back to `OPENAI_API_KEY` — which must
#: never be sent to an arbitrary local or self-hosted endpoint.
_NOOP_API_KEY = "sk-noop"


def resolve_openai_compatible_model(model_str: str, config: CliConfig) -> OpenAIChatModel:
    """Build an `OpenAIChatModel` for an `openai-compatible:<name>` model string.

    The name after the prefix is the model served by the endpoint; the endpoint
    URL comes from `config.base_url`. The API key comes from the keystore
    (`OPENAI_COMPATIBLE_API_KEY`), never from `config.toml`; most local servers
    ignore it, so a noop stand-in is used when none is set.

    Raises:
        ValueError: If no `base_url` is configured.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    if not config.base_url:
        raise ValueError(
            "No base_url configured for the OpenAI-compatible endpoint. "
            "Run /provider, pick OpenAI-compatible, and enter the server URL."
        )
    name = model_str[len(OPENAI_COMPATIBLE_PREFIX) :] or "local-model"
    api_key = os.environ.get(OPENAI_COMPATIBLE_API_KEY_ENV) or _NOOP_API_KEY
    provider = OpenAIProvider(base_url=config.base_url, api_key=api_key)
    return OpenAIChatModel(name, provider=provider)


def resolve_cli_model(model: str | Model, config: CliConfig | None = None) -> str | Model:
    """Return `model` unchanged, or a `Model` instance for the local-endpoint sentinel.

    Args:
        model: A CLI model string, or an already-built `Model` (which callers
            pass around once one link in the chain has resolved it) — those are
            returned untouched.
        config: Config to read `base_url` from. Loaded on demand when omitted,
            so callers that don't already hold a config don't have to build one.
    """
    if not isinstance(model, str) or not model.startswith(OPENAI_COMPATIBLE_PREFIX):
        return model
    return resolve_openai_compatible_model(model, config if config is not None else load_config())


__all__ = ["resolve_cli_model", "resolve_openai_compatible_model"]
