"""CLI commands for SWE-bench evaluation.

Usage:
    pydantic-deep swebench run -m openrouter:openai/gpt-4.1 -i django__django-16379
    pydantic-deep swebench run -m anthropic:claude-sonnet-4 -w 8 -o predictions.jsonl
    pydantic-deep swebench evaluate predictions.jsonl
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import typer

swebench_app = typer.Typer(
    name="swebench",
    help="SWE-bench evaluation — test pydantic-deep on real GitHub issues.",
    no_args_is_help=True,
)


@swebench_app.command("run")
def swebench_run(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (e.g. openrouter:openai/gpt-4.1)"),
    ] = None,
    dataset: Annotated[
        str,
        typer.Option("--dataset", "-d", help="HuggingFace dataset name"),
    ] = "princeton-nlp/SWE-bench_Verified",
    split: Annotated[
        str,
        typer.Option("--split", help="Dataset split"),
    ] = "test",
    instance: Annotated[
        list[str] | None,
        typer.Option("--instance", "-i", help="Specific instance IDs (repeatable)"),
    ] = None,
    workers: Annotated[
        int,
        typer.Option("--workers", "-w", help="Max parallel instances"),
    ] = 1,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Per-instance timeout in seconds"),
    ] = 300,
    output: Annotated[
        str,
        typer.Option("--output", "-o", help="Output JSONL file path"),
    ] = "predictions.jsonl",
    temperature: Annotated[
        float,
        typer.Option("--temperature", "-t", help="Model temperature"),
    ] = 0.0,
    cost_budget: Annotated[
        float | None,
        typer.Option("--cost-budget", help="Max total cost in USD"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose per-instance output"),
    ] = False,
    image: Annotated[
        str | None,
        typer.Option("--image", help="Docker image template (default: Epoch AI ghcr.io)"),
    ] = None,
    trajs_dir: Annotated[
        str | None,
        typer.Option("--trajs-dir", help="Directory for trajectory files (per-instance tool call logs)"),
    ] = None,
    model_settings_json: Annotated[
        str | None,
        typer.Option("--model-settings", help="Model settings as JSON"),
    ] = None,
) -> None:
    """Run pydantic-deep agent on SWE-bench instances."""
    import json

    from swebench_agent.runner import run_swebench
    from swebench_agent.types import RunConfig

    effective_model = model
    if not effective_model:
        from cli.config import load_config

        config = load_config()
        effective_model = config.model

    ms: dict[str, Any] | None = None
    if model_settings_json:
        ms = json.loads(model_settings_json)

    run_config = RunConfig(
        model=effective_model,
        dataset=dataset,
        split=split,
        instance_ids=list(instance) if instance else [],
        workers=workers,
        timeout=timeout,
        output_path=output,
        temperature=temperature,
        cost_budget_usd=cost_budget,
        model_settings=ms,
        image_template=image,
        trajs_dir=trajs_dir,
    )

    asyncio.run(run_swebench(run_config, verbose=verbose))


@swebench_app.command("list")
def swebench_list(
    dataset: Annotated[
        str,
        typer.Option("--dataset", "-d", help="HuggingFace dataset name"),
    ] = "princeton-nlp/SWE-bench_Verified",
    split: Annotated[
        str,
        typer.Option("--split", help="Dataset split"),
    ] = "test",
    repo: Annotated[
        str | None,
        typer.Option("--repo", "-r", help="Filter by repo (e.g. django/django)"),
    ] = None,
) -> None:
    """List available SWE-bench instances."""
    from rich.console import Console
    from rich.table import Table

    from swebench_agent.runner import load_dataset
    from swebench_agent.types import RunConfig

    console = Console()
    console.print(f"Loading dataset [cyan]{dataset}[/cyan]...")

    config = RunConfig(dataset=dataset, split=split)
    instances = load_dataset(config)

    if repo:
        instances = [i for i in instances if repo.lower() in i.repo.lower()]

    if not instances:
        console.print("[red]No instances found.[/red]")
        raise typer.Exit(1)

    # Group by repo
    repos: dict[str, int] = {}
    for inst in instances:
        repos[inst.repo] = repos.get(inst.repo, 0) + 1

    # Summary table
    summary = Table(show_header=True, header_style="bold", title="Repos")
    summary.add_column("Repo", style="cyan")
    summary.add_column("Count", justify="right")
    for r, count in sorted(repos.items(), key=lambda x: -x[1]):
        summary.add_row(r, str(count))
    summary.add_row("[bold]Total[/bold]", f"[bold]{len(instances)}[/bold]")
    console.print(summary)

    # Instance list (truncated if large)
    if len(instances) <= 100 or repo:
        console.print()
        table = Table(show_header=True, header_style="bold")
        table.add_column("Instance ID", style="cyan")
        table.add_column("Repo")
        table.add_column("Version")
        for inst in instances:
            table.add_row(inst.instance_id, inst.repo, inst.version)
        console.print(table)
    else:
        console.print(f"\n[dim]Showing repos only ({len(instances)} instances). "
                       f"Use --repo to filter.[/dim]")


@swebench_app.command("evaluate")
def swebench_evaluate(
    predictions: Annotated[
        str,
        typer.Argument(help="Path to predictions JSONL file"),
    ],
    run_id: Annotated[
        str,
        typer.Option("--run-id", "-id", help="Unique run identifier"),
    ] = "pydantic-deep",
    dataset: Annotated[
        str,
        typer.Option("--dataset", "-d", help="HuggingFace dataset name"),
    ] = "princeton-nlp/SWE-bench_Verified",
    split: Annotated[
        str,
        typer.Option("--split", help="Dataset split"),
    ] = "test",
    workers: Annotated[
        int,
        typer.Option("--workers", "-w", help="Max parallel evaluation workers"),
    ] = 4,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Per-instance evaluation timeout in seconds"),
    ] = 1800,
    cache_level: Annotated[
        str,
        typer.Option("--cache-level", help="Docker cache level (none, base, env, instance)"),
    ] = "env",
) -> None:
    """Evaluate predictions using the SWE-bench harness.

    Wraps ``python -m swebench.harness.run_evaluation``.
    """
    import subprocess
    import sys

    cmd = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "-p",
        predictions,
        "-d",
        dataset,
        "-s",
        split,
        "-id",
        run_id,
        "--max_workers",
        str(workers),
        "-t",
        str(timeout),
        "--cache_level",
        cache_level,
    ]

    typer.echo(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)
