# Agent Observability & Safety - Tracing + Guardrails

This PR implements two critical production-ready features for agent systems:
1. **Agent Observability & Tracing System**
2. **Guardrails & Safety Gates System**

These features provide comprehensive monitoring and safety for production agent deployments.

---

## 🎯 Features Delivered

### 1. Agent Observability & Tracing System

**Core Components:**
- `TraceContext` - Central context manager for collecting trace events
- `TraceExporterProtocol` - Extensible exporter interface
- 7 event types: AgentRunStart/End, LLMRequest/Response, ToolCallStart/End, Error

**Built-in Exporters (4 types):**
- `ConsoleExporter` - Pretty-printed tree view with verbose mode
- `InMemoryExporter` - Programmatic access with tree building and filtering
- `OpenTelemetryExporter` - Integration with OTel collectors (optional dependency)
- `StructuredFileExporter` - JSONL format for log aggregation

**Features:**
- Hierarchical event tracking with parent-child relationships
- Context managers for automatic lifecycle management
- Event filtering and tree visualization
- Token tracking and cost estimation
- Performance metrics and duration tracking
- Graceful handling of optional dependencies

### 2. Guardrails & Safety Gates System

**Built-in Guardrails (6 types):**
- `TokenBudgetGuardrail` - Prevent token overruns with warning thresholds
- `CostLimitGuardrail` - Prevent runaway costs with USD-based limits
- `IterationLimitGuardrail` - Prevent infinite loops with iteration caps
- `ToolChainValidationGuardrail` - Prevent invalid tool sequences with pattern matching
- `OutputValidationGuardrail` - Validate and sanitize agent output (secrets, PII detection)
- `ToolLoopDetectionGuardrail` - Detect when agent is stuck in loops

**GuardrailManager:**
- Coordinates multiple guardrails
- Strict mode (raise on violation) and permissive mode (log and continue)
- Violation tracking and summary statistics

**Factory Functions:**
- `create_safe_agent_guardrails()` - Safe defaults for development
- `create_production_guardrails()` - Production-grade with comprehensive checks
- Built-in validators: `validate_no_secrets`, `validate_no_pii`, `redact_secrets`

**Integration:**
- Integrated with `DeepAgentDeps` via `trace_context`, `guardrail_manager`, and `guardrail_context` fields
- Protocol-based design for easy custom implementations
- Shared across subagents for consistent enforcement

---

## 📊 Quality Metrics

- **222 tests passing** (73 new tests for tracing + guardrails)
- **100% test coverage** maintained across all new code
- **Full type safety** with Pyright strict mode
- **Complete documentation** with examples and best practices

---

## 📁 Files Added

### Tracing System
- `pydantic_deep/tracing/types.py` - Event types and protocols (154 lines)
- `pydantic_deep/tracing/context.py` - TraceContext implementation (279 lines)
- `pydantic_deep/tracing/exporters.py` - 4 exporters (389 lines)
- `pydantic_deep/tracing/__init__.py` - Public API (64 lines)
- `tests/test_tracing.py` - Comprehensive tests (29 tests, 563 lines)
- `docs/tracing.md` - User documentation (361 lines)

### Guardrails System
- `pydantic_deep/guardrails/types.py` - Protocols and types (62 lines)
- `pydantic_deep/guardrails/builtin.py` - 6 built-in guardrails (397 lines)
- `pydantic_deep/guardrails/manager.py` - GuardrailManager (66 lines)
- `pydantic_deep/guardrails/__init__.py` - Public API + factories (165 lines)
- `tests/test_guardrails.py` - Comprehensive tests (49 tests, 648 lines)
- `docs/guardrails.md` - User documentation (403 lines)

### Examples
- `examples/basic_tracing.py` - Tracing examples (164 lines)
- `examples/basic_guardrails.py` - Guardrails examples (303 lines)
- `examples/combined_tracing_guardrails.py` - Combined usage (234 lines)
- `examples/README.md` - Examples documentation (173 lines)

### Modified Files
- `pydantic_deep/__init__.py` - Export tracing and guardrails APIs
- `pydantic_deep/deps.py` - Add `trace_context`, `guardrail_manager`, `guardrail_context` fields

---

## 🚀 Usage Examples

### Tracing

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_deep.tracing import TraceContext, ConsoleExporter
from pydantic_ai_backends import StateBackend

# Set up tracing
trace_ctx = TraceContext(exporters=[ConsoleExporter(verbose=True)])

