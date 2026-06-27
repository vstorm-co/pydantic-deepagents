"""Hooks feature — dispatch user hooks on tool lifecycle events.

A lifecycle-only slice: `capability.py` (HooksCapability, the Hook/HookEvent/
HookInput/HookResult types, exit-code constants, and the built-in security hook).
"""

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
    "default_security_hook",
]
