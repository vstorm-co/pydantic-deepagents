"""CLI agent factory — wraps create_deep_agent() with CLI-specific defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai_backends import LocalBackend

from pydantic_deep.agent import create_deep_agent
from cli.prompts import build_cli_instructions
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.middleware.hooks import Hook, HookEvent, HookInput, HookResult


def _make_shell_allow_list_hook(allow_list: list[str]) -> Hook:
    """Create a hook that blocks shell commands not in the allow list.

    Args:
        allow_list: List of allowed command prefixes (e.g., ["python", "pip", "npm"]).

    Returns:
        Hook that filters execute tool calls.
    """

    async def _check_command(hook_input: HookInput) -> HookResult:
        command = str(hook_input.tool_input.get("command", ""))
        cmd_base = command.strip().split()[0] if command.strip() else ""

        for allowed in allow_list:
            if cmd_base == allowed or command.strip().startswith(allowed):
                return HookResult(allow=True)

        allowed_str = ", ".join(allow_list)
        return HookResult(
            allow=False,
            reason=(
                f"Command '{cmd_base}' is not in the allow-list. "
                f"Allowed commands: {allowed_str}. "
                f"Try a different approach or use an allowed command."
            ),
        )

    return Hook(
        event=HookEvent.PRE_TOOL_USE,
        handler=_check_command,
        matcher=r"^execute$",
    )


def create_cli_agent(
    model: str | None = None,
    working_dir: str | None = None,
    shell_allow_list: list[str] | None = None,
    on_cost_update: Any | None = None,
    on_context_update: Any | None = None,
    extra_middleware: list[Any] | None = None,
    backend: Any | None = None,
    permission_handler: Any | None = None,
    *,
    include_skills: bool = True,
    include_plan: bool = True,
    include_memory: bool = True,
    include_checkpoints: bool = True,
    include_subagents: bool = True,
    include_todo: bool = True,
    context_discovery: bool = True,
    config_path: Path | None = None,
) -> tuple[Any, DeepAgentDeps]:
    """Create a CLI-configured agent with all pydantic-deep capabilities.

    Configuration precedence: explicit arguments > config file > defaults.

    Args:
        model: Model to use. Falls back to config, then ``"openai:gpt-4.1"``.
        working_dir: Filesystem root directory. Defaults to cwd.
        shell_allow_list: Allowed shell command prefixes. None = all allowed.
        on_cost_update: Callback for cost updates.
        on_context_update: Callback for context usage updates.
        extra_middleware: Additional middleware to include.
        backend: Override the file storage backend (e.g., DockerSandbox).
        include_skills: Whether to include the skills toolset.
        include_plan: Whether to include the planner subagent.
        include_memory: Whether to include persistent agent memory.
        include_checkpoints: Whether to include conversation checkpointing.
        include_subagents: Whether to include the subagent toolset.
        include_todo: Whether to include the todo toolset.
        context_discovery: Whether to auto-discover context files (DEEP.md, CLAUDE.md, etc.).
        config_path: Override config file path (for testing).

    Returns:
        Tuple of (agent, deps) ready for agent.run().
    """
    from cli.config import load_config

    config = load_config(config_path)

    # Apply config defaults — explicit params override
    effective_model = model or config.model
    effective_working_dir = working_dir or config.working_dir
    effective_allow_list = shell_allow_list or config.shell_allow_list or None

    root = Path(effective_working_dir) if effective_working_dir else Path.cwd()
    effective_backend = backend or LocalBackend(root_dir=root)

    # Build hooks list
    hooks: list[Hook] = []
    if effective_allow_list is not None:
        hooks.append(_make_shell_allow_list_hook(effective_allow_list))

    # Build middleware list
    from cli.middleware.loop_detection import LoopDetectionMiddleware

    middleware: list[Any] = [LoopDetectionMiddleware()]
    if extra_middleware:
        middleware.extend(extra_middleware)

    # Build dynamic system prompt based on active toolsets
    instructions = build_cli_instructions(
        include_execute=True,
        include_todo=include_todo,
        include_subagents=include_subagents,
    )

    # Append working directory context
    working_dir_section = (
        f"\n\n## Working Directory\n\n"
        f"You are operating in: `{root.resolve()}`\n\n"
        f"All file paths must be absolute, starting with `{root.resolve()}`."
    )
    instructions += working_dir_section

    # Add local context toolset (git info + directory tree)
    from cli.local_context import LocalContextToolset

    local_context = LocalContextToolset(root_dir=root)

    # Built-in skills directory (SKILL.md files shipped with the package)
    skill_dirs: list[str] = []
    if include_skills:
        builtin_skills_dir = Path(__file__).parent / "skills"
        if builtin_skills_dir.is_dir():
            skill_dirs.append(str(builtin_skills_dir))

    agent = create_deep_agent(
        model=effective_model,
        instructions=instructions,
        backend=effective_backend,
        skill_directories=skill_dirs or None,
        # Filesystem & execution
        include_execute=True,
        include_filesystem=True,
        # Planning & task management
        include_todo=include_todo,
        include_plan=include_plan,
        # Delegation
        include_subagents=include_subagents,
        include_general_purpose_subagent=True,
        # Skills
        include_skills=include_skills,
        # Memory
        include_memory=include_memory,
        # Checkpointing
        include_checkpoints=include_checkpoints,
        # Context files (auto-discover DEEP.md, CLAUDE.md, AGENTS.md, SOUL.md)
        context_discovery=context_discovery,
        # Teams (not needed for CLI single-agent use)
        include_teams=False,
        # Context management
        context_manager=True,
        context_manager_max_tokens=200_000,
        on_context_update=on_context_update,
        eviction_token_limit=20_000,
        # Cost tracking
        cost_tracking=True,
        on_cost_update=on_cost_update,
        # Output style
        output_style="concise",
        # Middleware & hooks
        hooks=hooks or None,
        middleware=middleware,
        permission_handler=permission_handler,
        toolsets=[local_context],
    )

    deps = DeepAgentDeps(backend=effective_backend)
    return agent, deps


__all__ = ["create_cli_agent"]
