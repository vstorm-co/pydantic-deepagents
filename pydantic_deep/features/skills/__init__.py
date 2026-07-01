"""Skills toolset for pydantic-deep agents.

This package provides a complete skills system for extending agent capabilities
with modular, discoverable skill packages.

Skills are directories containing a SKILL.md file with YAML frontmatter and
Markdown instructions, along with optional resource files and executable scripts.
"""

from typing import TYPE_CHECKING, Any

from pydantic_deep.features.skills.backend import (
    BackendSkillResource,
    BackendSkillScript,
    BackendSkillScriptExecutor,
    BackendSkillsDirectory,
    create_backend_resource,
    create_backend_script,
)
from pydantic_deep.features.skills.directory import SkillsDirectory
from pydantic_deep.features.skills.exceptions import (
    SkillException,
    SkillNotFoundError,
    SkillResourceLoadError,
    SkillResourceNotFoundError,
    SkillScriptExecutionError,
    SkillValidationError,
)
from pydantic_deep.features.skills.local import (
    CallableSkillScriptExecutor,
    FileBasedSkillResource,
    FileBasedSkillScript,
    LocalSkillScriptExecutor,
    create_file_based_resource,
    create_file_based_script,
)
from pydantic_deep.features.skills.toolset import (
    LOAD_SKILL_TEMPLATE,
    SkillsToolset,
)
from pydantic_deep.features.skills.types import (
    SKILL_NAME_PATTERN,
    Skill,
    SkillResource,
    SkillScript,
    SkillWrapper,
    normalize_skill_name,
)

__all__ = [
    # Toolset
    "SkillsToolset",
    "SkillsCapability",
    "LOAD_SKILL_TEMPLATE",
    # Types
    "Skill",
    "SkillResource",
    "SkillScript",
    "SkillWrapper",
    "SKILL_NAME_PATTERN",
    "normalize_skill_name",
    # Directory
    "SkillsDirectory",
    # Backend
    "BackendSkillResource",
    "BackendSkillScript",
    "BackendSkillScriptExecutor",
    "BackendSkillsDirectory",
    "create_backend_resource",
    "create_backend_script",
    # Local
    "FileBasedSkillResource",
    "FileBasedSkillScript",
    "LocalSkillScriptExecutor",
    "CallableSkillScriptExecutor",
    "create_file_based_resource",
    "create_file_based_script",
    # Exceptions
    "SkillException",
    "SkillNotFoundError",
    "SkillValidationError",
    "SkillResourceNotFoundError",
    "SkillResourceLoadError",
    "SkillScriptExecutionError",
]

if TYPE_CHECKING:
    from pydantic_deep.features.skills.capability import SkillsCapability


def __getattr__(name: str) -> Any:
    # SkillsCapability is imported lazily: it pulls in DeepAgentDeps, and this
    # package's `types` submodule is imported by the low-level pydantic_deep.types,
    # so an eager import here would create a deps↔types↔skills cycle.
    if name == "SkillsCapability":
        from pydantic_deep.features.skills.capability import SkillsCapability

        return SkillsCapability
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
