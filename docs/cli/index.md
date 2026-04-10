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

## Quick Start

```bash
pydantic-deep
```

This launches the Textual-based TUI — a rich interactive interface with streaming chat, tool call visualization, session management, and slash commands.

## Commands

### Default — Launch TUI

```bash
pydantic-deep                        # Launch TUI (default)
pydantic-deep tui                    # Explicit TUI command
pydantic-deep tui --model anthropic:claude-sonnet-4-6
pydantic-deep tui --working-dir /path/to/project
```

### `run` — Headless Execution

```bash
pydantic-deep run "Fix the failing test in test_auth.py"
pydantic-deep run --task-file task.md --json
pydantic-deep run "Refactor utils.py" --max-turns 50 --timeout 300
pydantic-deep run -f task.md -w /path/to/project -m openai:gpt-5.4
pydantic-deep run "Fix bug" --no-web-search --no-web-fetch --thinking false
```

Executes a single task non-interactively and prints the result to stdout. Designed for benchmarks (Terminal Bench), CI/CD pipelines, and scripted automation.

All feature flags default from `.pydantic-deep/config.toml` — the same defaults as the TUI. Use flags to override specific features.

| Option | Description |
|--------|-------------|
| `TASK` (argument) | Task description |
| `--task-file`, `-f` | Read task from file |
| `--model`, `-m` | Model override (from config) |
| `--working-dir`, `-w` | Working directory (default: cwd) |
| `--json` | Output result as JSON with usage stats |
| `--max-turns` | Maximum number of agent turns |
| `--timeout` | Timeout in seconds |
| `--temperature` | Sampling temperature (default: 0.0 in headless) |
| `--web-search` / `--no-web-search` | Web search (from config) |
| `--web-fetch` / `--no-web-fetch` | Web fetch (from config) |
| `--thinking` | Thinking effort: minimal/low/medium/high/xhigh/false (from config) |
| `--todo` / `--no-todo` | Task planning (from config) |
| `--subagents` / `--no-subagents` | Subagent delegation (from config) |
| `--skills` / `--no-skills` | Skills system (from config) |
| `--plan` / `--no-plan` | Plan mode (from config) |
| `--memory` / `--no-memory` | Persistent memory (from config) |
| `--teams` / `--no-teams` | Agent teams (from config) |
| `--context` / `--no-context` | Auto-discover AGENTS.md/SOUL.md (from config) |

JSON output includes the agent's response and token usage:

```json
{
  "output": "Fixed the test by...",
  "usage": {
    "total_tokens": 15420,
    "request_tokens": 12300,
    "response_tokens": 3120,
    "requests": 8
  }
}
```

### `init` — Initialize Project

```bash
pydantic-deep init
```

Creates `AGENTS.md`, `SOUL.md`, and `.pydantic-deep/` directory in the current project.

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
pydantic-deep threads export abc12345         # Export as markdown
pydantic-deep threads export abc12345 -f json # Export as JSON
```

### `config` — Configuration

```bash
pydantic-deep config show                     # Show current config
pydantic-deep config set model anthropic:claude-sonnet-4-6
```

## TUI Features

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands and shortcuts |
| `/clear` | Clear conversation history |
| `/compact` | Compress context (LLM summarization or quick trim) |
| `/context` | Show context usage with progress bar |
| `/config` | View or change config (e.g., `/config set model ...`) |
| `/copy` | Copy last response to clipboard |
| `/copy-all` | Copy entire conversation to clipboard |
| `/cost` | Show accumulated cost |
| `/diff` | Show git diff |
| `/improve` | Analyze past sessions and self-improve context files |
| `/load` | Browse and resume a previous session |
| `/model` | Switch model (interactive picker) |
| `/provider` | Configure AI provider and API keys |
| `/remember` | Save note to persistent memory |
| `/save` | Session auto-save info |
| `/settings` | Open settings screen |
| `/skills` | List available skills |
| `/theme` | Switch color theme |
| `/todos` | Toggle TODO side panel |
| `/tokens` | Show message and token stats |
| `/undo` | Remove last turn |
| `/version` | Show version |
| `/quit` | Exit |

### File References

Type `@filename` in your prompt to include file contents. The TUI expands `@` references automatically.

### Shell Commands

Prefix with `!` to run shell commands directly:

```
!git status
!make test
```

### Tool Approval

When the agent calls sensitive tools (like `execute`), an approval modal shows:
- Tool name and arguments
- **Y** — approve once
- **A** — auto-approve all
- **N** — deny
- **Esc** — cancel

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` | Open command picker |
| `@` | Open file picker |
| `Ctrl+J` | Toggle multiline input |
| `Ctrl+K` | Toggle TODO panel |
| `Ctrl+L` | Clear screen |
| `Ctrl+R` | Search messages |
| `Ctrl+C` | Interrupt agent |
| `Ctrl+D` | Quit |
| `F1` | Help |
| `F2` | Settings |
| `F5` | Context info |

