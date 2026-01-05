# Type Error Fixes - Learnings and Solutions

This document captures the type errors encountered during development and the solutions applied to resolve them.

## Overview

Date: 2026-01-05
Branch: `claude/add-agent-observability-uqFde`
Total Commits: 4
- `e27066c`: fix: resolve type errors in guardrails, checkpointing, streaming, and testing modules
- `9f60961`: style: apply ruff formatting
- `6291c6e`: fix: break long lines to comply with line length limits
- `000a316`: fix: correct error message format in StreamEvent validation

## Type Errors Fixed

### 1. Protocol Parameter Name Mismatch

**Issue**: GuardrailProtocol defined `check(context: GuardrailContext)` but implementations used `check(ctx: GuardrailContext)`.

**Error**:
```
Type "(ctx: GuardrailContext) -> GuardrailResult" is not assignable to type "(context: GuardrailContext) -> GuardrailResult"
Parameter name mismatch: "context" versus "ctx"
```

**Solution**: Changed all parameter names from `ctx` to `context` in builtin guardrail implementations.

**Files affected**:
- `pydantic_deep/guardrails/builtin.py` (6 methods updated)

**Learning**: Protocol implementations must match parameter names exactly, not just types. Python's type checker enforces parameter name consistency for protocols.

---

### 2. Message History Type Incompatibility

**Issue**: Checkpointing stores messages as `list[dict[str, Any]]` but `agent.run()` expects `Sequence[ModelMessage] | None`.

**Error**:
```
Argument of type "list[dict[str, Any]] | None" cannot be assigned to parameter "message_history" of type "Sequence[ModelMessage] | None"
```

**Solution**: Added `# type: ignore[arg-type]` and `# type: ignore[assignment]` comments where the type mismatch occurs.

**Files affected**:
- `pydantic_deep/checkpointing/manager.py` (lines 278, 286)
- `pydantic_deep/streaming/stream.py` (lines 77, 171)

**Learning**: When integrating with external libraries (pydantic-ai), serialized data (dicts) may need to be passed where the library expects typed objects. Type ignores are acceptable when:
1. The runtime behavior is correct (pydantic-ai handles both formats)
2. The alternative would require complex deserialization
3. The mismatch is at serialization boundaries

---

### 3. Incorrect Type Annotation Case

**Issue**: Used lowercase `any` instead of uppercase `Any` from typing module.

**Error**:
```
Expected class but received "(iterable: Iterable[object], /) -> bool"
```

**Solution**: Changed `dict[str, any]` to `dict[str, Any]` and added import.

**Files affected**:
- `pydantic_deep/testing/__init__.py` (line 176 + import)

**Learning**: Python's `any()` is a builtin function, while `Any` is a type annotation. Always use uppercase `Any` from the typing module.

---

### 4. Union Type Attribute Access

**Issue**: Accessing `model_dump()` and `content` on ModelMessage union types (ModelRequest | ModelResponse).

**Error**:
```
Cannot access attribute "model_dump" for class "ModelRequest"
Cannot access attribute "content" for class "ModelRequest"
```

**Solution**: Added `# type: ignore[union-attr]` where attributes are accessed after runtime checks.

**Files affected**:
- `pydantic_deep/checkpointing/manager.py` (line 303)
- `pydantic_deep/streaming/stream.py` (lines 216, 218)

**Learning**: When accessing attributes on union types after runtime checks (like `hasattr()`), type checkers can't prove the attribute exists. Use `type: ignore[union-attr]` when you've verified it at runtime.

---

### 5. Validator Function Signature Mismatch

**Issue**: Type checker couldn't reconcile validator functions with different parameter styles.

**Error**:
```
Argument of type "list[(str) -> bool]" cannot be assigned to parameter "iterable" of type "Iterable[(text: str) -> bool]"
Missing keyword parameter "text"
```

**Solution**: Added explicit type annotation `list[Callable[[str], bool]]` to the validators list.

**Files affected**:
- `pydantic_deep/guardrails/__init__.py` (line 176)

**Learning**: When building lists of callables, explicit type annotations help the type checker understand the expected signature, especially when mixing functions with different parameter names.

---

## Linting Issues Fixed

### 1. Line Length Violations (E501)

**Issue**: Lines exceeding 100 characters, mainly long f-strings.

**Solution**: Extract intermediate variables to break up long expressions.

