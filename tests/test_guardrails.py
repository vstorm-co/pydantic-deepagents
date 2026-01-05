"""Tests for guardrails and safety gates."""

from __future__ import annotations

import pytest

from pydantic_deep.guardrails import (
    CostLimitGuardrail,
    GuardrailContext,
    GuardrailManager,
    GuardrailViolation,
    IterationLimitGuardrail,
    OutputValidationGuardrail,
    TokenBudgetGuardrail,
    ToolCall,
    ToolChainValidationGuardrail,
    ToolLoopDetectionGuardrail,
    create_production_guardrails,
    create_safe_agent_guardrails,
)


def create_test_context(**overrides) -> GuardrailContext:
    """Create a test guardrail context with sensible defaults."""
    defaults = {
        "agent_name": "test-agent",
        "run_id": "test-run-123",
        "iteration_count": 1,
        "total_tokens": 1000,
        "total_cost_usd": 0.01,
        "duration_seconds": 1.0,
        "tool_calls": [],
        "last_n_tools": [],
    }
    defaults.update(overrides)
    return GuardrailContext(**defaults)


class TestTokenBudgetGuardrail:
    """Tests for token budget guardrail."""

    def test_within_budget(self) -> None:
        """Test normal operation within budget."""
        guardrail = TokenBudgetGuardrail(max_tokens=10000)
        ctx = create_test_context(total_tokens=5000)

        result = guardrail.check(ctx)

        assert result.passed is True
        assert result.message is None

    def test_warn_threshold(self) -> None:
        """Test warning at threshold."""
        guardrail = TokenBudgetGuardrail(max_tokens=10000, warn_at=0.8)
        ctx = create_test_context(total_tokens=8500)  # 85% of max

        result = guardrail.check(ctx)

        assert result.passed is True
        assert result.message is not None
        assert "warning" in result.message.lower()
        assert "8500/10000" in result.message

    def test_budget_exceeded(self) -> None:
        """Test exception when budget exceeded."""
        guardrail = TokenBudgetGuardrail(max_tokens=10000, action="raise")
        ctx = create_test_context(total_tokens=15000)

        result = guardrail.check(ctx)

        assert result.passed is False
        assert "exceeded" in result.message.lower()
        assert "15000/10000" in result.message

    def test_on_violation_called(self) -> None:
        """Test on_violation is called."""
        guardrail = TokenBudgetGuardrail(max_tokens=10000)
        ctx = create_test_context(total_tokens=15000)

        # Should not raise
        guardrail.on_violation(ctx)


class TestIterationLimitGuardrail:
    """Tests for iteration limit guardrail."""

    def test_within_limit(self) -> None:
        """Test normal operation within limit."""
        guardrail = IterationLimitGuardrail(max_iterations=20)
        ctx = create_test_context(iteration_count=10)

        result = guardrail.check(ctx)

        assert result.passed is True

    def test_limit_exceeded(self) -> None:
        """Test exception when limit exceeded."""
        guardrail = IterationLimitGuardrail(max_iterations=20)
        ctx = create_test_context(iteration_count=25)

        result = guardrail.check(ctx)

        assert result.passed is False
        assert "exceeded" in result.message.lower()
        assert "25/20" in result.message

    def test_on_violation_called(self) -> None:
        """Test on_violation is called."""
        guardrail = IterationLimitGuardrail(max_iterations=20)
        ctx = create_test_context(iteration_count=25)

        # Should not raise
        guardrail.on_violation(ctx)


class TestCostLimitGuardrail:
    """Tests for cost limit guardrail."""

    def test_within_limit(self) -> None:
        """Test normal operation within limit."""
        guardrail = CostLimitGuardrail(max_cost_usd=10.0)
        ctx = create_test_context(total_cost_usd=5.0)

        result = guardrail.check(ctx)

        assert result.passed is True

    def test_cost_limit_exceeded(self) -> None:
        """Test cost limit enforcement."""
        guardrail = CostLimitGuardrail(max_cost_usd=10.0)
        ctx = create_test_context(total_cost_usd=15.0)

        result = guardrail.check(ctx)

        assert result.passed is False
        assert "exceeded" in result.message.lower()
        assert "$15.00" in result.message or "$15.0000" in result.message

    def test_warn_threshold(self) -> None:
        """Test warning at threshold."""
        guardrail = CostLimitGuardrail(max_cost_usd=10.0, warn_at=0.7)
        ctx = create_test_context(total_cost_usd=8.0)  # 80% of max

        result = guardrail.check(ctx)

        assert result.passed is True
        assert result.message is not None
        assert "warning" in result.message.lower()

    def test_on_violation_called(self) -> None:
        """Test on_violation is called."""
        guardrail = CostLimitGuardrail(max_cost_usd=10.0)
        ctx = create_test_context(total_cost_usd=15.0)

        # Should not raise
        guardrail.on_violation(ctx)


