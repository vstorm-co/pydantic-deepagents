# Implementation Plan: Guardrails & Safety Gates

## Overview
Implement built-in protection against agent failures, runaway loops, cost explosions, and invalid operations. This complements the tracing system by preventing issues before they occur.

## Priority: High Impact, Medium Effort
**Estimated Time**: 4-6 hours
**LOC**: ~800-1000 lines
**Test Coverage**: 100% (as always)

---

## Phase 1: Core Guardrail Infrastructure (1.5 hours)

### 1.1 Guardrail Types & Protocol
**File**: `pydantic_deep/guardrails/types.py`

```python
class GuardrailViolation(Exception):
    """Raised when a guardrail is violated."""
    pass

@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

class GuardrailProtocol(Protocol):
    """Protocol for all guardrails."""

    def check(self, context: GuardrailContext) -> GuardrailResult:
        """Check if the guardrail passes."""
        ...

    def on_violation(self, context: GuardrailContext) -> None:
        """Called when guardrail is violated."""
        ...
```

### 1.2 Guardrail Context
**File**: `pydantic_deep/guardrails/context.py`

```python
@dataclass
class GuardrailContext:
    """Context passed to guardrails during checks."""

    # Agent state
    agent_name: str
    run_id: str
    iteration_count: int

    # Resource usage
    total_tokens: int
    total_cost_usd: float
    duration_seconds: float

    # Tool history
    tool_calls: list[ToolCall]
    last_n_tools: list[str]  # For detecting loops

    # Custom metadata
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

## Phase 2: Built-in Guardrails (2 hours)

### 2.1 Token Budget Guardrail
**File**: `pydantic_deep/guardrails/builtin.py`

```python
class TokenBudgetGuardrail:
    """Prevent token budget overruns."""

    def __init__(
        self,
        max_tokens: int,
        warn_at: float = 0.8,
        action: Literal["raise", "warn", "soft_stop"] = "raise",
    ):
        self.max_tokens = max_tokens
        self.warn_threshold = int(max_tokens * warn_at)
        self.action = action

    def check(self, ctx: GuardrailContext) -> GuardrailResult:
        if ctx.total_tokens > self.max_tokens:
            return GuardrailResult(
                passed=False,
                message=f"Token budget exceeded: {ctx.total_tokens}/{self.max_tokens}",
            )
        elif ctx.total_tokens > self.warn_threshold:
            # Emit warning but continue
            return GuardrailResult(
                passed=True,
                message=f"Token budget warning: {ctx.total_tokens}/{self.max_tokens}",
            )
        return GuardrailResult(passed=True)
```

### 2.2 Iteration Limit Guardrail
```python
class IterationLimitGuardrail:
    """Prevent infinite loops."""

    def __init__(
        self,
        max_iterations: int = 20,
        action: Literal["raise", "return_partial"] = "raise",
    ):
        self.max_iterations = max_iterations
        self.action = action
```

### 2.3 Cost Limit Guardrail
```python
class CostLimitGuardrail:
    """Prevent runaway costs."""

    def __init__(
        self,
        max_cost_usd: float,
        warn_at: float = 0.7,
        pricing: dict[str, ModelPricing] | None = None,
    ):
        self.max_cost_usd = max_cost_usd
        self.warn_at = warn_at
        self.pricing = pricing or DEFAULT_PRICING
```

### 2.4 Tool Chain Validation Guardrail
```python
class ToolChainValidationGuardrail:
    """Prevent invalid tool call sequences."""

    def __init__(
        self,
        forbidden_sequences: list[list[str]],
        forbidden_patterns: list[str] | None = None,
    ):
        self.forbidden_sequences = forbidden_sequences
        # Pattern examples: ["delete_*", "read_*"] = can't read after delete
        self.forbidden_patterns = forbidden_patterns or []

    def check(self, ctx: GuardrailContext) -> GuardrailResult:
        # Check last N tools against forbidden sequences
        for seq in self.forbidden_sequences:
            if self._matches_sequence(ctx.last_n_tools, seq):
                return GuardrailResult(
                    passed=False,
                    message=f"Forbidden tool sequence: {' -> '.join(seq)}",
                )
        return GuardrailResult(passed=True)
```

### 2.5 Output Validation Guardrail
```python
class OutputValidationGuardrail:
    """Validate agent output before returning."""

    def __init__(
        self,
        validators: list[Callable[[str], bool]],
        on_fail: Literal["raise", "sanitize", "log"] = "raise",
        sanitizer: Callable[[str], str] | None = None,
    ):
        self.validators = validators
        self.on_fail = on_fail
        self.sanitizer = sanitizer
