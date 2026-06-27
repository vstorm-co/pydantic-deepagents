# Settings & themes

Tune the CLI to fit how you work — model, thinking effort, themes, and which capabilities are switched on. Change things live from a modal, or commit them to a config file that travels with your project.

## The fastest way: `/settings`

Type `/settings` in the chat and a compact overlay appears. Arrow keys move, space toggles, enter edits. Every change is written to disk **and** applied immediately — no restart.

```text
◆ settings
 ▸ Model      anthropic:claude-sonnet-4-6
   Thinking   high
   Theme      default

   ◉  Skills
   ◉  Memory
   ◉  Subagents
   ◉  Plan mode
   ◉  Todos
   ◉  Web search
   ◉  Web fetch
   ◉  Tool search (defer tools)
   ◉  Browser
   ○  Teams
   ◉  Context discovery
   ◉  Show cost
   ◉  Show tokens

↑↓ move   space toggle   enter edit   esc close
```

The top three rows are *values* you edit; the rest are *toggles* you flip:

- **Model** — opens the model picker (same one `/model` uses). The agent is rebuilt around your choice on the spot.
- **Thinking** — cycles `high → medium → low` in place. This is the extended-thinking budget the model reasons with.
- **Theme** — cycles through the built-in themes and recolors the UI live as you press enter.
- **Toggles** — Skills, Memory, Subagents, Plan mode, Todos, Web search, Web fetch, Tool search, Browser, Teams, Context discovery, Show cost, Show tokens. Each is a capability or HUD element that gets enabled or disabled the moment you toggle it.

!!! tip "Changes are persistent"
    The modal writes straight to `config.toml`. What you toggle today is still
    set next time you launch the CLI in the same project.

## Where settings live: `config.toml`

The CLI keeps project-scoped settings in `.pydantic-deep/config.toml`, resolved relative to your working directory. Precedence runs **environment variables > config file > defaults**, so a config file lets a project pin its own model and capabilities without touching your global environment.

```toml
# .pydantic-deep/config.toml
model = "anthropic:claude-sonnet-4-6"
theme = "ocean"
thinking_effort = "high"
temperature = 0.2

include_skills = true
include_subagents = true
web_search = true
show_cost = true
show_tokens = true
```

You rarely write this by hand — `/settings` and the slash commands below maintain it for you — but it's plain TOML you can read, diff, and commit.

### Model & provider

`model` is any Pydantic AI model string: `anthropic:…`, `openai:…`, `google-gla:…`, `openrouter:…`. The provider prefix is required; the CLI warns you on launch if it's missing.

```toml
model = "openai:gpt-4o"
fallback_model = "openrouter:anthropic/claude-haiku-4-5"
```

`fallback_model` is used automatically when the primary model fails on a rate limit or 5xx. Set both from the `/model` picker.

!!! info "Override per launch"
    `PYDANTIC_DEEP_MODEL`, `PYDANTIC_DEEP_THEME`, `PYDANTIC_DEEP_WORKING_DIR`,
    and `PYDANTIC_DEEP_CHARSET` override the file for a single run — handy for
    a one-off model swap without editing config.

### Thinking & temperature

```toml
thinking_effort = "high"   # high | medium | low
temperature = 0.2          # omit to use the model's default
```

`thinking_effort` controls the extended-thinking budget; leave it on `high` for hard work, drop it for quick, cheap turns. `temperature` is optional — leave it unset and the model's own default applies.

### Sandbox

```toml
sandbox = "local"               # local | docker
sandbox_image = "python:3.12-slim"
```

`local` runs the agent's shell against your filesystem; `docker` isolates execution inside a container built from `sandbox_image`. The Docker path needs the `docker` extra.

## Slash commands that write config

The `/settings` modal covers the common toggles. A few settings have their own dedicated commands:

- `/model` — pick the primary (and fallback) model.
- `/theme` — switch themes (see below).
- `/fork-config` — configure live run forking: branch count, per-branch models and budgets, and the merge strategy. See [Sessions, forking & MCP](sessions-forking-mcp.md).

All of them persist to the same `config.toml`.

## `/theme` and the built-in themes

Run `/theme` to switch palettes. Five cohesive dark themes ship with the CLI:

| Name | Look |
| --- | --- |
| `default` | Warm amber on near-black (the brand theme) |
| `emerald` | Cool emerald/teal |
| `ocean` | Cool blue/cyan |
| `rose` | Warm rose/magenta |
| `minimal` | Near-monochrome, pure minimalist |

The theme recolors instantly and the choice is saved to `theme` in your config. The CLI always applies one of its own themes — it never falls back to Textual's stock palette.

!!! note "Set it from anywhere"
    Pick a theme with `/theme`, cycle it inside `/settings`, write `theme = "rose"`
    in `config.toml`, or export `PYDANTIC_DEEP_THEME=rose`. They all land in the
    same place.

## Recap

- `/settings` is the fastest path — arrow-key overlay that toggles capabilities and edits model, thinking, and theme, applying every change live and persisting it.
- Settings live in `.pydantic-deep/config.toml` in your working directory; precedence is env vars > file > defaults.
- `model` takes any provider-prefixed Pydantic AI string; `fallback_model` kicks in on failures; `thinking_effort` and `temperature` tune how the model reasons.
- `/theme` switches between five built-in themes — `default`, `emerald`, `ocean`, `rose`, `minimal` — recoloring the UI instantly.

Next, let's pick up where you left off and connect external tools.

- [Sessions, forking & MCP →](sessions-forking-mcp.md)
