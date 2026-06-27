# Commands

Slash commands drive everything in the CLI that isn't a message to the agent. Type one at the input, hit `Enter`, and it runs.

## The command picker

You don't have to memorize anything. Press `/` at the start of an empty input and the **command picker** opens — a floating list of every command with its description.

Start typing and the list **filters fuzzily**: characters match anywhere in the command name *or* its description, best matches first. So `/cmp`, `compact`, or `compress` all surface `/compact`. Use `↑ ↓` to move, `Enter` to pick, `Esc` to cancel.

!!! tip "Skills show up too"
    Any skills you've installed appear in the picker under a **── Skills ──** divider. Picking one (or typing `/skill-name`) tells the agent to use that skill. More in [Skills](#tools-info).

Everything below is also available from `/help` (or `F1`) inside the app.

## Conversation

Manage the transcript — undo, redo, copy, and export.

| Command | What it does |
| --- | --- |
| `/clear` | Clear conversation history (also drops any active goal) |
| `/undo` | Remove the last turn from history and the transcript |
| `/retry` | Re-run the last prompt, dropping the previous turn first |
| `/export [path]` | Write the conversation to a Markdown file (defaults to `conversation-<timestamp>.md`) |
| `/copy` | Copy the last response to the clipboard |
| `/copy-all` | Copy the entire conversation to the clipboard |

!!! note "Undo vs. clear"
    `/undo` peels off one exchange at a time so you can rewind a bad turn; `/clear` wipes the whole conversation and starts fresh.

## Context & cost

See how much of the window you're using, compress it, and track spend.

| Command | What it does |
| --- | --- |
| `/context` | Show context-window usage (offers to `/compact` from the view) |
| `/compact` | Compress context — LLM summarization, or zero-cost trim |
| `/cost` | Show accumulated cost in USD plus input/output tokens |
| `/tokens` | Show message count and input/output token totals |

`/compact` opens a small modal: choose **LLM** summarization (the context manager rewrites old turns into a summary) or **trim** (just keep the last N messages, no model call). `/cost` reports the authoritative tracked cost when available, falling back to an estimate prefixed with `~`.

## Configuration

Switch models, providers, themes, and feature toggles.

| Command | What it does |
| --- | --- |
| `/model` | Change the active model (then optionally pick a fallback) |
| `/provider` | Configure an AI provider and its API key |
| `/settings` | Open settings — toggle features, model, theme |
| `/theme [name]` | Switch color theme; with no name, lists the available themes |

!!! info "Models and fallbacks"
    `/model` lets you pick a primary model and then a fallback. If the primary fails or hits a limit, the agent falls back automatically. See [Fallback models](../advanced/fallback-models.md).

## Tools & info

Inspect what's wired into the running agent.

| Command | What it does |
| --- | --- |
| `/info` | Show what's wired in — tools, backend, MCP, context files |
| `/mcp` | Manage MCP servers — connect, login, import from Claude Code |
| `/skills` | List available skills |
| `/shells` | List background shells started via `run_in_background` |
| `/todos` | Show the todo list (pinned above the input when tasks exist) |

`/info` is the fastest way to confirm an MCP server connected or a context file like `CLAUDE.md` was picked up. `/mcp` opens the full management view — see [Sessions, forking & MCP](sessions-forking-mcp.md).

## Memory & goal

Persist notes, schedule reminders, and keep the agent working toward a condition.

| Command | What it does |
| --- | --- |
| `/remember [note]` | Add a note to persistent memory (`.pydantic-deep/main/MEMORY.md`) |
| `/remind` | Switch periodic reminder mode (off / first / context / llm) |
| `/goal <condition>` | Keep working toward a condition; `/goal clear` to stop |

!!! tip "Set a goal, walk away"
    `/goal` keeps re-prompting the agent until your condition is met — great for "don't stop until the tests pass." Clear it with `/goal clear`. See [Goal loop](../advanced/goal.md) and [Periodic reminders](../advanced/periodic-reminder.md).

## Sessions

Your conversation is auto-saved after every turn, so these are mostly for loading older work.

| Command | What it does |
| --- | --- |
| `/load` | Load a saved session from a picker |
| `/save` | Reports that sessions are auto-saved after each turn |

## Forking

Run several branches in parallel from the current state, then keep the best. This is **Live Run Forking** — see [Sessions, forking & MCP](sessions-forking-mcp.md) and [Live Run Forking](../advanced/forking.md).

| Command | What it does |
| --- | --- |
| `/fork` | Spawn N parallel branches from the current state |
| `/fork diff` | Pick a file + branches to open in an external diff tool (PyCharm/VS Code) |
| `/fork-config` | Configure fork branches, models, and budgets (persisted) |
| `/merge` | Resolve the active fork — pick a winning branch |

!!! warning "Forking must be enabled"
    `/fork` only works when the agent was started with forking enabled. While a fork is active you can't `/retry` or `/fork` again — resolve it with `/merge` first.

## Miscellaneous

| Command | What it does |
| --- | --- |
| `/paste` | Attach an image from the clipboard (also `Ctrl+V`) |
| `/diff` | Show the git diff for the working directory |
| `/screenshot [name]` | Export the current screen as an SVG image |
| `/improve [days]` | Analyze recent sessions and propose self-improvements (default 7 days) |
| `/help` | Show commands and shortcuts (also `F1`) |
| `/version` | Show the pydantic-deep version |
| `/bug` | Open the GitHub issues page in your browser |
| `/quit` | Exit the app (aliases: `/exit`, `/q`) |

!!! note "Unknown commands become skills"
    Type a command that isn't built in and the CLI checks whether it matches an installed skill. If it does, it runs that skill; otherwise you get an "Unknown command" warning.

## Recap

- Press `/` to open the **command picker**; typing **filters fuzzily** across names and descriptions.
- Commands group into **conversation**, **context & cost**, **configuration**, **tools & info**, **memory & goal**, **sessions**, **forking**, and **misc**.
- Sessions **auto-save** every turn — `/load` brings old ones back, `/save` just confirms it.
- `/fork` → `/merge` runs and resolves parallel branches; `/goal` keeps the agent working until a condition is met.
- Anything not built in is tried as a **skill**.

Next, the keys behind these commands.

- [Keys & input →](keybindings.md)
