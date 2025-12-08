"""Tests for SessionManager."""

import time
from unittest.mock import MagicMock, patch

import pytest

from pydantic_deep.session import SessionManager
from pydantic_deep.types import RuntimeConfig


class MockDockerSandbox:
    """Mock DockerSandbox for testing SessionManager."""

    def __init__(
        self,
        runtime: RuntimeConfig | str | None = None,
        session_id: str | None = None,
        idle_timeout: int = 3600,
        **kwargs,
    ):
        self._id = session_id or "test-id"
        self._runtime = runtime
        self._idle_timeout = idle_timeout
        self._last_activity = time.time()
        self._alive = True

    @property
    def session_id(self) -> str:
        return self._id

    def is_alive(self) -> bool:
        return self._alive

    def start(self) -> None:
        self._alive = True

    def stop(self) -> None:
        self._alive = False


class TestSessionManager:
    """Tests for SessionManager class."""

    def test_init_defaults(self):
        """Test default initialization."""
        manager = SessionManager()
        assert manager._default_runtime is None
        assert manager._default_idle_timeout == 3600
        assert manager.session_count == 0
        assert len(manager) == 0

    def test_init_with_runtime(self):
        """Test initialization with default runtime."""
        runtime = RuntimeConfig(name="test")
        manager = SessionManager(default_runtime=runtime)
        assert manager._default_runtime is runtime

    def test_init_with_string_runtime(self):
        """Test initialization with runtime name."""
        manager = SessionManager(default_runtime="python-datascience")
        assert manager._default_runtime == "python-datascience"

    def test_init_with_timeout(self):
        """Test initialization with custom timeout."""
        manager = SessionManager(default_idle_timeout=1800)
        assert manager._default_idle_timeout == 1800

    @pytest.mark.asyncio
    async def test_get_or_create_new_session(self):
        """Test creating a new session."""
        manager = SessionManager()

        with patch("pydantic_deep.backends.sandbox.DockerSandbox", MockDockerSandbox):
            sandbox = await manager.get_or_create("user-123")
            assert sandbox.session_id == "user-123"
            assert "user-123" in manager
            assert manager.session_count == 1

    @pytest.mark.asyncio
    async def test_get_or_create_existing_session(self):
        """Test retrieving existing session."""
        manager = SessionManager()

        with patch("pydantic_deep.backends.sandbox.DockerSandbox", MockDockerSandbox):
            sandbox1 = await manager.get_or_create("user-123")
            sandbox2 = await manager.get_or_create("user-123")
            assert sandbox1 is sandbox2
            assert manager.session_count == 1

    @pytest.mark.asyncio
    async def test_get_or_create_dead_session_recreates(self):
        """Test that dead sessions are recreated."""
        manager = SessionManager()

        with patch("pydantic_deep.backends.sandbox.DockerSandbox", MockDockerSandbox):
            sandbox1 = await manager.get_or_create("user-123")
            sandbox1._alive = False  # Simulate container death

            sandbox2 = await manager.get_or_create("user-123")
            assert sandbox1 is not sandbox2
            assert manager.session_count == 1

    @pytest.mark.asyncio
    async def test_release_existing_session(self):
        """Test releasing an existing session."""
        manager = SessionManager()

        with patch("pydantic_deep.backends.sandbox.DockerSandbox", MockDockerSandbox):
            await manager.get_or_create("user-123")
            assert manager.session_count == 1

            result = await manager.release("user-123")
            assert result is True
            assert manager.session_count == 0
            assert "user-123" not in manager

    @pytest.mark.asyncio
    async def test_release_nonexistent_session(self):
        """Test releasing a non-existent session."""
        manager = SessionManager()
        result = await manager.release("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_idle_sessions(self):
        """Test cleaning up idle sessions."""
        manager = SessionManager(default_idle_timeout=10)

        with patch("pydantic_deep.backends.sandbox.DockerSandbox", MockDockerSandbox):
            sandbox1 = await manager.get_or_create("user-1")
            sandbox2 = await manager.get_or_create("user-2")

            # Make one session idle
            sandbox1._last_activity = time.time() - 20  # 20 seconds ago
            sandbox2._last_activity = time.time()  # Just now

            cleaned = await manager.cleanup_idle(max_idle=10)
            assert cleaned == 1
            assert manager.session_count == 1
            assert "user-1" not in manager
            assert "user-2" in manager

    @pytest.mark.asyncio
    async def test_cleanup_idle_uses_default_timeout(self):
        """Test cleanup uses default timeout when not specified."""
        manager = SessionManager(default_idle_timeout=5)

        with patch("pydantic_deep.backends.sandbox.DockerSandbox", MockDockerSandbox):
            sandbox = await manager.get_or_create("user-1")
            sandbox._last_activity = time.time() - 10  # 10 seconds ago

            cleaned = await manager.cleanup_idle()
            assert cleaned == 1

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """Test shutting down all sessions."""
        manager = SessionManager()

        with patch("pydantic_deep.backends.sandbox.DockerSandbox", MockDockerSandbox):
            await manager.get_or_create("user-1")
            await manager.get_or_create("user-2")
            await manager.get_or_create("user-3")
            assert manager.session_count == 3

            count = await manager.shutdown()
            assert count == 3
            assert manager.session_count == 0

    def test_sessions_property(self):
        """Test sessions property returns copy."""
        manager = SessionManager()
        manager._sessions["test"] = MagicMock()  # type: ignore

        sessions = manager.sessions
        assert "test" in sessions
        # Verify it's a copy
        sessions["new"] = MagicMock()  # type: ignore
        assert "new" not in manager._sessions

    def test_contains(self):
        """Test __contains__ method."""
        manager = SessionManager()
        manager._sessions["test"] = MagicMock()  # type: ignore

        assert "test" in manager
        assert "other" not in manager

    def test_len(self):
        """Test __len__ method."""
        manager = SessionManager()
        assert len(manager) == 0

        manager._sessions["a"] = MagicMock()  # type: ignore
        manager._sessions["b"] = MagicMock()  # type: ignore
        assert len(manager) == 2

    def test_start_cleanup_loop(self):
        """Test starting cleanup loop."""
        manager = SessionManager()
        assert manager._cleanup_task is None

        # We can't actually test the async loop without running it,
        # but we can verify it's created
        with patch("asyncio.create_task") as mock_create_task:
            manager.start_cleanup_loop(interval=60)
            mock_create_task.assert_called_once()

        # Calling again should do nothing
        with patch("asyncio.create_task") as mock_create_task:
            manager._cleanup_task = MagicMock()  # type: ignore
            manager.start_cleanup_loop()
            mock_create_task.assert_not_called()

    def test_stop_cleanup_loop(self):
        """Test stopping cleanup loop."""
        manager = SessionManager()
        mock_task = MagicMock()
        manager._cleanup_task = mock_task

        manager.stop_cleanup_loop()
        mock_task.cancel.assert_called_once()
        assert manager._cleanup_task is None

    def test_stop_cleanup_loop_when_not_running(self):
        """Test stopping cleanup loop when not running."""
        manager = SessionManager()
        manager.stop_cleanup_loop()  # Should not raise
        assert manager._cleanup_task is None