```

### 2.6 Tool Loop Detection Guardrail
```python
class ToolLoopDetectionGuardrail:
    """Detect when agent is stuck in a loop."""

    def __init__(
        self,
        window_size: int = 5,
        max_repeats: int = 3,
    ):
        self.window_size = window_size
        self.max_repeats = max_repeats

    def check(self, ctx: GuardrailContext) -> GuardrailResult:
        # Check if same tool called repeatedly with same args
        recent = ctx.tool_calls[-self.window_size:]
        # Detect patterns like: read, write, read, write, read, write
        ...
```

---

## Phase 3: Guardrail Manager & Integration (1 hour)

### 3.1 Guardrail Manager
**File**: `pydantic_deep/guardrails/manager.py`

```python
class GuardrailManager:
    """Manages and executes guardrails."""

    def __init__(
        self,
        guardrails: list[GuardrailProtocol],
        mode: Literal["strict", "permissive"] = "strict",
    ):
        self.guardrails = guardrails
        self.mode = mode
        self.violations: list[GuardrailViolation] = []

    def check_all(self, context: GuardrailContext) -> list[GuardrailResult]:
        """Check all guardrails."""
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
        """Get summary of guardrail checks."""
        return {
            "total_checks": len(self.guardrails),
            "violations": len(self.violations),
            "violation_types": [v.message for v in self.violations],
        }
```

### 3.2 Integration with DeepAgentDeps
**File**: `pydantic_deep/deps.py` (modify)

```python
@dataclass
class DeepAgentDeps:
    # ... existing fields ...
    guardrail_manager: GuardrailManager | None = None
    guardrail_context: GuardrailContext | None = None
```

---

## Phase 4: Helper Factory Functions (0.5 hours)

### 4.1 Convenience Builders
**File**: `pydantic_deep/guardrails/__init__.py`

```python
def create_safe_agent_guardrails(
    max_tokens: int = 100000,
    max_cost_usd: float = 10.0,
    max_iterations: int = 20,
) -> list[GuardrailProtocol]:
    """Create a safe set of default guardrails."""
    return [
        TokenBudgetGuardrail(max_tokens=max_tokens, warn_at=0.8),
        CostLimitGuardrail(max_cost_usd=max_cost_usd, warn_at=0.7),
        IterationLimitGuardrail(max_iterations=max_iterations),
        ToolLoopDetectionGuardrail(),
    ]

def create_production_guardrails(
    max_tokens: int = 200000,
    max_cost_usd: float = 50.0,
) -> list[GuardrailProtocol]:
    """Production-grade guardrails with sensible defaults."""
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
            validators=[validate_no_secrets, validate_no_pii],
            on_fail="sanitize",
        ),
    ]
```

---

## Phase 5: Testing (1 hour)

### 5.1 Test Structure
**File**: `tests/test_guardrails.py`

```python
class TestTokenBudgetGuardrail:
    def test_within_budget(self):
        """Test normal operation within budget."""

    def test_warn_threshold(self):
        """Test warning at threshold."""

    def test_budget_exceeded_raise(self):
        """Test exception when budget exceeded."""

    def test_budget_exceeded_soft_stop(self):
        """Test soft stop when budget exceeded."""

class TestIterationLimitGuardrail:
    def test_within_limit(self):
        """Test normal operation within limit."""

    def test_limit_exceeded(self):
        """Test exception when limit exceeded."""

class TestCostLimitGuardrail:
    def test_cost_calculation(self):
        """Test cost calculation from tokens."""

    def test_cost_limit_exceeded(self):
        """Test cost limit enforcement."""

class TestToolChainValidationGuardrail:
    def test_valid_sequence(self):
        """Test valid tool sequences."""

    def test_forbidden_sequence(self):
        """Test forbidden sequence detection."""

    def test_pattern_matching(self):
        """Test pattern-based validation."""

class TestGuardrailManager:
    def test_strict_mode(self):
        """Test strict mode raises on violation."""

    def test_permissive_mode(self):
        """Test permissive mode logs violations."""

    def test_multiple_guardrails(self):
        """Test checking multiple guardrails."""
```

### 5.2 Integration Tests
```python
class TestGuardrailIntegration:
    async def test_agent_with_guardrails(self):
        """Test full agent run with guardrails."""
        guardrails = create_safe_agent_guardrails()
        manager = GuardrailManager(guardrails)

        deps = DeepAgentDeps(
            backend=StateBackend(),
            guardrail_manager=manager,
        )

        agent = create_deep_agent()
        # Test that guardrails are enforced

    async def test_token_budget_enforcement(self):
        """Test token budget is enforced during run."""

    async def test_iteration_limit_enforcement(self):
        """Test iteration limit stops runaway loops."""
