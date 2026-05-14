"""Periodic reminder capability for long-running agents.

Injects a "what are you supposed to be doing" nudge every N model-request
turns to keep the agent anchored to its original task.

Three generator shapes are supported:

- **Static string** — a fixed reminder message used verbatim.
- **Async callable** — receives ``(ctx, turn, messages)`` and returns a str.
- **LLMReminderGenerator** — uses a small model to summarize progress.

Example:
    ```python
    from pydantic_deep import create_deep_agent
    from pydantic_deep.capabilities.periodic_reminder import (
        PeriodicReminderCapability,
        PeriodicReminderConfig
    )

    agent = create_deep_agent(periodic_reminder=True)
    ```
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

# Prefixes used by _render() to wrap injected reminders.  Used to filter
# synthetic entries out of compact transcripts so they don't pollute future
# reminder generation.
_REMINDER_PREFIXES = ("<system-reminder>", "[Developer note for the assistant:")


@runtime_checkable
class ReminderGenerator(Protocol):
    """Protocol for reminder generator callables and classes.

    Implement this to provide custom reminder text based on conversation
    state.  Both plain ``async def`` functions and classes with
    ``async def __call__`` satisfy this protocol.
    """

    async def __call__(
        self,
        ctx: RunContext[Any],
        turn: int,
        messages: list[ModelMessage],
    ) -> str:
        """Generate a reminder string.

        Args:
            ctx: Current run context.
            turn: Current model-request turn counter.
            messages: Full conversation history at the moment of injection.

        Returns:
            Reminder text (will be rendered according to ``render_style``).
        """
        ...


@dataclass
class PeriodicReminderConfig:
    """Configuration for :class:`PeriodicReminderCapability`.

    Args:
        every_n_turns: Fire a reminder every N turns after the first one (default 10).
        first_after: Turn on which to fire the *first* reminder (default: 5).
            Pass ``None`` to use ``every_n_turns``.
        max_reminders_per_run: Cap on total reminders per run. None means unlimited.
        render_style: How to wrap the reminder before injecting it.
            ``"system_reminder_tag"`` wraps in ``<system-reminder>`` tags,
            ``"developer_note"`` prefixes with a bracketed note,
            ``"user_prompt"`` injects plain text.
        generator: What to use for the reminder text.
            ``None`` → zero-cost default (extracts first user message).
            ``str`` → static message used verbatim.
            :class:`ReminderGenerator` → async callable / class.
    """

    every_n_turns: int = 10
    first_after: int | None = 5
    max_reminders_per_run: int | None = None
    render_style: Literal["system_reminder_tag", "user_prompt", "developer_note"] = (
        "system_reminder_tag"
    )
    generator: str | ReminderGenerator | None = None
    on_reminder: Callable[[int, str], None] | None = field(default=None, repr=False)


@dataclass
class LLMReminderGenerator:
    """Reminder generator that asks a small LLM to summarize agent progress.

    Builds a compacted transcript (original user goal + last N messages)
    and asks a cheap model to produce a single-sentence stay-on-task nudge.

    Args:
        model: pydantic-ai model string (default: claude-haiku).
        max_context_messages: Number of recent messages included in the
            compact transcript to save tokens.
    """

    model: str = "anthropic:claude-haiku-4-5-20251001"
    max_context_messages: int = 10

    _agent: Agent[None, str] | None = field(default=None, init=False, repr=False)

    async def __call__(
        self,
        ctx: RunContext[Any],
        turn: int,
        messages: list[ModelMessage],
    ) -> str:
        try:
            if self._agent is None:
                self._agent = Agent(
                    model=self.model,
                    system_prompt=(
                        "You are a concise assistant. Output only the reminder text, no preamble."
                    ),
                )
            compact = build_compact_transcript(messages, self.max_context_messages)
            prompt = (
                f"Agent conversation so far (compacted):\n\n{compact}\n\n"
                f"Current turn: {turn}\n\n"
                "Summarise in 2 sentences what the agent was originally asked to do "
                "and what remains. Output the reminder text only."
            )
            result = await self._agent.run(prompt)
            return result.output
        except Exception:
            return _default_generate(messages)


def build_compact_transcript(messages: list[ModelMessage], max_recent: int) -> str:
    """Build a compact string summary of the conversation for LLM context.

    Synthetic reminder messages previously injected by this capability are
    filtered out so they don't pollute future reminder generation.
    """
    lines: list[str] = []

    first_user: str | None = None
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if (
                    isinstance(part, UserPromptPart)
                    and isinstance(part.content, str)
                    and not part.content.startswith(_REMINDER_PREFIXES)
                ):
                    first_user = part.content[:400]
                    break
        if first_user is not None:
            break

    if first_user:
        lines.append(f"[Original goal] {first_user}")

    recent = messages[-max_recent:] if len(messages) > max_recent else messages
    for msg in recent:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if (
                    isinstance(part, UserPromptPart)
                    and isinstance(part.content, str)
                    and not part.content.startswith(_REMINDER_PREFIXES)
                ):
                    lines.append(f"[User] {part.content[:150]}")
        else:
            lines.append("[Assistant/Tool turn]")

    return "\n".join(lines) if lines else "(no messages yet)"


def _default_generate(messages: list[ModelMessage]) -> str:
    """Zero-cost default: extract the first user message as the goal."""
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if (
                    isinstance(part, UserPromptPart)
                    and isinstance(part.content, str)
                    and not part.content.startswith(_REMINDER_PREFIXES)
                ):
                    truncated_task = part.content[:400]
                    return (
                        f"The original request was:\n"
                        f'  "{truncated_task}"\n'
                        "Check that your next action advances this goal. If the goal is "
                        "already satisfied, produce the final answer instead of calling more tools."
                    )
    return "Stay on task. Focus on completing your original objective."


def _render(style: str, text: str) -> str:
    """Wrap reminder text according to the configured render style."""
    if style == "system_reminder_tag":
        return f"<system-reminder>\n{text}\n</system-reminder>"
    if style == "developer_note":
        return f"[Developer note for the assistant: {text}]"
    return text


def _should_fire(turn: int, reminder_count: int, cfg: PeriodicReminderConfig) -> bool:
    """Return True when a reminder should fire on this turn."""
    if cfg.max_reminders_per_run is not None and reminder_count >= cfg.max_reminders_per_run:
        return False
    first = cfg.first_after if cfg.first_after is not None else cfg.every_n_turns
    return turn == first or (turn > first and (turn - first) % cfg.every_n_turns == 0)


@dataclass
class PeriodicReminderCapability(AbstractCapability[Any]):
    """Capability that periodically reminds the agent of its original task.

    Uses ``before_model_request`` to increment a turn counter and inject a
    reminder ``ModelRequest`` into the message history every N turns.
    Per-run state isolation via ``for_run()`` ensures concurrent runs don't
    share turn counters.

    Args:
        config: :class:`PeriodicReminderConfig` controlling firing cadence,
            render style, and generator.  Pass
            ``PeriodicReminderConfig()`` for sensible defaults.
    """

    config: PeriodicReminderConfig = field(default_factory=PeriodicReminderConfig)

    _turn_counter: int = field(default=0, init=False, repr=False)
    _reminder_count: int = field(default=0, init=False, repr=False)

    async def for_run(self, ctx: RunContext[Any]) -> PeriodicReminderCapability:
        """Return a fresh instance with isolated per-run counters."""
        return replace(self)

    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: Any,
    ) -> Any:
        """Increment turn counter and inject a reminder when it fires."""
        self._turn_counter += 1
        messages: list[ModelMessage] = request_context.messages

        if not _should_fire(self._turn_counter, self._reminder_count, self.config):
            return request_context

        gen = self.config.generator
        if gen is None:
            text = _default_generate(messages)
        elif isinstance(gen, str):
            text = gen
        else:
            text = await gen(ctx, self._turn_counter, messages)

        rendered = _render(self.config.render_style, text)
        request_context.messages = list(messages) + [
            ModelRequest(parts=[UserPromptPart(content=rendered)])
        ]
        self._reminder_count += 1
        if self.config.on_reminder is not None:
            self.config.on_reminder(self._turn_counter, rendered)
        return request_context


def make_config_for_mode(mode: str) -> PeriodicReminderConfig:
    """Build a :class:`PeriodicReminderConfig` for a named reminder mode.

    Convenience factory that maps a string mode name to a fully-configured
    :class:`PeriodicReminderConfig` with sensible per-mode defaults.

    Args:
        mode: ``"llm"`` (default — uses :class:`LLMReminderGenerator`),
              ``"first"`` (zero-cost, re-states first user message),
              ``"context"`` (zero-cost compact transcript), or any other
              string (falls back to LLM generation).

    Returns:
        A ready-to-use :class:`PeriodicReminderConfig`.
    """
    generator: str | ReminderGenerator | None
    if mode == "context":

        async def _ctx_gen(_ctx: Any, _turn: int, messages: list[ModelMessage]) -> str:
            return build_compact_transcript(messages, max_recent=10)

        generator = _ctx_gen  # type: ignore[assignment]
    elif mode == "llm":
        generator = LLMReminderGenerator()
    elif mode == "first":
        generator = None
    else:
        generator = LLMReminderGenerator()

    return PeriodicReminderConfig(
        generator=generator,
        every_n_turns=15 if mode == "llm" else 10,
        max_reminders_per_run=3 if mode == "llm" else None,
    )


__all__ = [
    "LLMReminderGenerator",
    "PeriodicReminderCapability",
    "PeriodicReminderConfig",
    "ReminderGenerator",
    "build_compact_transcript",
    "make_config_for_mode",
]