class TestToolChainValidationGuardrail:
    """Tests for tool chain validation guardrail."""

    def test_valid_sequence(self) -> None:
        """Test valid tool sequences."""
        guardrail = ToolChainValidationGuardrail(forbidden_sequences=[["delete_file", "read_file"]])
        ctx = create_test_context(last_n_tools=["read_file", "write_file"])

        result = guardrail.check(ctx)

        assert result.passed is True

    def test_forbidden_sequence(self) -> None:
        """Test forbidden sequence detection."""
        guardrail = ToolChainValidationGuardrail(forbidden_sequences=[["delete_file", "read_file"]])
        ctx = create_test_context(last_n_tools=["write_file", "delete_file", "read_file"])

        result = guardrail.check(ctx)

        assert result.passed is False
        assert "forbidden" in result.message.lower()
        assert "delete_file -> read_file" in result.message

    def test_pattern_matching(self) -> None:
        """Test pattern-based validation."""
        guardrail = ToolChainValidationGuardrail(
            forbidden_sequences=[],
            forbidden_patterns=[("delete_*", "read_*")],
        )
        ctx = create_test_context(last_n_tools=["delete_file", "read_data"])

        result = guardrail.check(ctx)

        assert result.passed is False
        assert "pattern" in result.message.lower()

    def test_no_forbidden_patterns(self) -> None:
        """Test when no patterns match."""
        guardrail = ToolChainValidationGuardrail(
            forbidden_sequences=[],
            forbidden_patterns=[("delete_*", "read_*")],
        )
        ctx = create_test_context(last_n_tools=["read_file", "write_file"])

        result = guardrail.check(ctx)

        assert result.passed is True

    def test_on_violation_called(self) -> None:
        """Test on_violation is called."""
        guardrail = ToolChainValidationGuardrail(forbidden_sequences=[["delete_file", "read_file"]])
        ctx = create_test_context(last_n_tools=["delete_file", "read_file"])

        # Should not raise
        guardrail.on_violation(ctx)

    def test_sequence_longer_than_tools(self) -> None:
        """Test when forbidden sequence is longer than available tools."""
        guardrail = ToolChainValidationGuardrail(
            forbidden_sequences=[["tool1", "tool2", "tool3", "tool4", "tool5"]]
        )
        ctx = create_test_context(last_n_tools=["tool1", "tool2"])

        result = guardrail.check(ctx)

        # Should pass because sequence is too long to match
        assert result.passed is True


