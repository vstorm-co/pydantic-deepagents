"""Built-in guardrails for common safety patterns."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic_deep.guardrails.types import (
    GuardrailContext,
    GuardrailResult,
)


class TokenBudgetGuardrail:
    """Prevent token budget overruns."""

    def __init__(
        self,
        max_tokens: int,
        warn_at: float = 0.8,
        action: Literal["raise", "warn", "soft_stop"] = "raise",
    ) -> None:
        """Initialize token budget guardrail.

        Args:
            max_tokens: Maximum tokens allowed.
            warn_at: Fraction at which to emit warning (0.0-1.0).
            action: Action to take on violation.
        """
        self.max_tokens = max_tokens
        self.warn_threshold = int(max_tokens * warn_at)
        self.action = action

    def check(self, context: GuardrailContext) -> GuardrailResult:
        """Check if token budget is within limits.

        Args:
            context: Guardrail context.

        Returns:
            Result indicating if budget is within limits.
        """
        if context.total_tokens > self.max_tokens:
            return GuardrailResult(
                passed=False,
                message=f"Token budget exceeded: {context.total_tokens}/{self.max_tokens}",
                metadata={"action": self.action},
            )
        elif context.total_tokens > self.warn_threshold:
            # Emit warning but continue
            return GuardrailResult(
                passed=True,
                message=f"Token budget warning: {context.total_tokens}/{self.max_tokens} ({context.total_tokens / self.max_tokens * 100:.1f}%)",
                metadata={"warning": True},
            )
        return GuardrailResult(passed=True)

    def on_violation(self, context: GuardrailContext) -> None:
        """Handle token budget violation.

        Args:
            context: Guardrail context.
        """
        # Default behavior is to raise exception
        # Could be extended to log, emit metrics, etc.
        pass


class IterationLimitGuardrail:
    """Prevent infinite loops."""

    def __init__(
        self,
        max_iterations: int = 20,
        action: Literal["raise", "return_partial"] = "raise",
    ) -> None:
        """Initialize iteration limit guardrail.

        Args:
            max_iterations: Maximum iterations allowed.
            action: Action to take on violation.
        """
        self.max_iterations = max_iterations
        self.action = action

    def check(self, context: GuardrailContext) -> GuardrailResult:
        """Check if iteration count is within limits.

        Args:
            context: Guardrail context.

        Returns:
            Result indicating if iteration count is within limits.
        """
        if context.iteration_count > self.max_iterations:
            return GuardrailResult(
                passed=False,
                message=f"Iteration limit exceeded: {context.iteration_count}/{self.max_iterations}",
                metadata={"action": self.action},
            )
        return GuardrailResult(passed=True)

    def on_violation(self, context: GuardrailContext) -> None:
        """Handle iteration limit violation.

        Args:
            context: Guardrail context.
        """
        pass


class CostLimitGuardrail:
    """Prevent runaway costs."""

    def __init__(
        self,
        max_cost_usd: float,
        warn_at: float = 0.7,
    ) -> None:
        """Initialize cost limit guardrail.

        Args:
            max_cost_usd: Maximum cost in USD allowed.
            warn_at: Fraction at which to emit warning (0.0-1.0).
        """
        self.max_cost_usd = max_cost_usd
        self.warn_threshold = max_cost_usd * warn_at

    def check(self, context: GuardrailContext) -> GuardrailResult:
        """Check if cost is within limits.

        Args:
            context: Guardrail context.

        Returns:
            Result indicating if cost is within limits.
        """
        if context.total_cost_usd > self.max_cost_usd:
            return GuardrailResult(
                passed=False,
                message=f"Cost limit exceeded: ${context.total_cost_usd:.4f}/${self.max_cost_usd:.2f}",
            )
        elif context.total_cost_usd > self.warn_threshold:
            return GuardrailResult(
                passed=True,
                message=f"Cost warning: ${context.total_cost_usd:.4f}/${self.max_cost_usd:.2f} ({context.total_cost_usd / self.max_cost_usd * 100:.1f}%)",
                metadata={"warning": True},
            )
        return GuardrailResult(passed=True)

    def on_violation(self, context: GuardrailContext) -> None:
        """Handle cost limit violation.

        Args:
            context: Guardrail context.
        """
        pass


class ToolChainValidationGuardrail:
    """Prevent invalid tool call sequences."""

    def __init__(
        self,
        forbidden_sequences: list[list[str]],
        forbidden_patterns: list[tuple[str, str]] | None = None,
    ) -> None:
        """Initialize tool chain validation guardrail.

        Args:
            forbidden_sequences: List of forbidden tool sequences.
            forbidden_patterns: List of (pattern1, pattern2) tuples representing
                forbidden patterns (e.g., ("delete_*", "read_*")).
        """
        self.forbidden_sequences = forbidden_sequences
        self.forbidden_patterns = forbidden_patterns or []

    def _matches_sequence(self, tools: list[str], sequence: list[str]) -> bool:
        """Check if tools contain the forbidden sequence.

        Args:
            tools: List of recent tool names.
            sequence: Forbidden sequence to check for.

        Returns:
            True if sequence is found in tools.
        """
        if len(sequence) > len(tools):
            return False

        # Check all possible windows
        for i in range(len(tools) - len(sequence) + 1):
            window = tools[i : i + len(sequence)]
            if window == sequence:
                return True

        return False

    def _matches_pattern(
        self, tool1: str, tool2: str, pattern1: str, pattern2: str
    ) -> bool:
        """Check if two tools match a forbidden pattern.

        Args:
            tool1: First tool name.
            tool2: Second tool name.
            pattern1: First pattern (e.g., "delete_*").
            pattern2: Second pattern (e.g., "read_*").

        Returns:
            True if tools match the pattern.
        """
        import fnmatch

        return fnmatch.fnmatch(tool1, pattern1) and fnmatch.fnmatch(tool2, pattern2)

    def check(self, context: GuardrailContext) -> GuardrailResult:
        """Check if tool call sequence is valid.

        Args:
            context: Guardrail context.

        Returns:
            Result indicating if tool sequence is valid.
        """
        # Check forbidden sequences
        for seq in self.forbidden_sequences:
            if self._matches_sequence(context.last_n_tools, seq):
                return GuardrailResult(
                    passed=False,
                    message=f"Forbidden tool sequence: {' -> '.join(seq)}",
                )

        # Check forbidden patterns
        for pattern1, pattern2 in self.forbidden_patterns:
            for i in range(len(context.last_n_tools) - 1):
                if self._matches_pattern(
                    context.last_n_tools[i], context.last_n_tools[i + 1], pattern1, pattern2
                ):
                    return GuardrailResult(
                        passed=False,
                        message=f"Forbidden pattern: {pattern1} -> {pattern2} (found: {context.last_n_tools[i]} -> {context.last_n_tools[i + 1]})",
                    )

        return GuardrailResult(passed=True)

    def on_violation(self, context: GuardrailContext) -> None:
        """Handle tool chain violation.

        Args:
            context: Guardrail context.
        """
        pass


class OutputValidationGuardrail:
    """Validate agent output before returning."""

    def __init__(
        self,
        validators: list[Callable[[str], bool]],
        on_fail: Literal["raise", "sanitize", "log"] = "raise",
        sanitizer: Callable[[str], str] | None = None,
    ) -> None:
        """Initialize output validation guardrail.

        Args:
            validators: List of validation functions (return True if valid).
            on_fail: Action to take on validation failure.
            sanitizer: Function to sanitize output if on_fail="sanitize".
        """
        self.validators = validators
        self.on_fail = on_fail
        self.sanitizer = sanitizer

    def check(self, context: GuardrailContext) -> GuardrailResult:
        """Check if output passes all validators.

        Args:
            context: Guardrail context.

        Returns:
            Result indicating if output is valid.
        """
        # For now, we'll check metadata for output
        output = context.metadata.get("output", "")
        if not isinstance(output, str):
            output = str(output)

        for i, validator in enumerate(self.validators):
            if not validator(output):
                return GuardrailResult(
                    passed=False,
                    message=f"Output validation failed: validator {i}",
                    metadata={"validator_index": i, "on_fail": self.on_fail},
                )

        return GuardrailResult(passed=True)

    def on_violation(self, context: GuardrailContext) -> None:
        """Handle output validation violation.

        Args:
            context: Guardrail context.
        """
        if self.on_fail == "sanitize" and self.sanitizer:
            output = context.metadata.get("output", "")
            if isinstance(output, str):
                context.metadata["output"] = self.sanitizer(output)


class ToolLoopDetectionGuardrail:
    """Detect when agent is stuck in a loop."""

    def __init__(
        self,
        window_size: int = 5,
        max_repeats: int = 3,
    ) -> None:
        """Initialize tool loop detection guardrail.

        Args:
            window_size: Size of the window to check for loops.
            max_repeats: Maximum allowed repeats of the same pattern.
        """
        self.window_size = window_size
        self.max_repeats = max_repeats

    def _detect_pattern(self, tools: list[str]) -> tuple[bool, str]:
        """Detect if tools contain a repeating pattern.

        Args:
            tools: List of recent tool names.

        Returns:
            Tuple of (is_loop, pattern_description).
        """
        if len(tools) < self.window_size:
            return False, ""

        recent = tools[-self.window_size :]

        # Check for exact repeats (same tool repeatedly)
        if len(set(recent)) == 1:
            return True, f"Tool '{recent[0]}' repeated {len(recent)} times"

        # Check for alternating patterns (A, B, A, B, A, B)
        if len(recent) >= 4:  # pragma: no branch
            # Check 2-element patterns
            for pattern_len in [2, 3]:
                if len(recent) >= pattern_len * self.max_repeats:
                    pattern = recent[:pattern_len]
                    repeat_count = 0
                    for i in range(0, len(recent), pattern_len):
                        chunk = recent[i : i + pattern_len]
                        if chunk == pattern:
                            repeat_count += 1
                        else:
                            break

                    if repeat_count >= self.max_repeats:
                        return True, f"Pattern {pattern} repeated {repeat_count} times"

        return False, ""

    def check(self, context: GuardrailContext) -> GuardrailResult:
        """Check if agent is stuck in a loop.

        Args:
            context: Guardrail context.

        Returns:
            Result indicating if a loop was detected.
        """
        is_loop, pattern = self._detect_pattern(context.last_n_tools)

        if is_loop:
            return GuardrailResult(
                passed=False,
                message=f"Tool loop detected: {pattern}",
            )

        return GuardrailResult(passed=True)

    def on_violation(self, context: GuardrailContext) -> None:
        """Handle tool loop violation.

        Args:
            context: Guardrail context.
        """
        pass
