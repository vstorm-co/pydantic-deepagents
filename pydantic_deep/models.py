"""Single source of truth for the default LLM models used across pydantic-deep.

Every default model the library reaches for is named here, so bumping a model
is a one-file change. Each constant is keyed by *role* - where the model is
used by `create_deep_agent` and the surrounding capabilities and toolsets.

This module deliberately imports nothing from `pydantic_deep`, so it is safe
to import from anywhere without risking an import cycle.
"""

from __future__ import annotations

from typing import Final

# Role-based defaults --------------------------------------------------------

DEFAULT_MODEL: Final = "anthropic:claude-opus-4-6"
"""Primary model for the top-level deep agent."""

DEFAULT_SUBAGENT_MODEL: Final = "anthropic:claude-sonnet-4-6"
"""Model for delegated subagents."""

DEFAULT_SUMMARIZATION_MODEL: Final = "anthropic:claude-haiku-4-5-20251001"
"""Model for conversation summarization / compression."""

DEFAULT_GOAL_MODEL: Final = "anthropic:claude-haiku-4-5-20251001"
"""Model for the goal-completion evaluator loop."""

DEFAULT_JUDGE_MODEL: Final = "anthropic:claude-haiku-4-5-20251001"
"""Model for the fork-merge autonomous judge."""

DEFAULT_TEAM_MEMBER_MODEL: Final = "anthropic:claude-sonnet-4-6"
"""Default model for spawned agent-team members."""

DEFAULT_REMINDER_MODEL: Final = "anthropic:claude-haiku-4-5-20251001"
"""Model for the LLM-backed periodic reminder generator."""

DEFAULT_IMPROVE_MODEL: Final = "openrouter:anthropic/claude-sonnet-4"
"""Model for the self-improvement session analyzer."""


# Fork vote-panel detection --------------------------------------------------

#: (env var, cheap model) checked in order; the first present key wins a slot.
NATIVE_CHEAP_MODELS: Final[tuple[tuple[str, str], ...]] = (
    ("ANTHROPIC_API_KEY", "anthropic:claude-haiku-4-5"),
    ("OPENAI_API_KEY", "openai:gpt-4o-mini"),
    ("MISTRAL_API_KEY", "mistral:mistral-small-latest"),
    ("GROQ_API_KEY", "groq:llama-3.1-8b-instant"),
    ("COHERE_API_KEY", "cohere:command-r"),
)

#: Google uses several env var names depending on the SDK version.
GOOGLE_ENV_VARS: Final[tuple[str, ...]] = (
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
)
GOOGLE_CHEAP_MODEL: Final = "google-gla:gemini-3.1-flash-lite-preview"

#: OpenRouter: one key, three cheap model-family representatives.
OPENROUTER_CHEAP_MODELS: Final[tuple[str, ...]] = (
    "openrouter:anthropic/claude-haiku-4-5",
    "openrouter:openai/gpt-5.4",
    "openrouter:google/gemini-3.1-flash-lite-preview",
)
