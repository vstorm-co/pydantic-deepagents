# ACP adapter (Zed)

Run your pydantic-deep agent right inside your editor. The ACP adapter exposes a full deep agent over the [Agent Client Protocol](https://agentclientprotocol.com), so editors like [Zed](https://zed.dev) can drive it — streaming responses, tool-call visibility, and model switching included.

## What is ACP?

ACP is a small stdio protocol that editors speak to AI agents. Zed talks ACP; this adapter answers in ACP and translates everything into a [`create_deep_agent()`][pydantic_deep.create_deep_agent] run under the hood. You get the editor's chat panel as a front end and the full deep agent — filesystem, shell, web, memory, skills, subagents — as the brain.

## Install

```bash
pip install pydantic-deep[acp]
```

The `[acp]` extra pulls in the ACP runtime alongside the core library.

## Quick start

Run the adapter as a module:

<div class="termy">

```console
$ python -m apps.acp
```

</div>

That's it. The server starts on stdio, auto-detects your API key, picks a matching provider, and waits for an editor to connect. There's no port and no config file to write — Zed launches this command for you (see [Wire it into Zed](#wire-it-into-zed)).

!!! note "It speaks stdio, not HTTP"
    The adapter communicates over standard input/output, the way ACP clients
    expect. You won't see a URL — the editor owns the process.

## API-key auto-detection

You don't tell the adapter which model to use; it figures that out from the keys it can find. It searches these locations and uses the **first one** that has a key:

| Priority | Location | Scope |
|----------|----------|-------|
| 1 | Environment variables | This session |
| 2 | `~/.pydantic-deep/.env` | Global (all projects) |
| 3 | `.pydantic-deep/.env` | Per-project |
| 4 | `.env` | Current directory |

The simplest setup is a global key file:

```bash
mkdir -p ~/.pydantic-deep
echo 'OPENROUTER_API_KEY=sk-or-your-key' > ~/.pydantic-deep/.env
```

Or scope it to one project:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-your-key' > .pydantic-deep/.env
```

### Provider selection

Whichever key it finds maps to a sensible default model:

| Environment variable | Default model |
|----------------------|---------------|
| `ANTHROPIC_API_KEY` | `anthropic:claude-sonnet-4-6` |
| `OPENROUTER_API_KEY` | `openrouter:anthropic/claude-sonnet-4` |
| `OPENAI_API_KEY` | `openai:gpt-4.1` |
| `GOOGLE_API_KEY` | `google:gemini-2.5-pro` |

Want to pin a specific model instead of the default? Pass it on the command line:

```bash
python -m apps.acp                                     # auto-detect
python -m apps.acp --model anthropic:claude-opus-4-6   # pin a model
python -m apps.acp --cwd /path/to/project              # set the working dir
```

## Wire it into Zed

Open Zed's settings (`Cmd+,` → edit JSON, or `~/.config/zed/settings.json`) and register the adapter as a custom agent server:

```json
{
  "agent_servers": {
    "pydantic-deep": {
      "type": "custom",
      "command": "/path/to/your/venv/bin/python",
      "args": ["-m", "apps.acp"],
      "cwd": "/path/to/pydantic-deep"
    }
  }
}
```

Point `command` at the Python that has `pydantic-deep[acp]` installed. From the project directory, this prints the right path:

```bash
echo "$(pwd)/.venv/bin/python"
```

Save the file and **pydantic-deep** appears in Zed's agent panel. Start a chat and you're talking to your deep agent.

!!! tip "What you see in the panel"
    Responses stream in token by token. Each tool call shows a labelled title
    (`read_file: /src/main.py`, `grep: TODO`, `execute: npm test`) with its
    result inline. Use Zed's model picker to switch providers mid-session.

## Custom server

The default factory builds a full deep agent. To customize it — turn on thinking, change which models the picker offers — build your own `DeepAgentACP` and pass an agent factory:

```python
from apps.acp.server import DeepAgentACP, AgentSessionContext
from pydantic_deep import create_deep_agent


def build_agent(ctx: AgentSessionContext):
    return create_deep_agent(
        model=ctx.model,
        context_discovery=True,
        thinking="high",
    )


server = DeepAgentACP(
    agent=build_agent,
    models=[
        {"value": "anthropic:claude-opus-4-6", "name": "Claude Opus 4.6"},
        {"value": "anthropic:claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
    ],
)
```

The factory receives an `AgentSessionContext` (the editor's `cwd`, current `mode`, and selected `model`) for each session, so every conversation gets an agent built for its own working directory and model choice.

## Recap

- ACP lets editors like Zed drive a pydantic-deep agent over a small stdio protocol.
- Install with `pip install pydantic-deep[acp]`, then run `python -m apps.acp`.
- The adapter auto-detects your API key and picks a matching provider — no config needed; pin a model with `--model`.
- Register it as a custom `agent_servers` entry in Zed, pointing at your venv's Python.
- For full control, build your own `DeepAgentACP` with an agent factory and a custom model list.

Where to go next:

- [Your first agent →](../learn/first-agent.md) — the agent this adapter runs
- [Web search & MCP →](../learn/web-and-mcp.md) — add external tools
- [Skills →](../learn/skills.md) — extend what your agent can do
