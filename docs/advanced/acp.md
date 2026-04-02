# ACP -- Editor Integration

The [Agent Client Protocol (ACP)](https://agentclientprotocol.com) adapter enables pydantic-deep agents to run inside editors like [Zed](https://zed.dev), providing streaming responses, tool call visibility, and model switching.

## Installation

```bash
pip install pydantic-deep[acp]
```

## Quick Start

```bash
python -m apps.acp
```

The server auto-detects your API key and picks the right provider.

## API Key Setup

The ACP server loads API keys from multiple locations (first found wins):

| Priority | Location | Scope |
|----------|----------|-------|
| 1 | Environment variables | Session |
| 2 | `~/.pydantic-deep/.env` | Global (all projects) |
| 3 | `.pydantic-deep/.env` | Per-project |
| 4 | `.env` | Current directory |

Create a global key file:

```bash
mkdir -p ~/.pydantic-deep
echo 'OPENROUTER_API_KEY=sk-or-your-key' > ~/.pydantic-deep/.env
```

Or per-project:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-your-key' > .pydantic-deep/.env
```

### Supported Providers

| Environment Variable | Default Model |
|---------------------|---------------|
| `ANTHROPIC_API_KEY` | `anthropic:claude-sonnet-4-6` |
| `OPENROUTER_API_KEY` | `openrouter:anthropic/claude-sonnet-4` |
| `OPENAI_API_KEY` | `openai:gpt-4.1` |
| `GOOGLE_API_KEY` | `google:gemini-2.5-pro` |

## Zed Configuration

Add to Zed settings (`Cmd+,` or `~/.config/zed/settings.json`):

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
echo "$(pwd)/.venv/bin/python"
```

After saving, select "pydantic-deep" in Zed's agent panel.

## What You See in Zed

### Streaming Text
Agent responses stream in real time, token by token.

### Tool Calls
Each tool call shows:
- **Title with context**: `read_file: /src/main.py`, `grep: TODO`, `execute: npm test`
- **Status**: pending → completed
- **Results**: file contents, search output, command results (truncated to 500 chars)

### Model Switching
Use Zed's model picker to switch between providers mid-session. Available models include Anthropic, OpenRouter, OpenAI, and Google.

## CLI Options

```bash
python -m apps.acp                                     # Auto-detect
python -m apps.acp --model anthropic:claude-opus-4-6   # Specific model
python -m apps.acp --cwd /path/to/project              # Working directory
```

## Custom Server

Build your own ACP server with custom configuration:

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

## Architecture

```
Editor (Zed)
    |
    |  ACP protocol (stdio)
    |
    v
DeepAgentACP (apps/acp/server.py)
    |
    |  pydantic-ai Agent.iter() + node.stream()
    |
    v
create_deep_agent() -- full deep agent
    |
    +-- Filesystem tools (read, write, edit, glob, grep, execute)
    +-- Web tools (search, fetch)
    +-- Memory (MEMORY.md)
    +-- Skills (SKILL.md)
    +-- Subagents (research, custom)
    +-- Context files (AGENTS.md, SOUL.md)
    +-- Thinking (configurable effort)
```

## Next Steps

- [MCP Servers](mcp.md) -- Add external tools via MCP
- [Skills](../concepts/skills.md) -- Extend agent capabilities
- [Hooks](hooks.md) -- Lifecycle hooks for custom behavior
