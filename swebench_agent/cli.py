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
    )

    asyncio.run(run_swebench(run_config, verbose=verbose))


@swebench_app.command("evaluate")
def swebench_evaluate(
    predictions: Annotated[
        str,
        typer.Argument(help="Path to predictions JSONL file"),
    ],
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
        "--predictions_path",
        predictions,
        "--swe_bench_tasks",
        dataset,
        "--split",
        split,
        "--max_workers",
        str(workers),
    ]

    typer.echo(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)
