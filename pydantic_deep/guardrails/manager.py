"""Guardrail manager for coordinating multiple guardrails."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic_deep.guardrails.types import (
    GuardrailContext,
    GuardrailResult,
    GuardrailViolation,
)

if TYPE_CHECKING:
    from pydantic_deep.guardrails.types import GuardrailProtocol


class GuardrailManager:
    """Manages and executes guardrails."""

    def __init__(
        self,
        guardrails: list[GuardrailProtocol],
        mode: Literal["strict", "permissive"] = "strict",
    ) -> None:
        """Initialize guardrail manager.

        Args:
            guardrails: List of guardrails to check.
            mode: Enforcement mode - "strict" raises on violation,
                  "permissive" logs violations but continues.
        """
        self.guardrails = guardrails
        self.mode = mode
        self.violations: list[GuardrailResult] = []

    def check_all(self, context: GuardrailContext) -> list[GuardrailResult]:
        """Check all guardrails.

        Args:
            context: Current guardrail context.

        Returns:
            List of results from all guardrails.

        Raises:
            GuardrailViolation: If any guardrail fails in strict mode.
        """
        results = []
        for guardrail in self.guardrails:
            result = guardrail.check(context)
            results.append(result)

            if not result.passed:
                if self.mode == "strict":
                    guardrail.on_violation(context)
                    raise GuardrailViolation(result.message)
                else:
                    # Log but continue
                    self.violations.append(result)

        return results

    def get_summary(self) -> dict[str, Any]:
        """Get summary of guardrail checks.

        Returns:
            Dictionary with summary statistics.
        """
        return {
            "total_checks": len(self.guardrails),
            "violations": len(self.violations),
            "violation_types": [v.message for v in self.violations],
        }

    def reset(self) -> None:
        """Reset violation history."""
        self.violations.clear()
