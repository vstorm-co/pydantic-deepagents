"""Tests for ACP session history when a turn ends with an error (issue #249).

`DeepAgentACP.prompt` used to save conversation history only when a run
finished normally, so a turn that failed partway through — after its tools
had already done real work — vanished from the next turn's context. These
tests pin the fixed behavior: the messages a failed turn did complete are
kept (with a dangling tool call closed out), and the success path is
unchanged.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from acp.schema import AgentMessageChunk, TextContentBlock
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from apps.acp.server import DeepAgentACP

STEP1 = (
    "Step 1: Create a file named notes.txt in the current directory containing "
    "exactly one line: release-code=ALPHA-7731\n"
    "Reply with the word done once the file has been written."
)
STEP2 = (
    "Step 2: What release code did I ask you to put into notes.txt in my "
    "previous message? Please answer from our conversation."
)


class _RecordingClient:
    """Stands in for the editor connection and records every session update."""

    def __init__(self) -> None:
        self.updates: list[Any] = []

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        self.updates.append(update)


def _error_texts(client: _RecordingClient) -> list[str]:
    return [
        u.content.text
        for u in client.updates
        if isinstance(u, AgentMessageChunk)
        and isinstance(u.content, TextContentBlock)
        and u.content.text.startswith("Error:")
    ]


def _last_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                return str(part.content)
    return ""


def _make_server(agent: Agent[Any, str], client: _RecordingClient) -> DeepAgentACP:
    server = DeepAgentACP(agent=agent)
    server.on_connect(client)
    return server


async def test_tool_failure_preserves_turn_in_history(tmp_path: Path) -> None:
    """A tool that does its work and then raises must not erase the turn.

    The trigger is the tool's own exception — no tool-result event is ever
    produced — so this is independent of the FunctionToolResultEvent
    attribute crash in #248.
    """
    notes_path = tmp_path / "notes.txt"
    turn2_seen: list[ModelMessage] = []

    def decide(messages: list[ModelMessage]) -> str:
        text = _last_user_text(messages)
        if text.startswith("Step 1"):
            return "tool"
        turn2_seen.extend(messages)
        return "answer"

    def model_sync(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if decide(messages) == "tool":
            args = {"path": str(notes_path), "content": "release-code=ALPHA-7731"}
            return ModelResponse(parts=[ToolCallPart("write_note", args, "call-1")])
        return ModelResponse(parts=[TextPart("answer")])

    async def model_stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        if decide(messages) == "tool":
            args = json.dumps({"path": str(notes_path), "content": "release-code=ALPHA-7731"})
            yield {0: DeltaToolCall(name="write_note", json_args=args, tool_call_id="call-1")}
        else:
            yield "answer"

    agent: Agent[Any, str] = Agent(FunctionModel(model_sync, stream_function=model_stream))

    @agent.tool_plain
    def write_note(path: str, content: str) -> str:
        Path(path).write_text(content + "\n", encoding="utf-8")
        raise RuntimeError("post-write sync failed")

    client = _RecordingClient()
    server = _make_server(agent, client)
    session = await server.new_session(cwd=str(tmp_path))
    session_id = session.session_id

    # Turn 1: the tool writes the file, then raises.
    response = await server.prompt(
        [TextContentBlock(type="text", text=STEP1)], session_id=session_id
    )
    assert response.stop_reason == "end_turn"
    assert _error_texts(client) == ["Error: post-write sync failed"]
    # The work really happened even though the turn failed.
    assert notes_path.read_text(encoding="utf-8") == "release-code=ALPHA-7731\n"

    history = server._session_histories[session_id]
    user_prompts = [
        str(p.content) for m in history for p in m.parts if isinstance(p, UserPromptPart)
    ]
    tool_calls = [p for m in history for p in m.parts if isinstance(p, ToolCallPart)]
    tool_returns = [p for m in history for p in m.parts if isinstance(p, ToolReturnPart)]
    assert any(text.startswith("Step 1") for text in user_prompts)
    assert [tc.tool_name for tc in tool_calls] == ["write_note"]
    # The interrupted call is closed out, so the history stays runnable.
    assert [tr.tool_call_id for tr in tool_returns] == ["call-1"]

    # Turn 2: the model is given turn 1's user message and executed tool call.
    client.updates.clear()
    response2 = await server.prompt(
        [TextContentBlock(type="text", text=STEP2)], session_id=session_id
    )
    assert response2.stop_reason == "end_turn"
    assert _error_texts(client) == []
    seen_prompts = [
        str(p.content) for m in turn2_seen for p in m.parts if isinstance(p, UserPromptPart)
    ]
    seen_tool_calls = [p for m in turn2_seen for p in m.parts if isinstance(p, ToolCallPart)]
    assert any(text.startswith("Step 1") for text in seen_prompts)
    assert [tc.tool_name for tc in seen_tool_calls] == ["write_note"]


async def test_model_failure_preserves_user_message(tmp_path: Path) -> None:
    """If the model itself fails mid-turn, the user prompt is still kept."""
    state = {"fail": True}
    turn2_seen: list[ModelMessage] = []

    def model_sync(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if state["fail"]:
            raise RuntimeError("simulated model failure")
        turn2_seen.extend(messages)
        return ModelResponse(parts=[TextPart("ok")])

    async def model_stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        if state["fail"]:
            raise RuntimeError("simulated model failure")
        turn2_seen.extend(messages)
        yield "ok"

    agent: Agent[Any, str] = Agent(FunctionModel(model_sync, stream_function=model_stream))
    client = _RecordingClient()
    server = _make_server(agent, client)
    session = await server.new_session(cwd=str(tmp_path))
    session_id = session.session_id

    response = await server.prompt(
        [TextContentBlock(type="text", text="Remember this: the sky is teal.")],
        session_id=session_id,
    )
    assert response.stop_reason == "end_turn"
    assert _error_texts(client) == ["Error: simulated model failure"]

    history = server._session_histories[session_id]
    assert len(history) == 1
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert "the sky is teal" in str(history[0].parts[0].content)

    state["fail"] = False
    client.updates.clear()
    await server.prompt(
        [TextContentBlock(type="text", text="What color is the sky?")],
        session_id=session_id,
    )
    assert _error_texts(client) == []
    seen_prompts = [
        str(p.content) for m in turn2_seen for p in m.parts if isinstance(p, UserPromptPart)
    ]
    assert any("the sky is teal" in text for text in seen_prompts)


async def test_successful_turn_history_is_unchanged(tmp_path: Path) -> None:
    """The normal path still saves the finished run's full message list."""

    def model_sync(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("pong")])

    async def model_stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        yield "pong"

    agent: Agent[Any, str] = Agent(FunctionModel(model_sync, stream_function=model_stream))
    client = _RecordingClient()
    server = _make_server(agent, client)
    session = await server.new_session(cwd=str(tmp_path))
    session_id = session.session_id

    response = await server.prompt(
        [TextContentBlock(type="text", text="ping")], session_id=session_id
    )
    assert response.stop_reason == "end_turn"
    assert _error_texts(client) == []

    history = server._session_histories[session_id]
    assert len(history) == 2
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert history[0].parts[0].content == "ping"
    assert isinstance(history[1].parts[0], TextPart)
    assert history[1].parts[0].content == "pong"


class _ExplodingAgent:
    """An agent whose run cannot even start."""

    def iter(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("cannot start run")


async def test_unstarted_run_leaves_history_untouched(tmp_path: Path) -> None:
    """When no run object exists, the previously saved history is kept as-is."""
    state = {"ok": True}

    def model_sync(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("pong")])

    async def model_stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        yield "pong"

    real_agent: Agent[Any, str] = Agent(FunctionModel(model_sync, stream_function=model_stream))

    def factory(ctx: Any) -> Any:
        return real_agent if state["ok"] else _ExplodingAgent()

    client = _RecordingClient()
    server = DeepAgentACP(agent=factory)
    server.on_connect(client)
    session = await server.new_session(cwd=str(tmp_path))
    session_id = session.session_id

    await server.prompt([TextContentBlock(type="text", text="ping")], session_id=session_id)
    saved = list(server._session_histories[session_id])
    assert len(saved) == 2

    state["ok"] = False
    client.updates.clear()
    response = await server.prompt(
        [TextContentBlock(type="text", text="ping again")], session_id=session_id
    )
    assert response.stop_reason == "end_turn"
    assert _error_texts(client) == ["Error: cannot start run"]
    assert server._session_histories[session_id] == saved
