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

import inspect
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    ToolReturn,
    ToolReturnPart,
    UserPromptPart,
)
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

DEFAULT_MAX_BINARY_CONTENT = 3
"""Default maximum number of multimodal binary parts to keep in history."""

EVICTION_MESSAGE_TEMPLATE = """Tool result too large, saved to: {file_path}

Read the result using read_file with offset and limit parameters.
Example: read_file(path="{file_path}", offset=0, limit=100)

Preview (head/tail):

{content_sample}
"""
"""Template for the replacement message after eviction."""

BINARY_PRUNED_TEMPLATE = (
    "[Binary content omitted: {media_type}, {size} bytes, "
    'saved to {file_path}. Use read_file(path="{file_path}") to retrieve.]'
)
"""Template for the text replacement of a pruned ``BinaryContent`` part."""

_MEDIA_TYPE_EXTENSIONS: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/flac": "flac",
    "audio/ogg": "ogg",
    "audio/aac": "aac",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "application/pdf": "pdf",
    "application/json": "json",
    "text/plain": "txt",
    "text/csv": "csv",
    "text/markdown": "md",
    "text/html": "html",
}
"""Mapping of common media types to file extensions used when storing pruned binaries."""


def _extension_for_media_type(media_type: str) -> str:
    """Return a filename extension for ``media_type``.

    Falls back to the media subtype (e.g. ``"image/x-foo"`` -> ``"x-foo"``)
    or ``"bin"`` when the media type cannot be split.
    """
    if media_type in _MEDIA_TYPE_EXTENSIONS:
        return _MEDIA_TYPE_EXTENSIONS[media_type]
    if "/" in media_type:
        subtype = media_type.split("/", 1)[1].split(";", 1)[0].strip()
        if subtype:
            return re.sub(r"[^a-zA-Z0-9_-]", "_", subtype) or "bin"
    return "bin"


def _binary_storage_path(eviction_path: str, binary: BinaryContent) -> str:
    """Build a deterministic storage path for a ``BinaryContent`` value."""
    extension = _extension_for_media_type(binary.media_type)
    return f"{eviction_path.rstrip('/')}/binary_{binary.identifier}.{extension}"


def _binary_replacement_text(binary: BinaryContent, file_path: str) -> str:
    """Return the text placeholder used to replace a pruned binary part."""
    return BINARY_PRUNED_TEMPLATE.format(
        media_type=binary.media_type,
        size=len(binary.data),
        file_path=file_path,
    )


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
        agent = Agent("anthropic:claude-sonnet-4-6", history_processors=[processor])
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

    on_eviction: Callable[[str, str, int, int], Any] | None = None
    """Callback when tool output is evicted.

    Called with (tool_name, file_path, original_chars, preview_chars).
    """

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
                    new_parts.append(part)  # type: ignore[arg-type]
                    continue

                content_str = _content_to_str(part.content)

                if len(content_str) <= char_limit:
                    new_parts.append(part)  # type: ignore[arg-type]
                    continue

                # Evict: save to backend, replace with preview
                sanitized_id = _sanitize_id(part.tool_call_id)
                file_path = f"{self.eviction_path}/{sanitized_id}"
                write_result = backend.write(file_path, content_str)

                if write_result.error:
                    # Keep original on write failure
                    new_parts.append(part)  # type: ignore[arg-type]
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
                new_parts.append(evicted_part)  # type: ignore[arg-type]
                self._evicted_ids.add(part.tool_call_id)

                if self.on_eviction is not None:
                    _result = self.on_eviction(
                        part.tool_name, file_path, len(content_str), len(replacement)
                    )
                    if inspect.isawaitable(_result):
                        await _result

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
    on_eviction: Callable[[str, str, int, int], Any] | None = None,
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
        on_eviction: Callback when tool output is evicted. Called with
            (tool_name, file_path, original_chars, preview_chars).

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
        on_eviction=on_eviction,
    )


# ---------------------------------------------------------------------------
# Capability-based eviction (preferred — intercepts before history)
# ---------------------------------------------------------------------------

from pydantic_ai.capabilities import AbstractCapability  # noqa: E402
from pydantic_ai.messages import ToolCallPart  # noqa: E402
from pydantic_ai.tools import ToolDefinition  # noqa: E402


