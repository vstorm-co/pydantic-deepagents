"""Output styles for controlling agent tone and response format.

Output styles are markdown-based formatting directives injected into the
system prompt at agent creation time. They control how the agent formats
and presents its responses.

Built-in styles:
    - ``concise``: Minimal output, code-only, no explanations
    - ``explanatory``: Step-by-step reasoning, examples, definitions
    - ``formal``: Professional, structured, numbered sections
    - ``conversational``: Friendly, casual, uses analogies

Example:
    ```python
    from pydantic_deep import create_deep_agent

    # Use a built-in style
    agent = create_deep_agent(output_style="concise")

    # Use a custom style
    from pydantic_deep.styles import OutputStyle
    agent = create_deep_agent(
        output_style=OutputStyle(
            name="technical",
            description="Deep technical detail",
            content="Always include implementation details...",
        )
    )

    # Load from a directory
    agent = create_deep_agent(
        output_style="my-style",
        styles_dir="/path/to/styles",
    )
    ```
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class OutputStyle:
    """An output style that controls agent tone and response format.

    Attributes:
        name: Style identifier (e.g. "concise", "formal").
        description: Brief description of the style.
        content: The actual instructions to inject into the system prompt.
    """

    name: str
    description: str
    content: str


# --- Built-in styles ---

CONCISE_STYLE = OutputStyle(
    name="concise",
    description="Minimal output, just the essentials",
    content="""\
Be extremely concise in all responses:
- No explanations unless explicitly asked
- Code only with minimal comments
- One-line answers when possible
- Skip pleasantries and preamble
- Use bullet points over paragraphs
- Omit "here is" / "I'll" / "Let me" phrases""",
)

EXPLANATORY_STYLE = OutputStyle(
    name="explanatory",
    description="Detailed explanations with examples",
    content="""\
Provide detailed explanations in all responses:
- Explain your reasoning step by step
- Define technical terms when first used
- Provide concrete examples for abstract concepts
- Include "why" not just "what" when making decisions
- Summarize key points at the end of longer responses
- Link related concepts to build understanding""",
)

FORMAL_STYLE = OutputStyle(
    name="formal",
    description="Professional, structured format",
    content="""\
Use a professional, structured format in all responses:
- Use numbered sections and clear headings
- Write in complete sentences with proper grammar
- Cite specific files, functions, and line numbers
- Present trade-offs explicitly when relevant
- Include a brief summary at the start of longer responses
- Avoid colloquialisms and informal language""",
)

CONVERSATIONAL_STYLE = OutputStyle(
    name="conversational",
    description="Friendly, casual tone with analogies",
    content="""\
Use a friendly, conversational tone:
- Explain things as you would to a colleague
- Use analogies to clarify complex concepts
- Ask follow-up questions when requirements are ambiguous
- Share brief context for your decisions
- Be encouraging when the user is learning
- Keep technical accuracy while being approachable""",
)

BUILTIN_STYLES: dict[str, OutputStyle] = {
    "concise": CONCISE_STYLE,
    "explanatory": EXPLANATORY_STYLE,
    "formal": FORMAL_STYLE,
    "conversational": CONVERSATIONAL_STYLE,
}
"""Registry of built-in output styles, keyed by name."""


# --- Frontmatter parsing ---

_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)^---\s*\n", re.DOTALL | re.MULTILINE)
_KV_PATTERN = re.compile(r"^(\w+)\s*:\s*(.+)$", re.MULTILINE)


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like frontmatter from a markdown file.

    Uses regex-only parsing (no PyYAML dependency) since style
    frontmatter is simple key-value pairs.

    Args:
        content: Raw markdown file content.

    Returns:
        Tuple of (frontmatter dict, body text).
    """
    match = _FRONTMATTER_PATTERN.search(content)
    if not match:
        return {}, content.strip()

    frontmatter_text = match.group(1).strip()
    body = content[match.end() :].strip()

    # Parse key: value pairs
    frontmatter: dict[str, Any] = {}
    for kv_match in _KV_PATTERN.finditer(frontmatter_text):
        key = kv_match.group(1).strip()
        value = kv_match.group(2).strip()
        frontmatter[key] = value

    return frontmatter, body


# --- File loading ---


def load_style_from_file(path: str | Path) -> OutputStyle:
    """Load an OutputStyle from a markdown file with frontmatter.

    The file should have YAML-style frontmatter with at least a ``name``
    field, followed by the style content:

    ```markdown
    ---
    name: my-style
    description: My custom style
    ---

    Be very detailed in responses...
    ```

    Args:
        path: Path to the markdown style file.

    Returns:
        Loaded OutputStyle instance.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file has no ``name`` in frontmatter.
    """
    file_path = Path(path)
    content = file_path.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(content)

    name = frontmatter.get("name")
    if not name:
        raise ValueError(f"Style file {path} must have a 'name' in frontmatter")

    return OutputStyle(
        name=str(name),
        description=str(frontmatter.get("description", "")),
        content=body,
    )


def discover_styles(directory: str | Path) -> dict[str, OutputStyle]:
    """Discover output styles from markdown files in a directory.

    Scans the directory for ``*.md`` files, parses each as a style file
    (frontmatter + body), and returns a dict keyed by style name.
    Files without a ``name`` in frontmatter are skipped.

    Args:
        directory: Path to the styles directory.

    Returns:
        Dict of style name to OutputStyle.
    """
    dir_path = Path(directory)
    styles: dict[str, OutputStyle] = {}

    if not dir_path.is_dir():
        return styles

    for md_file in sorted(dir_path.glob("*.md")):
        if not md_file.is_file():
            continue  # pragma: no cover
        try:
            style = load_style_from_file(md_file)
            styles[style.name] = style
        except (ValueError, OSError):
            continue  # Skip files without valid frontmatter

    return styles


# --- Resolution ---


def resolve_style(
    style: str | OutputStyle,
    styles_dir: str | list[str] | None = None,
) -> OutputStyle:
    """Resolve a style by name or pass through an OutputStyle instance.

    Resolution order:
    1. If ``style`` is an OutputStyle, return it directly.
    2. If ``style`` is a string, look up in built-in styles.
    3. If not found, search in ``styles_dir`` directories.
    4. If still not found, raise ValueError.

    Args:
        style: Style name (string) or OutputStyle instance.
        styles_dir: Directory or list of directories to search for
            custom styles.

    Returns:
        Resolved OutputStyle instance.

    Raises:
        ValueError: If style name is not found anywhere.
    """
    if isinstance(style, OutputStyle):
        return style

    # Look up in built-ins
    if style in BUILTIN_STYLES:
        return BUILTIN_STYLES[style]

    # Search in directories
    dirs: list[str] = []
    if isinstance(styles_dir, str):
        dirs = [styles_dir]
    elif styles_dir is not None:
        dirs = list(styles_dir)

    for d in dirs:
        found = discover_styles(d)
        if style in found:
            return found[style]

    available = list(BUILTIN_STYLES.keys())
    raise ValueError(f"Unknown output style '{style}'. Available built-in styles: {available}")


# --- Formatting ---


def format_style_prompt(style: OutputStyle) -> str:
    """Format an OutputStyle for injection into the system prompt.

    Args:
        style: The output style to format.

    Returns:
        Formatted string ready for system prompt injection.
    """
    return f"## Output Style: {style.name}\n\n{style.content}"
