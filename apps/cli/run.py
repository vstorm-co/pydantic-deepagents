"""Headless (non-interactive) runner for pydantic-deep.

Executes a single task without user interaction and returns the result.
Designed for benchmarks, CI/CD pipelines, and scripted automation.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from pydantic_ai.usage import Usage

from apps.cli.agent import create_cli_agent
from pydantic_deep.deps import DEFAULT_USAGE_LIMITS


async def execute_headless(  # noqa: C901
    *,
    task: str,
    working_dir: str,
    model: str | None = None,
    output_json: bool = False,
    max_turns: int | None = None,
    timeout: int | None = None,
    web_search: bool | None = None,
    web_fetch: bool | None = None,
    thinking: str | None = None,
    include_todo: bool | None = None,
    include_subagents: bool | None = None,
    include_skills: bool | None = None,
    include_plan: bool | None = None,
    include_memory: bool | None = None,
    include_teams: bool | None = None,
    context_discovery: bool | None = None,
    temperature: float | None = None,
    config_path: str | None = None,
) -> int:
    """Execute a task in headless mode and print the result.

    All feature flags default to ``None`` which means "use config.toml
    defaults" — the same defaults as the interactive TUI. Pass explicit
    values to override.

    Args:
        task: The task description to execute.
        working_dir: Filesystem root directory.
        model: Model override (default: from config).
        output_json: Whether to output result as JSON.
        max_turns: Maximum number of agent turns.
        timeout: Timeout in seconds.
        web_search: Enable web search. None = from config.
        web_fetch: Enable web fetch. None = from config.
        thinking: Thinking effort level. None = from config.
        include_todo: Enable todo tools. None = from config.
        include_subagents: Enable subagent tools. None = from config.
        include_skills: Enable skills. None = from config.
        include_plan: Enable plan mode. None = from config.
        include_memory: Enable persistent memory. None = from config.
        config_path: Override config file path.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    from pathlib import Path

    from apps.cli.init import ensure_initialized

    ensure_initialized(Path(working_dir))

    agent_kwargs: dict[str, Any] = {
        "model": model,
        "working_dir": working_dir,
        "non_interactive": True,
    }
    if config_path is not None:
        agent_kwargs["config_path"] = Path(config_path)
    # Only pass explicit overrides — None means "use config default"
    if web_search is not None:
        agent_kwargs["web_search"] = web_search
    if web_fetch is not None:
        agent_kwargs["web_fetch"] = web_fetch
    if thinking is not None:
        # "false" from CLI string → False bool
        agent_kwargs["thinking"] = False if thinking.lower() == "false" else thinking
    if include_todo is not None:
        agent_kwargs["include_todo"] = include_todo
    if include_subagents is not None:
        agent_kwargs["include_subagents"] = include_subagents
    if include_skills is not None:
        agent_kwargs["include_skills"] = include_skills
    if include_plan is not None:
        agent_kwargs["include_plan"] = include_plan
    if include_memory is not None:
        agent_kwargs["include_memory"] = include_memory
    if include_teams is not None:
        agent_kwargs["include_teams"] = include_teams
    if context_discovery is not None:
        agent_kwargs["context_discovery"] = context_discovery
    if temperature is not None:
        agent_kwargs["temperature"] = temperature

    agent, deps = create_cli_agent(**agent_kwargs)

    run_kwargs: dict[str, Any] = {
        "usage_limits": DEFAULT_USAGE_LIMITS,
    }
    if max_turns is not None:
        run_kwargs["max_turns"] = max_turns

    if timeout is not None:
        import asyncio

        try:
            result = await asyncio.wait_for(
                agent.run(task, deps=deps, **run_kwargs),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            _print_error("Timed out", output_json)
            return 1
    else:
        result = await agent.run(task, deps=deps, **run_kwargs)

    if output_json:
        output = _build_json_output(result.output, result.usage())
        print(json.dumps(output, indent=2, default=str))
    else:
        print(result.output)

    return 0


def _build_json_output(output: str, usage: Usage) -> dict[str, Any]:
    """Build a JSON-serializable output dict."""
    return {
        "output": output,
        "usage": {
            "total_tokens": usage.total_tokens,
            "request_tokens": usage.request_tokens,
            "response_tokens": usage.response_tokens,
            "requests": usage.requests,
        },
    }


def _print_error(message: str, output_json: bool) -> None:
    """Print an error message to stderr (or as JSON)."""
    if output_json:
        print(json.dumps({"error": message}), file=sys.stderr)
    else:
        print(f"Error: {message}", file=sys.stderr)
