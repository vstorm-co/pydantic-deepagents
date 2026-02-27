"""CLI agent factory — wraps create_deep_agent() with CLI-specific defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai_backends import LocalBackend

from cli.prompts import build_cli_instructions
from pydantic_deep.agent import create_deep_agent
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


def create_cli_agent(  # noqa: C901
    model: str | None = None,
    working_dir: str | None = None,
    shell_allow_list: list[str] | None = None,
    on_cost_update: Any | None = None,
    on_context_update: Any | None = None,
    summarization_model: str | None = None,
    extra_middleware: list[Any] | None = None,
    backend: Any | None = None,
    permission_handler: Any | None = None,
    *,
    include_skills: bool = True,
    include_plan: bool = True,
    include_memory: bool = True,
    include_subagents: bool = True,
    include_todo: bool = True,
    include_local_context: bool = True,
    include_web: bool = False,
    context_discovery: bool = True,
    non_interactive: bool = False,
    lean: bool = False,
    config_path: Path | None = None,
    model_settings: dict[str, Any] | None = None,
    session_id: str | None = None,
    skills_dir: str | None = None,
    extra_instructions: str | None = None,
) -> tuple[Any, DeepAgentDeps]:
    """Create a CLI-configured agent with all pydantic-deep capabilities.

    Configuration precedence: explicit arguments > config file > defaults.

    Args:
        model: Model to use. Falls back to config, then ``"openrouter:openai/gpt-4.1"``.
        working_dir: Filesystem root directory. Defaults to cwd.
        shell_allow_list: Allowed shell command prefixes. None = all allowed.
        on_cost_update: Callback for cost updates.
        on_context_update: Callback for context usage updates.
        extra_middleware: Additional middleware to include.
        backend: Override the file storage backend (e.g., DockerSandbox).
        include_skills: Whether to include the skills toolset.
        include_plan: Whether to include the planner subagent.
        include_memory: Whether to include persistent agent memory.
        include_subagents: Whether to include the subagent toolset.
        include_todo: Whether to include the todo toolset.
        include_local_context: Whether to include local context (git info, dir tree).
            Disable for Docker/sandbox backends where the root dir doesn't exist on host.
        context_discovery: Whether to auto-discover context files (AGENT.md).
        config_path: Override config file path (for testing).
        session_id: Session identifier for per-session plans storage.
        extra_instructions: Additional instructions appended to the system prompt.
        skills_dir: Override skills directory path. When None, auto-discovers
            from ``{working_dir}/.pydantic-deep/skills/``.

    Returns:
        Tuple of (agent, deps) ready for agent.run().
    """
    from cli.config import load_config

    config = load_config(config_path)

    # Apply config defaults — explicit params override
    effective_model = model or config.model
    effective_working_dir = working_dir or config.working_dir
    effective_allow_list = shell_allow_list or config.shell_allow_list or None

    # Warn (but don't block) if provider env vars are missing
    from cli.providers import format_provider_error

    provider_error = format_provider_error(effective_model)
    if provider_error:
        import sys

        print(f"Warning: {provider_error}", file=sys.stderr)
        print("Run 'pydantic-deep providers list' to see all providers.", file=sys.stderr)

    root = Path(effective_working_dir) if effective_working_dir else Path.cwd()
    effective_backend = backend or LocalBackend(root_dir=root)

    # Build hooks list
    hooks: list[Hook] = []
    if effective_allow_list is not None:
        hooks.append(_make_shell_allow_list_hook(effective_allow_list))

    # Build middleware list
    middleware: list[Any] = []
    if not lean:
        from cli.middleware.loop_detection import LoopDetectionMiddleware

        middleware.append(LoopDetectionMiddleware())
    if extra_middleware:
        middleware.extend(extra_middleware)

    # Build dynamic system prompt (tool-specific guidance lives in tool descriptions)
    instructions = build_cli_instructions(
        non_interactive=non_interactive,
        lean=lean,
    )

    # Append working directory context
    working_dir_section = (
        f"\n\n## Working Directory\n\n"
        f"You are operating in: `{root.resolve()}`\n\n"
        f"All file paths must be absolute, starting with `{root.resolve()}`."
    )
    instructions += working_dir_section

    if extra_instructions:
        instructions += "\n\n" + extra_instructions

    # Add local context toolset (git info + directory tree)
    # Skipped for Docker/sandbox backends where root_dir doesn't exist on host
    local_context = None
    if include_local_context:
        from cli.local_context import LocalContextToolset

        local_context = LocalContextToolset(root_dir=root)

    # Skills directory — explicit override > project root > bundled fallback
    skill_dirs: list[str] = []
    if include_skills:
        if skills_dir:
            sd = Path(skills_dir)
            if sd.is_dir():
                skill_dirs.append(str(sd))
        else:
            project_skills_dir = root / ".pydantic-deep" / "skills"
            if project_skills_dir.is_dir():
                skill_dirs.append(str(project_skills_dir))

        # Fallback to bundled skills shipped with the package
        if not skill_dirs:
            bundled = Path(__file__).resolve().parent.parent / "pydantic_deep" / "bundled_skills"
            if bundled.is_dir():
                skill_dirs.append(str(bundled))

    # In non-interactive mode: no approval needed, disable interactive features
    # (memory, plan, subagents). Skills stay ON — they're static
    # instructions that improve benchmark performance.
    interrupt_on = {"execute": False} if non_interactive else None

    effective_memory = include_memory and not non_interactive
    effective_skills = include_skills if not lean else False  # Lean: no skills noise
    effective_plan = include_plan and not non_interactive
    effective_subagents = include_subagents if not lean else False  # Lean: no subagents
    effective_todo = include_todo if not lean else False  # Lean: no todo overhead

    # Model settings — non-interactive defaults, then config, then explicit overrides
    effective_model_settings: dict[str, Any] = {}
    if non_interactive:
        effective_model_settings["temperature"] = 0.0
    # Config-level defaults (lowest priority after non-interactive)
    if config.temperature is not None and "temperature" not in (model_settings or {}):
        effective_model_settings["temperature"] = config.temperature
    if config.reasoning_effort and "openai_reasoning_effort" not in (model_settings or {}):
        effective_model_settings["openai_reasoning_effort"] = config.reasoning_effort
    if config.thinking and "anthropic_thinking" not in (model_settings or {}):
        if config.thinking_budget:
            effective_model_settings["anthropic_thinking"] = {
                "type": "enabled",
                "budget_tokens": config.thinking_budget,
            }
        else:
            effective_model_settings["anthropic_thinking"] = {"type": "adaptive"}
    elif config.thinking_budget and "anthropic_thinking" not in (model_settings or {}):
        effective_model_settings["anthropic_thinking"] = {
            "type": "enabled",
            "budget_tokens": config.thinking_budget,
        }
    # Explicit CLI flags override everything
    if model_settings:
        effective_model_settings.update(model_settings)

    # Per-session plans directory (relative to backend root)
    if session_id:
        plans_dir = f".pydantic-deep/sessions/{session_id}/plans"
    else:
        plans_dir = ".pydantic-deep/plans"

    # Ensure session directory exists (for plans, messages.json)
    if session_id:
        from cli.config import get_sessions_dir

        session_dir = get_sessions_dir() / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

    agent = create_deep_agent(
        model=effective_model,
        instructions=instructions,
        backend=effective_backend,
        skill_directories=skill_dirs if effective_skills else None,
        interrupt_on=interrupt_on,
        model_settings=effective_model_settings or None,
        # Filesystem & execution
        include_execute=True,
        include_filesystem=True,
        # Planning & task management
        include_todo=effective_todo,
        include_plan=effective_plan,
        plans_dir=plans_dir,
        # Delegation
        include_subagents=effective_subagents,
        include_general_purpose_subagent=effective_subagents,
        # Skills
        include_skills=effective_skills,
        # Memory (store in .pydantic-deep/main/MEMORY.md)
        include_memory=effective_memory,
        memory_dir=".pydantic-deep",
        # Context files (auto-discover AGENT.md)
        context_discovery=context_discovery if not lean else False,
        # Teams (not needed for CLI single-agent use)
        include_teams=False,
        # Web tools (search, fetch, HTTP)
        include_web=include_web,
        # History persistence — per-session messages.json
        history_messages_path=(
            f".pydantic-deep/sessions/{session_id}/messages.json"
            if session_id
            else ".pydantic-deep/messages.json"
        ),
        # Context management
        context_manager=not lean,
        context_manager_max_tokens=None,  # auto-detect from genai-prices
        on_context_update=on_context_update,
        summarization_model=summarization_model,
        eviction_token_limit=20_000,
        # Cost tracking
        cost_tracking=True,
        on_cost_update=on_cost_update,
        # Output style
        output_style="concise" if not lean else None,
        # Middleware & hooks
        hooks=hooks or None,
        middleware=middleware or None,
        permission_handler=permission_handler,
        toolsets=[local_context] if local_context else None,
    )

    # Extract context middleware for CLI commands (/compact, /context)
    context_mw = getattr(agent, "_context_middleware", None)

    deps = DeepAgentDeps(
        backend=effective_backend,
        context_middleware=context_mw,
    )
    return agent, deps


__all__ = ["create_cli_agent"]
