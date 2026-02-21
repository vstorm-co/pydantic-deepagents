# SWE-bench Agent

Evaluate pydantic-deep on [SWE-bench](https://www.swebench.com/) — a benchmark of real GitHub issues from popular Python repos (Django, Flask, scikit-learn, sympy, etc.).

The agent receives an issue description, explores the codebase inside a Docker container, makes code changes, and produces a `git diff` patch. The patch is then evaluated by running the project's test suite.

## Quick Start

```bash
# Install dependencies
pip install pydantic-deep[swebench,sandbox]

# Run on a single instance (debug)
pydantic-deep swebench run \
    -m openrouter:openai/gpt-4.1 \
    -i django__django-16379

# Run on SWE-bench Verified (500 instances)
pydantic-deep swebench run \
    -m anthropic:claude-sonnet-4 \
    -w 8 \
    -o predictions.jsonl

# Evaluate results
pydantic-deep swebench evaluate predictions.jsonl
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
│     image: swebench/sweb.eval.x86_64.*  │
│     work_dir: /testbed                  │
│                                         │
│  2. Run pydantic-deep agent             │
│     create_cli_agent(                   │
│       backend=DockerSandbox,            │
│       non_interactive=True              │
│     )                                   │
│                                         │
│  3. Extract patch: git diff             │
│                                         │
│  4. Stop container                      │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│  Write JSONL     │  predictions.jsonl
│  Print summary   │
└─────────────────┘
```

## CLI Reference

### `pydantic-deep swebench run`

| Flag | Default | Description |
|------|---------|-------------|
| `-m, --model` | from config | Model to use (e.g. `openrouter:openai/gpt-4.1`) |
| `-d, --dataset` | `princeton-nlp/SWE-bench_Verified` | HuggingFace dataset |
| `--split` | `test` | Dataset split |
| `-i, --instance` | all | Specific instance IDs (repeatable) |
| `-w, --workers` | `1` | Max parallel instances |
| `--timeout` | `300` | Per-instance timeout in seconds |
| `-o, --output` | `predictions.jsonl` | Output JSONL path |
| `-t, --temperature` | `0.0` | Model temperature |
| `--cost-budget` | unlimited | Max total cost in USD |
| `-v, --verbose` | off | Verbose per-instance output |
| `--model-settings` | none | Model settings as JSON string |

### `pydantic-deep swebench evaluate`

Wraps `python -m swebench.harness.run_evaluation`.

| Argument/Flag | Default | Description |
|---------------|---------|-------------|
| `predictions` | required | Path to predictions JSONL |
| `-d, --dataset` | `princeton-nlp/SWE-bench_Verified` | HuggingFace dataset |
| `--split` | `test` | Dataset split |
| `-w, --workers` | `4` | Parallel evaluation workers |

## SWE-bench Variants

| Variant | Instances | Description |
|---------|-----------|-------------|
| **SWE-bench Full** | 2,294 | Complete dataset |
| **SWE-bench Verified** | 500 | Human-verified as solvable (default) |
| **SWE-bench Lite** | 300 | Smaller subset for quick testing |

```bash
# Use Lite for faster iteration
pydantic-deep swebench run -d princeton-nlp/SWE-bench_Lite -m openai:gpt-4.1

# Use Full for comprehensive evaluation
pydantic-deep swebench run -d princeton-nlp/SWE-bench -m openai:gpt-4.1
```

## Prerequisites

- **Docker** — SWE-bench uses per-instance Docker images (~2-5 GB each)
- **HuggingFace token** — for downloading the dataset (set `HF_TOKEN`)
- **Model API key** — for the LLM provider you choose

Pull SWE-bench images before running:

```bash
# Pull a single instance image
docker pull swebench/sweb.eval.x86_64.django__django-16379:latest
```

## Output Format

The predictions JSONL follows the standard SWE-bench format:

```json
{"instance_id": "django__django-16379", "model_name_or_path": "openai:gpt-4.1", "model_patch": "diff --git a/..."}
```

## Architecture

| Module | Description |
|--------|-------------|
| `types.py` | Data models: `SWEBenchInstance`, `Prediction`, `RunConfig`, `InstanceResult` |
| `prompt.py` | SWE-bench system prompt and task message formatting |
| `instance.py` | Single instance execution — `create_cli_agent` + `DockerSandbox` + `git diff` |
| `runner.py` | Orchestration — load dataset, parallel execution, write JSONL |
| `cli.py` | Typer commands wired into `pydantic-deep swebench` |
