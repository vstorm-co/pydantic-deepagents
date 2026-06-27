# Harbor (Terminal Bench)

Harbor lets you evaluate a pydantic-deep agent on [Terminal-Bench](https://www.tbench.ai/) — the benchmark that scores agents on real, end-to-end terminal tasks inside isolated containers.

This is a small reference adapter. It plugs the pydantic-deep CLI into Harbor's installed-agent interface so the benchmark can install, run, and score your agent without you writing any glue.

## What it does

The adapter is a single class, `PydanticDeepAgent`, that implements Harbor's `BaseInstalledAgent`. Harbor drives it through three phases for every task:

1. **Install** — spins up a fresh container, installs `uv`, creates a virtualenv at `/opt/pydantic-deep-venv`, and `pip install`s `pydantic-deep[cli]` straight from the GitHub repo.
2. **Run** — invokes `pydantic-deep run` in **headless mode** (`--json --verbose`) with the task instruction, forwarding your API keys into the container.
3. **Post-run** — parses the agent's stdout for token usage and USD cost and reports them back to Harbor.

You bring a model and your API keys; the adapter handles the rest.

## Run an evaluation

The adapter's module docstring documents the entrypoint. Point Harbor at it with `--agent-import-path`:

<div class="termy">

```console
$ harbor run -d "terminal-bench@2.0" \
    -m anthropic/claude-opus-4-6 \
    --agent-import-path apps.harbor.agent:PydanticDeepAgent
```

</div>

That's the whole loop: Harbor pulls the Terminal-Bench dataset, builds a container per task, installs pydantic-deep, runs it against each instruction, and scores the result.

!!! note "Model names are converted for you"
    Harbor passes models as `provider/model`. The adapter rewrites them to
    pydantic-ai's `provider:model` form — so `anthropic/claude-opus-4-6`
    becomes `anthropic:claude-opus-4-6`. A bare name or one that already uses
    `:` is passed through unchanged.

## API keys

Before the run, the adapter collects API-key environment variables from your host (loading a `.env` file if `python-dotenv` is installed) and forwards them into the container. Set whichever your model needs, for example:

<div class="termy">

```console
$ export ANTHROPIC_API_KEY=sk-ant-...
```

</div>

A broad set is supported, including `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, the AWS Bedrock and Azure OpenAI variables, and `LOGFIRE_TOKEN`. Only keys that are actually set are forwarded.

## Tuning the agent

`PydanticDeepAgent` accepts constructor arguments that map onto pydantic-deep's CLI flags. Pass them through Harbor's agent-kwargs (`--ak`):

- `max_turns`, `timeout` — run limits.
- `temperature`, `thinking` — model behavior.
- `web_search`, `web_fetch`, `todo`, `subagents`, `skills`, `plan`, `memory`, `teams`, `context` — boolean feature toggles, each emitted as `--flag` / `--no-flag`.

Leave a flag unset to keep pydantic-deep's own default for that feature.

!!! tip "Pin a specific revision"
    By default the adapter installs from the `main` branch. Set
    `PYDANTIC_DEEP_GIT_REF` to a branch, tag, or commit SHA to benchmark a
    specific revision — useful for comparing changes across runs.

## How results come back

After a task finishes, the adapter reads the captured stdout and:

- parses the `--json` block to pull `usage.total_tokens`, and
- scans for a `Cost: $…` line to recover the USD cost.

Both land on Harbor's `AgentContext`, so token and cost numbers show up alongside Terminal-Bench's pass/fail scoring.

## Recap

- Harbor adapts the pydantic-deep CLI for **Terminal-Bench** evaluation through one class, `PydanticDeepAgent`.
- It **installs** pydantic-deep in a container, **runs** it headless with `--json --verbose`, and **reports** tokens and cost back.
- Launch it with `harbor run ... --agent-import-path apps.harbor.agent:PydanticDeepAgent`.
- Forward API keys via the environment, tune behavior through agent-kwargs, and pin a revision with `PYDANTIC_DEEP_GIT_REF`.

Where to go next:

- [Terminal-Bench](https://www.tbench.ai/) — the benchmark itself.
- [Applications overview](index.md) — the other reference apps built on pydantic-deep.
- [Your first agent](../learn/first-agent.md) — the headless agent Harbor is driving.
