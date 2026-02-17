"""Claude Code-style hooks system for pydantic-deep.

Hooks allow executing shell commands or Python handlers on tool lifecycle events
(PreToolUse, PostToolUse, PostToolUseFailure). Command hooks run via the backend's
SandboxProtocol.execute() and use exit codes for decisions (0=allow, 2=deny).

Example:
    ```python
    from pydantic_deep import create_deep_agent, Hook, HookEvent

    agent = create_deep_agent(
        hooks=[
            Hook(
                event=HookEvent.PRE_TOOL_USE,
                command="my-security-checker",
                matcher="execute|write_file",
            ),
        ],
    )
    ```
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic_ai_backends import SandboxProtocol

if TYPE_CHECKING:
    from pydantic_ai_backends import ExecuteResponse

    from pydantic_deep.deps import DeepAgentDeps

logger = logging.getLogger(__name__)

# Exit code conventions (matching Claude Code)
EXIT_ALLOW = 0
EXIT_DENY = 2


class HookEvent(str, Enum):
    """Hook lifecycle events, matching Claude Code conventions."""

    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"


@dataclass
class HookInput:
    """Data passed to hook commands/handlers as JSON.

    Command hooks receive this as JSON via stdin piping.
    Python handlers receive this as a dataclass instance.
    """

    event: str
    tool_name: str
    tool_input: dict[str, Any]
    tool_result: str | None = None
    tool_error: str | None = None


@dataclass
class HookResult:
    """Result from a hook execution.

    For PRE_TOOL_USE: allow=False denies the tool call.
    For POST_TOOL_USE: modified_result replaces the tool output.
    """

    allow: bool = True
    reason: str | None = None
    modified_args: dict[str, Any] | None = None
    modified_result: str | None = None


@dataclass
class Hook:
    """A hook definition that fires on tool lifecycle events.

    Either ``command`` or ``handler`` must be provided (not both).
    Command hooks run shell commands via SandboxProtocol.execute().
    Handler hooks call async Python functions.

    Args:
        event: Which lifecycle event triggers this hook.
        command: Shell command to execute (receives HookInput JSON via stdin).
        handler: Async Python function ``(HookInput) -> HookResult``.
        matcher: Regex pattern matched against tool_name. None matches all tools.
        timeout: Command execution timeout in seconds.
        background: If True, hook runs as fire-and-forget (non-blocking).
    """

    event: HookEvent
    command: str | None = None
    handler: Callable[[HookInput], Awaitable[HookResult]] | None = None
    matcher: str | None = None
    timeout: int = 30
    background: bool = False

    def __post_init__(self) -> None:
        if self.command is None and self.handler is None:
            msg = "Hook must have either 'command' or 'handler'"
            raise ValueError(msg)
        if self.command is not None and self.handler is not None:
            msg = "Hook cannot have both 'command' and 'handler'"
            raise ValueError(msg)


def _match_hooks(hooks: list[Hook], event: HookEvent, tool_name: str) -> list[Hook]:
    """Filter hooks by event and tool_name regex matcher."""
    matched = []
    for hook in hooks:
        if hook.event != event:
            continue
        if hook.matcher is not None and not re.search(hook.matcher, tool_name):
            continue
        matched.append(hook)
    return matched


def _build_hook_input(
    event: HookEvent,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_result: Any | None = None,
    tool_error: Exception | None = None,
) -> HookInput:
    """Build HookInput from hook context."""
    return HookInput(
        event=event.value,
        tool_name=tool_name,
        tool_input=tool_args,
        tool_result=str(tool_result) if tool_result is not None else None,
        tool_error=str(tool_error) if tool_error is not None else None,
    )


def _parse_command_result(response: ExecuteResponse) -> HookResult:
    """Parse ExecuteResponse into HookResult using Claude Code exit code conventions."""
    # Exit code 2 = deny (Claude Code convention)
    if response.exit_code == EXIT_DENY:
        reason = response.output.strip() if response.output.strip() else "Denied by hook"
        return HookResult(allow=False, reason=reason)

    # Exit code 0 = allow, try to parse stdout as JSON for modifications
    result = HookResult(allow=True)
    if response.output.strip():
        try:
            data = json.loads(response.output)
            if isinstance(data, dict):
                if "modified_args" in data:
                    result.modified_args = data["modified_args"]
                if "modified_result" in data:
                    result.modified_result = data["modified_result"]
                if "reason" in data:
                    result.reason = data["reason"]
        except (json.JSONDecodeError, TypeError):
            # Non-JSON output is fine, just ignore it
            pass

    return result


async def _execute_command_hook(
    hook: Hook,
    hook_input: HookInput,
    backend: SandboxProtocol,
) -> HookResult:
    """Execute a command hook via SandboxProtocol.execute()."""
    json_str = json.dumps(asdict(hook_input))
    # Escape single quotes for shell safety
    escaped = json_str.replace("'", "'\\''")
    full_command = f"printf '%s' '{escaped}' | {hook.command}"
    response: ExecuteResponse = await asyncio.to_thread(backend.execute, full_command, hook.timeout)
    return _parse_command_result(response)


async def _execute_handler_hook(
    hook: Hook,
    hook_input: HookInput,
) -> HookResult:
    """Execute a Python handler hook."""
    assert hook.handler is not None
    return await hook.handler(hook_input)


async def _run_hook(
    hook: Hook,
    hook_input: HookInput,
    backend: SandboxProtocol | None,
) -> HookResult:
    """Run a single hook (command or handler)."""
    if hook.command is not None:
        if backend is None or not isinstance(backend, SandboxProtocol):
            msg = (
                "Command hooks require a SandboxProtocol backend "
                "(LocalBackend or DockerSandbox). "
                "Current backend does not support execute()."
            )
            raise RuntimeError(msg)
        return await _execute_command_hook(hook, hook_input, backend)
    return await _execute_handler_hook(hook, hook_input)


async def _run_background_hook(
    hook: Hook,
    hook_input: HookInput,
    backend: SandboxProtocol | None,
) -> None:
    """Run a background hook, logging errors without propagating."""
    try:
        await _run_hook(hook, hook_input, backend)
    except Exception:
        logger.exception("Background hook failed: %s", hook.command or hook.handler)


def _get_sandbox_backend(deps: DeepAgentDeps | None) -> SandboxProtocol | None:
    """Extract SandboxProtocol backend from deps, if available."""
    if deps is None:
        return None
    backend = deps.backend
    if isinstance(backend, SandboxProtocol):
        return backend
    return None


from pydantic_ai_middleware import (  # noqa: E402
    AgentMiddleware,
    ToolDecision,
    ToolPermissionResult,
)


class HooksMiddleware(AgentMiddleware["DeepAgentDeps"]):  # type: ignore[type-arg]
    """Middleware that executes hooks on tool lifecycle events.

    This middleware maps tool events to shell commands (via execute()) or
    Python handlers, following Claude Code's hook conventions:
    - PRE_TOOL_USE: before tool execution, can allow/deny
    - POST_TOOL_USE: after successful tool execution
    - POST_TOOL_USE_FAILURE: after failed tool execution

    Args:
        hooks: List of Hook definitions to execute.
    """

    def __init__(self, hooks: list[Hook]) -> None:
        self.hooks = hooks

    async def before_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        deps: DeepAgentDeps | None,
        ctx: Any = None,
    ) -> dict[str, Any] | ToolPermissionResult:
        """Run PRE_TOOL_USE hooks. First deny wins."""
        matched = _match_hooks(self.hooks, HookEvent.PRE_TOOL_USE, tool_name)
        if not matched:
            return tool_args

        backend = _get_sandbox_backend(deps)
        hook_input = _build_hook_input(HookEvent.PRE_TOOL_USE, tool_name, tool_args)
        current_args = dict(tool_args)

        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
                continue

            result = await _run_hook(hook, hook_input, backend)

            # First deny wins
            if not result.allow:
                return ToolPermissionResult(
                    decision=ToolDecision.DENY,
                    reason=result.reason or "Denied by hook",
                )

            # Apply arg modifications
            if result.modified_args is not None:
                current_args = result.modified_args
                hook_input = _build_hook_input(HookEvent.PRE_TOOL_USE, tool_name, current_args)

        return current_args

    async def after_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
        deps: DeepAgentDeps | None,
        ctx: Any = None,
    ) -> Any:
        """Run POST_TOOL_USE hooks. Can modify result."""
        matched = _match_hooks(self.hooks, HookEvent.POST_TOOL_USE, tool_name)
        if not matched:
            return result

        backend = _get_sandbox_backend(deps)
        hook_input = _build_hook_input(
            HookEvent.POST_TOOL_USE, tool_name, tool_args, tool_result=result
        )
        current_result = result

        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
                continue

            hook_result = await _run_hook(hook, hook_input, backend)

            if hook_result.modified_result is not None:
                current_result = hook_result.modified_result
                hook_input = _build_hook_input(
                    HookEvent.POST_TOOL_USE,
                    tool_name,
                    tool_args,
                    tool_result=current_result,
                )

        return current_result

    async def on_tool_error(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        error: Exception,
        deps: DeepAgentDeps | None,
        ctx: Any = None,
    ) -> Exception | None:
        """Run POST_TOOL_USE_FAILURE hooks."""
        matched = _match_hooks(self.hooks, HookEvent.POST_TOOL_USE_FAILURE, tool_name)
        if not matched:
            return None

        backend = _get_sandbox_backend(deps)
        hook_input = _build_hook_input(
            HookEvent.POST_TOOL_USE_FAILURE,
            tool_name,
            tool_args,
            tool_error=error,
        )

        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
                continue

            await _run_hook(hook, hook_input, backend)

        return None


__all__ = [
    "EXIT_ALLOW",
    "EXIT_DENY",
    "Hook",
    "HookEvent",
    "HookInput",
    "HookResult",
    "HooksMiddleware",
]