class TestOutputValidationGuardrail:
    """Tests for output validation guardrail."""

    def test_valid_output(self) -> None:
        """Test valid output passes all validators."""

        def no_bad_words(text: str) -> bool:
            return "bad" not in text.lower()

        guardrail = OutputValidationGuardrail(validators=[no_bad_words])
        ctx = create_test_context(metadata={"output": "This is good output"})

        result = guardrail.check(ctx)

        assert result.passed is True

    def test_invalid_output(self) -> None:
        """Test invalid output fails validation."""

        def no_bad_words(text: str) -> bool:
            return "bad" not in text.lower()

        guardrail = OutputValidationGuardrail(validators=[no_bad_words])
        ctx = create_test_context(metadata={"output": "This is BAD output"})

        result = guardrail.check(ctx)

        assert result.passed is False
        assert "validation failed" in result.message.lower()

    def test_sanitization(self) -> None:
        """Test output sanitization on failure."""

        def no_bad_words(text: str) -> bool:
            return "bad" not in text.lower()

        def sanitize(text: str) -> str:
            return text.replace("BAD", "***")

        guardrail = OutputValidationGuardrail(
            validators=[no_bad_words],
            on_fail="sanitize",
            sanitizer=sanitize,
        )
        ctx = create_test_context(metadata={"output": "This is BAD output"})

        result = guardrail.check(ctx)
        assert result.passed is False

        # Call on_violation to sanitize
        guardrail.on_violation(ctx)
        assert ctx.metadata["output"] == "This is *** output"

    def test_no_output_in_metadata(self) -> None:
        """Test when output is not in metadata."""

        def always_true(text: str) -> bool:
            return True

        guardrail = OutputValidationGuardrail(validators=[always_true])
        ctx = create_test_context(metadata={})

        result = guardrail.check(ctx)

        # Should pass with empty string
        assert result.passed is True

    def test_non_string_output(self) -> None:
        """Test when output is not a string."""

        def always_true(text: str) -> bool:
            return True

        guardrail = OutputValidationGuardrail(validators=[always_true])
        ctx = create_test_context(metadata={"output": {"key": "value"}})

        result = guardrail.check(ctx)

        # Should convert to string
        assert result.passed is True

    def test_on_violation_without_sanitizer(self) -> None:
        """Test on_violation when on_fail != 'sanitize'."""

        def always_false(text: str) -> bool:
            return False

        guardrail = OutputValidationGuardrail(
            validators=[always_false],
            on_fail="raise",  # Not sanitize
        )
        ctx = create_test_context(metadata={"output": "test output"})

        # Should not raise or modify output
        guardrail.on_violation(ctx)
        assert ctx.metadata["output"] == "test output"

    def test_on_violation_with_non_string_output(self) -> None:
        """Test on_violation when output is not a string."""

        def always_false(text: str) -> bool:
            return False

        def sanitize(text: str) -> str:
            return "sanitized"

        guardrail = OutputValidationGuardrail(
            validators=[always_false],
            on_fail="sanitize",
            sanitizer=sanitize,
        )
        ctx = create_test_context(metadata={"output": {"key": "value"}})

        # Should not sanitize non-string output
        guardrail.on_violation(ctx)
        assert ctx.metadata["output"] == {"key": "value"}


class TestToolLoopDetectionGuardrail:
    """Tests for tool loop detection guardrail."""

    def test_no_loop(self) -> None:
        """Test normal operation without loops."""
        guardrail = ToolLoopDetectionGuardrail(window_size=5, max_repeats=3)
        ctx = create_test_context(last_n_tools=["read_file", "write_file", "execute", "grep"])

        result = guardrail.check(ctx)

        assert result.passed is True

    def test_exact_repeat_loop(self) -> None:
        """Test detection of exact repeats."""
        guardrail = ToolLoopDetectionGuardrail(window_size=5, max_repeats=3)
        ctx = create_test_context(
            last_n_tools=["read_file", "read_file", "read_file", "read_file", "read_file"]
        )

        result = guardrail.check(ctx)

        assert result.passed is False
        assert "loop" in result.message.lower()

    def test_pattern_repeat_loop(self) -> None:
        """Test detection of repeating patterns."""
        guardrail = ToolLoopDetectionGuardrail(window_size=6, max_repeats=3)
        ctx = create_test_context(
            last_n_tools=[
                "read_file",
                "write_file",
                "read_file",
                "write_file",
                "read_file",
                "write_file",
            ]
        )

        result = guardrail.check(ctx)

        assert result.passed is False
        assert "loop" in result.message.lower()
        assert "pattern" in result.message.lower()

    def test_short_history(self) -> None:
        """Test with history shorter than window size."""
        guardrail = ToolLoopDetectionGuardrail(window_size=10, max_repeats=3)
        ctx = create_test_context(last_n_tools=["read_file", "write_file"])

        result = guardrail.check(ctx)

        assert result.passed is True

    def test_very_short_history(self) -> None:
        """Test with history of exactly 3 tools (less than 4)."""
        guardrail = ToolLoopDetectionGuardrail(window_size=5, max_repeats=3)
        ctx = create_test_context(last_n_tools=["read", "write", "exec"])

        result = guardrail.check(ctx)

        # Should pass because history is too short for pattern detection
        assert result.passed is True

    def test_on_violation_called(self) -> None:
        """Test on_violation is called."""
        guardrail = ToolLoopDetectionGuardrail(window_size=5, max_repeats=3)
        ctx = create_test_context(last_n_tools=["read_file"] * 5)

        # Should not raise
        guardrail.on_violation(ctx)

    def test_three_element_pattern_loop(self) -> None:
        """Test detection of 3-element repeating patterns."""
        guardrail = ToolLoopDetectionGuardrail(window_size=9, max_repeats=3)
        ctx = create_test_context(
            last_n_tools=["read", "write", "exec", "read", "write", "exec", "read", "write", "exec"]
        )

        result = guardrail.check(ctx)

        assert result.passed is False
        assert "loop" in result.message.lower()
        assert "pattern" in result.message.lower()

    def test_broken_pattern(self) -> None:
        """Test when pattern starts but doesn't continue."""
        guardrail = ToolLoopDetectionGuardrail(window_size=8, max_repeats=3)
        ctx = create_test_context(
            last_n_tools=["read", "write", "read", "write", "read", "different", "read", "write"]
        )

        result = guardrail.check(ctx)

        # Should not detect loop because pattern breaks
        assert result.passed is True

    def test_insufficient_pattern_repeats(self) -> None:
        """Test when pattern repeats but not enough times."""
        guardrail = ToolLoopDetectionGuardrail(window_size=4, max_repeats=3)
        ctx = create_test_context(
            last_n_tools=["read", "write", "read", "write"]  # Pattern repeats only 2 times
        )

        result = guardrail.check(ctx)

        # Should not detect loop because pattern repeats < max_repeats
        assert result.passed is True

    def test_no_pattern_with_enough_history(self) -> None:
        """Test with 4+ tools but no repeating pattern."""
        guardrail = ToolLoopDetectionGuardrail(window_size=5, max_repeats=3)
        ctx = create_test_context(
            last_n_tools=["read", "write", "exec", "grep", "glob"]  # All different
        )

        result = guardrail.check(ctx)

        # Should pass because there's no pattern
        assert result.passed is True