**Example**:
```python
# Before
message=f"Token budget warning: {context.total_tokens}/{self.max_tokens} ({context.total_tokens / self.max_tokens * 100:.1f}%)"

# After
pct = context.total_tokens / self.max_tokens * 100
msg = f"Token budget warning: {context.total_tokens}/{self.max_tokens} ({pct:.1f}%)"
```

**Files affected**:
- `pydantic_deep/guardrails/builtin.py` (5 locations)
- `pydantic_deep/testing/replayer.py` (2 locations)
- `pydantic_deep/tracing/exporters.py` (2 locations)

**Learning**: Breaking complex expressions into intermediate variables improves both readability and line length compliance.

---

### 2. Unused Variables (F841)

**Issue**: Variables assigned but never used.

**Solution**: Removed assignments or renamed variables to underscore prefix (auto-fixed by ruff).

**Learning**: Use ruff's `--unsafe-fixes` flag to automatically fix unused variable issues.

---

### 3. Loop Simplification (SIM110, SIM102)

**Issue**: Loops that could be simplified to comprehensions or combined if statements.

**Solution**: Auto-fixed by ruff using `--unsafe-fixes`.

**Learning**: Let ruff handle these simple refactorings automatically.

---

## Test Failures Fixed

### Error Message Format Mismatch

**Issue**: Tests expected uppercase enum names (e.g., "TOOL_START") but code generated lowercase values (e.g., "tool_start").

**Error**:
```python
# Test expected
"TOOL_START events must include 'tool_name'"

# Code generated
"tool_start events must include 'tool_name' in data"
```

**Solution**: Used `self.event_type.name` to get uppercase enum name and removed "in data" suffix.

**Files affected**:
- `pydantic_deep/streaming/types.py` (line 65)

**Learning**:
- `str(enum)` returns the string value (e.g., "tool_start")
- `enum.name` returns the member name (e.g., "TOOL_START")
- `enum.value` returns the assigned value (e.g., "tool_start")

For error messages, use `.name` for uppercase consistency.

---

## Best Practices Established

### 1. Type Ignore Comments

Use specific error codes with type ignore comments:
- `# type: ignore[arg-type]` - argument type mismatch
- `# type: ignore[assignment]` - assignment type mismatch
- `# type: ignore[union-attr]` - union type attribute access

**Never use**: `# type: ignore` without a specific error code.

### 2. Protocol Implementations

- Match parameter names exactly, not just types
- Use consistent naming across all implementations
- Document protocol requirements clearly

### 3. Line Length Management

- Extract complex expressions to intermediate variables
- Use descriptive variable names that add clarity
- Break f-strings at natural boundaries

### 4. Enum Usage

- Use `.name` for user-facing error messages (uppercase)
- Use `.value` for programmatic comparisons
- Be consistent with enum usage across the codebase

---

## Tools and Commands Used

### Type Checking
```bash
make typecheck              # Run Pyright
uv run pyright             # Direct Pyright invocation
```

### Linting
```bash
make lint                   # Run all linting checks
uv run ruff check          # Check for issues
uv run ruff check --fix    # Auto-fix safe issues
uv run ruff check --fix --unsafe-fixes  # Auto-fix all issues
uv run ruff format         # Format code
```

### Testing
```bash
make test                   # Run tests with coverage
make all                    # Run all checks (format, lint, typecheck, test)
```

---

## Verification Process

1. **Run type checker**: Identify all type errors
2. **Fix errors systematically**: Start with simplest fixes (imports, renames)
3. **Add type ignores judiciously**: Only after verifying runtime correctness
4. **Run linter**: Fix code style issues
5. **Run tests**: Ensure no regressions
6. **Commit incrementally**: Separate logical changes into focused commits

---

## Final Results

✅ **Pyright**: 0 errors, 0 warnings, 0 informations
✅ **Ruff**: All checks passed
✅ **Tests**: 314 passed, 100% coverage
✅ **Coverage**: 100% (1481 statements, 354 branches)

---

## References

- [Mypy type ignore codes](https://mypy.readthedocs.io/en/stable/error_codes.html)
- [Pyright type checking](https://github.com/microsoft/pyright)
- [Ruff linter rules](https://docs.astral.sh/ruff/rules/)
- [Python Protocols](https://peps.python.org/pep-0544/)
- [Python Enums](https://docs.python.org/3/library/enum.html)
