"""Guardrails and safety gates for agent execution."""

from __future__ import annotations

from collections.abc import Callable

from pydantic_deep.guardrails.builtin import (
    CostLimitGuardrail,
    IterationLimitGuardrail,
    OutputValidationGuardrail,
    TokenBudgetGuardrail,
    ToolChainValidationGuardrail,
    ToolLoopDetectionGuardrail,
)
from pydantic_deep.guardrails.manager import GuardrailManager
from pydantic_deep.guardrails.types import (
    GuardrailContext,
    GuardrailProtocol,
    GuardrailResult,
    GuardrailViolation,
    ToolCall,
)

__all__ = [
    # Types
    "GuardrailContext",
    "GuardrailProtocol",
    "GuardrailResult",
    "GuardrailViolation",
    "ToolCall",
    # Manager
    "GuardrailManager",
    # Built-in guardrails
    "TokenBudgetGuardrail",
    "CostLimitGuardrail",
    "IterationLimitGuardrail",
    "ToolChainValidationGuardrail",
    "OutputValidationGuardrail",
    "ToolLoopDetectionGuardrail",
    # Factory functions
    "create_safe_agent_guardrails",
    "create_production_guardrails",
]


def create_safe_agent_guardrails(
    max_tokens: int = 100000,
    max_cost_usd: float = 10.0,
    max_iterations: int = 20,
) -> list[GuardrailProtocol]:
    """Create a safe set of default guardrails.

    Args:
        max_tokens: Maximum tokens allowed.
        max_cost_usd: Maximum cost in USD allowed.
        max_iterations: Maximum iterations allowed.

    Returns:
        List of configured guardrails.
    """
    return [
        TokenBudgetGuardrail(max_tokens=max_tokens, warn_at=0.8),
        CostLimitGuardrail(max_cost_usd=max_cost_usd, warn_at=0.7),
        IterationLimitGuardrail(max_iterations=max_iterations),
        ToolLoopDetectionGuardrail(),
    ]


def validate_no_secrets(text: str) -> bool:
    """Validate that text doesn't contain common secret patterns.

    Args:
        text: Text to validate.

    Returns:
        True if no secrets detected.
    """
    import re

    # Simple patterns for common secrets
    patterns = [
        r"(?i)(api[_-]?key|apikey)[\s:=]+['\"]?([a-z0-9_-]{20,})",
        r"(?i)(secret|password|passwd|pwd)[\s:=]+['\"]?([a-z0-9_-]{8,})",
        r"(?i)(token)[\s:=]+['\"]?([a-z0-9_-]{20,})",
        r"-----BEGIN [A-Z ]+ PRIVATE KEY-----",
    ]

    return all(not re.search(pattern, text) for pattern in patterns)


def validate_no_pii(text: str) -> bool:
    """Validate that text doesn't contain common PII patterns.

    Args:
        text: Text to validate.

    Returns:
        True if no PII detected.
    """
    import re

    # Simple patterns for common PII
    patterns = [
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
        r"\b\d{16}\b",  # Credit card
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",  # Email
    ]

    return all(not re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def redact_secrets(text: str) -> str:
    """Redact common secret patterns from text.

    Args:
        text: Text to sanitize.

    Returns:
        Sanitized text with secrets redacted.
    """
    import re

    # Redact API keys
    text = re.sub(
        r"(?i)(api[_-]?key|apikey)[\s:=]+['\"]?([a-z0-9_-]{20,})",
        r"\1=***REDACTED***",
        text,
    )

    # Redact passwords
    text = re.sub(
        r"(?i)(secret|password|passwd|pwd)[\s:=]+['\"]?([a-z0-9_-]{8,})",
        r"\1=***REDACTED***",
        text,
    )

    # Redact tokens
    text = re.sub(r"(?i)(token)[\s:=]+['\"]?([a-z0-9_-]{20,})", r"\1=***REDACTED***", text)

    # Redact private keys
    text = re.sub(
        r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----",
        "***PRIVATE KEY REDACTED***",
        text,
        flags=re.DOTALL,
    )

    return text


def create_production_guardrails(
    max_tokens: int = 200000,
    max_cost_usd: float = 50.0,
    custom_validators: list[Callable[[str], bool]] | None = None,
) -> list[GuardrailProtocol]:
    """Production-grade guardrails with sensible defaults.

    Args:
        max_tokens: Maximum tokens allowed.
        max_cost_usd: Maximum cost in USD allowed.
        custom_validators: Additional custom validators for output validation.

    Returns:
        List of configured production guardrails.
    """
    validators: list[Callable[[str], bool]] = [validate_no_secrets, validate_no_pii]
    if custom_validators:
        validators.extend(custom_validators)

    return [
        TokenBudgetGuardrail(max_tokens=max_tokens),
        CostLimitGuardrail(max_cost_usd=max_cost_usd),
        IterationLimitGuardrail(max_iterations=50),
        ToolChainValidationGuardrail(
            forbidden_sequences=[
                ["delete_file", "read_file"],  # Can't read deleted files
                ["drop_table", "insert_rows"],  # Can't insert after drop
            ]
        ),
        OutputValidationGuardrail(
            validators=validators,
            on_fail="sanitize",
            sanitizer=redact_secrets,
        ),
        ToolLoopDetectionGuardrail(),
    ]