### Self-Improvement (`/improve`)

The `/improve` command analyzes past conversation sessions and proposes updates to context files:

- **MEMORY.md** — user facts (name, role, expertise), agent learnings (effective commands, file locations)
- **SOUL.md** — communication preferences (language, style, tone)
- **AGENTS.md** — project conventions and architecture facts

Each proposed change shows confidence score and source sessions. You review and approve individually.

### Themes

Four built-in color themes:

| Theme | Description |
|-------|-------------|
| `default` | Emerald green primary |
| `ocean` | Blue primary |
| `rose` | Pink/red primary |
| `minimal` | Monochrome |

Switch with `/theme ocean` or save to config.

## Configuration

Config file: `.pydantic-deep/config.toml`

```toml
model = "anthropic:claude-sonnet-4-6"
include_skills = true
include_plan = true
include_memory = true
include_subagents = true
web_search = true
web_fetch = true
approve_tools = ["execute"]
```

API keys: `.pydantic-deep/keys.toml` (managed via `/provider` command)

CLI arguments always override config file values.

## Debug Logging

Per-session debug logs are saved to `.pydantic-deep/logs/`:

```
.pydantic-deep/logs/
├── session-abc123.log     # Per-session log
└── latest.log             # Symlink to current session
```

Logs include agent lifecycle events, tool calls with timing, command dispatches, and errors with tracebacks. Last 20 session logs are kept automatically.

## Architecture

```
apps/cli/
├── main.py              — Typer entry point (tui, run, init, skills, threads, config)
├── run.py               — Headless runner (execute_headless)
├── tui.py               — TUI launcher (run_tui, run_preview)
├── app.py               — DeepApp (Textual App root)
├── commands.py          — Slash command dispatcher
├── agent.py             — create_cli_agent() factory
├── config.py            — Config system (.pydantic-deep/config.toml)
├── prompts.py           — System prompt builder
├── init.py              — Project initialization
├── local_context.py     — Git/directory context detection
├── debug_log.py         — Per-session debug logging
├── keystore.py          — API key storage (keys.toml)
├── messages.py          — Textual message types
├── screens/
│   ├── chat.py          — Main chat screen (streaming, tool calls, approval)
│   ├── settings.py      — Settings form
│   └── onboarding.py    — First-run provider setup
├── modals/
│   ├── command_picker.py
│   ├── model_picker.py
│   ├── session_picker.py
│   ├── improve_review.py
│   ├── approval.py
│   ├── context_view.py
│   ├── compact.py
│   ├── diff_view.py
│   ├── skills_view.py
│   ├── help_view.py
│   ├── remember.py
│   ├── search.py
│   └── file_picker.py
├── widgets/
│   ├── header.py
│   ├── message_list.py
│   ├── assistant_message.py
│   ├── user_message.py
│   ├── tool_call.py
│   ├── input_area.py
│   ├── status_bar.py
│   ├── side_panel.py
│   └── ...
├── styles/
│   ├── app.tcss          — Textual CSS
│   └── themes.py         — Theme system
└── skills/               — Built-in SKILL.md files
```