class TestGuardrailManager:
    """Tests for guardrail manager."""

    def test_strict_mode(self) -> None:
        """Test strict mode raises on violation."""
        guardrails = [TokenBudgetGuardrail(max_tokens=1000)]
        manager = GuardrailManager(guardrails, mode="strict")
        ctx = create_test_context(total_tokens=2000)

        with pytest.raises(GuardrailViolation) as exc_info:
            manager.check_all(ctx)

        assert "exceeded" in str(exc_info.value).lower()

    def test_permissive_mode(self) -> None:
        """Test permissive mode logs violations."""
        guardrails = [TokenBudgetGuardrail(max_tokens=1000)]
        manager = GuardrailManager(guardrails, mode="permissive")
        ctx = create_test_context(total_tokens=2000)

        results = manager.check_all(ctx)

        assert len(results) == 1
        assert results[0].passed is False
        assert len(manager.violations) == 1

    def test_multiple_guardrails(self) -> None:
        """Test checking multiple guardrails."""
        guardrails = [
            TokenBudgetGuardrail(max_tokens=10000),
            IterationLimitGuardrail(max_iterations=20),
            CostLimitGuardrail(max_cost_usd=10.0),
        ]
        manager = GuardrailManager(guardrails, mode="strict")
        ctx = create_test_context(
            total_tokens=5000,
            iteration_count=10,
            total_cost_usd=5.0,
        )

        results = manager.check_all(ctx)

        assert len(results) == 3
        assert all(r.passed for r in results)

    def test_summary(self) -> None:
        """Test getting summary of guardrail checks."""
        guardrails = [
            TokenBudgetGuardrail(max_tokens=1000),
            IterationLimitGuardrail(max_iterations=10),
        ]
        manager = GuardrailManager(guardrails, mode="permissive")
        ctx = create_test_context(total_tokens=2000, iteration_count=15)

        manager.check_all(ctx)
        summary = manager.get_summary()

        assert summary["total_checks"] == 2
        assert summary["violations"] == 2
        assert len(summary["violation_types"]) == 2

    def test_reset(self) -> None:
        """Test resetting violation history."""
        guardrails = [TokenBudgetGuardrail(max_tokens=1000)]
        manager = GuardrailManager(guardrails, mode="permissive")
        ctx = create_test_context(total_tokens=2000)

        manager.check_all(ctx)
        assert len(manager.violations) == 1

        manager.reset()
        assert len(manager.violations) == 0


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_safe_agent_guardrails(self) -> None:
        """Test creating safe agent guardrails."""
        guardrails = create_safe_agent_guardrails(
            max_tokens=50000,
            max_cost_usd=5.0,
            max_iterations=15,
        )

        assert len(guardrails) == 4
        assert isinstance(guardrails[0], TokenBudgetGuardrail)
        assert isinstance(guardrails[1], CostLimitGuardrail)
        assert isinstance(guardrails[2], IterationLimitGuardrail)
        assert isinstance(guardrails[3], ToolLoopDetectionGuardrail)

    def test_create_production_guardrails(self) -> None:
        """Test creating production guardrails."""
        guardrails = create_production_guardrails(
            max_tokens=100000,
            max_cost_usd=25.0,
        )

        assert len(guardrails) == 6
        assert isinstance(guardrails[0], TokenBudgetGuardrail)
        assert isinstance(guardrails[1], CostLimitGuardrail)
        assert isinstance(guardrails[2], IterationLimitGuardrail)
        assert isinstance(guardrails[3], ToolChainValidationGuardrail)
        assert isinstance(guardrails[4], OutputValidationGuardrail)
        assert isinstance(guardrails[5], ToolLoopDetectionGuardrail)

    def test_create_production_with_custom_validators(self) -> None:
        """Test creating production guardrails with custom validators."""

        def custom_validator(text: str) -> bool:
            return "custom" not in text

        guardrails = create_production_guardrails(custom_validators=[custom_validator])

        # Find OutputValidationGuardrail
        output_guardrail = next(g for g in guardrails if isinstance(g, OutputValidationGuardrail))
        assert len(output_guardrail.validators) == 3  # 2 default + 1 custom


