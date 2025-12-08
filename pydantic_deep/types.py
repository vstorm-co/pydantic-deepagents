"""Type definitions for pydantic-deep."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict, TypeVar

from pydantic import BaseModel
from pydantic_ai.output import OutputSpec
from typing_extensions import NotRequired

# Re-export OutputSpec from pydantic-ai for structured output support
# This allows users to specify the response format for agents
ResponseFormat = OutputSpec[object]

# Type variable for output types
OutputT = TypeVar("OutputT")


class FileData(TypedDict):
    """Data structure for storing file content."""

    content: list[str]  # Lines of the file
    created_at: str  # ISO 8601 timestamp
    modified_at: str  # ISO 8601 timestamp


class FileInfo(TypedDict):
    """Information about a file or directory."""

    name: str
    path: str
    is_dir: bool
    size: int | None


@dataclass
class WriteResult:
    """Result of a write operation."""

    path: str | None = None
    error: str | None = None


@dataclass
class EditResult:
    """Result of an edit operation."""

    path: str | None = None
    error: str | None = None
    occurrences: int | None = None


@dataclass
class ExecuteResponse:
    """Response from command execution."""

    output: str
    exit_code: int | None = None
    truncated: bool = False


class GrepMatch(TypedDict):
    """A single grep match result."""

    path: str
    line_number: int
    line: str


class Todo(BaseModel):
    """A todo item for task tracking."""

    content: str
    status: Literal["pending", "in_progress", "completed"]
    active_form: str  # Present continuous form (e.g., "Implementing feature X")


class SubAgentConfig(TypedDict):
    """Configuration for a subagent."""

    name: str
    description: str
    instructions: str
    tools: NotRequired[list[object]]
    model: NotRequired[str]


class CompiledSubAgent(TypedDict):
    """A pre-compiled subagent ready for use."""

    name: str
    description: str
    agent: NotRequired[object]  # Agent instance - typed as object to avoid circular imports


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


class RuntimeConfig(BaseModel):
    """Configuration for a runtime environment.

    A runtime defines a pre-configured execution environment with specific
    packages and settings. Can be used with DockerSandbox to provide
    ready-to-use environments without manual package installation.

    Example:
        ```python
        from pydantic_deep import RuntimeConfig, DockerSandbox

        # Custom runtime with ML packages
        ml_runtime = RuntimeConfig(
            name="ml-env",
            description="Machine learning environment",
            base_image="python:3.12-slim",
            packages=["torch", "transformers", "datasets"],
        )

        sandbox = DockerSandbox(runtime=ml_runtime)
        ```
    """

    name: str
    """Unique name for the runtime (e.g., "python-datascience")."""

    description: str = ""
    """Human-readable description of the runtime."""

    # Image source (one of these)
    image: str | None = None
    """Ready-to-use Docker image (e.g., "myregistry/python-ds:v1")."""

    base_image: str | None = None
    """Base image to build upon (e.g., "python:3.12-slim")."""

    # Packages to install (only if base_image)
    packages: list[str] = []
    """Packages to install (e.g., ["pandas", "numpy", "matplotlib"])."""

    package_manager: Literal["pip", "npm", "apt", "cargo"] = "pip"
    """Package manager to use for installation."""

    # Additional configuration
    setup_commands: list[str] = []
    """Additional setup commands to run (e.g., ["apt-get update"])."""

    env_vars: dict[str, str] = {}
    """Environment variables to set in the container."""

    work_dir: str = "/workspace"
    """Working directory inside the container."""

    # Cache settings
    cache_image: bool = True
    """Whether to cache the built image locally."""
