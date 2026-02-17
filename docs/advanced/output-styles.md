# Output Styles

Output styles are markdown-based formatting directives injected into the system prompt to control how the agent formats and presents its responses.

## Quick Start

```python
from pydantic_deep import create_deep_agent

# Use a built-in style
agent = create_deep_agent(output_style="concise")
```

## Built-in Styles

| Style | Description |
|-------|-------------|
| `concise` | Minimal output, code-only, no explanations |
| `explanatory` | Step-by-step reasoning, examples, definitions |
| `formal` | Professional, structured, numbered sections |
| `conversational` | Friendly, casual, uses analogies |

```python
# Minimal, code-focused responses
agent = create_deep_agent(output_style="concise")

# Detailed explanations for learning
agent = create_deep_agent(output_style="explanatory")

# Professional documentation style
agent = create_deep_agent(output_style="formal")

# Friendly teaching style
agent = create_deep_agent(output_style="conversational")
```

## Custom Styles

### Inline

Pass an `OutputStyle` instance directly:

```python
from pydantic_deep.styles import OutputStyle

agent = create_deep_agent(
    output_style=OutputStyle(
        name="technical",
        description="Deep technical detail",
        content="Always include implementation details, cite specific files and line numbers...",
    ),
)
```

### From Files

Create markdown style files with YAML frontmatter:

```markdown
---
name: my-style
description: My custom output style
---

Use a structured format:
- Start with a one-sentence summary
- Include code examples for every suggestion
- End with action items
```

Then reference by name:

```python
agent = create_deep_agent(
    output_style="my-style",
    styles_dir="/path/to/styles",  # Directory containing .md style files
)
```

### Discovery

Load all styles from a directory:

```python
from pydantic_deep.styles import discover_styles

styles = discover_styles("/path/to/styles")
# Returns: {"my-style": OutputStyle(...), "another": OutputStyle(...)}
```

## Resolution Order

When you pass a string name to `output_style`, the resolution order is:

1. Return `OutputStyle` instances directly
2. Look up in `BUILTIN_STYLES` (`concise`, `explanatory`, `formal`, `conversational`)
3. Search `styles_dir` directories for matching `.md` files
4. Raise `ValueError` if not found

## How It Works

The resolved style is appended to the agent's instructions as a system prompt section:

```
## Output Style: concise

Be extremely concise in all responses:
- No explanations unless explicitly asked
- Code only with minimal comments
- One-line answers when possible
...
```

## Components

| Component | Description |
|-----------|-------------|
| [`OutputStyle`][pydantic_deep.styles.OutputStyle] | Style dataclass (name, description, content) |
| [`BUILTIN_STYLES`][pydantic_deep.styles.BUILTIN_STYLES] | Registry of 4 built-in styles |
| [`resolve_style`][pydantic_deep.styles.resolve_style] | Resolve style name to OutputStyle |
| [`discover_styles`][pydantic_deep.styles.discover_styles] | Discover styles from a directory |
| [`load_style_from_file`][pydantic_deep.styles.load_style_from_file] | Load a single style from a markdown file |
| [`format_style_prompt`][pydantic_deep.styles.format_style_prompt] | Format style for system prompt injection |

## Next Steps

- [Context Files](context-files.md) — Project context injection
- [Memory](memory.md) — Persistent agent memory
- [Agents](../concepts/agents.md) — Full agent configuration
