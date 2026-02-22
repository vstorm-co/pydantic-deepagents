"""Single SWE-bench instance execution."""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any

from swebench_agent.prompt import format_task_message
from swebench_agent.types import InstanceResult, RunConfig, SWEBenchInstance

# Image registries (Epoch AI images are ~10x smaller than official ones)
EPOCH_IMAGE = "ghcr.io/epoch-research/swe-bench.eval.x86_64.{instance_id}"
OFFICIAL_IMAGE = "swebench/sweb.eval.x86_64.{instance_id}:latest"

DEFAULT_IMAGE_TEMPLATE = EPOCH_IMAGE


def _create_sandbox(
    instance: SWEBenchInstance,
    image_template: str = DEFAULT_IMAGE_TEMPLATE,
) -> Any:
    """Create a DockerSandbox for a SWE-bench instance."""
    from pydantic_ai_backends import DockerSandbox

    image = image_template.format(instance_id=instance.instance_id)
    return DockerSandbox(image=image, work_dir="/testbed", auto_remove=True)


def _extract_patch(sandbox: Any) -> str:
    """Extract git diff from the container."""
    result = sandbox.execute("cd /testbed && git diff", timeout=30)
    if result.exit_code == 0:
        return result.output.strip()
    return ""


async def _run_agent_streaming(
    agent: Any,
    message: str,
    deps: Any,
    instance_id: str,
    verbose: bool,
) -> list[dict[str, str]]:
    """Run agent with streaming — shows tool calls and captures trajectory.

    Returns list of trajectory entries (dicts with 'type', 'tool', 'content').
    """
    from pydantic_ai import (
        FunctionToolCallEvent,
        FunctionToolResultEvent,
    )
    from pydantic_ai.usage import UsageLimits

    trajectory: list[dict[str, str]] = []

    async for event in agent.run_stream_events(
        message, deps=deps, usage_limits=UsageLimits(request_limit=200)
    ):
        if isinstance(event, FunctionToolCallEvent):
            tool_name = event.part.tool_name
            args = event.part.args if isinstance(event.part.args, dict) else {}
            short_args = ""
            for key in ("command", "path", "file_path", "pattern", "query"):
                if key in args:
                    val = str(args[key])
                    if len(val) > 80:
                        val = val[:77] + "..."
                    short_args = f" {val}"
                    break

            # Full args for trajectory (truncated for readability)
            args_str = str(args)
            if len(args_str) > 500:
                args_str = args_str[:497] + "..."

            trajectory.append({
                "type": "tool_call",
                "tool": tool_name,
                "content": args_str,
            })

            if verbose:
                print(f"    [{instance_id}] {tool_name}{short_args}")

        elif isinstance(event, FunctionToolResultEvent):
            tool_name = getattr(event.result, "tool_name", "")
            content = str(event.result.content)

            # Trajectory gets more content than verbose output
            traj_content = content
            if len(traj_content) > 2000:
                traj_content = traj_content[:1997] + "..."

            if tool_name:
                trajectory.append({
                    "type": "tool_result",
                    "tool": tool_name,
                    "content": traj_content,
                })

            if verbose and tool_name:
                display = content[:117] + "..." if len(content) > 120 else content
                print(f"    [{instance_id}]   -> {display}")

    return trajectory


def _format_trajectory(
    instance: SWEBenchInstance,
    entries: list[dict[str, str]],
    patch: str,
    cost_usd: float,
    duration: float,
    *,
    timed_out: bool = False,
    error: str | None = None,
) -> str:
    """Format trajectory entries as a markdown document."""
    lines = [
        f"# {instance.instance_id}",
        "",
        f"**Repository**: {instance.repo}",
        f"**Duration**: {duration:.1f}s",
        f"**Cost**: ${cost_usd:.4f}",
    ]
    if timed_out:
        lines.append("**Status**: Timed out")
    elif error:
        lines.append(f"**Status**: Error — {error}")
    else:
        lines.append("**Status**: Completed")

    patch_lines = len(patch.splitlines()) if patch else 0
    lines.append(f"**Patch**: {patch_lines} lines")
    lines.append("")

    # Tool call trace
    lines.append("## Tool Calls")
    lines.append("")

    step = 0
    for entry in entries:
        if entry["type"] == "tool_call":
            step += 1
            lines.append(f"### Step {step}: `{entry['tool']}`")
            lines.append("")
            lines.append("```")
            lines.append(entry["content"])
            lines.append("```")
            lines.append("")
        elif entry["type"] == "tool_result":
            lines.append(f"**Result** (`{entry['tool']}`):")
            lines.append("")
            lines.append("```")
            lines.append(entry["content"])
            lines.append("```")
            lines.append("")

    # Patch at the end
    if patch:
        lines.append("## Patch")
        lines.append("")
        lines.append("```diff")
        lines.append(patch)
        lines.append("```")

    return "\n".join(lines)


