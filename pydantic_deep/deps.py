"""Dependency injection container for deep agents."""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pydantic_ai.workspaces import Workspace
    from pydantic_ai_shields import CostTracking
    from pydantic_ai_summarization import ContextManagerCapability

    from pydantic_deep.features.checkpointing import CheckpointStore
    from pydantic_deep.features.forking.coordinator import ForkCoordinator
    from pydantic_deep.features.message_queue import MessageQueue
    from pydantic_deep.features.monitoring import MonitorManager
    from pydantic_deep.features.plan.toolset import PlanOption

    #: Interactive-question callback used by the plan `ask_user` tool.
    AskUserCallback = Callable[[str, list[PlanOption]], "str | Awaitable[str]"]

import chardet
from pydantic_ai.usage import UsageLimits

from pydantic_deep.types import Todo, UploadedFile

DEFAULT_UPLOAD_DIR = "uploads"
"""Where uploaded files land, relative to the workspace's working directory."""


#: pydantic-ai's default `request_limit=50` is too low for autonomous agents
#: that routinely need 50-200+ requests on complex tasks.
DEFAULT_USAGE_LIMITS = UsageLimits(request_limit=None)


@dataclass
class DeepAgentDeps:
    """Dependencies for deep agents.

    This container holds all the state and resources needed by the agent
    and its tools during execution. Files are not part of it: they live in the
    run's workspace, `ctx.workspace`, which a workspace capability supplies.

    Attributes:
        todos: Task list for planning
        subagents: Pre-configured subagents available for delegation
        checkpoint_store: Per-session checkpoint store (e.g. InMemoryCheckpointStore).
            When set, overrides the global store passed to `create_deep_agent()`.
    """

    todos: list[Todo] = field(default_factory=list)
    subagents: dict[str, Any] = field(default_factory=dict)  # Agent instances
    uploads: dict[str, UploadedFile] = field(default_factory=dict)  # Uploaded files metadata
    ask_user: AskUserCallback | None = field(default=None, repr=False)
    context_middleware: ContextManagerCapability | None = field(default=None, repr=False)
    share_todos: bool = False  # When True, subagents share parent's todo list
    checkpoint_store: CheckpointStore | None = field(default=None, repr=False)
    message_queue: MessageQueue | None = field(default=None, repr=False)
    monitor_manager: MonitorManager | None = field(default=None, repr=False)
    fork_coordinator: ForkCoordinator | None = field(default=None, repr=False)
    _fork_depth: int = field(default=0, repr=False)
    _branch_cost_tracking: CostTracking | None = field(default=None, repr=False)
    _branch_id: str | None = field(default=None, repr=False)
    _parent_fork_coordinator: ForkCoordinator | None = field(default=None, repr=False)
    _pending_uploads: dict[str, bytes] = field(default_factory=dict, repr=False)

    def get_todo_prompt(self) -> str:
        """Generate system prompt section for todos.

        Ids are included so the model can address a task with
        `update_todo_status` without re-reading the list.
        """
        if not self.todos:
            return ""

        lines = ["## Current Todos"]
        for todo in self.todos:
            status_icon = {
                "pending": "[ ]",
                "in_progress": "[*]",
                "completed": "[x]",
                "blocked": "[!]",
            }.get(todo.status, "[ ]")
            lines.append(f"- {status_icon} [{todo.id}] {todo.content}")

        return "\n".join(lines)

    def get_subagents_summary(self) -> str:
        """Generate summary of available subagents."""
        if not self.subagents:
            return ""

        lines = ["## Available Subagents"]
        for name in sorted(self.subagents.keys()):
            lines.append(f"- {name}")

        return "\n".join(lines)

    async def upload_file(
        self,
        name: str,
        content: bytes,
        *,
        upload_dir: str = DEFAULT_UPLOAD_DIR,
    ) -> str:
        """Upload a file for the next run and track it.

        The bytes are held here and written to the run's workspace when the
        run starts, by `write_pending_uploads`: a workspace is attached to a
        run, so before one starts there is nowhere to write them. The metadata
        is recorded now for display in the system prompt.

        Args:
            name: Original filename (e.g., "sales.csv")
            content: File content as bytes
            upload_dir: Directory to store uploads, relative to the workspace's
                working directory (default: "uploads")

        Returns:
            The path the file will be stored at (e.g., "uploads/sales.csv")

        Example:
            ```python
            deps = DeepAgentDeps()
            path = await deps.upload_file("data.csv", csv_bytes)
            # The agent finds it at uploads/data.csv in its workspace
            ```
        """
        path = f"{upload_dir.rstrip('/')}/{name}"
        self._pending_uploads[path] = content

        line_count = None
        is_text = False

        # Detect encoding
        detection = chardet.detect(content)
        encoding = detection.get("encoding")
        if encoding:
            try:
                text = content.decode(encoding)
                line_count = len(text.splitlines())
                is_text = True
            except (UnicodeDecodeError, LookupError):  # pragma: no cover
                pass  # Binary file or unknown encoding

        # Track metadata
        self.uploads[path] = UploadedFile(
            name=name,
            path=path,
            size=len(content),
            line_count=line_count,
            mime_type=mimetypes.guess_type(name)[0],
            encoding=encoding if is_text and encoding else "binary",
        )

        return path

    async def upload_files(
        self,
        files: list[tuple[str, bytes]],
        *,
        upload_dir: str = DEFAULT_UPLOAD_DIR,
    ) -> list[str]:
        """Upload multiple files for the next run.

        Each file is recorded independently - a failure on one file doesn't
        affect others, and is logged and skipped.

        Args:
            files: List of (filename, content) tuples.
            upload_dir: Directory to store uploads (default: "uploads").

        Returns:
            List of paths for successfully uploaded files.

        Example:
            ```python
            deps = DeepAgentDeps()
            paths = await deps.upload_files([
                ("data.csv", csv_bytes),
                ("config.json", json_bytes),
            ])
            ```
        """
        paths: list[str] = []
        for name, content in files:
            try:
                path = await self.upload_file(name, content, upload_dir=upload_dir)
                paths.append(path)
            except Exception:
                # Skip failed uploads so one bad file doesn't abort the batch
                # (encoding/metadata failures) — but log which file was
                # dropped so it isn't silently lost (B9).
                logging.getLogger(__name__).warning("Skipping upload of %r", name, exc_info=True)
                continue
        return paths

    async def write_pending_uploads(self, workspace: Workspace) -> None:
        """Write the files uploaded since the last run into `workspace`.

        Called when a run starts. A file that cannot be written raises, since
        the system prompt already tells the agent it is there.
        """
        while self._pending_uploads:
            path, content = next(iter(self._pending_uploads.items()))
            await workspace.write_bytes(path, content)
            del self._pending_uploads[path]

    def get_uploads_summary(self) -> str:
        """Generate summary of uploaded files for system prompt."""
        if not self.uploads:
            return ""

        lines = ["## Uploaded Files"]
        lines.append("")
        lines.append("Files uploaded by the user:")

        for path, info in sorted(self.uploads.items()):
            size_str = _format_size(info["size"])
            if info["line_count"] is not None:
                lines.append(f"- `{path}` ({size_str}, {info['line_count']} lines)")
            else:
                lines.append(f"- `{path}` ({size_str})")

        lines.append("")
        lines.append("Use `read_file`, `grep`, `glob` or `execute` to work with these files.")
        lines.append("For large files, use `offset` and `limit` in `read_file`.")

        return "\n".join(lines)

    def clone_for_subagent(self, max_depth: int = 0) -> DeepAgentDeps:
        """Create a new deps instance for a subagent.

        Subagents get:
        - Empty todos (isolated) - or same todos if share_todos=True
        - Empty subagents (no nested delegation by default)
        - Same uploads (shared)
        - Same ask_user callback (propagated)
        - Same checkpoint_store (shared)
        - Same message_queue (shared - subagents can steer the parent)

        Intentionally NOT propagated (a subagent is its own isolation
        domain, so these are reset rather than inherited):
        - `context_middleware`: a CLI-only handle used by `/compact` and
          `/context` over the *parent's* history; a subagent has its own
          history and never runs those commands.
        - `monitor_manager`: monitors are a top-level concern; a subagent
          starts with none rather than inheriting/duplicating the parent's
          background watches.
        - `fork_coordinator`: allocated lazily per-run by the fork
          capability, so a forking subagent gets its own (mirrors how
          `clone_for_branch` resets it).
        - `_fork_depth`: subagent nesting is bounded separately by
          `max_depth`; fork depth restarts at 0 for the subagent.
        - `_branch_cost_tracking` / `_branch_id` /
          `_parent_fork_coordinator`: branch bookkeeping set by
          `ForkCoordinator.fork` and only meaningful to an agent wired
          with the fork capability; inert on a separately-compiled subagent.

        Every other field (uploads, ask_user, share_todos, checkpoint_store,
        message_queue) is shared with the parent via `replace`, so new shared
        fields propagate automatically. Files are shared through the
        workspace, which the subagent toolset passes to the subagent's run.

        Args:
            max_depth: Maximum nesting depth for subagent. If > 0, subagents
                dict is copied to allow nested delegation.
        """
        return replace(
            self,
            todos=self.todos if self.share_todos else [],
            subagents=self.subagents.copy() if max_depth > 0 else {},
            context_middleware=None,
            monitor_manager=None,
            fork_coordinator=None,
            _fork_depth=0,
            _branch_cost_tracking=None,
            _branch_id=None,
            _parent_fork_coordinator=None,
        )


def _format_size(size_bytes: int) -> str:
    """Format byte size to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
