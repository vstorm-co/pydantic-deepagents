"""SWE-bench evaluation orchestration."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from swebench_agent.instance import run_instance
from swebench_agent.types import InstanceResult, Prediction, RunConfig, SWEBenchInstance


def load_dataset(config: RunConfig) -> list[SWEBenchInstance]:
    """Load SWE-bench instances from HuggingFace datasets.

    Args:
        config: Run configuration with dataset name, split, and optional filters.

    Returns:
        List of SWEBenchInstance objects.
    """
    from datasets import load_dataset as hf_load_dataset

    ds = hf_load_dataset(config.dataset, split=config.split)

    instances: list[SWEBenchInstance] = []
    for row in ds:
        # NOTE: We load hints_text, FAIL_TO_PASS, PASS_TO_PASS for metadata only.
        # These are NOT passed to the agent (see format_task_message in prompt.py).
        # SWE-bench rules forbid using these fields for official submissions.
        instance = SWEBenchInstance(
            instance_id=row["instance_id"],
            repo=row["repo"],
            base_commit=row["base_commit"],
            problem_statement=row["problem_statement"],
            hints_text=row.get("hints_text", ""),
            patch=row.get("patch", ""),
            test_patch=row.get("test_patch", ""),
            FAIL_TO_PASS=row.get("FAIL_TO_PASS", ""),
            PASS_TO_PASS=row.get("PASS_TO_PASS", ""),
            version=row.get("version", ""),
            environment_setup_commit=row.get("environment_setup_commit", ""),
        )
        instances.append(instance)

    # Filter by instance IDs if specified
    if config.instance_ids:
        id_set = set(config.instance_ids)
        # Support prefix matching (e.g. "django__django" matches all django instances)
        filtered = []
        for inst in instances:
            if inst.instance_id in id_set:
                filtered.append(inst)
            else:
                for prefix in id_set:
                    if inst.instance_id.startswith(prefix):
                        filtered.append(inst)
                        break
        instances = filtered

    return instances


def write_predictions(
    results: list[InstanceResult],
    config: RunConfig,
) -> Path:
    """Write predictions to JSONL file.

    Args:
        results: List of instance results.
        config: Run configuration (for model name and output path).

    Returns:
        Path to the written JSONL file.
    """
    output_path = Path(config.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        for result in results:
            if result.error and not result.model_patch:
                continue  # Skip errored instances with no patch

            prediction = Prediction(
                instance_id=result.instance_id,
                model_name_or_path=config.model,
                model_patch=result.model_patch,
            )
            f.write(json.dumps(prediction.to_dict()) + "\n")

    return output_path


def write_trajectories(
    results: list[InstanceResult],
    trajs_dir: str,
) -> Path:
    """Write per-instance trajectory markdown files.

    Args:
        results: List of instance results with trajectory data.
        trajs_dir: Directory to write trajectory files.

    Returns:
        Path to the trajectories directory.
    """
    trajs_path = Path(trajs_dir)
    trajs_path.mkdir(parents=True, exist_ok=True)

    for result in results:
        if not result.trajectory:
            continue
        traj_file = trajs_path / f"{result.instance_id}.md"
        traj_file.write_text(result.trajectory)

    return trajs_path


def _print_summary(
    results: list[InstanceResult],
    config: RunConfig,
    total_duration: float,
) -> None:
    """Print a summary of the evaluation run."""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    total = len(results)
    patched = sum(1 for r in results if r.model_patch)
    errored = sum(1 for r in results if r.error)
    total_cost = sum(r.cost_usd for r in results)

    console.print()
    console.print("[bold]SWE-bench Run Summary[/bold]")
    console.print()

    table = Table(show_header=False, show_lines=False, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")

    table.add_row("Model", config.model)
    table.add_row("Dataset", config.dataset)
    table.add_row("Instances", f"{total}")
    table.add_row("Patched", f"{patched}/{total}")
    table.add_row("Errors", f"{errored}")
    table.add_row("Total Cost", f"${total_cost:.4f}")
    table.add_row("Total Time", f"{total_duration:.1f}s")
    table.add_row("Output", config.output_path)

    console.print(table)

    # Per-instance details
    if total <= 50:
        console.print()
        detail_table = Table(show_header=True, header_style="bold", show_lines=False)
        detail_table.add_column("Instance", style="cyan")
        detail_table.add_column("Patch Lines", justify="right")
        detail_table.add_column("Cost", justify="right")
        detail_table.add_column("Time", justify="right")
        detail_table.add_column("Status")

        for r in results:
            patch_lines = len(r.model_patch.splitlines()) if r.model_patch else 0
            status = "[red]error[/red]" if r.error else "[green]ok[/green]"
            if not r.model_patch and not r.error:
                status = "[yellow]no patch[/yellow]"

            detail_table.add_row(
                r.instance_id,
                str(patch_lines),
                f"${r.cost_usd:.4f}",
                f"{r.duration_seconds:.1f}s",
                status,
            )

        console.print(detail_table)


async def run_swebench(
    config: RunConfig,
    *,
    verbose: bool = False,
) -> list[InstanceResult]:
    """Run SWE-bench evaluation.

    Loads the dataset, runs instances in parallel (bounded by workers),
    writes predictions, and prints a summary.

    Args:
        config: Run configuration.
        verbose: Print per-instance progress.

    Returns:
        List of InstanceResult objects.
    """
    from rich.console import Console

    console = Console()

    # Load dataset
    console.print(f"Loading dataset [cyan]{config.dataset}[/cyan]...")
    instances = load_dataset(config)

    if not instances:
        if config.instance_ids:
            # Load all IDs to suggest similar ones
            all_instances = load_dataset(RunConfig(
                dataset=config.dataset, split=config.split,
                model=config.model,
            ))
            all_ids = [i.instance_id for i in all_instances]
            # Find similar IDs (prefix match)
            for wanted in config.instance_ids:
                similar = [i for i in all_ids if wanted.split("-")[0] in i][:5]
                if similar:
                    console.print(
                        f"[red]Instance '{wanted}' not found.[/red] "
                        f"Similar: {', '.join(similar)}"
                    )
                else:
                    console.print(f"[red]Instance '{wanted}' not found in {config.dataset}.[/red]")
            console.print(f"\n[dim]Use 'pydantic-deep swebench list' to see available instances.[/dim]")
        else:
            console.print("[red]No instances found.[/red]")
        return []

    console.print(f"Found [bold]{len(instances)}[/bold] instances")
    console.print(
        f"Running with model=[cyan]{config.model}[/cyan] "
        f"workers=[cyan]{config.workers}[/cyan] "
        f"timeout=[cyan]{config.timeout}s[/cyan]"
    )
    console.print()

    # Run instances with bounded parallelism
    semaphore = asyncio.Semaphore(config.workers)
    start = time.monotonic()

    async def _run_bounded(instance: SWEBenchInstance) -> InstanceResult:
        async with semaphore:
            console.print(f"  Starting [cyan]{instance.instance_id}[/cyan]...")
            result = await run_instance(instance, config, verbose=verbose)

            patch_lines = len(result.model_patch.splitlines()) if result.model_patch else 0
            if result.error:
                status = f"[red]error[/red]"
                console.print(
                    f"  Finished [cyan]{instance.instance_id}[/cyan] "
                    f"({result.duration_seconds:.1f}s) {status}"
                )
                console.print(f"    [red]{result.error}[/red]")
            else:
                status = "[green]ok[/green]"
                console.print(
                    f"  Finished [cyan]{instance.instance_id}[/cyan] "
                    f"({patch_lines} lines, ${result.cost_usd:.4f}, "
                    f"{result.duration_seconds:.1f}s) {status}"
                )
            return result

    results = await asyncio.gather(*[_run_bounded(inst) for inst in instances])
    total_duration = time.monotonic() - start

    # Write predictions
    output_path = write_predictions(list(results), config)
    console.print(f"\nPredictions written to [bold]{output_path}[/bold]")

    # Write trajectories
    if config.trajs_dir:
        trajs_path = write_trajectories(list(results), config.trajs_dir)
        traj_count = sum(1 for r in results if r.trajectory)
        console.print(f"Trajectories written to [bold]{trajs_path}[/bold] ({traj_count} files)")

    # Summary
    _print_summary(list(results), config, total_duration)

    return list(results)
