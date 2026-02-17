"""Dependency injection container for deep agents."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import chardet
from pydantic_ai_backends import BackendProtocol, StateBackend

from pydantic_deep.types import FileData, Todo, UploadedFile

if TYPE_CHECKING:
    pass


@dataclass
class DeepAgentDeps:
    """Dependencies for deep agents.

    This container holds all the state and resources needed by the agent
    and its tools during execution.

    Attributes:
        backend: File storage backend (StateBackend, FilesystemBackend, etc.)
        files: In-memory file cache (used with StateBackend)
        todos: Task list for planning
        subagents: Pre-configured subagents available for delegation
    """

    backend: BackendProtocol = field(default_factory=StateBackend)
    files: dict[str, FileData] = field(default_factory=dict)
    todos: list[Todo] = field(default_factory=list)
    subagents: dict[str, Any] = field(default_factory=dict)  # Agent instances
    uploads: dict[str, UploadedFile] = field(default_factory=dict)  # Uploaded files metadata
    ask_user: Any = field(default=None, repr=False)  # Callback for interactive questions
    checkpoint_store: Any = field(default=None, repr=False)  # CheckpointStore | None
    share_todos: bool = False  # When True, subagents share parent's todo list

    def __post_init__(self) -> None:
        """Initialize backend with files if using StateBackend."""
        if isinstance(self.backend, StateBackend):
            if self.files:
                # Sync files to state backend
                self.backend._files = self.files
            else:
                # Use backend's files dict as the shared reference
                object.__setattr__(self, "files", self.backend._files)

    def get_todo_prompt(self) -> str:
        """Generate system prompt section for todos."""
        if not self.todos:
            return ""

        lines = ["## Current Todos"]
        for todo in self.todos:
            status_icon = {
                "pending": "[ ]",
                "in_progress": "[*]",
                "completed": "[x]",
            }.get(todo.status, "[ ]")
            lines.append(f"- {status_icon} {todo.content}")

        return "\n".join(lines)

    def get_files_summary(self) -> str:
        """Generate summary of files in memory."""
        if not self.files:
            return ""

        lines = ["## Files in Memory"]
        for path, data in sorted(self.files.items()):
            line_count = len(data["content"])
            lines.append(f"- {path} ({line_count} lines)")

        return "\n".join(lines)

    def get_subagents_summary(self) -> str:
        """Generate summary of available subagents."""
        if not self.subagents:
            return ""

        lines = ["## Available Subagents"]
        for name in sorted(self.subagents.keys()):
            lines.append(f"- {name}")

        return "\n".join(lines)

    def upload_file(
        self,
        name: str,
        content: bytes,
        *,
        upload_dir: str = "/uploads",
    ) -> str:
        """Upload a file to the backend and track it.

        The file is written to the backend and its metadata is stored
        for display in the system prompt.

        Args:
            name: Original filename (e.g., "sales.csv")
            content: File content as bytes
            upload_dir: Directory to store uploads (default: "/uploads")

        Returns:
            The path where the file was stored (e.g., "/uploads/sales.csv")

        Example:
            ```python
            deps = DeepAgentDeps(backend=StateBackend())
            path = deps.upload_file("data.csv", csv_bytes)
            # Agent can now access the file at /uploads/data.csv
            ```
        """
        path = f"{upload_dir}/{name}"

        # Write raw bytes to storage
        res = self.backend.write(path, content)

        if res.error:  # pragma: no cover
            raise RuntimeError(f"Failed to upload file: {res.error}")

        # Try to infer metadata after storage
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
        - Same backend (shared)
        - Empty todos (isolated) — or same todos if share_todos=True
        - Empty subagents (no nested delegation by default)
        - Same files (shared)
        - Same uploads (shared)

        Args:
            max_depth: Maximum nesting depth for subagent. If > 0, subagents
                dict is copied to allow nested delegation.
        """
        return DeepAgentDeps(
            backend=self.backend,
            files=self.files,  # Shared reference
            todos=self.todos if self.share_todos else [],  # Shared or fresh
            subagents=self.subagents.copy() if max_depth > 0 else {},
            uploads=self.uploads,  # Shared reference
            ask_user=self.ask_user,  # Propagate to subagents
            share_todos=self.share_todos,  # Propagate to subagents
        )


def _format_size(size_bytes: int) -> str:
    """Format byte size to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
