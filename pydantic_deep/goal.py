"""Goal-completion loop engine.

A *goal* is a completion condition the agent keeps working toward across turns
without the user prompting each step. After every turn a small, fast model
(:class:`GoalEvaluator`) judges — from the conversation transcript alone —
whether the condition is satisfied. If not, the host (CLI / headless loop)
starts another turn, passing the evaluator's reason back as guidance. When the
condition is met the goal is marked achieved and the loop stops.

This module is the provider/UI-agnostic engine. It mirrors Claude Code's
``/goal`` command but keeps all state in a plain :class:`GoalState` and exposes
pure helpers (:func:`parse_goal_command`, :func:`parse_verdict`,
:func:`build_goal_transcript`, :func:`format_goal_status`,
:func:`goal_continue_directive`) so a CLI or headless driver can wire the
behaviour without dragging in any UI.

Example:
    ```python
    from pydantic_deep.goal import GoalEvaluator, GoalState, goal_continue_directive

    goal = GoalState(condition="all tests in tests/auth pass")
    evaluator = GoalEvaluator()

    # ... after each agent turn ...
    result = await evaluator.evaluate(goal.condition, message_history)
    goal.turns += 1
    goal.last_reason = result.reason
    if result.met:
        goal.achieved = True
    else:
        directive = goal_continue_directive(goal.condition, result.reason)
        # run another turn with `directive`
    ```
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Literal

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model

logger = logging.getLogger(__name__)

# Default small/fast evaluator model. Matches the periodic-reminder default so
# both auxiliary features bill against the same cheap tier.
DEFAULT_GOAL_MODEL = "anthropic:claude-haiku-4-5-20251001"

# Maximum length of a goal condition, mirroring Claude Code's 4,000-char cap.
MAX_GOAL_CONDITION_CHARS = 4000

# Words accepted as the argument to clear an active goal early.
GOAL_CLEAR_ALIASES = frozenset({"clear", "stop", "off", "reset", "none", "cancel"})

# Verdict-word prefixes the evaluator may use. Order is irrelevant; ``_MET`` is
# checked before ``_NOT_MET`` and "incomplete" deliberately does not start with
# "complete", so it falls through to the not-met set.
_MET_PREFIXES = ("yes", "met", "done", "true", "complete", "achieved", "satisfied")
_NOT_MET_PREFIXES = ("no", "not", "false", "incomplete", "unmet", "fail")

_VERDICT_RE = re.compile(
    r"^\s*(yes|no|not\s+met|not|met|done|true|false|complete|incomplete|"
    r"achieved|satisfied|unmet|fail(?:ed)?)\b[\s:,.\-–—]*",
    re.IGNORECASE,
)

GOAL_EVALUATOR_SYSTEM_PROMPT = (
    "You are a strict goal-completion evaluator. You judge ONLY from the "
    "conversation transcript provided — you cannot run commands or read files. "
    "Decide whether the stated goal condition is fully satisfied by evidence "
    "that is already present in the transcript. If the evidence is missing, "
    "partial, or unverified, the goal is NOT met. "
    "Respond with a single line that starts with YES or NO, followed by a brief "
    "one-sentence reason. Example: 'NO - the tests have not been run yet.'"
)

GOAL_EVALUATOR_PROMPT = (
    "Goal condition:\n{condition}\n\n"
    "Conversation transcript (most recent last):\n{transcript}\n\n"
    "Is the goal condition fully satisfied by evidence in the transcript? "
    "Answer YES or NO with a one-sentence reason."
)


@dataclass(frozen=True)
class GoalEvaluation:
    """Result of a single goal evaluation.

    Args:
        met: Whether the evaluator judged the condition satisfied.
        reason: One-sentence explanation, surfaced to the user and fed back to
            the agent as guidance for the next turn when ``met`` is ``False``.
        input_tokens: Prompt tokens spent by the evaluator (0 if unknown).
        output_tokens: Completion tokens spent by the evaluator (0 if unknown).
    """

    met: bool
    reason: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class GoalState:
    """Mutable, session-scoped state for one active goal.

    The host owns the wall-clock timer (``started_monotonic``) and increments
    ``turns`` / token counters as it drives the loop. ``max_turns`` is a hard
    safety cap so a poorly-specified condition can never loop forever.

    Args:
        condition: The completion condition the agent works toward.
        turns: Number of evaluation turns spent so far.
        achieved: Set once the evaluator confirms the condition is met.
        last_reason: The evaluator's most recent reason.
        max_turns: Hard cap on evaluation turns before the loop stops itself.
        started_monotonic: ``time.monotonic()`` baseline set by the host.
        input_tokens: Cumulative evaluator prompt tokens.
        output_tokens: Cumulative evaluator completion tokens.
    """

    condition: str
    turns: int = 0
    achieved: bool = False
    last_reason: str = ""
    max_turns: int = 100
    started_monotonic: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def is_active(self) -> bool:
        """Whether the goal is still being worked toward."""
        return not self.achieved

    def record(self, evaluation: GoalEvaluation) -> None:
        """Fold one evaluation into the running state."""
        self.turns += 1
        self.last_reason = evaluation.reason
        self.input_tokens += evaluation.input_tokens
        self.output_tokens += evaluation.output_tokens
        if evaluation.met:
            self.achieved = True

    @property
    def exhausted(self) -> bool:
        """Whether the turn cap has been reached without achieving the goal."""
        return not self.achieved and self.turns >= self.max_turns


def parse_goal_command(arg: str) -> tuple[Literal["status", "clear", "set"], str]:
    """Interpret the argument to a ``/goal`` command.

    Returns a ``(action, condition)`` pair:

    - empty argument → ``("status", "")``
    - a clear alias (see :data:`GOAL_CLEAR_ALIASES`) → ``("clear", "")``
    - anything else → ``("set", <condition truncated to the char cap>)``
    """
    stripped = arg.strip()
    if not stripped:
        return ("status", "")
    if stripped.lower() in GOAL_CLEAR_ALIASES:
        return ("clear", "")
    return ("set", stripped[:MAX_GOAL_CONDITION_CHARS])


def _extract_reason(head: str, rest: str) -> str:
    """Strip the leading verdict word from ``head`` and fall back to ``rest``."""
    match = _VERDICT_RE.match(head)
    remainder = head[match.end() :].strip() if match else head.strip()
    if not remainder:
        remainder = rest.strip()
    return remainder


def parse_verdict(text: str) -> GoalEvaluation:
    """Parse a free-text evaluator reply into a :class:`GoalEvaluation`.

    The evaluator is asked to start its reply with ``YES`` or ``NO`` followed by
    a one-sentence reason. Parsing is lenient: only the first non-empty line's
    leading word decides the verdict, and an ambiguous reply is treated as
    *not met* so the loop keeps working rather than declaring premature success.
    """
    raw = text.strip()
    if not raw:
        return GoalEvaluation(met=False, reason="Evaluator returned no output.")

    first, _, rest = raw.partition("\n")
    head = first.strip()
    lowered = head.lower()

    reason = _extract_reason(head, rest)

    if lowered.startswith(_MET_PREFIXES):
        return GoalEvaluation(met=True, reason=reason or "Condition met.")
    if lowered.startswith(_NOT_MET_PREFIXES):
        return GoalEvaluation(met=False, reason=reason or "Condition not yet met.")
    # Ambiguous: keep working, surfacing the raw reply as the reason.
    return GoalEvaluation(met=False, reason=raw[:200])


def _first_user_text(messages: list[ModelMessage]) -> str | None:
    """Return the first string user prompt — the original task — or ``None``."""
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    return None


def _trunc(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` chars with an ellipsis marker."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + " …[truncated]"


def build_goal_transcript(
    messages: list[ModelMessage],
    max_recent: int = 12,
    max_chars: int = 600,
) -> str:
    """Render a compact transcript for the evaluator to judge against.

    Unlike the periodic-reminder transcript, this keeps the *content* the
    evaluator needs — assistant text and tool results (truncated) — because the
    verdict depends on evidence the agent surfaced (test output, build status,
    file state). The original request is always included as anchoring context.

    Args:
        messages: Full conversation history.
        max_recent: How many of the most recent messages to render in detail.
        max_chars: Per-part truncation budget.
    """
    lines: list[str] = []

    first = _first_user_text(messages)
    if first:
        lines.append(f"[Original request] {_trunc(first, max_chars)}")

    recent = messages[-max_recent:] if len(messages) > max_recent else messages
    for msg in recent:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    lines.append(f"[User] {_trunc(part.content, max_chars)}")
                elif isinstance(part, ToolReturnPart):
                    lines.append(
                        f"[Tool result: {part.tool_name}] {_trunc(str(part.content), max_chars)}"
                    )
        else:  # ModelResponse — the only other ModelMessage variant
            for rpart in msg.parts:
                if isinstance(rpart, TextPart) and rpart.content.strip():
                    lines.append(f"[Assistant] {_trunc(rpart.content, max_chars)}")
                elif isinstance(rpart, ToolCallPart):
                    lines.append(f"[Tool call: {rpart.tool_name}]")

    return "\n".join(lines) if lines else "(no conversation yet)"


def goal_continue_directive(condition: str, reason: str) -> str:
    """Build the synthetic prompt that drives the next goal turn."""
    return (
        "You are working toward a goal that is not yet satisfied.\n"
        f"Goal: {condition}\n"
        f"Evaluator feedback: {reason}\n\n"
        "Continue working to satisfy the goal. Surface concrete evidence "
        "(command output, test results, file state) in your reply so completion "
        "can be verified. If the goal is in fact already satisfied, say so "
        "explicitly and show the evidence."
    )


def _format_duration(seconds: float) -> str:
    """Render an elapsed duration as a compact ``1h2m`` / ``3m4s`` / ``5s``."""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes}m"
    if minutes:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


def format_goal_status(state: GoalState, elapsed_seconds: float | None = None) -> str:
    """Render a human-readable status block for ``/goal`` with no argument."""
    status = "achieved" if state.achieved else "active"
    lines = [f"Goal ({status}): {state.condition}"]
    if elapsed_seconds is not None:
        lines.append(f"Running for {_format_duration(elapsed_seconds)}")
    lines.append(f"Turns evaluated: {state.turns}")
    tokens = state.input_tokens + state.output_tokens
    if tokens:
        lines.append(f"Evaluator tokens: {tokens}")
    if state.last_reason:
        lines.append(f"Latest: {state.last_reason}")
    return "\n".join(lines)


@dataclass
class GoalEvaluator:
    """Judges whether a goal condition is met using a small, fast model.

    The evaluator does not call tools; it reasons only over the transcript built
    by :func:`build_goal_transcript`, matching Claude Code's behaviour where the
    condition must be demonstrable from what the agent has already surfaced.

    Args:
        model: pydantic-ai model string or :class:`~pydantic_ai.models.Model`
            instance (default: a small Haiku model).
        max_context_messages: Recent-message budget for the transcript.
        max_chars_per_part: Per-part truncation budget for the transcript.
    """

    model: Model | str = DEFAULT_GOAL_MODEL
    max_context_messages: int = 12
    max_chars_per_part: int = 600

    _agent: Agent[None, str] | None = field(default=None, init=False, repr=False)

    def _get_agent(self) -> Agent[None, str]:
        if self._agent is None:
            self._agent = Agent(
                model=self.model,
                system_prompt=GOAL_EVALUATOR_SYSTEM_PROMPT,
            )
        return self._agent

    async def evaluate(
        self,
        condition: str,
        messages: list[ModelMessage],
    ) -> GoalEvaluation:
        """Evaluate ``condition`` against the conversation ``messages``.

        On any failure the evaluation defaults to *not met* (with an error
        reason) so a transient evaluator hiccup keeps the agent working rather
        than declaring premature success.
        """
        transcript = build_goal_transcript(
            messages, self.max_context_messages, self.max_chars_per_part
        )
        prompt = GOAL_EVALUATOR_PROMPT.format(condition=condition, transcript=transcript)
        try:
            result = await self._get_agent().run(prompt)
        except Exception:
            logger.warning(
                "Goal evaluator failed via model %r; treating as not-met.",
                self.model,
                exc_info=True,
            )
            return GoalEvaluation(met=False, reason="Evaluator error; continuing.")

        verdict = parse_verdict(result.output)
        usage = result.usage
        return replace(
            verdict,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
        )


__all__ = [
    "DEFAULT_GOAL_MODEL",
    "GOAL_CLEAR_ALIASES",
    "GOAL_EVALUATOR_PROMPT",
    "GOAL_EVALUATOR_SYSTEM_PROMPT",
    "MAX_GOAL_CONDITION_CHARS",
    "GoalEvaluation",
    "GoalEvaluator",
    "GoalState",
    "build_goal_transcript",
    "format_goal_status",
    "goal_continue_directive",
    "parse_goal_command",
    "parse_verdict",
]
