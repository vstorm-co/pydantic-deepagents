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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai_backends import SandboxProtocol

if TYPE_CHECKING:
    from pydantic_ai_backends import ExecuteResponse

    from pydantic_deep.deps import DeepAgentDeps

logger = logging.getLogger(__name__)

# Exit code conventions (matching Claude Code)
EXIT_ALLOW = 0
EXIT_DENY = 2


class HookEvent(str, Enum):
    """Hook lifecycle events.

    Tool events follow Claude Code conventions. Run and model events
    map to pydantic-ai's AbstractCapability lifecycle hooks.
    """

    # Tool events (Claude Code compatible)
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"

    # Run events
    BEFORE_RUN = "before_run"
    AFTER_RUN = "after_run"
    RUN_ERROR = "run_error"

    # Model request events
    BEFORE_MODEL_REQUEST = "before_model_request"
    AFTER_MODEL_REQUEST = "after_model_request"

    # Fallback events
    MODEL_FALLBACK_TRIGGERED = "model_fallback_triggered"


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
    tool_error: BaseException | None = None,
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


from dataclasses import dataclass, field  # noqa: E402

from pydantic_ai import RunContext  # noqa: E402
from pydantic_ai.capabilities import AbstractCapability  # noqa: E402
from pydantic_ai.messages import ToolCallPart  # noqa: E402
from pydantic_ai.tools import ToolDefinition  # noqa: E402