@dataclass
class EvictionCapability(AbstractCapability[Any]):
    """Capability that intercepts large tool outputs via ``after_tool_execute``.

    Unlike :class:`EvictionProcessor` (a history processor that runs after the
    result is already in message history), this capability intercepts the tool
    result **before** it enters the conversation — so the large output never
    bloats the message list.

    The evicted content is saved to a file via the backend, and the tool result
    is replaced with a compact preview + file reference.

    For tool results that are :class:`pydantic_ai.messages.ToolReturn` values,
    only the ``return_value`` is considered for size-based eviction; multimodal
    ``content`` (such as :class:`BinaryContent` screenshots) is preserved.

    Multimodal binary parts that accumulate across messages are bounded by
    ``max_binary_content`` via :meth:`before_model_request`. Older binaries are
    written to the backend and replaced with a compact retrievable text
    reference, so the agent can still re-read them via ``read_file``.

    Args:
        backend: Fallback backend for writing evicted files.
        token_limit: Maximum estimated tokens before eviction (default: 20K).
        eviction_path: Directory in the backend for evicted files.
        head_lines: Lines from start in preview.
        tail_lines: Lines from end in preview.
        max_binary_content: Maximum multimodal binary parts to keep in
            history. Older binaries are persisted to the backend and replaced
            with a text reference. ``None`` disables binary pruning.
        on_eviction: Optional callback ``(tool_name, file_path, original_chars, preview_chars)``.
    """

    backend: BackendProtocol | None = None
    token_limit: int = DEFAULT_TOKEN_LIMIT
    eviction_path: str = DEFAULT_EVICTION_PATH
    head_lines: int = DEFAULT_HEAD_LINES
    tail_lines: int = DEFAULT_TAIL_LINES
    max_binary_content: int | None = DEFAULT_MAX_BINARY_CONTENT
    on_eviction: Callable[[str, str, int, int], Any] | None = None

    def _resolve_backend(self, ctx: RunContext[Any]) -> BackendProtocol | None:
        """Resolve backend from deps or fallback."""
        deps_backend = getattr(ctx.deps, "backend", None)
        if deps_backend is not None and isinstance(deps_backend, BackendProtocol):
            return deps_backend
        return self.backend

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Intercept large tool results before they enter message history.

        ``ToolReturn`` results are handled specially: only ``return_value`` is
        considered for size-based text eviction so multimodal ``content`` (e.g.
        :class:`BinaryContent` screenshots) is never collapsed into a string.
        """
        if isinstance(result, ToolReturn):
            evicted_value = await self._maybe_evict_text(ctx, call=call, value=result.return_value)
            if evicted_value is None:
                return result
            return ToolReturn(
                return_value=evicted_value,
                content=result.content,
                metadata=result.metadata,
            )

        evicted = await self._maybe_evict_text(ctx, call=call, value=result)
        if evicted is None:
            return result
        return evicted

    async def _maybe_evict_text(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        value: Any,
    ) -> str | None:
        """Apply text eviction to ``value``.

        Returns the replacement text when eviction occurred or ``None`` when
        the value is below the threshold or eviction could not be performed.
        """
        content_str = _content_to_str(value)
        char_limit = self.token_limit * NUM_CHARS_PER_TOKEN

        if len(content_str) <= char_limit:
            return None

        backend = self._resolve_backend(ctx)
        if backend is None:
            return None

        sanitized_id = _sanitize_id(call.tool_call_id)
        file_path = f"{self.eviction_path}/{sanitized_id}"
        write_result = backend.write(file_path, content_str)

        if write_result.error:
            return None

        preview = create_content_preview(
            content_str,
            head_lines=self.head_lines,
            tail_lines=self.tail_lines,
        )
        replacement = EVICTION_MESSAGE_TEMPLATE.format(
            file_path=file_path,
            content_sample=preview,
        )

        if self.on_eviction is not None:
            _cb_result = self.on_eviction(
                call.tool_name, file_path, len(content_str), len(replacement)
            )
            if inspect.isawaitable(_cb_result):
                await _cb_result

        return replacement

    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: Any,
    ) -> Any:
        """Bound the number of multimodal binary parts in message history.

        Walks ``request_context.messages`` newest-to-oldest and keeps the most
        recent ``max_binary_content`` :class:`BinaryContent` parts. Older
        binaries are written to the runtime backend and replaced with a
        compact text reference so the agent can still retrieve them via
        ``read_file``. Binaries are left untouched when no backend is
        available or when a write fails, to avoid losing data.
        """
        limit = self.max_binary_content
        if limit is None or limit < 0:
            return request_context

        backend = self._resolve_backend(ctx)
        if backend is None:
            return request_context

        request_context.messages = _prune_binaries_in_messages(
            request_context.messages,
            max_binary_content=limit,
            backend=backend,
            eviction_path=self.eviction_path,
        )
        return request_context


def _prune_binaries_in_messages(
    messages: list[ModelMessage],
    *,
    max_binary_content: int,
    backend: BackendProtocol,
    eviction_path: str,
) -> list[ModelMessage]:
    """Return ``messages`` with older binary parts pruned and stored in ``backend``."""
    kept = 0
    new_messages: list[ModelMessage] = list(messages)

    for msg_idx in range(len(new_messages) - 1, -1, -1):
        message = new_messages[msg_idx]
        if not isinstance(message, ModelRequest):
            continue

        new_parts = list(message.parts)
        modified = False

        for part_idx in range(len(new_parts) - 1, -1, -1):
            part = new_parts[part_idx]

            if isinstance(part, UserPromptPart):
                new_content, kept, part_modified = _prune_user_content(
                    part.content,
                    kept=kept,
                    max_binary_content=max_binary_content,
                    backend=backend,
                    eviction_path=eviction_path,
                )
                if part_modified:
                    new_parts[part_idx] = UserPromptPart(
                        content=new_content,
                        timestamp=part.timestamp,
                    )
                    modified = True

            elif isinstance(part, ToolReturnPart):
                new_content, kept, part_modified = _prune_tool_return_content(
                    part.content,
                    kept=kept,
                    max_binary_content=max_binary_content,
                    backend=backend,
                    eviction_path=eviction_path,
                )
                if part_modified:
                    new_parts[part_idx] = ToolReturnPart(
                        tool_name=part.tool_name,
                        content=new_content,
                        tool_call_id=part.tool_call_id,
                        metadata=part.metadata,
                        timestamp=part.timestamp,
                    )
                    modified = True

        if modified:
            new_messages[msg_idx] = ModelRequest(
                parts=new_parts,
                timestamp=message.timestamp,
                instructions=message.instructions,
            )

    return new_messages


def _prune_user_content(
    content: str | Sequence[Any],
    *,
    kept: int,
    max_binary_content: int,
    backend: BackendProtocol,
    eviction_path: str,
) -> tuple[str | list[Any], int, bool]:
    """Prune binaries from a ``UserPromptPart.content`` value.

    Walks the list right-to-left so the most recent binaries (later in the
    list) are kept. Returns the rebuilt content, updated ``kept`` count, and a
    flag indicating whether any pruning occurred.
    """
    if isinstance(content, str):
        return content, kept, False

    items = list(content)
    modified = False

    for i in range(len(items) - 1, -1, -1):
        item = items[i]
        if not isinstance(item, BinaryContent):
            continue
        if kept < max_binary_content:
            kept += 1
            continue
        replacement = _store_and_replace_binary(item, backend=backend, eviction_path=eviction_path)
        if replacement is None:
            kept += 1
            continue
        items[i] = replacement
        modified = True

    return items, kept, modified


def _prune_tool_return_content(
    content: Any,
    *,
    kept: int,
    max_binary_content: int,
    backend: BackendProtocol,
    eviction_path: str,
) -> tuple[Any, int, bool]:
    """Prune binaries from a ``ToolReturnPart.content`` value.

    Handles three shapes:

    - A bare :class:`BinaryContent` value (replaced with text when pruned).
    - A list/tuple containing :class:`BinaryContent` items (walked
      right-to-left so the most recent binaries are kept).
    - Any other value (returned unchanged).
    """
    if isinstance(content, BinaryContent):
        if kept < max_binary_content:
            return content, kept + 1, False
        replacement = _store_and_replace_binary(
            content, backend=backend, eviction_path=eviction_path
        )
        if replacement is None:
            return content, kept + 1, False
        return replacement, kept, True

    if isinstance(content, (list, tuple)):
        items = list(content)
        modified = False

        for i in range(len(items) - 1, -1, -1):
            item = items[i]
            if not isinstance(item, BinaryContent):
                continue
            if kept < max_binary_content:
                kept += 1
                continue
            replacement = _store_and_replace_binary(
                item, backend=backend, eviction_path=eviction_path
            )
            if replacement is None:
                kept += 1
                continue
            items[i] = replacement
            modified = True

        return items, kept, modified

    return content, kept, False


def _store_and_replace_binary(
    binary: BinaryContent,
    *,
    backend: BackendProtocol,
    eviction_path: str,
) -> str | None:
    """Persist ``binary`` to the backend and return a text replacement.

    Returns ``None`` when the write fails, signalling that the caller should
    keep the original binary in place.
    """
    file_path = _binary_storage_path(eviction_path, binary)
    write_result = backend.write(file_path, binary.data)
    if write_result.error:
        return None
    return _binary_replacement_text(binary, file_path)
