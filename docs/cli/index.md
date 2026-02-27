# CLI

The pydantic-deep CLI gives you a Claude Code-style AI coding assistant in your terminal — powered by the full [pydantic-deep](../index.md) framework.

## Installation

```bash
pip install pydantic-deep[cli]
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install pydantic-deep[cli]
```

## Commands

### `chat` — Interactive Chat

```bash
pydantic-deep chat
pydantic-deep chat --model anthropic:claude-sonnet-4-20250514
pydantic-deep chat --working-dir /path/to/project
```

Full-featured interactive chat with streaming, tool approval, slash commands, and Rich terminal output.

### `run` — Non-Interactive

```bash
# stdout = response only (clean for piping), stderr = diagnostics
pydantic-deep run "Fix the failing tests in src/"
pydantic-deep run "Create a REST API" --model openai:gpt-4.1
pydantic-deep run "Refactor the auth module" --quiet
```

### `init` — Initialize Project

```bash
pydantic-deep init
```

Creates an `AGENT.md` context file and `.pydantic-deep/` directory in the current project.

### `skills` — Manage Skills

```bash
pydantic-deep skills list                     # List built-in + user skills
pydantic-deep skills info code-review         # Show skill details
pydantic-deep skills create my-skill          # Scaffold a new SKILL.md
```

### `threads` — Manage Sessions

```bash
pydantic-deep threads list                    # List saved sessions
pydantic-deep threads delete abc12345         # Delete by ID prefix
```

### `config` — Configuration

```bash
pydantic-deep config show                     # Show current config
pydantic-deep config set model anthropic:claude-sonnet-4-20250514
```

### Docker Sandbox

```bash
pydantic-deep run "Build a web scraper" --sandbox --runtime python-web
pydantic-deep chat --sandbox --runtime python-datascience
```

| Runtime | Description |
|---------|-------------|
| `python-minimal` | Python 3.12 (default) |
| `python-datascience` | Python + numpy, pandas, matplotlib |
| `python-web` | Python + FastAPI, Django, Flask |
| `node-minimal` | Node.js 20 |
| `node-react` | Node.js + React, Next.js |

## Interactive Chat Features

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands and shortcuts |
| `/clear` | Clear conversation history |
| `/compact` | Trim and compress history (with optional focus topic) |
| `/context` | Show context usage breakdown (tokens, progress, compression stats) |
| `/undo` | Remove last turn from history |
| `/copy` | Copy last response to clipboard |
| `/todos` | Show current TODO list |
| `/cost` | Show accumulated cost |
| `/tokens` | Show message and token stats |
| `/model` | Switch model or show interactive picker |
| `/save` | Session auto-save info |
| `/load` | Browse and resume a previous session |
| `/remember` | View or save to persistent memory |
| `/skills` | List available skills |
| `/diff` | Show git diff of uncommitted changes |
| `/version` | Show version |
| `/bug` | Report a bug (opens GitHub) |
| `/quit` | Exit the chat |

### File Approval UI

When the agent wants to edit or create files, you see a rich preview before approving:

**Edit files** — colored unified diff with gutter bars:

```
File: src/main.py
@@ -10,3 +10,4 @@
│ import os
▌ import sys
▌ import json
│
  +2 -0
```

Green gutter bars (▌) for additions, red for deletions, dim vertical bars (│) for context lines.

**Write files** — line-numbered preview with head/tail truncation for large files:

```
File: src/utils.py (45 lines) python
   1 """Utility functions."""
   2
   3 import os
   4 from pathlib import Path
  ...
  42     return result
  43
  44 if __name__ == "__main__":
  45     main()
```

You can respond with:

- **y** — approve this tool call
- **n** — deny this tool call
- **a** — auto-approve all remaining tool calls for this turn

### Status Bar

The status bar at the bottom of each response shows:

- **Model name** — current model being used
- **Cost** — accumulated USD cost for the session
- **Context progress** — visual bar showing token usage percentage with threshold colors:
    - Green: <60% of budget
    - Amber: 60–85% of budget
    - Red: >85% of budget
- **Auto-approve** — `auto` (green) or `manual` (amber) indicator

### Tool Call Display

Tool calls are rendered with smart formatting:

```
⏺ read_file(src/main.py)
✓ read_file(src/main.py) (0.3s)
⎿ 42 lines read

⏺ execute(python -m pytest)
✗ execute(python -m pytest)
⎿ exit code 1
```

- Pending calls show ⏺ in amber
- Successful calls show ✓ in green with elapsed time
- Failed calls show ✗ in red
- Result previews show first 3 lines of output

### Streaming

Text streams as Rich Markdown with a braille spinner while waiting:

1. **Thinking phase** — animated braille spinner with elapsed time
2. **Text phase** — seamless transition to Markdown rendering (code blocks, lists, bold, etc.)

The transition is instant with no visual gap.

### Input Features

- **@file mentions** — type `@` to autocomplete file paths and include file content in your message
- **Ctrl+V image paste** — paste images from clipboard (supported on macOS)
- **Tab completion** — slash commands and @file paths auto-complete

## Configuration

Config file: `~/.pydantic-deep/config.toml`

```toml
model = "openai:gpt-4.1"
include_skills = true
include_plan = true
include_memory = true
include_checkpoints = true
shell_allow_list = ["python", "pip", "npm", "make"]
```

CLI arguments always override config file values.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `PYDANTIC_DEEP_THEME` | Color theme: `default`, `classic`, or `minimal` |
| `PYDANTIC_DEEP_CHARSET` | Character set: `auto`, `unicode`, or `ascii` |

## Themes

Three built-in color themes:

| Theme | Description |
|-------|-------------|
| `default` | Emerald green primary with hex colors |
| `classic` | Standard terminal colors (green, cyan, yellow) |
| `minimal` | Blue primary with standard terminal colors |

Set via environment variable:

```bash
PYDANTIC_DEEP_THEME=classic pydantic-deep chat
```

For terminals without Unicode support, force ASCII glyphs:

```bash
PYDANTIC_DEEP_CHARSET=ascii pydantic-deep chat
```

## Architecture

```
cli/
├── main.py              — Typer entry (run, chat, init, skills, threads, config)
├── agent.py             — create_cli_agent() factory
├── prompts.py           — Modular system prompt (dynamic assembly)
├── config.py            — Config system (~/.pydantic-deep/config.toml)
├── init.py              — Project initialization
├── non_interactive.py   — Headless execution (benchmark + sandbox)
├── interactive.py       — Chat loop (Rich streaming + tool approval)
├── local_context.py     — Git/directory context injection
├── theme.py             — Color palette + Unicode/ASCII glyph system
├── tool_display.py      — Smart tool call formatting + result previews
├── diff_display.py      — Colored diffs + file previews for approval
├── picker.py            — Interactive model/session picker
├── providers.py         — Model provider registry
├── middleware/
│   └── loop_detection.py
└── skills/              — Built-in SKILL.md files
    ├── skill-creator/
    ├── code-review/
    ├── test-writer/
    ├── refactor/
    └── git-workflow/
```
