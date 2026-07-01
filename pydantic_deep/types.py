"""Type definitions for pydantic-deep."""

from __future__ import annotations

from dataclasses import dataclass as _dataclass
from typing import TypedDict, TypeVar

from pydantic_ai.output import OutputSpec
from pydantic_ai_backends import (
    EditResult as EditResult,
)
from pydantic_ai_backends import (
    ExecuteResponse as ExecuteResponse,
)
from pydantic_ai_backends import (
    FileData as FileData,
)
from pydantic_ai_backends import (
    FileInfo as FileInfo,
)
from pydantic_ai_backends import (
    GrepMatch as GrepMatch,
)
from pydantic_ai_backends import (
    RuntimeConfig as RuntimeConfig,
)
from pydantic_ai_backends import (
    WriteResult as WriteResult,
)
from pydantic_ai_todo import Todo as Todo
from subagents_pydantic_ai import CompiledSubAgent as CompiledSubAgent
from subagents_pydantic_ai import SubAgentConfig as SubAgentConfig

# Re-export new Skill dataclass from skills package
from pydantic_deep.features.skills.types import Skill as Skill

# Re-export OutputSpec from pydantic-ai for structured output support
ResponseFormat = OutputSpec[object]

# Type variable for output types
OutputT = TypeVar("OutputT")


@_dataclass
class BrowseResult:
    """Result of a browser navigation or interaction.

    Returned by helper utilities that wrap `BrowserToolset` tool output
    into a structured form. The toolset tools themselves return plain strings
    for pydantic-ai compatibility; use this dataclass when you want typed
    access to individual fields in your own code.

    Attributes:
        url: The page URL after the action.
        title: The page title.
        content: Page content as Markdown, truncated to `max_content_tokens`.
        screenshot: Base64-encoded PNG screenshot, or `None` if not captured.
        error: Error message if the action failed, or `None` on success.
    """

    url: str
    title: str
    content: str
    screenshot: str | None = None
    error: str | None = None


class UploadedFile(TypedDict):
    """Metadata for an uploaded file.

    Uploaded files are stored in the backend and can be accessed by the agent
    through file tools (read_file, grep, glob, execute).
    """

    name: str  # Original filename
    path: str  # Path in backend (e.g., /uploads/sales.csv)
    size: int  # Size in bytes
    line_count: int | None  # Number of lines (for text files)
    mime_type: str | None  # MIME type (e.g., text/plain)
    encoding: str  # Encoding (e.g., utf-8, binary)
