"""Pytest configuration and fixtures."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai_backends import LocalBackend, StateBackend

from pydantic_deep.deps import DeepAgentDeps


@pytest.fixture(autouse=True)
def mock_subagent_agent():
    """Mock the Agent class in subagents_pydantic_ai to avoid needing API keys."""
    mock_agent = MagicMock()
    with patch("subagents_pydantic_ai.toolset.Agent", return_value=mock_agent):
        yield mock_agent


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
