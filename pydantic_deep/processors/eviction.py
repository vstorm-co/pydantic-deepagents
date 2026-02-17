"""Large tool output eviction processor.

Automatically saves large tool outputs to files and replaces them with
a preview + file reference, preventing context pollution.

Pattern inspired by deepagents FilesystemMiddleware._intercept_large_tool_result().
Architecture follows summarization-pydantic-ai (SummarizationProcessor pattern).

Uses ``RunContext`` to access the runtime backend from deps, ensuring evicted
files are written to the same backend that console tools (read_file, grep) use.
Falls back to ``self.backend`` for standalone usage without ``RunContext``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
from pydantic_ai.tools import RunContext
from pydantic_ai_backends import BackendProtocol

NUM_CHARS_PER_TOKEN = 4
"""Approximate number of characters per token.

Same convention as ``count_tokens_approximately`` in summarization-pydantic-ai.
"""

DEFAULT_TOKEN_LIMIT = 20_000
"""Default token limit before eviction (20K tokens)."""

DEFAULT_EVICTION_PATH = "/large_tool_results"
"""Default directory path for evicted tool outputs."""

DEFAULT_HEAD_LINES = 5
"""Default number of lines to show from the start of content in preview."""

DEFAULT_TAIL_LINES = 5
"""Default number of lines to show from the end of content in preview."""

EVICTION_MESSAGE_TEMPLATE = """Tool result too large, saved to: {file_path}

Read the result using read_file with offset and limit parameters.
Example: read_file(path="{file_path}", offset=0, limit=100)

Preview (head/tail):

{content_sample}
"""
"""Template for the replacement message after eviction."""


def create_content_preview(content: str, *, head_lines: int = 5, tail_lines: int = 5) -> str:
    """Create a preview showing the head and tail of content with a truncation marker.

    Args:
        content: The full content string to preview.
        head_lines: Number of lines to show from the start.
        tail_lines: Number of lines to show from the end.

    Returns:
        Preview string with head, truncation marker, and tail.
    """
    lines = content.splitlines()

    if len(lines) <= head_lines + tail_lines:
        return content

    head = lines[:head_lines]
    tail = lines[-tail_lines:]
    truncated = len(lines) - head_lines - tail_lines

    return "\n".join(head) + f"\n\n... [{truncated} lines truncated] ...\n\n" + "\n".join(tail)


def _content_to_str(content: Any) -> str:
    """Convert ToolReturnContent to a string for size estimation.

    Args:
        content: The tool return content (str, dict, list, or any).

    Returns:
        String representation of the content.
    """
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, default=str)
    except (TypeError, ValueError):
        return str(content)


def _sanitize_id(tool_call_id: str) -> str:
    """Sanitize a tool call ID for use as a filename.

    Replaces any characters that are not alphanumeric, underscore,
    or hyphen with underscores.

    Args:
        tool_call_id: The original tool call identifier.

    Returns:
        Sanitized string safe for use as a filename.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", tool_call_id)


