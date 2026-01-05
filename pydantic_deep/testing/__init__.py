"""Deterministic testing infrastructure for agents.

This module provides record/replay capabilities for LLM interactions,
enabling fast, free, and deterministic tests.

Example:
    ```python
    from pydantic_deep.testing import record_mode, replay_mode

    # Record mode: Capture LLM responses to fixture
    with record_mode("tests/fixtures/create_file.json"):
        agent = create_deep_agent(model="openai:gpt-4o")
        result = await agent.run("Create hello.txt", deps=deps)

    # Replay mode: Use recorded responses (fast, free, deterministic)
    with replay_mode("tests/fixtures/create_file.json"):
        agent = create_deep_agent(model="test")
        result = await agent.run("Create hello.txt", deps=deps)
        # Same result as recording, but 100x faster and free!
    ```
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from pydantic_deep.testing.recorder import Recorder
from pydantic_deep.testing.replayer import Replayer
from pydantic_deep.testing.types import (
    FixtureFile,
    FixtureValidationError,
    RecordedInteraction,
    RecordedRequest,
    RecordedResponse,
    RecordMode,
    ReplayMismatchError,
)

__all__ = [
    # Core classes
    "Recorder",
    "Replayer",
    # Types
    "RecordedRequest",
    "RecordedResponse",
    "RecordedInteraction",
    "FixtureFile",
    "RecordMode",
    # Exceptions
    "FixtureValidationError",
    "ReplayMismatchError",
    # Convenience functions
    "record_mode",
    "replay_mode",
    "create_fixture",
    "validate_fixture",
]


# Global state for recording/replay
_current_recorder: Recorder | None = None
_current_replayer: Replayer | None = None


def get_current_recorder() -> Recorder | None:
    """Get the currently active recorder.

    Returns:
        Active recorder or None.
    """
    return _current_recorder


def get_current_replayer() -> Replayer | None:
    """Get the currently active replayer.

    Returns:
        Active replayer or None.
    """
    return _current_replayer


@contextmanager
def record_mode(
    fixture_file: str | Path,
    model: str = "openai:gpt-4o",
    description: str = "",
) -> Iterator[Recorder]:
    """Context manager for recording LLM interactions.

    Args:
        fixture_file: Path to fixture file (will be created).
        model: Model name for metadata.
        description: Description of the fixture.

    Yields:
        Recorder instance.

    Example:
        ```python
        with record_mode("tests/fixtures/test.json"):
            agent = create_deep_agent(model="openai:gpt-4o")
            result = await agent.run("Do something", deps=deps)
        ```
    """
    global _current_recorder

    recorder = Recorder(fixture_file, model=model)
    _current_recorder = recorder

    try:
        yield recorder
    finally:
        recorder.save(description=description)
        _current_recorder = None


@contextmanager
def replay_mode(
    fixture_file: str | Path,
    strict: bool = True,
) -> Iterator[Replayer]:
    """Context manager for replaying LLM interactions.

    Args:
        fixture_file: Path to fixture file.
        strict: If True, raise on request mismatch.

    Yields:
        Replayer instance.

    Example:
        ```python
        with replay_mode("tests/fixtures/test.json"):
            agent = create_deep_agent(model="test")
            result = await agent.run("Do something", deps=deps)
        ```
    """
    global _current_replayer

    replayer = Replayer(fixture_file, strict=strict)
    _current_replayer = replayer

    try:
        yield replayer
    finally:
        stats = replayer.get_stats()
        if stats["remaining"] > 0:
            print(
                f"⚠️  Warning: {stats['remaining']} interactions not replayed "
                f"({stats['replayed']}/{stats['total_interactions']} used)"
            )
        _current_replayer = None


def create_fixture(
    fixture_file: str | Path,
    model: str,
    description: str = "",
) -> Recorder:
    """Create a new fixture file.

    Args:
        fixture_file: Path to fixture file.
        model: Model name.
        description: Description of the fixture.

    Returns:
        Recorder instance.
    """
    return Recorder(fixture_file, model=model)


def validate_fixture(fixture_file: str | Path) -> dict[str, Any]:
    """Validate and get info about a fixture file.

    Args:
        fixture_file: Path to fixture file.

    Returns:
        Dictionary with fixture info.

    Raises:
        FixtureValidationError: If fixture is invalid.
    """
    import json

    path = Path(fixture_file)

    if not path.exists():
        raise FixtureValidationError(f"Fixture file not found: {path}")

    with open(path) as f:
        fixture_dict = json.load(f)

    # Validate version
    version = fixture_dict.get("version", "unknown")
    if version != "1.0":
        raise FixtureValidationError(f"Unsupported fixture version: {version} (expected 1.0)")

    return {
        "version": fixture_dict["version"],
        "model": fixture_dict.get("model", "unknown"),
        "total_interactions": fixture_dict.get("total_interactions", 0),
        "total_tokens": fixture_dict.get("total_tokens", 0),
        "created_at": fixture_dict.get("created_at", "unknown"),
        "description": fixture_dict.get("description", ""),
    }
