# SWE-bench Agent

Evaluate pydantic-deep on [SWE-bench](https://www.swebench.com/) — a benchmark of real GitHub issues from popular Python repos (Django, Flask, scikit-learn, sympy, etc.).

Uses the **same agent and prompt** as `pydantic-deep run` / Terminal-Bench (`create_cli_agent` with `non_interactive=True`). The only difference is the backend: `DockerSandbox` pointed at a SWE-bench Docker image with `/testbed` as working directory.

## Quick Start

```bash
# Install dependencies
pip install pydantic-deep[swebench,sandbox]

# Run on a single instance
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -i django__django-16950 \
    --timeout 600 -v

# Run on SWE-bench Verified (500 instances)
pydantic-deep swebench run \
    -m openrouter:minimax/minimax-m2.5 \
    --reasoning \
    -w 8 \
    --timeout 600 \
    -o all_preds.jsonl \
    --trajs-dir trajs/

# Evaluate results
pydantic-deep swebench evaluate all_preds.jsonl
```

## How It Works

```
pydantic-deep swebench run
        │
        ▼
┌─────────────────┐
│  Load dataset    │  HuggingFace: princeton-nlp/SWE-bench_Verified
│  (500 instances) │
└────────┬────────┘
         │
         ▼  (per instance, parallel with --workers)
┌─────────────────────────────────────────┐
│  1. Start Docker container              │
│     image: ghcr.io/epoch-research/...   │
│     work_dir: /testbed                  │
│                                         │
│  2. Run pydantic-deep agent             │
│     create_cli_agent(                   │
│       backend=DockerSandbox,            │
│       working_dir="/testbed",           │
│       non_interactive=True              │
│     )                                   │
│                                         │
│  3. Extract patch: git diff             │
│  4. Save trajectory                     │
│  5. Stop container                      │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│  Write JSONL     │  all_preds.jsonl
│  Write trajs/    │  per-instance markdown
│  Print summary   │
└─────────────────┘
```

## CLI Reference

### `pydantic-deep swebench run`

| Flag | Default | Description |
|------|---------|-------------|
| `-m, --model` | from config | Model to use |
| `-r, --reasoning` | off | Enable reasoning/thinking mode |
| `--reasoning-effort` | `high` | Reasoning effort: high, medium, low |
| `-d, --dataset` | `princeton-nlp/SWE-bench_Verified` | HuggingFace dataset |
| `-i, --instance` | all | Specific instance IDs (repeatable) |
| `-w, --workers` | `1` | Max parallel instances |
| `--timeout` | `300` | Per-instance timeout in seconds |
| `-o, --output` | `predictions.jsonl` | Output JSONL path |
| `--trajs-dir` | none | Directory for trajectory files |
| `--image` | Epoch AI ghcr.io | Docker image template |
| `-v, --verbose` | off | Verbose per-instance output |
| `--model-settings` | none | Model settings as JSON string |

### `pydantic-deep swebench evaluate`

| Argument/Flag | Default | Description |
|---------------|---------|-------------|
| `predictions` | required | Path to predictions JSONL |
| `--run-id` | `pydantic-deep` | Unique run identifier |
| `-d, --dataset` | `princeton-nlp/SWE-bench_Verified` | HuggingFace dataset |
| `-w, --workers` | `4` | Parallel evaluation workers |
| `--timeout` | `1800` | Per-instance eval timeout |
| `--cache-level` | `env` | Docker cache level |

### `pydantic-deep swebench list`

List available instances, optionally filtered by repo.

## Architecture

| Module | Description |
|--------|-------------|
| `types.py` | Data models: `SWEBenchInstance`, `Prediction`, `RunConfig`, `InstanceResult` |
| `instance.py` | Single instance execution — `create_cli_agent` + `DockerSandbox` + `git diff` + trajectory |
| `runner.py` | Orchestration — load dataset, parallel execution, write JSONL + trajectories |
| `cli.py` | Typer commands wired into `pydantic-deep swebench` |
