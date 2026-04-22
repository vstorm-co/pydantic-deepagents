"""CLI agent factory — wraps create_deep_agent() with CLI-specific defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai_backends import LocalBackend

from apps.cli.prompts import build_cli_instructions
from pydantic_deep.agent import DEFAULT_INSTRUCTIONS, create_deep_agent
from pydantic_deep.capabilities.hooks import Hook, HookEvent, HookInput, HookResult
from pydantic_deep.deps import DeepAgentDeps


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
    on_before_compress: Any | None = None,
    on_after_compress: Any | None = None,
    on_eviction: Any | None = None,
    summarization_model: str | None = None,
    extra_middleware: list[Any] | None = None,
    backend: Any | None = None,
    sandbox: str | None = None,
    sandbox_image: str | None = None,
    workspace: str | None = None,
    *,
    include_skills: bool | None = None,
    include_plan: bool | None = None,
    include_memory: bool | None = None,
    include_subagents: bool | None = None,
    include_todo: bool | None = None,
    include_local_context: bool = True,
    context_discovery: bool | None = None,
    non_interactive: bool = False,
    lean: bool = False,
    config_path: Path | None = None,
    model_settings: dict[str, Any] | None = None,
    session_id: str | None = None,
    skills_dir: str | None = None,
    extra_instructions: str | None = None,
    web_search: bool | None = None,
    web_fetch: bool | None = None,
    thinking: bool | str | None = None,
    include_teams: bool | None = None,
    temperature: float | None = None,
    include_browser: bool | None = None,
    browser_headless: bool | None = None,
    include_liteparse: bool | None = None,
) -> tuple[Any, DeepAgentDeps]:
    """Create a CLI-configured agent with all pydantic-deep capabilities.

    Configuration precedence: explicit arguments > config file > defaults.

    Args:
        model: Model to use. Falls back to config, then ``"anthropic:claude-sonnet-4-6"``.
        working_dir: Filesystem root directory. Defaults to cwd.
        shell_allow_list: Allowed shell command prefixes. None = all allowed.
        on_cost_update: Callback for cost updates.
        on_context_update: Callback for context usage updates.
        extra_middleware: Additional middleware to include.
        backend: Override the file storage backend (e.g., DockerSandbox).
            Takes precedence over ``sandbox``.
        sandbox: Sandbox type: ``"local"`` or ``"docker"``. When ``"docker"``,
            creates a DockerSandbox with the working directory mounted at
            ``/workspace``. Falls back to ``config.sandbox``.
        sandbox_image: Docker image for the sandbox container. Falls back to
            ``config.sandbox_image`` (default: ``python:3.12-slim``).
        workspace: Named Docker workspace shared across threads. When set, the
            container persists between sessions so installed packages and any
            files outside the mounted volume survive restarts. Multiple threads
            (conversation histories) can share the same workspace. The actual
            Docker container name is ``pydantic-deep-{dir_hash}-{workspace}``.
        include_skills: Whether to include the skills toolset.
        include_plan: Whether to include the planner subagent.
        include_memory: Whether to include persistent agent memory.
        include_subagents: Whether to include the subagent toolset.
        include_todo: Whether to include the todo toolset.
        include_local_context: Whether to include local context (git info, dir tree).
            Disable for Docker/sandbox backends where the root dir doesn't exist on host.
        context_discovery: Whether to auto-discover context files (AGENTS.md).
        config_path: Override config file path (for testing).
        session_id: Session identifier for per-session plans storage.
        extra_instructions: Additional instructions appended to the system prompt.
        skills_dir: Override skills directory path. When None, auto-discovers
            from ``{working_dir}/.pydantic-deep/skills/``.

    Returns:
        Tuple of (agent, deps) ready for agent.run().
    """
    from apps.cli.config import load_config

    config = load_config(config_path)

    # Apply config defaults — explicit params override
    effective_model = model or config.model
    effective_working_dir = working_dir or config.working_dir
    effective_allow_list = shell_allow_list or config.shell_allow_list or None

    root = Path(effective_working_dir) if effective_working_dir else Path.cwd()

    # Resolve sandbox: explicit param > config
    effective_sandbox = sandbox or config.sandbox
    if effective_sandbox == "docker" and backend is None:
        from pydantic_ai_backends import DockerSandbox

        docker_kwargs: dict[str, Any] = {
            "volumes": {str(root.resolve()): "/workspace"},
            "work_dir": "/workspace",
            "image": sandbox_image or config.sandbox_image,
        }

        # Named workspace → reusable container (packages + state persist between threads)
        # No workspace → ephemeral container (clean slate every time)
        if workspace:
            import hashlib

            dir_hash = hashlib.md5(str(root.resolve()).encode()).hexdigest()[:8]
            docker_kwargs["container_name"] = f"pydantic-deep-{dir_hash}-{workspace}"

        effective_backend: Any = DockerSandbox(**docker_kwargs)
    else:
        effective_backend = backend or LocalBackend(root_dir=root)

    # Build hooks list
    hooks: list[Hook] = []
    if effective_allow_list is not None:
        hooks.append(_make_shell_allow_list_hook(effective_allow_list))

    # Build middleware list
    middleware: list[Any] = []
    if extra_middleware:
        middleware.extend(extra_middleware)

    instructions = (
        DEFAULT_INSTRUCTIONS
        + "\n\n"
        + build_cli_instructions(
            non_interactive=non_interactive,
            lean=lean,
        )
    )

    # Append working directory context
    # When using Docker sandbox, the agent operates inside the container at /workspace
    instruction_root = "/workspace" if effective_sandbox == "docker" else str(root.resolve())
    working_dir_section = (
        f"\n\n## Working Directory\n\n"
        f"You are operating in: `{instruction_root}`\n\n"
        f"All file paths must be absolute, starting with `{instruction_root}`."
    )
    instructions += working_dir_section

    if extra_instructions:
        instructions += "\n\n" + extra_instructions

    # Add local context toolset (git info + directory tree)
    # Skipped for Docker/sandbox backends where root_dir doesn't exist on host
    local_context = None
    if include_local_context:
        from apps.cli.local_context import LocalContextToolset

        local_context = LocalContextToolset(root_dir=root)

    # Skills directories — searched in order, all matching dirs included:
    # 1. Bundled skills (shipped with CLI package)
    # 2. User-level skills (~/.pydantic-deep/skills/)
    # 3. Project-level skills (.pydantic-deep/skills/)
    # 4. Explicit override (--skills-dir flag)
    skill_dirs: list[str] = []
    if include_skills:
        # Bundled skills (always available)
        bundled = Path(__file__).resolve().parent / "skills"
        if bundled.is_dir():
            skill_dirs.append(str(bundled))

        # User-level skills (home directory)
        user_skills = Path.home() / ".pydantic-deep" / "skills"
        if user_skills.is_dir():
            skill_dirs.append(str(user_skills))

        # Project-level skills (working directory)
        project_skills_dir = root / ".pydantic-deep" / "skills"
        if project_skills_dir.is_dir():
            skill_dirs.append(str(project_skills_dir))

        # Explicit override (highest priority — appended last)
        if skills_dir:
            sd = Path(skills_dir)
            if sd.is_dir():
                skill_dirs.append(str(sd))

    # In non-interactive mode: no approval needed, disable interactive features
    # (memory, plan, subagents). Skills stay ON — they're static
    # instructions that improve benchmark performance.
    if non_interactive:
        interrupt_on: dict[str, bool] | None = {"execute": False}
    else:
        # Build interrupt_on from config.approve_tools
        interrupt_on = (
            {tool: True for tool in config.approve_tools} if config.approve_tools else None
        )

    # Resolve feature flags: explicit param > config.toml > lean override
    _skills = include_skills if include_skills is not None else config.include_skills
    _plan = include_plan if include_plan is not None else config.include_plan
    _memory = include_memory if include_memory is not None else config.include_memory
    _subagents = include_subagents if include_subagents is not None else config.include_subagents
    _todo = include_todo if include_todo is not None else config.include_todo
    _context_disc = context_discovery if context_discovery is not None else config.context_discovery

    effective_skills = _skills if not lean else False
    effective_plan = _plan if not lean else False
    effective_memory = _memory if not lean else False
    effective_subagents = _subagents if not lean else False
    effective_todo = _todo if not lean else False

    _browser = include_browser if include_browser is not None else config.include_browser
    effective_browser = _browser if not lean else False

    _liteparse = include_liteparse if include_liteparse is not None else config.include_liteparse
    effective_liteparse = _liteparse if not lean else False

    # Model settings — explicit param > model_settings dict > non-interactive > config
    effective_model_settings: dict[str, Any] = {}
    if non_interactive:
        effective_model_settings["temperature"] = 0.0
    if config.temperature is not None and "temperature" not in (model_settings or {}):
        effective_model_settings["temperature"] = config.temperature
    if config.reasoning_effort and "openai_reasoning_effort" not in (model_settings or {}):
        effective_model_settings["openai_reasoning_effort"] = config.reasoning_effort
    if model_settings:
        effective_model_settings.update(model_settings)
    # Explicit temperature param has highest priority
    if temperature is not None:
        effective_model_settings["temperature"] = temperature

    # Per-session plans directory (relative to backend root)
    if session_id:
        plans_dir = f".pydantic-deep/sessions/{session_id}/plans"
    else:
        plans_dir = ".pydantic-deep/plans"

    # Ensure session directory exists (for plans, messages.json)
    if session_id:
        from apps.cli.config import get_sessions_dir

        session_dir = get_sessions_dir() / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

    # Build extra capabilities list (browser, future additions)
    extra_capabilities: list[Any] = []
    if effective_browser:
        try:
            from pydantic_deep.capabilities.browser import BrowserCapability

            effective_headless = (
                browser_headless if browser_headless is not None else config.browser_headless
            )
            extra_capabilities.append(BrowserCapability(headless=effective_headless))
        except ImportError:
            import warnings

            warnings.warn(
                "BrowserCapability requires playwright. "
                "Install with: pip install 'pydantic-deep[browser]' && playwright install chromium",
                stacklevel=2,
            )

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
        include_builtin_subagents=effective_subagents,
        # Skills
        include_skills=effective_skills,
        # Memory (store in .pydantic-deep/main/MEMORY.md)
        include_memory=effective_memory,
        memory_dir=".pydantic-deep",
        # Context files (auto-discover AGENTS.md, SOUL.md)
        context_discovery=_context_disc if not lean else False,
        # Teams
        include_teams=(include_teams if include_teams is not None else config.include_teams),
        # Document parsing
        include_liteparse=effective_liteparse,
        # Self-improvement
        include_improve=True,
        # Web tools — explicit params override config
        web_search=(
            web_search if web_search is not None else (config.web_search if not lean else False)
        ),
        web_fetch=(
            web_fetch if web_fetch is not None else (config.web_fetch if not lean else False)
        ),
        # Thinking
        thinking=(
            thinking if thinking is not None else (config.thinking_effort if not lean else False)
        ),
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
        on_before_compress=on_before_compress,
        on_after_compress=on_after_compress,
        summarization_model=summarization_model,
        eviction_token_limit=20_000,
        on_eviction=on_eviction,
        # Cost tracking
        cost_tracking=True,
        on_cost_update=on_cost_update,
        # Output style
        output_style="concise" if not lean else None,
        # Middleware & hooks
        hooks=hooks or None,
        middleware=middleware or None,
        toolsets=[local_context] if local_context else None,
        capabilities=extra_capabilities or None,
    )

    # Extract context middleware for CLI commands (/compact, /context)
    context_mw = getattr(agent, "_context_middleware", None)
    task_mgr = getattr(agent, "_task_manager", None)

    deps = DeepAgentDeps(
        backend=effective_backend,
        context_middleware=context_mw,
    )
    deps._task_manager = task_mgr  # type: ignore[attr-defined]
    return agent, deps


__all__ = ["create_cli_agent"]
