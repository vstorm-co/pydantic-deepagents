# Output styles

Same agent, same tools — different voice. An **output style** changes *how* your agent writes: its tone, its formatting, how much it explains. You pick one with a single argument, and switch it per run.

```python hl_lines="3"
from pydantic_deep import create_deep_agent

agent = create_deep_agent(output_style="concise")
```

That's it. The agent now answers in clipped, code-first replies — no preamble, no "here's what I'll do". Swap `"concise"` for `"explanatory"` and the same agent starts teaching instead.

!!! info "Prompt-level, not validation"
    An output style is text appended to the system prompt. It *asks* the model to
    write a certain way — it never inspects or rejects the result. If you need the
    output to actually *conform* to a shape, that's [structured output](../learn/structured-output.md),
    not a style. More on the difference below.

## The built-in styles

Seven styles ship in the box. Pass any of them by name to `output_style=`:

| Style | What the agent does |
|-------|---------------------|
| `concise` | Minimal output, code-only, skips explanations and pleasantries |
| `explanatory` | Step-by-step reasoning, defines terms, gives examples |
| `formal` | Numbered sections, complete sentences, cites files and lines |
| `conversational` | Friendly and casual, uses analogies, asks follow-ups |
| `markdown` | Always well-formed markdown — headings, fenced code, tables |
| `json-only` | A single valid JSON value, no prose around it |
| `bullet` | Bulleted lists only, one idea per bullet, no paragraphs |

Pick the one that fits the surface your output lands on:

```python
# A coding session where you just want the answer
agent = create_deep_agent(output_style="concise")

# Onboarding docs that explain the "why"
agent = create_deep_agent(output_style="explanatory")

# Output piped straight into a markdown renderer
agent = create_deep_agent(output_style="markdown")

# Raw JSON on stdout for jq or a parser
agent = create_deep_agent(output_style="json-only")
```

!!! example "Check it"
    Run the same prompt twice — once with `output_style="concise"` and once with
    `output_style="explanatory"`. The plan, the tools, the files written are
    identical. Only the words around them change.

## `json-only` is a prompt, not a guarantee

It's tempting to reach for `json-only` when you want machine-readable output. Be careful: the model is *asked* to emit valid JSON, but nothing checks that it did. A stray sentence, a trailing comma, a markdown fence — any of those breaks the parser downstream, and the style can't stop them.

If you know the shape of the data, use [`output_type`](../learn/structured-output.md) instead. It uses the provider's native JSON / tool-calling mode, validates against your schema, and retries on failure:

```python
from pydantic import BaseModel
from pydantic_deep import create_deep_agent


class Result(BaseModel):
    status: str
    items: list[str]


agent = create_deep_agent(output_type=Result)  # result.output is a Result
```

Here's the side-by-side:

| | `json-only` (style) | `output_type` (structured output) |
|---|---|---|
| Mechanism | Prompt directive | Provider-native JSON / tool calling |
| Validation | None | Schema-validated, retries on failure |
| Result type | `str` | Your typed Pydantic model |
| Use when | Shape is free-form or unknown | Shape is known and fixed |

So reach for `json-only` only when `output_type` genuinely doesn't fit:

- Free-form JSON whose shape depends on the input (e.g. metadata pulled from arbitrary documents).
- Models or providers without structured-output support.
- CLI piping where you want raw JSON on stdout, unwrapped.
- An intermediate step that needs JSON while the run's final `output_type` stays `str`.

## Writing your own style

The seven built-ins are a starting point, not a ceiling. You can supply a style two ways.

### Inline

Build an `OutputStyle` and pass the instance straight in:

```python hl_lines="3 4 5 6 7"
from pydantic_deep import create_deep_agent
from pydantic_deep.styles import OutputStyle

agent = create_deep_agent(
    output_style=OutputStyle(
        name="technical",
        description="Deep technical detail",
        content=(
            "Always include implementation details. "
            "Cite specific files and line numbers."
        ),
    ),
)
```

An `OutputStyle` is just three fields: a `name`, a one-line `description`, and the `content` that gets injected into the prompt.

### From a markdown file

For styles you want to reuse or share, write them as markdown files with YAML frontmatter — the body *is* the style content:

```markdown
---
name: my-style
description: My custom output style
---

Use a structured format:
- Start with a one-sentence summary
- Include a code example for every suggestion
- End with action items
```

Drop that file in a directory, point `styles_dir` at it, and reference the style by its frontmatter `name`:

```python hl_lines="3"
agent = create_deep_agent(
    output_style="my-style",
    styles_dir="/path/to/styles",  # directory of .md style files
)
```

!!! tip "Inspect a directory of styles"
    [`discover_styles`][pydantic_deep.styles.discover_styles] loads every valid
    `.md` style in a directory into a `{name: OutputStyle}` dict — handy for
    listing what's available before you pick one.

    ```python
    from pydantic_deep.styles import discover_styles

    styles = discover_styles("/path/to/styles")
    # {"my-style": OutputStyle(...), "another": OutputStyle(...)}
    ```

## How a name gets resolved

When you pass a string to `output_style`, [`resolve_style`][pydantic_deep.styles.resolve_style] walks this order:

1. If you passed an `OutputStyle` instance, it's used as-is.
2. Otherwise the name is looked up in [`BUILTIN_STYLES`][pydantic_deep.styles.BUILTIN_STYLES].
3. If it's not a built-in, each directory in `styles_dir` is searched for a matching `.md` file.
4. If nothing matches anywhere, you get a `ValueError` listing the built-ins.

Whichever style wins, it's appended to the agent's instructions as a labeled section:

```text
## Output Style: concise

Be extremely concise in all responses:
- No explanations unless explicitly asked
- Code only with minimal comments
...
```

## Recap

- An output style shapes *how* the agent writes — tone and format — without changing *what* it does.
- It's prompt-level: appended to the system prompt, never validated. `json-only` asks for JSON; it doesn't enforce it.
- Seven built-ins ship ready to use: `concise`, `explanatory`, `formal`, `conversational`, `markdown`, `json-only`, `bullet`.
- Bring your own with an inline `OutputStyle` or a markdown file picked up from `styles_dir`.
- When you need the output to *conform* to a shape, use `output_type`, not a style.

Where to go next:

- [Structured output →](../learn/structured-output.md) — validated, typed results instead of free-form text
- [Memory →](../learn/memory.md) — give the agent persistent context across runs
