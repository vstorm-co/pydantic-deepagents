"""Large tool output eviction.

`EvictionCapability` intercepts oversized tool results in `after_tool_execute`
- before they enter message history - and replaces them with a compact preview
plus a file reference written to the runtime backend, so console tools
(`read_file`, `grep`) can still retrieve the full content. It also bounds the
number of multimodal `BinaryContent` parts kept in history.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    ToolCallPart,
    ToolReturn,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai_backends import AsyncBackendProtocol

from pydantic_deep._text import NUM_CHARS_PER_TOKEN, create_content_preview
from pydantic_deep.deps import DeepAgentDeps

DEFAULT_TOKEN_LIMIT = 20_000
"""Default token limit before eviction (20K tokens)."""

DEFAULT_EVICTION_PATH = "/large_tool_results"
"""Default directory path for evicted tool outputs."""

DEFAULT_HEAD_LINES = 5
"""Default number of lines to show from the start of content in preview."""

DEFAULT_TAIL_LINES = 5
"""Default number of lines to show from the end of content in preview."""

DEFAULT_PREVIEW_MAX_CHARS = 2_000
"""Character cap for a preview, so payloads with few newlines still shrink."""

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
"""Template for the text replacement of a pruned `BinaryContent` part."""

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
    """Return a filename extension for `media_type`, falling back to the subtype."""
    if media_type in _MEDIA_TYPE_EXTENSIONS:
        return _MEDIA_TYPE_EXTENSIONS[media_type]
    if "/" in media_type:
        subtype = media_type.split("/", 1)[1].split(";", 1)[0].strip()
        if subtype:
            return re.sub(r"[^a-zA-Z0-9_-]", "_", subtype) or "bin"
    return "bin"


def _binary_storage_path(eviction_path: str, binary: BinaryContent) -> str:
    """Build a deterministic storage path for a `BinaryContent` value."""
    # BinaryContent's fields and `identifier` are invisible to pyright but present
    # at runtime (upstream type-info gap); mypy's pydantic plugin sees them.
    extension = _extension_for_media_type(binary.media_type)  # type: ignore[attr-defined, unused-ignore]
    return f"{eviction_path.rstrip('/')}/binary_{binary.identifier}.{extension}"  # type: ignore[attr-defined, unused-ignore]


def _binary_replacement_text(binary: BinaryContent, file_path: str) -> str:
    """Return the text placeholder used to replace a pruned binary part."""
    return BINARY_PRUNED_TEMPLATE.format(
        media_type=binary.media_type,  # type: ignore[attr-defined, unused-ignore]
        size=len(binary.data),  # type: ignore[attr-defined, unused-ignore]
        file_path=file_path,
    )


def _contains_binary(value: Any) -> bool:
    """Return True if `value` is a `BinaryContent` or a list/tuple holding one.

    Text eviction must skip such multimodal payloads: coercing the bytes to a
    text repr would discard the image and bloat the context.
    """
    if isinstance(value, BinaryContent):
        return True
    if isinstance(value, (list, tuple)):
        return any(isinstance(item, BinaryContent) for item in value)
    return False


def _content_to_str(content: Any) -> str:
    """Convert tool return content to a string for size estimation."""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, default=str)
    except (TypeError, ValueError):
        return str(content)


def _sanitize_id(tool_call_id: str) -> str:
    """Sanitize a tool call ID for use as a filename.

    When sanitization is lossy (the id had filename-unsafe characters), distinct
    ids could collapse to the same name and overwrite each other's evicted file.
    Append a short hash of the raw id in that case so they stay distinct (B8).
    Clean ids (the common alphanumeric case) are returned unchanged.
    """
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_call_id)
    if safe != tool_call_id:
        suffix = hashlib.sha256(tool_call_id.encode()).hexdigest()[:8]
        return f"{safe}-{suffix}"
    return safe


logger = logging.getLogger(__name__)


@dataclass
class EvictionCapability(AbstractCapability[DeepAgentDeps]):
    """Capability that intercepts large tool outputs via `after_tool_execute`.

    The oversized result is saved to a file via the backend and replaced with a
    compact preview plus a file reference, so the large output never enters the
    message list. For `ToolReturn` values only `return_value` is size-checked;
    multimodal `content` (e.g. `BinaryContent` screenshots) is preserved.

    Multimodal binary parts accumulating across messages are bounded by
    `max_binary_content` in `before_model_request`: older binaries are written to
    the backend and replaced with a retrievable text reference.

    Args:
        backend: Fallback backend for writing evicted files.
        token_limit: Maximum estimated tokens before eviction (default: 20K).
        eviction_path: Directory in the backend for evicted files.
        head_lines: Lines from start in preview.
        tail_lines: Lines from end in preview.
        max_binary_content: Maximum multimodal binary parts to keep in history.
            `None` disables binary pruning.
        on_eviction: Optional callback `(tool_name, file_path, original_chars, preview_chars)`.
    """

    backend: AsyncBackendProtocol | None = None
    token_limit: int = DEFAULT_TOKEN_LIMIT
    eviction_path: str = DEFAULT_EVICTION_PATH
    head_lines: int = DEFAULT_HEAD_LINES
    tail_lines: int = DEFAULT_TAIL_LINES
    max_binary_content: int | None = DEFAULT_MAX_BINARY_CONTENT
    on_eviction: Callable[[str, str, int, int], Any] | None = None

    def __post_init__(self) -> None:
        if self.token_limit <= 0:
            raise ValueError(f"token_limit must be positive, got {self.token_limit}")

    def _resolve_backend(self, ctx: RunContext[DeepAgentDeps]) -> AsyncBackendProtocol | None:
        """Prefer the runtime backend from deps; fall back to `self.backend`."""
        deps_backend = getattr(ctx.deps, "backend", None)
        if deps_backend is not None and isinstance(deps_backend, AsyncBackendProtocol):
            return deps_backend
        return self.backend

    async def after_tool_execute(
        self,
        ctx: RunContext[DeepAgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Intercept large tool results before they enter message history."""
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
        ctx: RunContext[DeepAgentDeps],
        *,
        call: ToolCallPart,
        value: Any,
    ) -> str | None:
        """Evict `value` when it is over the limit, returning the replacement text."""
        if _contains_binary(value):
            return None
        content_str = _content_to_str(value)
        char_limit = self.token_limit * NUM_CHARS_PER_TOKEN

        if len(content_str) <= char_limit:
            return None

        backend = self._resolve_backend(ctx)
        if backend is None:
            return None

        preview = create_content_preview(
            content_str,
            head_lines=self.head_lines,
            tail_lines=self.tail_lines,
            max_chars=DEFAULT_PREVIEW_MAX_CHARS,
        )

        sanitized_id = _sanitize_id(call.tool_call_id)
        file_path = f"{self.eviction_path}/{sanitized_id}"
        write_result = await backend.write(file_path, content_str)

        if write_result.error:
            # The write failed, so the agent can't read the file back. Returning
            # the original (oversized) content would silently defeat eviction and
            # blow the context, so return the truncated preview instead (B4).
            logger.warning(
                "Eviction write to %s failed (%s); returning truncated preview",
                file_path,
                write_result.error,
            )
            return preview

        replacement = EVICTION_MESSAGE_TEMPLATE.format(
            file_path=file_path,
            content_sample=preview,
        )

        if self.on_eviction is not None:
            # A notification side-channel must never abort the run (B10).
            try:
                _cb_result = self.on_eviction(
                    call.tool_name, file_path, len(content_str), len(replacement)
                )
                if inspect.isawaitable(_cb_result):
                    await _cb_result
            except Exception:
                logger.warning("on_eviction callback raised; continuing", exc_info=True)

        return replacement

    async def before_model_request(
        self,
        ctx: RunContext[DeepAgentDeps],
        request_context: Any,
    ) -> Any:
        """Bound the number of multimodal binary parts in message history.

        Walks messages newest-to-oldest, keeps the most recent
        `max_binary_content` `BinaryContent` parts, and replaces older ones with
        a retrievable text reference. Binaries are left untouched when no backend
        is available or a write fails.
        """
        limit = self.max_binary_content
        if limit is None or limit < 0:
            return request_context

        backend = self._resolve_backend(ctx)
        if backend is None:
            return request_context

        request_context.messages = await _prune_binaries_in_messages(
            request_context.messages,
            max_binary_content=limit,
            backend=backend,
            eviction_path=self.eviction_path,
        )
        return request_context


