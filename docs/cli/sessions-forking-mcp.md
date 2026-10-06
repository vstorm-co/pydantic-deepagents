# Sessions, forking & MCP

Three power features turn the terminal app from a chat box into a workbench: your conversations are saved automatically and resumable, you can split a live run into parallel branches and pick a winner, and you can wire in MCP servers without leaving the TUI. Let's take them one at a time.

## Sessions

Every conversation is a **session**, and the CLI saves it for you — no command required.

After each turn, the app writes the full message history to `.pydantic-deep/sessions/<id>/messages.json`. A fresh `id` is minted each time you launch, so every run is its own resumable thread. There's nothing to remember and nothing to lose.

!!! note "There's no `/save`"
    Typing `/save` just reminds you: *"Sessions are auto-saved after each turn."* The work is already on disk.

### Resume a past conversation with `/load`

To pick up where you left off, type `/load`:

<div class="termy">

```console
> /load
```

</div>

A picker lists your recent sessions. Choose one and the CLI replays its messages into the transcript and restores the history the model sees — so your next prompt continues the old thread, not a new one.

!!! tip "Start clean, or rewind a step"
    `/clear` wipes the current conversation (and any active goal). `/undo` drops the last turn; `/retry` re-runs your last prompt after discarding the previous response. None of these touch saved sessions — only the live one.

### Messages from outside the terminal

A long session doesn't have to be steered from the terminal it runs in. A reply in a Slack thread, a Jira comment, a CI job that just went green or an n8n workflow can send the session a message, and the session handles it the way it handles what you type:

- **while the agent is running**, it's queued: a follow-up by default, delivered when the run would otherwise stop, or steering, delivered before the next model request;
- **while it's idle**, it starts a turn.

It shows in the transcript and reaches the model labelled with where it came from, e.g. `[via slack] also check MR 123` or `[follow-up via ci] build is green`. The integration owns everything on its side (talking to Slack, polling, deduplication); the session only takes the message.

Start the session with `--listen` and it accepts messages on a loopback HTTP endpoint:

<div class="termy">

```console
$ pydantic-deep tui --listen
```

</div>

It listens on `127.0.0.1` at a random port, and writes the URL and a bearer token to `.pydantic-deep/session-endpoint.json`, readable by your user only and listed in `.pydantic-deep/.gitignore`, so a `git add -A` while the session runs doesn't commit it. An integration reads that file and posts:

```bash
endpoint=.pydantic-deep/session-endpoint.json
curl -s "$(jq -r .url $endpoint)" \
  -H "Authorization: Bearer $(jq -r .token $endpoint)" \
  -d '{"text": "also check MR 123", "source": "slack", "mode": "auto"}'
# {"delivery": "queued"}
```

| Field | |
|---|---|
| `text` | The message: up to 32,000 characters, not only whitespace. |
| `source` | Where it came from: up to 32 letters, digits, `_`, `.`, `:` or `-`. The model sees it. |
| `mode` | `auto` (default) or `follow_up` queue it as a follow-up mid-run; `steer` delivers it before the next model request. An idle session starts a turn in every mode. |
| `metadata` | Optional string pairs - a thread id, a message id. They go to the session log (`.pydantic-deep/logs/`), never to the model. |

The answer is `202` with `delivery` set to `steered`, `queued` or `started`. A session that can't take the message answers `409` and says why: no agent configured, a [fork](#live-run-forking) is active, the queue is full, or the session is still starting or already closing. `401` means a missing or wrong token, `400` a malformed body, and `413` a body over 256 KiB.

A message waits behind whatever the session is already doing before it's delivered - a follow-up turn about to start, or a `/goal` check deciding whether to continue - so it's queued for that turn rather than starting a second one beside it.

Steering that arrives after the run's last model request is kept as a follow-up rather than dropped, since its sender can't see the terminal's warning. One listening session per project: a second `--listen` session publishes over the first one's file, and each removes the file on exit only if it's still its own.

!!! tip "In the same process"
    An integration running inside your own Python process can skip HTTP and call the app directly: `await app.inject_external_message("also check MR 123", source="slack", mode="auto")`. It returns the same `"steered"`, `"queued"` or `"started"`, and raises `ExternalMessageRefused` (from `apps.cli.external_messages`) where the endpoint answers `409`. Under the hood both use the [message queue](../advanced/message-queue.md).

!!! warning "The token is the only lock"
    Anyone who can read the endpoint file, or the token in it, can talk to your agent - and the agent can run commands. The file is created `0600` and the server only listens on loopback, but keep the token out of logs and shared shells, and start the session without `--listen` when nothing needs to reach it.

## Live Run Forking

[Live Run Forking](../advanced/forking.md) is *git branch, but for cognition*: split the current run into parallel branches that share history up to the fork point, let each explore a different approach, then merge the winner. The CLI exposes the whole workflow through slash commands and live branch panels.

Forking has to be enabled on the agent (`forking=True` — `create_cli_agent()` flips this on for you). If it isn't, `/fork` tells you to restart with forking on.

### Fork the current run

Finish a turn, then type `/fork`:

<div class="termy">

```console
> Help me name a Python library for distributed locks.
[…agent answers…]
> /fork
```

</div>