@dataclass
class HooksCapability(AbstractCapability[Any]):
    """Capability that executes hooks on tool lifecycle events.

    Maps tool events to shell commands (via execute()) or Python handlers,
    following Claude Code's hook conventions:
    - PRE_TOOL_USE: before tool execution, can deny
    - POST_TOOL_USE: after successful tool execution
    - POST_TOOL_USE_FAILURE: after failed tool execution
    """

    hooks: list[Hook] = field(default_factory=list)

    async def before_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Run PRE_TOOL_USE hooks. First deny raises SkipToolExecution."""
        matched = _match_hooks(self.hooks, HookEvent.PRE_TOOL_USE, call.tool_name)
        if not matched:
            return args

        deps = ctx.deps
        backend = _get_sandbox_backend(deps)
        hook_input = _build_hook_input(HookEvent.PRE_TOOL_USE, call.tool_name, args)
        current_args = dict(args)

        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
                continue

            result = await _run_hook(hook, hook_input, backend)

            if not result.allow:
                from pydantic_ai.exceptions import ModelRetry

                raise ModelRetry(result.reason or "Denied by hook")

            if result.modified_args is not None:
                current_args = result.modified_args
                hook_input = _build_hook_input(HookEvent.PRE_TOOL_USE, call.tool_name, current_args)

        return current_args

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Run POST_TOOL_USE hooks. Can modify result."""
        matched = _match_hooks(self.hooks, HookEvent.POST_TOOL_USE, call.tool_name)
        if not matched:
            return result

        deps = ctx.deps
        backend = _get_sandbox_backend(deps)
        hook_input = _build_hook_input(
            HookEvent.POST_TOOL_USE, call.tool_name, args, tool_result=result
        )
        current_result = result

        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
                continue

            hook_result = await _run_hook(hook, hook_input, backend)

            if hook_result.modified_result is not None:
                if isinstance(current_result, str):
                    current_result = hook_result.modified_result
                else:
                    logger.debug(
                        "[hooks] modified_result skipped: original result is %s, not str",
                        type(current_result).__name__,
                    )
                hook_input = _build_hook_input(
                    HookEvent.POST_TOOL_USE,
                    call.tool_name,
                    args,
                    tool_result=current_result,
                )

        return current_result

    async def on_tool_execute_error(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        error: Exception,
    ) -> Any:
        """Run POST_TOOL_USE_FAILURE hooks."""
        matched = _match_hooks(self.hooks, HookEvent.POST_TOOL_USE_FAILURE, call.tool_name)
        if not matched:
            raise error

        deps = ctx.deps
        backend = _get_sandbox_backend(deps)
        hook_input = _build_hook_input(
            HookEvent.POST_TOOL_USE_FAILURE,
            call.tool_name,
            args,
            tool_error=error,
        )

        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
                continue

            await _run_hook(hook, hook_input, backend)

        raise error

    async def before_run(self, ctx: RunContext[Any]) -> None:
        """Run BEFORE_RUN hooks at the start of agent.run()."""
        matched = [h for h in self.hooks if h.event == HookEvent.BEFORE_RUN]
        if not matched:
            return
        backend = _get_sandbox_backend(ctx.deps)
        hook_input = _build_hook_input(HookEvent.BEFORE_RUN, "", {})
        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
            else:
                await _run_hook(hook, hook_input, backend)

    async def after_run(self, ctx: RunContext[Any], *, result: Any) -> Any:
        """Run AFTER_RUN hooks at the end of agent.run()."""
        matched = [h for h in self.hooks if h.event == HookEvent.AFTER_RUN]
        if not matched:
            return result
        backend = _get_sandbox_backend(ctx.deps)
        hook_input = _build_hook_input(HookEvent.AFTER_RUN, "", {}, tool_result=result)
        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
            else:
                await _run_hook(hook, hook_input, backend)
        return result

    async def on_run_error(self, ctx: RunContext[Any], *, error: BaseException) -> Any:
        """Run RUN_ERROR hooks when agent.run() fails."""
        matched = [h for h in self.hooks if h.event == HookEvent.RUN_ERROR]
        if not matched:
            raise error
        backend = _get_sandbox_backend(ctx.deps)
        hook_input = _build_hook_input(HookEvent.RUN_ERROR, "", {}, tool_error=error)
        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
            else:
                await _run_hook(hook, hook_input, backend)
        raise error

    async def before_model_request(self, ctx: RunContext[Any], request_context: Any) -> Any:
        """Run BEFORE_MODEL_REQUEST hooks before each LLM call."""
        matched = [h for h in self.hooks if h.event == HookEvent.BEFORE_MODEL_REQUEST]
        if not matched:
            return request_context
        backend = _get_sandbox_backend(ctx.deps)
        hook_input = _build_hook_input(HookEvent.BEFORE_MODEL_REQUEST, "", {})
        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
            else:
                await _run_hook(hook, hook_input, backend)
        return request_context

    async def after_model_request(
        self, ctx: RunContext[Any], *, request_context: Any, response: Any
    ) -> Any:
        """Run AFTER_MODEL_REQUEST hooks after each LLM response."""
        matched = [h for h in self.hooks if h.event == HookEvent.AFTER_MODEL_REQUEST]
        if not matched:
            return response
        backend = _get_sandbox_backend(ctx.deps)
        hook_input = _build_hook_input(HookEvent.AFTER_MODEL_REQUEST, "", {})
        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, backend))
            else:
                await _run_hook(hook, hook_input, backend)
        return response

    async def dispatch_model_fallback(
        self,
        primary: str,
        fallback: str,
        error: Exception,
        backend: Any,
    ) -> None:
        """Dispatch MODEL_FALLBACK_TRIGGERED hooks outside the normal capability lifecycle.

        Called by the fallback_on handler in create_deep_agent when FallbackModel
        switches from the primary to a fallback model.
        """
        matched = [h for h in self.hooks if h.event == HookEvent.MODEL_FALLBACK_TRIGGERED]
        if not matched:
            return
        sandbox = backend if isinstance(backend, SandboxProtocol) else None
        hook_input = _build_hook_input(
            HookEvent.MODEL_FALLBACK_TRIGGERED,
            "",
            {"primary": primary, "fallback": fallback},
            tool_error=error,
        )
        for hook in matched:
            if hook.background:
                asyncio.create_task(_run_background_hook(hook, hook_input, sandbox))
            else:
                await _run_hook(hook, hook_input, sandbox)


