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

            status = "[green]ok[/green]" if not result.error else f"[red]{result.error[:50]}[/red]"
            patch_lines = len(result.model_patch.splitlines()) if result.model_patch else 0
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

    # Summary
    _print_summary(list(results), config, total_duration)

    return list(results)
