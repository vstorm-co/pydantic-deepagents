# Deterministic Testing Mode

The testing module provides record/replay capabilities for LLM interactions, enabling **fast**, **free**, and **deterministic** tests.

## Problem Statement

Testing agents with real LLMs is:
- **Slow** - Each test takes 2-30 seconds waiting for API responses
- **Expensive** - Tests cost $0.01-$0.50 per run
- **Flaky** - Non-deterministic responses cause test failures
- **Rate-limited** - Can't run hundreds of tests in parallel

## Solution: Record/Replay

**Record mode**: Run tests once with real LLM, capture all responses to fixture files
**Replay mode**: Run tests with recorded responses - 100x faster, $0 cost, deterministic

```python
# Without testing mode: Slow, expensive, flaky
agent = create_deep_agent(model="openai:gpt-4o")
result = await agent.run("Create hello.txt", deps=deps)
# Cost: $0.05, Time: 2s, Deterministic: No

# With replay mode: Fast, free, deterministic!
from pydantic_deep.testing import replay_mode

with replay_mode("tests/fixtures/create_file.json"):
    agent = create_deep_agent(model="test")
    result = await agent.run("Create hello.txt", deps=deps)
# Cost: $0, Time: 0.02s, Deterministic: Yes ✓
```

---

## Quick Start

### 1. Record Mode - Capture LLM Responses

```python
import asyncio
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_deep.testing import record_mode
from pydantic_ai_backends import StateBackend

async def test_create_file_record():
    """Record LLM interactions to fixture."""
    with record_mode(
        fixture_file="tests/fixtures/create_file.json",
        model="openai:gpt-4o",
        description="Test creating a file",
    ):
        agent = create_deep_agent(model="openai:gpt-4o")
        deps = DeepAgentDeps(backend=StateBackend())

        result = await agent.run(
            "Create a file called hello.txt with 'Hello, World!'",
            deps=deps
        )

        # Verify result
        assert "hello.txt" in result.output

# Run once to create fixture
asyncio.run(test_create_file_record())
# ✓ Saved 3 interactions to tests/fixtures/create_file.json
```

### 2. Replay Mode - Use Recorded Responses

```python
async def test_create_file_replay():
    """Replay recorded interactions (fast, free, deterministic)."""
    with replay_mode("tests/fixtures/create_file.json"):
        agent = create_deep_agent(model="test")  # Model doesn't matter
        deps = DeepAgentDeps(backend=StateBackend())

        result = await agent.run(
            "Create a file called hello.txt with 'Hello, World!'",
            deps=deps
        )

        # Same assertions as record mode
        assert "hello.txt" in result.output

# Run in CI/CD - 100x faster, $0 cost
asyncio.run(test_create_file_replay())
# ✓ Loaded 3 interactions from tests/fixtures/create_file.json
```

---

## Core Concepts

### Fixture Files

Fixtures are JSON files containing recorded LLM interactions:

```json
{
  "version": "1.0",
  "model": "openai:gpt-4o",
  "description": "Test creating a file",
  "total_interactions": 3,
  "total_tokens": 450,
  "interactions": [
    {
      "interaction_id": 0,
      "duration_seconds": 1.23,
      "request": {
        "timestamp": "2026-01-04T18:00:00",
        "model": "gpt-4o",
        "messages_count": 2,
        "tools_count": 5,
        "messages": [...],
        "tools": [...],
        "request_hash": "a1b2c3d4e5f6g7h8"
      },
      "response": {
        "timestamp": "2026-01-04T18:00:01",
        "model": "gpt-4o",
        "finish_reason": "tool_calls",
        "tool_calls": [...],
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150
      }
    }
  ]
}
```

### Request Matching

During replay, requests are matched by **hash** (SHA256 of messages + tools):
- **Strict mode** (default): Raises error if request doesn't match
- **Permissive mode**: Warns but uses recorded response anyway

```python
# Strict mode - raises on mismatch
with replay_mode("fixture.json", strict=True):
    result = await agent.run("Different prompt")  # ReplayMismatchError!

# Permissive mode - warns but continues
with replay_mode("fixture.json", strict=False):
    result = await agent.run("Different prompt")  # ⚠️ Warning, but uses response
```

---

## API Reference

### record_mode()

Context manager for recording LLM interactions.

```python
from pydantic_deep.testing import record_mode

with record_mode(
    fixture_file="tests/fixtures/test.json",
    model="openai:gpt-4o",
    description="Test description",
) as recorder:
    # Run your agent
    result = await agent.run("Do something", deps=deps)
```