# Default destructive-command patterns matched against the ``command`` arg of
# the ``execute`` tool. Each entry is a regex; the first match denies the call.
DEFAULT_BLOCKED_COMMANDS: tuple[str, ...] = (
    # rm with recursive+force short flags (-rf, -fr, -rfv, etc.) targeting
    # root (/), root-glob (/*), home dir (~), $HOME, or current dir (.)
    r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\s+(?:/\*?|~(?=\s|$)|\$\{?HOME\}?(?=\s|$)|\.)(?:\s|/|$)",
    r"\brm\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR][a-zA-Z]*\s+(?:/\*?|~(?=\s|$)|\$\{?HOME\}?(?=\s|$)|\.)(?:\s|/|$)",
    # rm with long options --recursive/--force (any order) on dangerous targets
    r"\brm\s+--recursive\s+--force\s+(?:/\*?|~(?=\s|$)|\$\{?HOME\}?(?=\s|$)|\.)(?:\s|/|$)",
    r"\brm\s+--force\s+--recursive\s+(?:/\*?|~(?=\s|$)|\$\{?HOME\}?(?=\s|$)|\.)(?:\s|/|$)",
    # Classic fork bomb
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
    # Filesystem nuke
    r"\bmkfs(?:\.\w+)?\b",
    # Block-device clobber via dd
    r"\bdd\s+[^\n;|&]*\bof=/dev/",
    # curl/wget piped into a shell
    r"\b(?:curl|wget)\s+[^\n;|&]*\|\s*(?:sh|bash|zsh|ksh|dash)\b",
)


# Default sensitive-path patterns matched against the ``path`` arg of
# ``read_file``. Each entry is a regex anchored loosely so the same rule fires
# whether the agent passes ``/etc/shadow``, ``./.ssh/id_rsa`` or ``~/.aws/...``.
DEFAULT_BLOCKED_READ_PATHS: tuple[str, ...] = (
    r"(?:^|/)etc/shadow\b",
    r"(?:^|/|~/)\.ssh(?:/|$)",
    r"(?:^|/)\.env(?:\.[\w.-]+)?$",
    r"(?:^|/|~/)\.aws/credentials\b",
    r"(?:^|/|~/)\.config/gcloud(?:/|$)",
    r"application_default_credentials\.json$",
)


# Default sensitive-path patterns blocked for ``write_file``/``edit_file``.
# Writing to these paths is at least as dangerous as reading them, so we apply
# a symmetric denylist independent of ``allowed_write_roots``.
DEFAULT_BLOCKED_WRITE_PATHS: tuple[str, ...] = (
    r"(?:^|/|~/)\.ssh(?:/|$)",  # SSH keys, authorized_keys
    r"(?:^|/)etc/(?:passwd|shadow|sudoers)\b",  # Critical system auth files
    r"(?:^|/)etc/cron",  # Cron configs (persistence vector)
    r"(?:^|/|~/)\.aws/credentials\b",  # AWS credentials
    r"(?:^|/)\.env(?:\.[\w.-]+)?$",  # .env / .env.production (hold secrets)
    r"(?:^|/|~/)\.(?:bash_profile|bashrc|profile|zshrc|zprofile)\b",  # Shell startup
)


# Secret-shaped tokens redacted from POST_TOOL_USE output. Each pattern is
# replaced with ``[REDACTED]`` when ``redact_secrets`` is enabled.
DEFAULT_SECRET_PATTERNS: tuple[str, ...] = (
    r"AKIA[0-9A-Z]{16}",  # AWS access key ID
    # OpenAI-style API keys: legacy (sk-<alphanum>), and current formats
    # sk-proj-…, sk-svcacct-…, sk-admin-… which contain hyphens/underscores
    r"sk-(?:proj|svcacct|admin)?-?[A-Za-z0-9_-]{20,}",
    r"ghp_[A-Za-z0-9]{36}",  # GitHub personal access token (classic)
    r"github_pat_[A-Za-z0-9_]{22,}",  # GitHub fine-grained PAT
    # JWT-shaped tokens (header.payload.signature, base64url segments)
    r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
)


# Tools whose ``path`` argument must stay inside ``allowed_write_roots``.
_WRITE_TOOLS: tuple[str, ...] = ("write_file", "edit_file")


def _normalize_path(raw: str) -> str:
    """Resolve a path without requiring it to exist.

    Does NOT expand ``~`` - callers must validate that paths are absolute before
    calling this, because ``~`` expands against the *controller* HOME which may
    differ from the agent backend's filesystem namespace.
    """
    return str(Path(raw).resolve(strict=False))


