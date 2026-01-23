"""Type definitions for pydantic-deep."""

from __future__ import annotations

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
from typing_extensions import NotRequired

# Re-export OutputSpec from pydantic-ai for structured output support
# This allows users to specify the response format for agents
ResponseFormat = OutputSpec[object]

# Type variable for output types
OutputT = TypeVar("OutputT")


class SkillFrontmatter(TypedDict):
    """YAML frontmatter from a SKILL.md file."""

    name: str
    description: str
    tags: NotRequired[list[str]]
    version: NotRequired[str]
    author: NotRequired[str]


class Skill(TypedDict):
    """A loaded skill with its metadata and content."""

    name: str
    description: str
    path: str  # Path to the skill directory
    tags: list[str]
    version: str
    author: str
    frontmatter_loaded: bool  # Whether only frontmatter is loaded
    instructions: NotRequired[str]  # Full instructions (loaded on demand)
    resources: NotRequired[list[str]]  # List of additional files in the skill directory


class SkillDirectory(TypedDict):
    """Configuration for a skill directory."""

    path: str  # Path to the skills directory
    recursive: NotRequired[bool]  # Whether to search recursively


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