**Parameters:**
- `fixture_file` - Path to fixture file (will be created)
- `model` - Model name for metadata
- `description` - Description of the fixture

**Returns:** `Recorder` instance

### replay_mode()

Context manager for replaying LLM interactions.

```python
from pydantic_deep.testing import replay_mode

with replay_mode(
    fixture_file="tests/fixtures/test.json",
    strict=True,
) as replayer:
    # Run your agent (responses come from fixture)
    result = await agent.run("Do something", deps=deps)
```

**Parameters:**
- `fixture_file` - Path to fixture file
- `strict` - If True, raise on request mismatch (default: True)

**Returns:** `Replayer` instance

### Recorder Class

Low-level recording API.

```python
from pydantic_deep.testing import Recorder

recorder = Recorder("tests/fixtures/test.json", model="gpt-4o")

# Record request
request = recorder.record_request(
    messages=[{"role": "user", "content": "Hello"}],
    tools=[...],
)

# Record response
response = recorder.record_response(
    content="Hello back!",
    total_tokens=150,
)

# Record interaction
recorder.record_interaction(request, response, duration_seconds=1.5)

# Save to file
recorder.save(description="Test fixture")
```

### Replayer Class

Low-level replay API.

```python
from pydantic_deep.testing import Replayer

replayer = Replayer("tests/fixtures/test.json", strict=True)

# Replay response for request
response = replayer.replay(
    messages=[{"role": "user", "content": "Hello"}],
    tools=[...],
)

# Get statistics
stats = replayer.get_stats()
# {'total_interactions': 5, 'replayed': 2, 'remaining': 3}

# Reset to beginning
replayer.reset()
```

### validate_fixture()

Validate and inspect a fixture file.

```python
from pydantic_deep.testing import validate_fixture

info = validate_fixture("tests/fixtures/test.json")
# {
#   'version': '1.0',
#   'model': 'gpt-4o',
#   'total_interactions': 5,
#   'total_tokens': 450,
#   'created_at': '2026-01-04T18:00:00',
#   'description': 'Test fixture'
# }
```

---

## Testing Patterns

### Pattern 1: pytest Fixtures

```python
import pytest
from pydantic_deep.testing import record_mode, replay_mode

@pytest.fixture
def fixture_file(request):
    """Determine fixture file based on test name."""
    test_name = request.node.name
    return f"tests/fixtures/{test_name}.json"

def test_create_file(fixture_file):
    """Test with automatic fixture naming."""
    # Use RECORD=1 pytest ... to record
    # Use normal pytest ... to replay
    import os
    mode = record_mode if os.getenv("RECORD") else replay_mode

    with mode(fixture_file):
        agent = create_deep_agent(model="openai:gpt-4o")
        result = await agent.run("Create hello.txt", deps=deps)
        assert "hello.txt" in result.output
```

### Pattern 2: Separate Record/Replay Tests

```python
# test_agent_record.py - Run manually to update fixtures
async def test_create_file_record():
    with record_mode("tests/fixtures/create_file.json"):
        agent = create_deep_agent(model="openai:gpt-4o")
        result = await agent.run("Create hello.txt", deps=deps)
        assert "hello.txt" in result.output

# test_agent.py - Run in CI/CD
async def test_create_file():
    with replay_mode("tests/fixtures/create_file.json"):
        agent = create_deep_agent(model="test")
        result = await agent.run("Create hello.txt", deps=deps)
        assert "hello.txt" in result.output
```

### Pattern 3: Conditional Recording

```python
import os
from pydantic_deep.testing import record_mode, replay_mode

def get_test_mode(fixture_file):
    """Auto-detect record vs replay mode."""
    if os.getenv("RECORD"):
        return record_mode(fixture_file, model="openai:gpt-4o")
    else:
        return replay_mode(fixture_file)

async def test_agent():
    with get_test_mode("tests/fixtures/test.json"):
        result = await agent.run("Do something", deps=deps)
        assert result.output
```

---

## Best Practices

### 1. One Fixture Per Test

✅ **Good** - Clear, focused, easy to maintain:
```python
def test_create_file():
    with replay_mode("fixtures/test_create_file.json"):
        ...

def test_delete_file():
    with replay_mode("fixtures/test_delete_file.json"):
        ...
```

❌ **Bad** - Shared fixtures are brittle:
```python
def test_create_file():
    with replay_mode("fixtures/shared.json"):  # Which interaction?
        ...
```

### 2. Version Control Fixtures

Commit fixtures to git for:
- ✅ Reproducible tests across team
- ✅ Historical record of agent behavior
- ✅ Catch regressions in agent logic