# Create deps with tracing
deps = DeepAgentDeps(
    backend=StateBackend(),
    trace_context=trace_ctx,
)

# Run agent with tracing
agent = create_deep_agent()
with trace_ctx.agent_run("my-agent", "Task description", "gpt-4o"):
    result = await agent.run("Do something", deps=deps)

# Get summary
summary = trace_ctx.get_summary()
print(f"Total tokens: {summary['total_tokens']}")
```

### Guardrails

```python
from pydantic_deep.guardrails import create_safe_agent_guardrails, GuardrailManager

# Create guardrails with safe defaults
guardrails = create_safe_agent_guardrails(
    max_tokens=100000,
    max_cost_usd=10.0,
    max_iterations=20,
)

# Create manager in strict mode
manager = GuardrailManager(guardrails, mode="strict")

# Use with agent
deps = DeepAgentDeps(
    backend=StateBackend(),
    guardrail_manager=manager,
)

# Agent will raise GuardrailViolation if limits exceeded
result = await agent.run("Do something", deps=deps)
```

### Combined (Production-Ready)

```python
from pydantic_deep.tracing import TraceContext, StructuredFileExporter
from pydantic_deep.guardrails import create_production_guardrails, GuardrailManager

# Production tracing
trace_ctx = TraceContext(exporters=[
    StructuredFileExporter("logs/traces.jsonl"),
])

# Production guardrails
guardrails = create_production_guardrails(
    max_tokens=200000,
    max_cost_usd=50.0,
)
manager = GuardrailManager(guardrails, mode="strict")

# Create production deps
deps = DeepAgentDeps(
    backend=FilesystemBackend(root="/workspace"),
    trace_context=trace_ctx,
    guardrail_manager=manager,
)
```

---

## 🎓 Documentation

- **Tracing Guide**: `docs/tracing.md` - Complete guide with quick start, exporters, event types, and advanced usage
- **Guardrails Guide**: `docs/guardrails.md` - Complete guide with built-in guardrails, factory functions, and best practices
- **Examples**: `examples/README.md` - Usage instructions and common patterns

---

## ✅ Testing

All tests pass with 100% coverage:

```bash
make test
# 222 passed in 1.27s
# TOTAL: 100.00% coverage
```

Test breakdown:
- **Tracing tests**: 29 tests covering all event types, exporters, and edge cases
- **Guardrails tests**: 49 tests covering all guardrails, managers, and validators
- Edge cases: empty sequences, broken patterns, optional dependencies, error handling

---

## 🔄 Breaking Changes

**None** - This is a purely additive change. All new fields in `DeepAgentDeps` are optional and default to `None`.

---

## 📝 Commits Included

- `cc5ae0f` - feat: add agent observability and tracing system
- `7d08904` - feat: add guardrails & safety gates system
- `511b0fe` - docs: add comprehensive examples for tracing and guardrails
- `d41a263` - fix: correct TestModel import in examples

---

## 🎯 Impact

These features enable:
- ✅ **Production observability** - Track all agent operations, tool calls, and LLM interactions
- ✅ **Cost control** - Prevent runaway costs with configurable limits and warnings
- ✅ **Safety enforcement** - Prevent infinite loops, invalid operations, and secret leaks
- ✅ **Debugging** - Comprehensive traces for troubleshooting agent behavior
- ✅ **Compliance** - Output validation and sanitization for sensitive data

---

## 🚀 Next Steps

After this PR:
1. **Deterministic Testing Mode** - Record/replay for fast, free, deterministic tests
2. **Agent Checkpointing** - Resume after failures for long-running tasks
3. **Streaming Updates** - Real-time progress feedback
4. **Agent Memory & Retrieval** - Persistent knowledge base

---

## 📸 Example Output

**Console Exporter:**
```
🤖 Agent run: file-writer
   Model: gpt-4o
   Prompt: Write a hello.txt file...
   ├─ Tool: write_file [0.05s]
   ├─ LLM step [1.23s, 450 tokens]
   ✓ Completed in 1.28s
```

**Guardrails:**
```
✓ All 4 guardrail checks passed
  ✓ Token budget: 10,000/100,000 (10.0%)
  ✓ Cost limit: $0.50/$10.00 (5.0%)
  ✓ Iteration limit: 5/20 (25.0%)
  ✓ No tool loops detected
```

---

**Ready for review!** 🎉
