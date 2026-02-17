"""Skills toolset for pydantic-deep agents.

This package provides a complete skills system for extending agent capabilities
with modular, discoverable skill packages.

Skills are directories containing a SKILL.md file with YAML frontmatter and
Markdown instructions, along with optional resource files and executable scripts.
"""

from pydantic_deep.toolsets.skills.backend import (
    BackendSkillResource,
    BackendSkillScript,
    BackendSkillScriptExecutor,
    BackendSkillsDirectory,
    create_backend_resource,
    create_backend_script,
)
from pydantic_deep.toolsets.skills.directory import SkillsDirectory
from pydantic_deep.toolsets.skills.exceptions import (
    SkillException,
    SkillNotFoundError,
    SkillResourceLoadError,
    SkillResourceNotFoundError,
    SkillScriptExecutionError,
    SkillValidationError,
)
from pydantic_deep.toolsets.skills.local import (
    CallableSkillScriptExecutor,
    FileBasedSkillResource,
    FileBasedSkillScript,
    LocalSkillScriptExecutor,
    create_file_based_resource,
    create_file_based_script,
)
from pydantic_deep.toolsets.skills.toolset import (
    LOAD_SKILL_TEMPLATE,
    SkillsToolset,
)
from pydantic_deep.toolsets.skills.types import (
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