A picker opens with one row per branch. Give each a **label** and a **steer** (the instruction that makes that branch different), then submit. Branches run concurrently and their status badges update live — `●` running, `✓` done, `✗` failed, `⊘` terminated.

!!! note "One fork at a time"
    `/fork` is blocked while a run is in flight (press `Esc` first) and while a fork is already active (`/merge` to resolve). If the *agent* forked itself mid-run, the CLI adopts that fork automatically and the panels light up — `/fork` then warns you to resolve the agent's fork first.

### Configure the next fork with `/fork-config`

`/fork-config` opens a settings modal for the *next* fork — branch count, per-branch and aggregate budget caps, per-branch model overrides, and the merge strategy. Settings persist to `.pydantic-deep/config.toml`, so they survive restarts. (You can't change them mid-fork — that would clobber the active coordinator.)

### Steer a running branch with `>>label`

While branches run, target one with the `>>` steer prefix and its label:

<div class="termy">

```console
> >>a make the names shorter
```

</div>

That message lands on branch `a`'s queue only; the others are unaffected. If the label doesn't match a live branch, the input is rejected — `>>` is steering-only and never falls through to the agent. (The `!` prefix still runs a shell command during a fork.)

### Pick a winner with `/merge`

When you're ready, type `/merge`:

<div class="termy">

```console
> /merge
```

</div>

What happens next depends on the [merge strategy](../advanced/forking.md#autonomous-merge):

- **Manual** — the merge picker shows each branch's diff; press `1`/`2` to pick.
- **Auto / auto-with-fallback** (default) — a cheap judge inspects the diffs and outcomes, then either commits its pick or hands you the picker with the judge's choice preselected and its reasoning shown.

The winner's file writes are flushed onto your real backend, its turn is replayed into the main transcript, and a one-line summary closes the fork:

```
Merged: kept branch whimsical · 2 files applied
```

!!! tip "Inspect before you decide"
    `/fork diff` launches your external diff tool (PyCharm or VS Code, auto-detected) on a branch's snapshot vs. the parent — or opens an in-TUI picker if no editor is found. The snapshots are read-only; edits there don't affect `/merge`. This is the one `/fork` sub-command allowed while a fork is active.

For budgets, isolation, nested forks, the autonomous judge, and the full tool surface, see [Live Run Forking](../advanced/forking.md).

## MCP servers

[MCP](../learn/web-and-mcp.md) servers connect your agent to GitHub, Figma, documentation lookups, and any custom server — their tools appear alongside the built-in filesystem and web tools. The CLI manages them interactively, no Python required.

### The `/mcp` manager

Type `/mcp` to open the manager. It lists every server — built-in and custom — with its status:

- `●` **enabled** · `○` **disabled** · `⚠` **needs login**

Drive it with single keys:

| Key | Action |
|-----|--------|
| `e` / `space` | Enable or disable the selected server |
| `l` | Log in — paste a token, stored in the git-ignored keystore (`keys.toml`) |
| `o` | Log out — revoke the stored token |
| `t` | Test the connection (lists the server's tools inline) |
| `a` | Add a custom server (URL → HTTP, anything else → stdio command) |
| `i` | Import servers from Claude Code |
| `d` | Remove a custom server |
| `Esc` | Close (and reconfigure the agent if anything changed) |

User servers and per-built-in enabled state persist to `.pydantic-deep/mcp.json`; tokens live in `.pydantic-deep/keys.toml`. Enabled, authenticated servers are wired into the agent automatically when you close the modal.

!!! note "OAuth servers sign in via `t`"
    A server with `oauth` auth (like the hosted Figma server) needs no pasted token — press `t` and a browser opens for sign-in. The token is cached under `~/.pydantic-deep/mcp-oauth` and reused across restarts.

### Import from Claude Code

Already have MCP servers configured in [Claude Code](https://code.claude.com/docs/en/mcp)? Press `i` in `/mcp` to import them. The CLI reads the same `mcpServers` JSON across Claude Code's three scopes (local > project > user), expands `${VAR}` references, and carries over tokens already in `env`/`headers` — so imported servers work right away. Built-in names are never overwritten.

!!! info "File-configured servers only"
    Import pulls in servers added with `claude mcp add`. It does **not** import claude.ai connectors — those live in your Anthropic account, not a local config file.

For the programmatic API — `MCPServerConfig`, `MCPRegistry`, `build_mcp_server`, declarative auth, and built-in servers — see [MCP Servers](../learn/web-and-mcp.md).

## Recap

- **Sessions** auto-save after every turn to `.pydantic-deep/sessions/<id>/`; `/load` resumes any past conversation. There's no `/save` to remember.
- **`tui --listen`** lets Slack, CI or a webhook message a live session over loopback HTTP, with the token in `.pydantic-deep/session-endpoint.json`; in-process code calls `app.inject_external_message()`.
- **`/fork`** splits the current run into parallel branches; `/fork-config` tunes the next fork; `>>label msg` steers one branch; `/merge` flushes the winner. `/fork diff` opens an external diff tool to compare branches.
- **`/mcp`** manages MCP servers interactively — enable/disable (`e`), login (`l`), test (`t`), add (`a`), and import from Claude Code (`i`). State persists across restarts.

Concepts live in the framework guides: [Live Run Forking](../advanced/forking.md) and [MCP Servers](../learn/web-and-mcp.md).

- [← Back to the CLI overview](index.md)
