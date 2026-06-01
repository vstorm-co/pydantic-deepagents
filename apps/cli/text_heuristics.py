"""Small text-classification helpers shared across CLI modules."""

from __future__ import annotations

_ERROR_KEYWORD_HEAD_CHARS = 100

_TRACEBACK_KEYWORD_HEAD_CHARS = 200


def looks_like_error(text: str, *, check_exit_code: bool = False) -> bool:
    """Heuristic — does this tool-return string read as an error?

    Used by the CLI for visual classification only (red vs neutral badges,
    "error" vs "completed" status labels). Never used for control flow —
    real tool errors come through `ToolReturnPart` metadata, not this
    keyword scan.

    Looks for `"error"` in the first `_ERROR_KEYWORD_HEAD_CHARS` chars
    or `"traceback"` in the first `_TRACEBACK_KEYWORD_HEAD_CHARS` chars
    of a lowercased copy of `text`. When `check_exit_code` is True
    (relevant for shell-tool output), also looks for `"exit code 1"`
    anywhere — shell wrappers prepend stdout/stderr before the exit line,
    so an early-prefix scan would miss it.
    """
    lower = text.lower()
    if "error" in lower[:_ERROR_KEYWORD_HEAD_CHARS]:
        return True
    if "traceback" in lower[:_TRACEBACK_KEYWORD_HEAD_CHARS]:
        return True
    return bool(check_exit_code and "exit code 1" in lower)