@dataclass
class EvictionProcessor:
    """History processor that evicts large tool outputs to files.

    Scans ``ToolReturnPart`` elements in message history and saves
    content exceeding the token limit to the backend filesystem,
    replacing it with a preview + file reference.

    Uses ``RunContext`` to access the runtime backend from deps, ensuring
    evicted files are written to the same backend that console tools
    (read_file, grep, execute) use. Falls back to ``self.backend`` for
    standalone usage without ``RunContext``.

    Attributes:
        backend: Fallback backend for standalone usage (without RunContext).
        token_limit: Maximum tokens before eviction (default: 20K).
        eviction_path: Directory path for evicted files.
        head_lines: Lines to show from start in preview.
        tail_lines: Lines to show from end in preview.

    Example:
        ```python
        from pydantic_deep import create_deep_agent

        # Via create_deep_agent (recommended — uses runtime deps.backend):
        agent = create_deep_agent(eviction_token_limit=20000)

        # Standalone with explicit backend:
        from pydantic_ai import Agent
        from pydantic_ai_backends import StateBackend
        from pydantic_deep.processors.eviction import EvictionProcessor

        backend = StateBackend()
        processor = EvictionProcessor(backend=backend)
        agent = Agent("openai:gpt-4.1", history_processors=[processor])
        ```
    """

    backend: BackendProtocol
    """Fallback backend used when RunContext is not available or deps has no backend."""

    token_limit: int = DEFAULT_TOKEN_LIMIT
    """Maximum estimated tokens before a tool output is evicted."""

    eviction_path: str = DEFAULT_EVICTION_PATH
    """Directory path in the backend where evicted files are stored."""

    head_lines: int = DEFAULT_HEAD_LINES
    """Number of lines from the start to include in the preview."""

    tail_lines: int = DEFAULT_TAIL_LINES
    """Number of lines from the end to include in the preview."""

    _evicted_ids: set[str] = field(default_factory=set, repr=False)
    """Tracks tool_call_ids that have already been evicted to prevent re-eviction."""

    def _resolve_backend(self, ctx: RunContext[Any]) -> BackendProtocol:
        """Resolve the backend to use for writing evicted content.

        Prefers the runtime backend from ``ctx.deps.backend`` to ensure
        evicted files are accessible by console tools (read_file, grep).
        Falls back to ``self.backend`` if deps has no backend attribute.

        Args:
            ctx: The run context from pydantic-ai.

        Returns:
            The backend to use for writing.
        """
        deps_backend = getattr(ctx.deps, "backend", None)
        if deps_backend is not None and isinstance(deps_backend, BackendProtocol):
            return deps_backend
        return self.backend

    async def __call__(
        self, ctx: RunContext[Any], messages: list[ModelMessage]
    ) -> list[ModelMessage]:
        """Process messages and evict large tool outputs.

        This is the main entry point called by pydantic-ai's history
        processor mechanism before each model request. The ``RunContext``
        parameter is detected by pydantic-ai's ``is_takes_ctx()`` and
        automatically provided.

        Args:
            ctx: Run context providing access to runtime deps.
            messages: Current message history.

        Returns:
            Message history with large tool outputs replaced by previews.
        """
        backend = self._resolve_backend(ctx)
        char_limit = self.token_limit * NUM_CHARS_PER_TOKEN
        result_messages: list[ModelMessage] = []

        for message in messages:
            if not isinstance(message, ModelRequest):
                result_messages.append(message)
                continue

            new_parts = []
            modified = False

            for part in message.parts:
                if not isinstance(part, ToolReturnPart):
                    new_parts.append(part)
                    continue

                # Skip already-evicted tool outputs
                if part.tool_call_id in self._evicted_ids:
                    new_parts.append(part)
                    continue

                content_str = _content_to_str(part.content)

                if len(content_str) <= char_limit:
                    new_parts.append(part)
                    continue

                # Evict: save to backend, replace with preview
                sanitized_id = _sanitize_id(part.tool_call_id)
                file_path = f"{self.eviction_path}/{sanitized_id}"
                write_result = backend.write(file_path, content_str)

                if write_result.error:
                    # Keep original on write failure
                    new_parts.append(part)
                    continue

                preview = create_content_preview(
                    content_str,
                    head_lines=self.head_lines,
                    tail_lines=self.tail_lines,
                )
                replacement = EVICTION_MESSAGE_TEMPLATE.format(
                    file_path=file_path,
                    content_sample=preview,
                )

                evicted_part = ToolReturnPart(
                    tool_name=part.tool_name,
                    content=replacement,
                    tool_call_id=part.tool_call_id,
                    metadata=part.metadata,
                    timestamp=part.timestamp,
                )
                new_parts.append(evicted_part)
                self._evicted_ids.add(part.tool_call_id)
                modified = True

            if modified:
                result_messages.append(
                    ModelRequest(
                        parts=new_parts,
                        timestamp=message.timestamp,
                        instructions=message.instructions,
                    )
                )
            else:
                result_messages.append(message)

        return result_messages


def create_eviction_processor(
    backend: BackendProtocol,
    *,
    token_limit: int = DEFAULT_TOKEN_LIMIT,
    eviction_path: str = DEFAULT_EVICTION_PATH,
    head_lines: int = DEFAULT_HEAD_LINES,
    tail_lines: int = DEFAULT_TAIL_LINES,
) -> EvictionProcessor:
    """Create an eviction processor for large tool outputs.

    Factory function following the pattern of ``create_summarization_processor()``
    from summarization-pydantic-ai.

    Args:
        backend: File storage backend for saving evicted content.
        token_limit: Maximum tokens before eviction (default: 20K).
        eviction_path: Directory path for evicted files.
        head_lines: Lines to show from start in preview.
        tail_lines: Lines to show from end in preview.

    Returns:
        Configured EvictionProcessor instance.

    Example:
        ```python
        from pydantic_ai_backends import StateBackend
        from pydantic_deep import create_eviction_processor

        processor = create_eviction_processor(
            backend=StateBackend(),
            token_limit=20000,
        )
        ```
    """
    return EvictionProcessor(
        backend=backend,
        token_limit=token_limit,
        eviction_path=eviction_path,
        head_lines=head_lines,
        tail_lines=tail_lines,
    )
