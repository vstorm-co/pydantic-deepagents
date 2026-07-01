"""Exceptions for skill-related errors.

This module defines the exception hierarchy for the skills toolset.
All skill exceptions inherit from `SkillException`, making it easy
to catch all skill-related errors.

Exception hierarchy:

- `SkillException`: Base exception for all skill errors
    - `SkillNotFoundError`: Skill not found in any source
    - `SkillValidationError`: Skill validation failed
    - `SkillResourceNotFoundError`: Resource file not found
    - `SkillResourceLoadError`: Failed to load resource
    - `SkillScriptExecutionError`: Script execution failed
"""

from __future__ import annotations


class SkillException(Exception):
    """Base exception for skill-related errors."""


class SkillNotFoundError(SkillException):
    """Skill not found in any source."""


class SkillValidationError(SkillException):
    """Skill validation failed."""


class SkillResourceNotFoundError(SkillException):
    """Skill resource not found."""


class SkillResourceLoadError(SkillException):
    """Failed to load skill resources."""


class SkillScriptExecutionError(SkillException):
    """Skill script execution failed."""
