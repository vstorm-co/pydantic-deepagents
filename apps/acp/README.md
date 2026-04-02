# ACP Adapter for pydantic-deep

[Agent Client Protocol (ACP)](https://agentclientprotocol.com) adapter that enables pydantic-deep agents to run inside editors like [Zed](https://zed.dev).

## Installation

```bash
pip install pydantic-deep[acp]
```

## Quick Start

```bash
python -m apps.acp
```

The server auto-detects your API key from environment variables or `.env` files and picks the right provider.

## API Key Setup

The ACP server looks for API keys in this order:

1. **Environment variables** (e.g., `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`)
2. **`~/.pydantic-deep/.env`** — global, all projects
3. **`.pydantic-deep/.env`** — per-project
4. **`.env`** — current directory

Create one:

```bash
# Global (recommended)
mkdir -p ~/.pydantic-deep
echo 'OPENROUTER_API_KEY=sk-or-your-key' > ~/.pydantic-deep/.env

# Or per-project
echo 'ANTHROPIC_API_KEY=sk-ant-your-key' > .pydantic-deep/.env
```

The server auto-detects the provider from available keys:
- `ANTHROPIC_API_KEY` → `anthropic:claude-sonnet-4-6`
- `OPENROUTER_API_KEY` → `openrouter:anthropic/claude-sonnet-4`
- `OPENAI_API_KEY` → `openai:gpt-4.1`
- `GOOGLE_API_KEY` → `google:gemini-2.5-pro`

## Zed Configuration

Add to your Zed settings (`Cmd+,` → edit JSON):

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

Find your Python path:

```bash
# From the pydantic-deep directory
echo "$(pwd)/.venv/bin/python"
```

After saving, "pydantic-deep" appears in Zed's agent panel.

## Features

- Streaming text responses with real-time deltas
- Tool call visibility with arguments (`read_file: /src/main.py`, `grep: TODO`)
- Tool results displayed inline (file contents, search results, command output)
- Model switching mid-session via Zed's model picker
- Auto-detect provider from API keys
- Session management with conversation history
- Context file discovery (AGENTS.md, SOUL.md)
- Full pydantic-deep toolset (filesystem, web, memory, skills, subagents)

## CLI Options

```bash
python -m apps.acp                                    # Auto-detect model
python -m apps.acp --model anthropic:claude-opus-4-6  # Specific model
python -m apps.acp --cwd /path/to/project             # Working directory
```

## Custom Agent Factory

```python
from apps.acp.server import DeepAgentACP, AgentSessionContext
from pydantic_deep import create_deep_agent

def build_agent(ctx: AgentSessionContext):
    return create_deep_agent(
        model=ctx.model,
        include_memory=True,
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

## Architecture

```
Editor (Zed)
    |
    |  ACP protocol (stdio)
    |  - text deltas
    |  - tool call start/complete with content
    |  - model switching
    |
    v
DeepAgentACP (apps/acp/server.py)
    |
    |  pydantic-ai Agent.iter() + node.stream()
    |
    v
create_deep_agent() -- full deep agent with all tools
```