async def _prune_binaries_in_messages(
    messages: list[ModelMessage],
    *,
    max_binary_content: int,
    backend: AsyncBackendProtocol,
    eviction_path: str,
) -> list[ModelMessage]:
    """Return `messages` with older binary parts pruned and stored in `backend`."""
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
                new_content, kept, part_modified = await _prune_user_content(
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
                new_content, kept, part_modified = await _prune_tool_return_content(
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


async def _prune_user_content(
    content: str | Sequence[Any],
    *,
    kept: int,
    max_binary_content: int,
    backend: AsyncBackendProtocol,
    eviction_path: str,
) -> tuple[str | list[Any], int, bool]:
    """Prune binaries from a `UserPromptPart.content` value (newest kept)."""
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
        replacement = await _store_and_replace_binary(
            item, backend=backend, eviction_path=eviction_path
        )
        if replacement is None:
            kept += 1
            continue
        items[i] = replacement
        modified = True

    return items, kept, modified


async def _prune_tool_return_content(
    content: Any,
    *,
    kept: int,
    max_binary_content: int,
    backend: AsyncBackendProtocol,
    eviction_path: str,
) -> tuple[Any, int, bool]:
    """Prune binaries from a `ToolReturnPart.content` value (newest kept).

    Handles a bare `BinaryContent`, a list/tuple holding `BinaryContent` items,
    or any other value (returned unchanged).
    """
    if isinstance(content, BinaryContent):
        if kept < max_binary_content:
            return content, kept + 1, False
        replacement = await _store_and_replace_binary(
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
            replacement = await _store_and_replace_binary(
                item, backend=backend, eviction_path=eviction_path
            )
            if replacement is None:
                kept += 1
                continue
            items[i] = replacement
            modified = True

        return items, kept, modified

    return content, kept, False


async def _store_and_replace_binary(
    binary: BinaryContent,
    *,
    backend: AsyncBackendProtocol,
    eviction_path: str,
) -> str | None:
    """Persist `binary` to the backend and return a text replacement, or `None` on failure."""
    file_path = _binary_storage_path(eviction_path, binary)
    write_result = await backend.write(file_path, binary.data)  # type: ignore[attr-defined, unused-ignore]
    if write_result.error:
        return None
    return _binary_replacement_text(binary, file_path)