async def run_instance(
    instance: SWEBenchInstance,
    config: RunConfig,
    *,
    verbose: bool = False,
) -> InstanceResult:
    """Run the agent on a single SWE-bench instance.

    Same configuration as ``pydantic-deep run`` (Terminal-Bench):
    create_cli_agent with non_interactive=True and DockerSandbox as backend.
    After the agent finishes, extracts git diff as the patch.
    """
    from cli.agent import create_cli_agent

    start = time.monotonic()
    sandbox = None
    cost_usd = 0.0

    def _on_cost(cost_info: Any) -> None:
        nonlocal cost_usd
        val = getattr(cost_info, "cumulative_cost_usd", None)
        if isinstance(val, (int, float)):
            cost_usd = val

    try:
        template = config.image_template or DEFAULT_IMAGE_TEMPLATE
        sandbox = _create_sandbox(instance, image_template=template)
        sandbox.start()

        if verbose:
            print(f"  [{instance.instance_id}] Container started")

        model_settings: dict[str, Any] = {"temperature": config.temperature}
        if config.model_settings:
            model_settings.update(config.model_settings)

        # Same config as `pydantic-deep run` / Terminal-Bench
        agent, deps = create_cli_agent(
            model=config.model,
            backend=sandbox,
            on_cost_update=_on_cost,
            non_interactive=True,
            model_settings=model_settings,
        )

        if verbose:
            print(f"  [{instance.instance_id}] Agent running...")

        task_message = format_task_message(instance)
        traj_entries: list[dict[str, str]] = []
        timed_out = False

        try:
            traj_entries = await asyncio.wait_for(
                _run_agent_streaming(
                    agent, task_message, deps, instance.instance_id, verbose
                ),
                timeout=config.timeout,
            )
            if verbose:
                print(f"  [{instance.instance_id}] Agent finished (cost=${cost_usd:.4f})")
        except asyncio.TimeoutError:
            timed_out = True
            if verbose:
                print(f"  [{instance.instance_id}] Timed out after {config.timeout}s")

        patch = _extract_patch(sandbox)

        if verbose:
            patch_lines = len(patch.splitlines()) if patch else 0
            print(f"  [{instance.instance_id}] Patch: {patch_lines} lines")

        trajectory = _format_trajectory(
            instance, traj_entries, patch, cost_usd,
            time.monotonic() - start, timed_out=timed_out,
        )

        return InstanceResult(
            instance_id=instance.instance_id,
            model_patch=patch,
            cost_usd=cost_usd,
            duration_seconds=time.monotonic() - start,
            trajectory=trajectory,
        )

    except Exception as e:
        tb = traceback.format_exc()
        error_msg = f"{type(e).__name__}: {e}"
        if verbose:
            print(f"  [{instance.instance_id}] Error: {error_msg}")
            print(f"  [{instance.instance_id}] Traceback:\n{tb}")

        # Still try to extract patch — agent may have made edits before erroring
        patch = ""
        if sandbox is not None:
            try:
                patch = _extract_patch(sandbox)
                if verbose and patch:
                    print(f"  [{instance.instance_id}] Recovered patch: {len(patch.splitlines())} lines")
            except Exception:
                pass

        elapsed = time.monotonic() - start
        trajectory = _format_trajectory(
            instance, [], patch, cost_usd, elapsed, error=error_msg,
        )

        return InstanceResult(
            instance_id=instance.instance_id,
            model_patch=patch,
            error=error_msg,
            cost_usd=cost_usd,
            duration_seconds=elapsed,
            trajectory=trajectory,
        )
    finally:
        if sandbox is not None:
            try:
                sandbox.stop()
            except Exception:
                pass