```

---

## Phase 6: Documentation (0.5 hours)

### 6.1 Documentation File
**File**: `docs/guardrails.md`

```markdown
# Guardrails & Safety Gates

## Quick Start
```python
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_deep.guardrails import (
    create_safe_agent_guardrails,
    GuardrailManager,
)

# Create guardrails
guardrails = create_safe_agent_guardrails(
    max_tokens=100000,
    max_cost_usd=5.0,
    max_iterations=20,
)

# Create manager
manager = GuardrailManager(guardrails, mode="strict")

# Use with agent
deps = DeepAgentDeps(guardrail_manager=manager)
agent = create_deep_agent()

result = await agent.run("Do something", deps=deps)
```

## Built-in Guardrails
...
```

---

## Phase 7: Export & Integration (0.5 hours)

### 7.1 Update __init__.py
**File**: `pydantic_deep/__init__.py`

```python
from pydantic_deep.guardrails import (
    GuardrailManager,
    GuardrailProtocol,
    GuardrailViolation,
    TokenBudgetGuardrail,
    CostLimitGuardrail,
    IterationLimitGuardrail,
    ToolChainValidationGuardrail,
    OutputValidationGuardrail,
    create_safe_agent_guardrails,
    create_production_guardrails,
)
```

---

## File Structure

```
pydantic_deep/guardrails/
├── __init__.py          # Public API exports
├── types.py             # GuardrailProtocol, GuardrailContext, etc.
├── context.py           # GuardrailContext implementation
├── manager.py           # GuardrailManager
├── builtin.py           # All built-in guardrails
└── validators.py        # Output validation helpers

tests/
├── test_guardrails.py           # Main guardrail tests
└── test_guardrails_integration.py  # Integration tests

docs/
└── guardrails.md        # User documentation
```

---

## Success Criteria

- ✅ 100% test coverage
- ✅ All tests passing
- ✅ Complete documentation
- ✅ Type-safe (Pyright strict)
- ✅ 6 built-in guardrails implemented
- ✅ Factory functions for common use cases
- ✅ Integration with existing agent system
- ✅ Examples in documentation

---

## Example Usage Scenarios

### Scenario 1: Prevent Runaway Costs
```python
guardrails = [
    CostLimitGuardrail(max_cost_usd=10.0, warn_at=0.7),
    TokenBudgetGuardrail(max_tokens=50000),
]
```

### Scenario 2: Prevent Infinite Loops
```python
guardrails = [
    IterationLimitGuardrail(max_iterations=15),
    ToolLoopDetectionGuardrail(window_size=5, max_repeats=3),
]
```

### Scenario 3: Validate Output Safety
```python
guardrails = [
    OutputValidationGuardrail(
        validators=[validate_no_api_keys, validate_no_passwords],
        on_fail="sanitize",
        sanitizer=redact_secrets,
    ),
]
```

### Scenario 4: Production-Safe Agent
```python
guardrails = create_production_guardrails(
    max_tokens=200000,
    max_cost_usd=50.0,
)
manager = GuardrailManager(guardrails, mode="strict")
```

---

## Integration with Tracing

Guardrails emit trace events when violations occur:

```python
# In GuardrailManager
if not result.passed:
    if deps.trace_context:
        deps.trace_context.events.append(
            GuardrailViolationEvent(
                guardrail_type=type(guardrail).__name__,
                message=result.message,
                context=context,
            )
        )
```

This allows you to see guardrail violations in your trace output:

```
🤖 Agent run: my-agent
   ├─ LLM step [0.8s, 1250 tokens]
   ├─ ✓ Tool: read_file [0.1s]
   ├─ ⚠️  Guardrail Warning: Token budget at 80% (40000/50000)
   ├─ LLM step [0.6s, 890 tokens]
   ✗ Guardrail Violation: Iteration limit exceeded (21/20)
```

---

## Next Steps After Guardrails

1. **Agent Memory & Retrieval** - Persistent knowledge base
2. **Multi-Agent Orchestration** - DAG-based task decomposition
3. **Deterministic Testing Mode** - Record/replay for CI/CD
4. **Agent Checkpointing** - Resume after failures

---

## Estimated Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| 1. Core Infrastructure | 1.5h | 1.5h |
| 2. Built-in Guardrails | 2h | 3.5h |
| 3. Manager & Integration | 1h | 4.5h |
| 4. Helper Functions | 0.5h | 5h |
| 5. Testing | 1h | 6h |
| 6. Documentation | 0.5h | 6.5h |
| 7. Export & Polish | 0.5h | 7h |

**Total: ~6-7 hours for complete implementation**
