# Harbor adapter — pydantic-deep on Terminal-Bench 2.0

Runs the pydantic-deep CLI agent as a Harbor "installed agent" so it can be
evaluated on [Terminal-Bench 2.0](https://www.tbench.ai/docs/run-terminal-bench-2-0).

The adapter (`agent.py`) is a thin wrapper: it installs pydantic-deep into each
task container and invokes `pydantic-deep run` headless. Every "new feature"
(forking, checkpoints, monitoring, stuck-loop detection, eviction, cost
tracking, context manager, improve, tool-search, MCP, teams, hooks) is wired up
by `create_cli_agent` on the CLI side — the adapter just forwards flags.

## Prerequisites

```bash
uv tool install harbor          # the harness
docker info                      # Docker must be running
```

## Model auth (Gemini 3.1 Pro)

Gemini needs the `google` extra (pulled in automatically by the container
install) plus credentials. Two paths — pick one:

### A. Vertex AI (recommended, matches our GCP setup)

```bash
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=vstorm-495409
export GOOGLE_CLOUD_LOCATION=us-central1
# Credentials file — either works; the adapter base64-injects it into the
# container and points GOOGLE_APPLICATION_CREDENTIALS at it:
#   • Service-account key (stable, preferred for long runs):
export GOOGLE_APPLICATION_CREDENTIALS=~/keys/vstorm-vertex-sa.json
#   • …or user ADC (already on disk after `gcloud auth application-default login`)
#     — no env var needed, the default ADC path is auto-detected.
```

Model id: `-m google-cloud/gemini-3.1-pro-preview` (or `vertex/…`).

### B. Gemini Developer API (simplest)

```bash
export GEMINI_API_KEY=...
```

Model id: `-m gemini/gemini-3.1-pro-preview` (maps to the `google:` provider).
Note: preview models may not be exposed on the Developer API — Vertex is the
confirmed path.

> A bare `-m google/…` auto-routes to Vertex (`google-cloud:`) when
> `GOOGLE_GENAI_USE_VERTEXAI` or `GOOGLE_CLOUD_PROJECT` is set, otherwise to the
> Developer API (`google:`).

## Logfire (required for the improve loop)

```bash
export LOGFIRE_TOKEN=...          # project: deepagents-terminal-bench
```

The adapter runs `pydantic-deep --logfire run …` (the flag is off by default)
and tags every span via OTEL resource attributes (Logfire honours these):

| attribute | value |
|---|---|
| `service.name` | `pydantic-deep-tb` |
| `deployment.environment` | `terminal-bench` |
| `tb.task` | clean task name, e.g. `sparql-university` — groups all trials/retries |
| `tb.trial` | unique per attempt, e.g. `sparql-university__Ab3Xy9q` |
| `tb.logs_path` | full per-trial logs path (exact correlation key) |

`tb.task`/`tb.trial` are derived from Harbor's own `session_id`
(`{trial_name}__agent`), so they match Harbor's naming exactly — no heuristics.

## Running

```bash
# Smoke test the harness (oracle solutions):
harbor run -d terminal-bench/terminal-bench-2 -a oracle -l 5

# 5 tasks with our agent on Gemini 3.1 Pro / Vertex (-l = task limit, -n = concurrency):
harbor run -d terminal-bench/terminal-bench-2 \
  -m google-cloud/gemini-3.1-pro-preview \
  -a apps.harbor.agent:PydanticDeepAgent \
  -l 5 -n 1

# Target a single task:
harbor run ... --include-task-name "<task-name>"
```

Feature flags are passed through Harbor's `--ak key=value` mechanism, e.g.
`--ak subagents=true --ak thinking=medium --ak web_search=false`. The adapter
forwards the agent's full `pydantic-deep run` feature surface — supported keys:
`web_search, web_fetch, thinking, todo, subagents, skills, plan, memory, teams,
context, browser, browser_headless, liteparse, temperature, sandbox, workspace`.

Defaults: every flag left unset uses the agent's own config default (skills,
plan, memory, subagents, todo, context on; teams off; thinking `high`), **except
these, which the adapter forces OFF**:

- `web_search` / `web_fetch` — on Gemini 3 they make pydantic-ai set
  `include_server_side_tool_invocations`, which **Vertex AI rejects** (crashes
  every request); TB containers are also usually offline.
- `browser` / `liteparse` — their extras (Playwright binaries, Node.js) aren't
  installed and terminal tasks don't need them.

Pass e.g. `--ak web_search=true` to opt any of them back in (e.g. web tools on a
non-Vertex model). `sandbox`/`workspace` default to unset — leave them alone
under Terminal-Bench (the agent already runs inside a task container;
`--sandbox docker` would nest Docker).

Install a specific branch with `PYDANTIC_DEEP_GIT_REF=<branch>` (default `main`).

## The analyse → improve loop

1. Run 5 tasks (above).
2. In Logfire (`deepagents-terminal-bench`), pull traces for this batch:
   ```sql
   SELECT otel_resource_attributes->>'tb.task'  AS task,
          otel_resource_attributes->>'tb.trial' AS trial,
          *
   FROM records
   WHERE otel_resource_attributes->>'service.name' = 'pydantic-deep-tb'
     AND start_timestamp >= now() - interval '1 hour'
   ```
   Group per task with `otel_resource_attributes->>'tb.task'`.
3. Analyse failures/token usage/tool loops → propose agent improvements.
4. Apply changes on a branch, set `PYDANTIC_DEEP_GIT_REF`, re-run. Repeat.
