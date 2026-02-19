# Harbor Agent — pydantic-deep on Terminal-Bench

Run pydantic-deep CLI on [Terminal-Bench 2.0](https://tbench.ai) via [Harbor](https://harborframework.com).

## Prerequisites

```bash
# Harbor is NOT a pydantic-deep dependency (requires Python >= 3.12).
# Install directly into your venv:
uv pip install harbor

# Docker must be running
docker --version
```

## Quick Start

Run from the **pydantic-deep repo root** (so `harbor_agent/` is importable):

```bash
# Set your API key
export OPENAI_API_KEY="sk-..."

# Verify harbor + oracle work first
harbor run -d terminal-bench@2.0 -a oracle -l 3

# Run pydantic-deep on terminal-bench
harbor run \
  -d terminal-bench@2.0 \
  -m openai/gpt-4.1 \
  --agent-import-path harbor_agent.pydantic_deep_agent:PydanticDeep

# Run a subset of tasks first (recommended)
harbor run \
  -d terminal-bench@2.0 \
  -m openai/gpt-4.1 \
  --agent-import-path harbor_agent.pydantic_deep_agent:PydanticDeep \
  -l 10

# Parallel execution
harbor run \
  -d terminal-bench@2.0 \
  -m openai/gpt-4.1 \
  --agent-import-path harbor_agent.pydantic_deep_agent:PydanticDeep \
  -n 8

# With Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
harbor run \
  -d terminal-bench@2.0 \
  -m anthropic/claude-sonnet-4-20250514 \
  --agent-import-path harbor_agent.pydantic_deep_agent:PydanticDeep
```

## How It Works

1. Harbor creates a Docker container for each task
2. `install-pydantic-deep.sh.j2` installs `uv` + `pydantic-deep[cli]` in the container
3. The agent runs: `pydantic-deep run "<instruction>" --model <provider:model>`
4. Harbor's verifier checks if the task was completed correctly

## Architecture

```
harbor_agent/
├── __init__.py                    # Package init
├── pydantic_deep_agent.py         # BaseInstalledAgent implementation
├── install-pydantic-deep.sh.j2    # Jinja2 container install script
└── README.md                      # This file
```

## Supported Providers

Any provider supported by pydantic-ai:

| Harbor `-m` flag | pydantic-ai model |
|---|---|
| `openai/gpt-4.1` | `openai:gpt-4.1` |
| `anthropic/claude-sonnet-4-20250514` | `anthropic:claude-sonnet-4-20250514` |
| `google/gemini-2.5-pro` | `google:gemini-2.5-pro` |
| `groq/llama-3.3-70b` | `groq:llama-3.3-70b` |

## Leaderboard

Submit results to the [Terminal-Bench 2 Leaderboard](https://huggingface.co/datasets/alexgshaw/terminal-bench-2-leaderboard).