def _path_escapes_roots(path: str, roots: Sequence[str]) -> bool:
    """Return True if ``path`` is not inside any of ``roots``."""
    resolved = _normalize_path(path)
    for root in roots:
        root_resolved = _normalize_path(root)
        try:
            Path(resolved).relative_to(root_resolved)
        except ValueError:
            continue
        return False
    return True


def _make_decision(
    *,
    mode: Literal["deny", "warn"],
    tool_name: str,
    reason: str,
) -> HookResult:
    """Build a HookResult honoring the configured ``mode``."""
    if mode == "warn":
        logger.warning("[security-hook] %s: %s", tool_name, reason)
        return HookResult(allow=True, reason=reason)
    return HookResult(allow=False, reason=reason)


def _check_execute(
    args: dict[str, Any],
    *,
    blocked_commands: Sequence[re.Pattern[str]],
) -> str | None:
    """Return a denial reason if the ``execute`` command matches a blocked pattern."""
    command = args.get("command")
    if not isinstance(command, str):
        return None
    for pattern in blocked_commands:
        if pattern.search(command):
            return f"Blocked dangerous command pattern: {pattern.pattern}"
    return None


def _check_write(
    args: dict[str, Any],
    *,
    allowed_write_roots: Sequence[str] | None,
    blocked_write_paths: Sequence[re.Pattern[str]],
) -> str | None:
    """Return a denial reason if ``write_file``/``edit_file`` targets an unsafe path."""
    path = args.get("path")
    if not isinstance(path, str):
        return None
    # Path-traversal segments are always suspicious, even without explicit roots.
    if re.search(r"(?:^|/)\.\.(?:/|$)", path):
        return f"Blocked path-traversal write: {path}"
    # Sensitive write-path denylist (applied unconditionally, independent of roots).
    for pattern in blocked_write_paths:
        if pattern.search(path):
            return f"Blocked write to sensitive path: {path}"
    if allowed_write_roots:
        # Reject paths we cannot safely compare against backend-absolute roots.
        # ``~`` expands against the controller's HOME which may differ from the
        # agent backend's filesystem namespace (e.g. DockerSandbox).
        if path.startswith("~") or not Path(path).is_absolute():
            return (
                f"Blocked write: cannot verify relative/home-relative path against "
                f"allowed roots (use an absolute backend path): {path}"
            )
        if _path_escapes_roots(path, allowed_write_roots):
            return f"Blocked write outside allowed roots: {path}"
    return None


def _check_read(
    args: dict[str, Any],
    *,
    blocked_read_paths: Sequence[re.Pattern[str]],
) -> str | None:
    """Return a denial reason if ``read_file`` targets a sensitive path."""
    path = args.get("path")
    if not isinstance(path, str):
        return None
    for pattern in blocked_read_paths:
        if pattern.search(path):
            return f"Blocked read of sensitive path: {path}"
    return None


def _redact(text: str, patterns: Sequence[re.Pattern[str]]) -> str:
    """Replace every secret-shaped match in ``text`` with ``[REDACTED]``."""
    for pattern in patterns:
        text = pattern.sub("[REDACTED]", text)
    return text


