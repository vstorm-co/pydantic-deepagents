"""Deprecated import location for the hooks feature.

The implementation moved to :mod:`pydantic_deep.features.hooks` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.hooks`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.hooks.capability import (
    DEFAULT_BLOCKED_COMMANDS,
    DEFAULT_BLOCKED_READ_PATHS,
    DEFAULT_BLOCKED_WRITE_PATHS,
    DEFAULT_SECRET_PATTERNS,
    EXIT_ALLOW,
    EXIT_DENY,
    Hook,
    HookEvent,
    HookInput,
    HookResult,
    HooksCapability,
    _build_hook_input,
    _execute_command_hook,
    _execute_handler_hook,
    _get_sandbox_backend,
    _match_hooks,
    _parse_command_result,
    _run_background_hook,
    _run_hook,
    default_security_hook,
)

__all__ = [
    "DEFAULT_BLOCKED_COMMANDS",
    "DEFAULT_BLOCKED_READ_PATHS",
    "DEFAULT_BLOCKED_WRITE_PATHS",
    "DEFAULT_SECRET_PATTERNS",
    "EXIT_ALLOW",
    "EXIT_DENY",
    "Hook",
    "HookEvent",
    "HookInput",
    "HookResult",
    "HooksCapability",
    "_build_hook_input",
    "_execute_command_hook",
    "_execute_handler_hook",
    "_get_sandbox_backend",
    "_match_hooks",
    "_parse_command_result",
    "_run_background_hook",
    "_run_hook",
    "default_security_hook",
]

warnings.warn(
    "pydantic_deep.capabilities.hooks has moved to pydantic_deep.features.hooks; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
