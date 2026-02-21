"""Single SWE-bench instance execution."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from swebench_agent.prompt import SWEBENCH_SYSTEM_PROMPT, format_task_message
from swebench_agent.types import InstanceResult, RunConfig, SWEBenchInstance


def _create_sandbox(instance: SWEBenchInstance) -> Any:
    """Create a DockerSandbox for a SWE-bench instance."""
    from pydantic_ai_backends import DockerSandbox

    image = f"swebench/sweb.eval.x86_64.{instance.instance_id}:latest"
    return DockerSandbox(image=image, work_dir="/testbed", auto_remove=True)


def _extract_patch(sandbox: Any) -> str:
    """Extract git diff from the container."""
    result = sandbox.execute("cd /testbed && git diff", timeout=30)
    if result.exit_code == 0:
        return result.output.strip()
    return ""


async def run_instance(
    instance: SWEBenchInstance,
    config: RunConfig,
    *,
    verbose: bool = False,
) -> InstanceResult:
    """Run the agent on a single SWE-bench instance.

    Uses create_cli_agent with non_interactive=True and the SWE-bench
    Docker image as backend. After the agent finishes, extracts the
    git diff as the patch.
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
        sandbox = _create_sandbox(instance)
        sandbox.start()

        if verbose:
            print(f"  [{instance.instance_id}] Container started")

        model_settings: dict[str, Any] = {"temperature": config.temperature}
        if config.model_settings:
            model_settings.update(config.model_settings)

        agent, deps = create_cli_agent(
            model=config.model,
            backend=sandbox,
            on_cost_update=_on_cost,
            non_interactive=True,
            model_settings=model_settings,
            # Disable features that waste context on single-shot SWE-bench tasks
            include_skills=False,
            include_plan=False,
            include_memory=False,
            include_checkpoints=False,
            include_subagents=False,
            context_discovery=False,
        )

        task_message = format_task_message(instance)

        try:
            await asyncio.wait_for(
                agent.run(task_message, deps=deps),
                timeout=config.timeout,
            )
            if verbose:
                print(f"  [{instance.instance_id}] Agent finished")
        except asyncio.TimeoutError:
            if verbose:
                print(f"  [{instance.instance_id}] Timed out after {config.timeout}s")

        patch = _extract_patch(sandbox)

        if verbose:
            patch_lines = len(patch.splitlines()) if patch else 0
            print(f"  [{instance.instance_id}] Patch: {patch_lines} lines")

        return InstanceResult(
            instance_id=instance.instance_id,
            model_patch=patch,
            cost_usd=cost_usd,
            duration_seconds=time.monotonic() - start,
        )

    except Exception as e:
        if verbose:
            print(f"  [{instance.instance_id}] Error: {e}")
        return InstanceResult(
            instance_id=instance.instance_id,
            error=str(e),
            cost_usd=cost_usd,
            duration_seconds=time.monotonic() - start,
        )
    finally:
        if sandbox is not None:
            try:
                sandbox.stop()
            except Exception:
                pass