def _compile_all(patterns: Sequence[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in patterns)


def default_security_hook(
    *,
    blocked_commands: Sequence[str] | None = None,
    allowed_write_roots: Sequence[str | Path] | None = None,
    blocked_write_paths: Sequence[str] | None = None,
    blocked_read_paths: Sequence[str] | None = None,
    redact_secrets: bool = True,
    secret_patterns: Sequence[str] | None = None,
    mode: Literal["deny", "warn"] = "deny",
) -> list[Hook]:
    """Return a ready-to-use list of security hooks for `create_deep_agent`.

    The returned hooks gate `execute`, `write_file`, `edit_file`, and
    `read_file` against destructive command patterns, path-traversal writes,
    sensitive-path writes, and sensitive-path reads. When `redact_secrets` is
    enabled, a second hook scrubs obvious secret shapes (AWS access keys,
    GitHub PATs, OpenAI `sk-` keys, JWTs) from `POST_TOOL_USE` output.

    The defaults are opt-out: pass `mode="warn"` to log instead of block,
    pass `blocked_commands=[]` to disable a category, or extend any list with
    your own patterns. Lists you pass *replace* the defaults - concatenate
    with `DEFAULT_BLOCKED_COMMANDS` etc. if you want to keep them.

    Args:
        blocked_commands: Regex patterns matched against the `command` arg of
            the `execute` tool. Defaults to `DEFAULT_BLOCKED_COMMANDS`.
        allowed_write_roots: If set, `write_file`/`edit_file` paths must
            resolve under one of these roots. Paths must be absolute (no `~`
            or relative segments) - `~` expands against the *controller*
            HOME, which may differ from the agent backend's filesystem
            namespace (e.g. DockerSandbox). Path-traversal (`..`) segments
            are blocked unconditionally regardless of this setting.
        blocked_write_paths: Regex patterns matched against the `path` arg of
            `write_file`/`edit_file`. Defaults to `DEFAULT_BLOCKED_WRITE_PATHS`.
            Applied unconditionally, independent of `allowed_write_roots`.
        blocked_read_paths: Regex patterns matched against the `path` arg of
            `read_file`. Defaults to `DEFAULT_BLOCKED_READ_PATHS`.
        redact_secrets: When True (default), add a `POST_TOOL_USE` hook that
            replaces matches of `secret_patterns` with `[REDACTED]` in tool
            output strings.
        secret_patterns: Regex patterns redacted from tool output. Defaults to
            `DEFAULT_SECRET_PATTERNS`.
        mode: `"deny"` (default) blocks matching calls via
            `HookResult(allow=False)`. `"warn"` allows them through but logs
            a warning - useful for shadow-mode rollout before enforcing.

    Returns:
        A list of `Hook` instances. Pass it straight to `create_deep_agent`:
        `hooks=default_security_hook()`. Use
        `hooks=[*default_security_hook(), my_extra]` to add custom hooks.
    """
    cmd_patterns = _compile_all(
        DEFAULT_BLOCKED_COMMANDS if blocked_commands is None else blocked_commands
    )
    read_patterns = _compile_all(
        DEFAULT_BLOCKED_READ_PATHS if blocked_read_paths is None else blocked_read_paths
    )
    write_path_patterns = _compile_all(
        DEFAULT_BLOCKED_WRITE_PATHS if blocked_write_paths is None else blocked_write_paths
    )
    write_roots: tuple[str, ...] | None = None
    if allowed_write_roots:
        validated: list[str] = []
        for p in allowed_write_roots:
            s = str(p)
            if s.startswith("~") or not Path(s).is_absolute():
                raise ValueError(
                    f"allowed_write_roots must be absolute paths (no ~ or relative): {s!r}"
                )
            validated.append(s)
        write_roots = tuple(validated)

    async def _pre_tool_use(hook_input: HookInput) -> HookResult:
        tool_name = hook_input.tool_name
        args = hook_input.tool_input
        reason: str | None = None
        if tool_name == "execute":
            reason = _check_execute(args, blocked_commands=cmd_patterns)
        elif tool_name in _WRITE_TOOLS:
            reason = _check_write(
                args,
                allowed_write_roots=write_roots,
                blocked_write_paths=write_path_patterns,
            )
        elif tool_name == "read_file":
            reason = _check_read(args, blocked_read_paths=read_patterns)
        if reason is None:
            return HookResult(allow=True)
        return _make_decision(mode=mode, tool_name=tool_name, reason=reason)

    hooks: list[Hook] = [
        Hook(
            event=HookEvent.PRE_TOOL_USE,
            handler=_pre_tool_use,
            matcher=r"^(?:execute|write_file|edit_file|read_file)$",
        )
    ]

    if redact_secrets:
        secret_compiled = _compile_all(
            DEFAULT_SECRET_PATTERNS if secret_patterns is None else secret_patterns
        )

        async def _post_tool_use(hook_input: HookInput) -> HookResult:
            if hook_input.tool_result is None:
                return HookResult(allow=True)
            redacted = _redact(hook_input.tool_result, secret_compiled)
            if redacted == hook_input.tool_result:
                return HookResult(allow=True)
            return HookResult(allow=True, modified_result=redacted)

        hooks.append(
            Hook(
                event=HookEvent.POST_TOOL_USE,
                handler=_post_tool_use,
            )
        )

    return hooks


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
