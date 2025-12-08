"""Session management for Docker sandboxes.

This module provides session management for multi-user applications,
allowing multiple users to have their own isolated Docker containers.

Example:
    ```python
    from pydantic_deep import SessionManager, RuntimeConfig

    # Create a session manager with default runtime
    manager = SessionManager(default_runtime="python-datascience")

    # Get or create a sandbox for a user session
    sandbox = await manager.get_or_create("user-123")

    # Use the sandbox...
    result = sandbox.execute("python script.py")

    # Release when done
    await manager.release("user-123")
    ```
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_deep.backends.sandbox import DockerSandbox
    from pydantic_deep.types import RuntimeConfig


class SessionManager:
    """Manages user sessions and their Docker containers.

    This class provides a way to manage multiple Docker sandbox instances
    for different user sessions. It handles:
    - Creating new sandboxes for new sessions
    - Reusing existing sandboxes for returning sessions
    - Cleaning up idle sessions automatically

    Example:
        ```python
        from pydantic_deep import SessionManager

        manager = SessionManager(default_runtime="python-datascience")

        # Get sandbox for user
        sandbox = await manager.get_or_create("user-123")

        # Later: cleanup idle sessions
        cleaned = await manager.cleanup_idle(max_idle=1800)  # 30 min
        print(f"Cleaned up {cleaned} idle sessions")
        ```
    """

    def __init__(
        self,
        default_runtime: RuntimeConfig | str | None = None,
        default_idle_timeout: int = 3600,
    ):
        """Initialize the session manager.

        Args:
            default_runtime: Default RuntimeConfig or name for new sandboxes.
            default_idle_timeout: Default idle timeout in seconds (default: 1 hour).
        """
        self._sessions: dict[str, DockerSandbox] = {}
        self._default_runtime = default_runtime
        self._default_idle_timeout = default_idle_timeout
        self._cleanup_task: asyncio.Task[None] | None = None

    @property
    def sessions(self) -> dict[str, DockerSandbox]:
        """Active sessions dictionary (read-only access)."""
        return dict(self._sessions)

    @property
    def session_count(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)

    async def get_or_create(
        self,
        session_id: str,
        runtime: RuntimeConfig | str | None = None,
    ) -> DockerSandbox:
        """Get an existing sandbox or create a new one.

        If a sandbox exists for the session_id and is still alive,
        it will be returned. Otherwise, a new sandbox will be created.

        Args:
            session_id: Unique identifier for the session.
            runtime: RuntimeConfig or name to use (defaults to manager's default).

        Returns:
            DockerSandbox instance for the session.

        Raises:
            ValueError: If no runtime specified and no default runtime set.
        """
        from pydantic_deep.backends.sandbox import DockerSandbox

        # Check for existing session
        if session_id in self._sessions:
            sandbox = self._sessions[session_id]
            if sandbox.is_alive():
                sandbox._last_activity = time.time()
                return sandbox
            # Container died, remove from cache
            del self._sessions[session_id]

        # Create new sandbox
        effective_runtime = runtime or self._default_runtime
        sandbox = DockerSandbox(
            runtime=effective_runtime,
            session_id=session_id,
            idle_timeout=self._default_idle_timeout,
        )
        sandbox.start()
        self._sessions[session_id] = sandbox
        return sandbox

    async def release(self, session_id: str) -> bool:
        """Release a session and stop its container.

        Args:
            session_id: Session identifier to release.

        Returns:
            True if session was found and released, False otherwise.
        """
        if session_id not in self._sessions:
            return False

        sandbox = self._sessions.pop(session_id)
        sandbox.stop()
        return True

    async def cleanup_idle(self, max_idle: int | None = None) -> int:
        """Clean up idle sessions.

        Removes and stops sandboxes that have been idle for longer than
        the specified time.

        Args:
            max_idle: Maximum idle time in seconds. Uses default if not specified.

        Returns:
            Number of sessions cleaned up.
        """
        max_idle = max_idle if max_idle is not None else self._default_idle_timeout
        now = time.time()
        to_remove: list[str] = []

        for session_id, sandbox in self._sessions.items():
            if now - sandbox._last_activity > max_idle:
                to_remove.append(session_id)

        for session_id in to_remove:
            await self.release(session_id)

        return len(to_remove)

    def start_cleanup_loop(self, interval: int = 300) -> None:
        """Start background cleanup loop.

        Periodically cleans up idle sessions.

        Args:
            interval: Cleanup interval in seconds (default: 5 minutes).
        """
        if self._cleanup_task is not None:
            return  # Already running

        async def _loop() -> None:  # pragma: no cover
            while True:
                await asyncio.sleep(interval)
                await self.cleanup_idle()

        self._cleanup_task = asyncio.create_task(_loop())

    def stop_cleanup_loop(self) -> None:
        """Stop the background cleanup loop."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None

    async def shutdown(self) -> int:
        """Shutdown all sessions and stop cleanup loop.

        Returns:
            Number of sessions that were stopped.
        """
        self.stop_cleanup_loop()

        count = len(self._sessions)
        session_ids = list(self._sessions.keys())

        for session_id in session_ids:
            await self.release(session_id)

        return count

    def __contains__(self, session_id: str) -> bool:
        """Check if a session exists."""
        return session_id in self._sessions

    def __len__(self) -> int:
        """Return number of active sessions."""
        return len(self._sessions)