### 3. Update Fixtures When Prompts Change

When you change prompts, re-record:
```bash
# Re-record all fixtures
RECORD=1 pytest tests/

# Re-record specific test
RECORD=1 pytest tests/test_agent.py::test_create_file
```

### 4. Use Descriptive Names

```python
# Good - Clear what's being tested
with record_mode("fixtures/test_create_file_with_permissions.json"):
    ...

# Bad - Unclear
with record_mode("fixtures/test1.json"):
    ...
```

### 5. Validate Fixtures in CI

```python
# In your CI pipeline
from pydantic_deep.testing import validate_fixture

def test_fixtures_valid():
    """Ensure all fixtures are valid."""
    import glob

    for fixture_file in glob.glob("tests/fixtures/**/*.json"):
        info = validate_fixture(fixture_file)
        assert info["version"] == "1.0"
```

---

## Advanced Usage

### Custom Model Wrappers

Integrate with your existing model wrapper:

```python
from pydantic_deep.testing import get_current_recorder, get_current_replayer

class MyModelWrapper:
    async def call_llm(self, messages, tools):
        # Check if recording
        recorder = get_current_recorder()
        if recorder:
            request = recorder.record_request(messages, tools)
            response = await self._real_llm_call(messages, tools)
            recorder.record_interaction(request, response, duration=1.0)
            return response

        # Check if replaying
        replayer = get_current_replayer()
        if replayer:
            return replayer.replay(messages, tools)

        # Normal operation
        return await self._real_llm_call(messages, tools)
```

### Debugging Mismatches

When strict mode raises `ReplayMismatchError`:

```python
try:
    with replay_mode("fixture.json", strict=True):
        result = await agent.run("Task", deps=deps)
except ReplayMismatchError as e:
    print(e)
    # Request mismatch at interaction 0:
    #   Expected hash: a1b2c3d4
    #   Actual hash: x9y8z7w6
    #   Expected 3 messages, 5 tools
    #   Got 3 messages, 4 tools

    # Solution: Re-record the fixture
```

### Partial Replay

Use permissive mode for partial replays:

```python
# Record with 5 interactions
with record_mode("fixture.json"):
    for i in range(5):
        result = await agent.run(f"Task {i}", deps=deps)

# Replay only 3
with replay_mode("fixture.json", strict=False):
    for i in range(3):  # Only uses 3 of 5
        result = await agent.run(f"Task {i}", deps=deps)
# ⚠️ Warning: 2 interactions not replayed
```

---

## Troubleshooting

### Issue: Request Mismatch Errors

**Problem:** `ReplayMismatchError: Request mismatch at interaction 0`

**Solutions:**
1. Re-record the fixture (prompt or tools changed)
2. Use permissive mode during debugging
3. Check that tool definitions match exactly

### Issue: Fixture Not Found

**Problem:** `FixtureValidationError: Fixture file not found`

**Solutions:**
1. Run in record mode first to create fixture
2. Check fixture path is correct
3. Ensure fixture is committed to git

### Issue: Invalid Fixture Version

**Problem:** `FixtureValidationError: Unsupported fixture version: 2.0`

**Solutions:**
1. Re-record fixture with current version
2. Update pydantic-deep to latest version

### Issue: Slow Recording

**Problem:** Recording takes too long

**Solutions:**
1. Record once, replay many times
2. Only record when prompts/tools change
3. Use smaller test cases for recording

---

## Performance Comparison

| Mode | Speed | Cost | Deterministic |
|------|-------|------|---------------|
| Real LLM | 2-30s | $0.01-$0.50 | ❌ No |
| Replay | 0.02s | $0 | ✅ Yes |

**Speedup:** 100-1500x faster
**Cost Savings:** 100% (free)
**Reliability:** Deterministic results

---

## Migration Guide

### From TestModel to Replay Mode

**Before:**
```python
from pydantic_ai.models.test import TestModel

agent = create_deep_agent(model=TestModel())
result = await agent.run("Create file", deps=deps)
# Returns dummy response
```

**After:**
```python
from pydantic_deep.testing import record_mode, replay_mode

# Record once with real model
with record_mode("fixtures/create_file.json"):
    agent = create_deep_agent(model="openai:gpt-4o")
    result = await agent.run("Create file", deps=deps)

# Use in tests - real responses, fast and free!
with replay_mode("fixtures/create_file.json"):
    agent = create_deep_agent(model="test")
    result = await agent.run("Create file", deps=deps)
```

---

## Examples

See `examples/deterministic_testing.py` for complete working examples.

## API Documentation

See [API Reference](api/testing.md) for detailed API documentation.
