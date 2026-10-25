"""Tests for the ACP adapter in apps/acp/server.py."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from acp.schema import AgentMessageChunk, TextContentBlock, ToolCallProgress
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from apps.acp.server import DeepAgentACP


class _RecordingClient:
    """Stands in for the editor connection and records every session update."""

    def __init__(self) -> None:
        self.updates: list[Any] = []

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        self.updates.append(update)


async def _call_tool_then_answer(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    if len(messages) == 1:
        yield {
            0: DeltaToolCall(
                name="lookup", json_args='{"key": "release-code"}', tool_call_id="call-1"
            )
        }
    else:
        yield "done"


async def test_prompt_reports_tool_result_and_continues(tmp_path):
    agent: Agent[Any, str] = Agent(FunctionModel(stream_function=_call_tool_then_answer))

    @agent.tool_plain
    def lookup(key: str) -> str:
        return f"{key}=ALPHA-7731"

    server = DeepAgentACP(agent=agent)
    client = _RecordingClient()
    server.on_connect(client)
    session = await server.new_session(cwd=str(tmp_path))

    response = await server.prompt(
        [TextContentBlock(type="text", text="What is the release code?")],
        session_id=session.session_id,
    )

    assert response.stop_reason == "end_turn"
    texts = [
        u.content.text
        for u in client.updates
        if isinstance(u, AgentMessageChunk) and isinstance(u.content, TextContentBlock)
    ]
    assert not [t for t in texts if t.startswith("Error:")], texts
    assert "".join(texts) == "done"

    completed = [u for u in client.updates if isinstance(u, ToolCallProgress)]
    assert len(completed) == 1
    assert completed[0].tool_call_id == "call-1"
    assert completed[0].status == "completed"
    assert completed[0].content is not None
    assert completed[0].content[0].content.text == "release-code=ALPHA-7731"

    # The turn finished, so its messages are kept for the next one.
    assert len(server._session_histories[session.session_id]) == 4