class TestGuardrailContext:
    """Tests for GuardrailContext."""

    def test_create_context(self) -> None:
        """Test creating a guardrail context."""
        ctx = GuardrailContext(
            agent_name="test-agent",
            run_id="run-123",
            iteration_count=5,
            total_tokens=1000,
            total_cost_usd=0.05,
            duration_seconds=2.5,
            tool_calls=[],
            last_n_tools=["read_file", "write_file"],
        )

        assert ctx.agent_name == "test-agent"
        assert ctx.run_id == "run-123"
        assert ctx.iteration_count == 5
        assert ctx.total_tokens == 1000
        assert ctx.total_cost_usd == 0.05
        assert ctx.duration_seconds == 2.5
        assert len(ctx.last_n_tools) == 2

    def test_context_with_metadata(self) -> None:
        """Test context with custom metadata."""
        ctx = create_test_context(metadata={"custom_key": "custom_value"})

        assert ctx.metadata["custom_key"] == "custom_value"


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_create_tool_call(self) -> None:
        """Test creating a tool call."""
        tool_call = ToolCall(
            tool_name="read_file",
            args={"path": "/test.txt"},
            result="file content",
            timestamp=1234567890.0,
        )

        assert tool_call.tool_name == "read_file"
        assert tool_call.args == {"path": "/test.txt"}
        assert tool_call.result == "file content"
        assert tool_call.timestamp == 1234567890.0

    def test_tool_call_with_error(self) -> None:
        """Test tool call with error."""
        tool_call = ToolCall(
            tool_name="write_file",
            args={"path": "/test.txt", "content": "data"},
            error="Permission denied",
        )

        assert tool_call.error == "Permission denied"
        assert tool_call.result is None


class TestValidators:
    """Tests for validation helper functions."""

    def test_validate_no_secrets(self) -> None:
        """Test secret validation."""
        from pydantic_deep.guardrails import validate_no_secrets

        # Should pass
        assert validate_no_secrets("This is clean text") is True

        # Should fail - API key
        assert validate_no_secrets("api_key: sk-1234567890abcdefghij") is False

        # Should fail - password
        assert validate_no_secrets("password: mysecretpassword123") is False

        # Should fail - private key
        assert validate_no_secrets("-----BEGIN RSA PRIVATE KEY-----") is False

    def test_validate_no_pii(self) -> None:
        """Test PII validation."""
        from pydantic_deep.guardrails import validate_no_pii

        # Should pass
        assert validate_no_pii("This is clean text") is True

        # Should fail - SSN
        assert validate_no_pii("My SSN is 123-45-6789") is False

        # Should fail - Credit card
        assert validate_no_pii("Card: 1234567890123456") is False

        # Should fail - Email
        assert validate_no_pii("Contact: user@example.com") is False

    def test_redact_secrets(self) -> None:
        """Test secret redaction."""
        from pydantic_deep.guardrails import redact_secrets

        text = "My api_key=sk-1234567890abcdefghij and password=secret123"
        redacted = redact_secrets(text)

        assert "sk-1234567890abcdefghij" not in redacted
        assert "secret123" not in redacted
        assert "***REDACTED***" in redacted
