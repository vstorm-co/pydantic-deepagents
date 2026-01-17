"""Pytest configuration and fixtures."""

import tempfile
from pathlib import Path

import pytest
from pydantic_ai_backends import LocalBackend, StateBackend

from pydantic_deep.deps import DeepAgentDeps


@pytest.fixture
def state_backend():
    """Create a fresh StateBackend."""
    return StateBackend()


@pytest.fixture
def deps(state_backend):
    """Create default DeepAgentDeps with StateBackend."""
    return DeepAgentDeps(backend=state_backend)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def local_backend(temp_dir):
    """Create a LocalBackend with temporary directory."""
    return LocalBackend(temp_dir)
