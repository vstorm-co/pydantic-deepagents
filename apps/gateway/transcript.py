"""Convert stored `ModelMessage` history into display items.

Lets a frontend rehydrate a session's transcript when it is (re)selected,
reusing the same tool classification the live stream uses.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from pydantic_deep.session import looks_like_tool_error, tool_kind, tool_title


def history_to_items(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Render message history into ``user``/``assistant`` display items.

    Tool calls are matched to their returns so each assistant turn shows its
    tools with final status and (truncated) result.
    """
    tool_results: dict[str, tuple[str, bool]] = {}
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    content = str(part.content) if part.content else ""
                    tool_results[part.tool_call_id] = (content, looks_like_tool_error(content))

    items: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    items.append({"kind": "user", "text": part.content})
        elif isinstance(message, ModelResponse):
            text = ""
            tools: list[dict[str, Any]] = []
            for part in message.parts:
                if isinstance(part, TextPart):
                    text += part.content
                elif isinstance(part, ToolCallPart):
                    content, is_error = tool_results.get(part.tool_call_id, ("", False))
                    args = part.args if isinstance(part.args, dict) else {}
                    tools.append(
                        {
                            "id": part.tool_call_id,
                            "name": part.tool_name,
                            "title": tool_title(part.tool_name, args),
                            "kind": tool_kind(part.tool_name),
                            "status": "error" if is_error else "completed",
                            "result": content,
                        }
                    )
            if text or tools:
                items.append(
                    {
                        "kind": "assistant",
                        "text": text,
                        "thinking": "",
                        "tools": tools,
                        "running": False,
                    }
                )
    return items


__all__ = ["history_to_items"]
