"""Shared text helpers: approximate token sizing and head/tail truncation."""

from __future__ import annotations

NUM_CHARS_PER_TOKEN = 4
"""Approximate characters per token, matching summarization-pydantic-ai's heuristic."""


def approx_tokens(text: str) -> int:
    """Estimate the token count of `text` using the chars-per-token heuristic."""
    return len(text) // NUM_CHARS_PER_TOKEN


def truncate_text(content: str, max_chars: int, *, head_ratio: float = 0.7) -> str:
    """Truncate `content` to `max_chars`, keeping a head and tail with a marker."""
    if len(content) <= max_chars:
        return content
    head_len = int(max_chars * head_ratio)
    tail_len = max_chars - head_len
    truncated = len(content) - max_chars
    tail = content[-tail_len:] if tail_len > 0 else ""
    return content[:head_len] + f"\n\n... [{truncated} chars truncated] ...\n\n" + tail


def create_content_preview(
    content: str,
    *,
    head_lines: int = 5,
    tail_lines: int = 5,
    max_chars: int | None = None,
) -> str:
    """Preview `content` by its first `head_lines` and last `tail_lines` lines.

    `max_chars`, when set, also bounds the result by characters so single-line
    or few-line payloads (minified JSON, base64) are shrunk rather than mirrored
    back whole. Line-only callers (unified diffs) leave it `None`.
    """
    lines = content.splitlines()

    if len(lines) <= head_lines + tail_lines:
        preview = content
    else:
        head = lines[:head_lines]
        tail = lines[-tail_lines:]
        truncated = len(lines) - head_lines - tail_lines
        preview = (
            "\n".join(head) + f"\n\n... [{truncated} lines truncated] ...\n\n" + "\n".join(tail)
        )

    if max_chars is not None and len(preview) > max_chars:
        head_chars = max_chars // 2
        tail_chars = max_chars - head_chars
        cut = len(preview) - max_chars
        preview = (
            preview[:head_chars]
            + f"\n\n... [{cut} chars truncated] ...\n\n"
            + preview[-tail_chars:]
        )

    return preview
