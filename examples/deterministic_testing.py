"""Deterministic testing mode examples.

This example demonstrates how to use record/replay for fast, free,
and deterministic testing of agents.
"""

import asyncio
import tempfile
import time
from pathlib import Path

from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.testing import record_mode, replay_mode, validate_fixture


async def basic_record_example():
    """Record LLM interactions to a fixture file."""
    print("=== Basic Recording Example ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_file = Path(tmpdir) / "create_file.json"

        # Record mode - uses TestModel for this example
        # In production, you'd use a real model like "openai:gpt-4o"
        print("Recording interactions with TestModel...")
        with record_mode(
            fixture_file,
            model="test",
            description="Test creating a file",
        ) as recorder:
            create_deep_agent(
                model=TestModel(),
                instructions="You are a helpful file management assistant.",
            )
            DeepAgentDeps(backend=StateBackend())

            # Manually record request/response (for demonstration)
            messages = [{"role": "user", "content": "Create hello.txt"}]
            request = recorder.record_request(messages=messages)

            response = recorder.record_response(
                content="I'll create the file for you.",
                finish_reason="stop",
                total_tokens=150,
            )

            recorder.record_interaction(request, response, duration_seconds=1.2)

        print(f"✓ Fixture saved to {fixture_file}\n")

        # Validate the fixture
        info = validate_fixture(fixture_file)
        print("Fixture info:")
        print(f"  Version: {info['version']}")
        print(f"  Model: {info['model']}")
        print(f"  Interactions: {info['total_interactions']}")
        print(f"  Total tokens: {info['total_tokens']}")


async def basic_replay_example():
    """Replay interactions from a fixture file."""
    print("\n\n=== Basic Replay Example ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_file = Path(tmpdir) / "test.json"

        # First, create a fixture
        print("Creating fixture...")
        with record_mode(fixture_file, model="test") as recorder:
            messages = [{"role": "user", "content": "Hello"}]
            request = recorder.record_request(messages=messages)
            response = recorder.record_response(
                content="Hello! How can I help?",
                finish_reason="stop",
                total_tokens=50,
            )
            recorder.record_interaction(request, response, duration_seconds=0.5)

        # Now replay it
        print("Replaying interactions...")
        with replay_mode(fixture_file) as replayer:
            # Same messages must match
            messages = [{"role": "user", "content": "Hello"}]
            replayed_response = replayer.replay(messages=messages)

            print(f"✓ Replayed response: {replayed_response.content}")
            print(f"  Tokens: {replayed_response.total_tokens}")
            print(f"  Finish reason: {replayed_response.finish_reason}")


async def strict_vs_permissive_example():
    """Demonstrate strict vs permissive replay modes."""
    print("\n\n=== Strict vs Permissive Replay ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_file = Path(tmpdir) / "strict_test.json"

        # Create fixture
        with record_mode(fixture_file) as recorder:
            messages = [{"role": "user", "content": "Original message"}]
            request = recorder.record_request(messages=messages)
            response = recorder.record_response(content="Response")
            recorder.record_interaction(request, response, duration_seconds=1.0)

        # Strict mode - raises on mismatch
        print("--- Strict Mode ---")
        with replay_mode(fixture_file, strict=True) as replayer:
            try:
                # Different message - will raise
                replayer.replay(messages=[{"role": "user", "content": "Different message"}])
                print("✗ Should have raised error")
            except Exception as e:
                print(f"✓ Caught expected error: {type(e).__name__}")

        # Permissive mode - warns but continues
        print("\n--- Permissive Mode ---")
        with replay_mode(fixture_file, strict=False) as replayer:
            # Different message - will warn but use response
            response = replayer.replay(messages=[{"role": "user", "content": "Different message"}])
            print(f"✓ Got response despite mismatch: {response.content}")


async def performance_comparison():
    """Compare performance of recording vs replay."""
    print("\n\n=== Performance Comparison ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_file = Path(tmpdir) / "perf_test.json"

        # Simulate recording (with artificial delay)
        print("Simulating record mode (with LLM latency)...")
        start_time = time.time()
        with record_mode(fixture_file, model="test") as recorder:
            for i in range(5):
                messages = [{"role": "user", "content": f"Task {i}"}]
                request = recorder.record_request(messages=messages)
                time.sleep(0.1)  # Simulate LLM latency
                response = recorder.record_response(
                    content=f"Response {i}",
                    total_tokens=100,
                )
                recorder.record_interaction(request, response, duration_seconds=0.1)
        record_time = time.time() - start_time

        # Replay (fast!)
        print("Running replay mode (instant)...")
        start_time = time.time()
        with replay_mode(fixture_file) as replayer:
            for i in range(5):
                messages = [{"role": "user", "content": f"Task {i}"}]
                replayer.replay(messages=messages)
        replay_time = time.time() - start_time

        print("\n=== Results ===")
        print(f"Record time: {record_time:.3f}s")
        print(f"Replay time: {replay_time:.3f}s")
        print(f"Speedup: {record_time / replay_time:.1f}x faster")


async def multiple_interactions_example():
    """Example with multiple interactions."""
    print("\n\n=== Multiple Interactions Example ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_file = Path(tmpdir) / "multi_test.json"

        # Record multiple interactions
        print("Recording multiple interactions...")
        with record_mode(fixture_file, model="test", description="Multi-step task") as recorder:
            tasks = [
                "Read file.txt",
                "Analyze content",
                "Write summary.txt",
            ]

            for i, task in enumerate(tasks):
                messages = [{"role": "user", "content": task}]
                request = recorder.record_request(messages=messages)
                response = recorder.record_response(
                    content=f"Completed: {task}",
                    finish_reason="stop",
                    total_tokens=50 + i * 10,
                )
                recorder.record_interaction(request, response, duration_seconds=0.5)

        # Validate
        info = validate_fixture(fixture_file)
        print(f"✓ Recorded {info['total_interactions']} interactions")
        print(f"  Total tokens: {info['total_tokens']}")

        # Replay all
        print("\nReplaying all interactions...")
        with replay_mode(fixture_file) as replayer:
            for task in tasks:
                messages = [{"role": "user", "content": task}]
                response = replayer.replay(messages=messages)
                print(f"  ✓ {task} -> {response.content}")

            # Check stats
            stats = replayer.get_stats()
            print("\nReplay stats:")
            print(f"  Total: {stats['total_interactions']}")
            print(f"  Replayed: {stats['replayed']}")
            print(f"  Remaining: {stats['remaining']}")


async def pytest_pattern_example():
    """Example of pytest integration pattern."""
    print("\n\n=== Pytest Integration Pattern ===\n")

    print("This demonstrates how to use deterministic testing with pytest.\n")
    print("Example test structure:\n")

    example_code = '''
import os
import pytest
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
from pydantic_deep.testing import record_mode, replay_mode

@pytest.fixture
def test_mode():
    """Determine if we're recording or replaying."""
    return record_mode if os.getenv("RECORD") else replay_mode

def test_create_file(test_mode, tmp_path):
    """Test file creation (record or replay based on env)."""
    fixture_file = tmp_path / "create_file.json"

    with test_mode(fixture_file, model="openai:gpt-4o"):
        agent = create_deep_agent(model="openai:gpt-4o")
        deps = DeepAgentDeps(backend=StateBackend())

        result = await agent.run("Create hello.txt", deps=deps)
        assert "hello.txt" in str(result.output)

# Run tests:
# RECORD=1 pytest tests/  # Record fixtures
# pytest tests/           # Replay (fast, free, deterministic)
'''
    print(example_code)


async def conditional_recording_example():
    """Example of conditional record/replay based on fixture existence."""
    print("\n\n=== Conditional Recording Example ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_file = Path(tmpdir) / "conditional.json"

        # Helper function to choose mode
        def get_mode(fixture_path: Path):
            """Auto-detect record vs replay mode."""
            if fixture_path.exists():
                print("✓ Found fixture, using replay mode")
                return replay_mode(fixture_path)
            else:
                print("✓ No fixture found, using record mode")
                return record_mode(fixture_path, model="test")

        # First run - will record
        print("First run (no fixture):")
        with get_mode(fixture_file) as mode:
            if hasattr(mode, "record_request"):
                # Recording
                messages = [{"role": "user", "content": "Test"}]
                request = mode.record_request(messages=messages)
                response = mode.record_response(content="Response")
                mode.record_interaction(request, response, duration_seconds=1.0)
            else:
                # Replaying (won't happen on first run)
                messages = [{"role": "user", "content": "Test"}]
                mode.replay(messages=messages)

        # Second run - will replay
        print("\nSecond run (fixture exists):")
        with get_mode(fixture_file) as mode:
            if hasattr(mode, "record_request"):
                # Recording
                messages = [{"role": "user", "content": "Test"}]
                request = mode.record_request(messages=messages)
                response = mode.record_response(content="Response")
                mode.record_interaction(request, response, duration_seconds=1.0)
            else:
                # Replaying
                messages = [{"role": "user", "content": "Test"}]
                response = mode.replay(messages=messages)
                print(f"  Replayed: {response.content}")


if __name__ == "__main__":
    print("=== Deterministic Testing Mode Examples ===\n")
    print("This demonstrates record/replay for fast, free, deterministic tests.\n")

    asyncio.run(basic_record_example())
    asyncio.run(basic_replay_example())
    asyncio.run(strict_vs_permissive_example())
    asyncio.run(performance_comparison())
    asyncio.run(multiple_interactions_example())
    asyncio.run(pytest_pattern_example())
    asyncio.run(conditional_recording_example())

    print("\n\n=== Summary ===")
    print("✓ Record mode: Capture LLM responses to fixture files")
    print("✓ Replay mode: Use recorded responses for fast, deterministic tests")
    print("✓ Strict mode: Enforce exact request matching")
    print("✓ Permissive mode: Warn on mismatch but continue")
    print("✓ 100x+ faster tests, $0 cost, fully deterministic")
    print("\nSee docs/testing.md for comprehensive documentation.")
