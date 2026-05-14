"""Tests for pydantic_deep.capabilities.message_queue."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.models.test import TestModel

from pydantic_deep.capabilities.message_queue import (
    MessageQueue,
    MessageQueueCapability,
    QueuedMessage,
    format_follow_up,
    format_steering,
    run_with_queue,
)
from pydantic_deep.deps import DeepAgentDeps

_MODEL = TestModel()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fake_ctx() -> Any:
    return type("FakeCtx", (), {"deps": None})()


def _fake_rc(messages: list[Any]) -> Any:
    return type("FakeRC", (), {"messages": messages})()


# ── QueuedMessage ─────────────────────────────────────────────────────────────


class TestQueuedMessage:
    def test_defaults(self) -> None:
        msg = QueuedMessage(content="hi", priority="steering")
        assert msg.delivery_mode == "one_at_a_time"
        assert msg.metadata == {}

    def test_custom_fields(self) -> None:
        msg = QueuedMessage(
            content="x",
            priority="follow_up",
            delivery_mode="all",
            metadata={"k": "v"},
        )
        assert msg.delivery_mode == "all"
        assert msg.metadata == {"k": "v"}


# ── MessageQueue ──────────────────────────────────────────────────────────────


class TestMessageQueue:
    @pytest.mark.anyio
    async def test_steer_adds_message(self) -> None:
        queue = MessageQueue()
        await queue.steer("stop")
        drained = await queue.drain_steering()
        assert len(drained) == 1
        assert drained[0].content == "stop"
        assert drained[0].priority == "steering"

    @pytest.mark.anyio
    async def test_follow_up_adds_message(self) -> None:
        queue = MessageQueue()
        await queue.follow_up("then do this")
        drained = await queue.drain_follow_up()
        assert len(drained) == 1
        assert drained[0].content == "then do this"
        assert drained[0].priority == "follow_up"

    @pytest.mark.anyio
    async def test_drain_empty_returns_empty(self) -> None:
        queue = MessageQueue()
        assert await queue.drain_steering() == []
        assert await queue.drain_follow_up() == []

    @pytest.mark.anyio
    async def test_drain_steering_one_at_a_time(self) -> None:
        queue = MessageQueue()
        await queue.steer("first")
        await queue.steer("second")

        first = await queue.drain_steering()
        assert len(first) == 1
        assert first[0].content == "first"

        second = await queue.drain_steering()
        assert len(second) == 1
        assert second[0].content == "second"

        assert await queue.drain_steering() == []

    @pytest.mark.anyio
    async def test_drain_steering_all(self) -> None:
        queue = MessageQueue()
        await queue.steer("a", delivery_mode="all")
        await queue.steer("b", delivery_mode="one_at_a_time")
        await queue.steer("c", delivery_mode="one_at_a_time")

        # delivery_mode is taken from the head message
        drained = await queue.drain_steering()
        assert len(drained) == 3
        assert [m.content for m in drained] == ["a", "b", "c"]
        assert await queue.drain_steering() == []

    @pytest.mark.anyio
    async def test_drain_follow_up_one_at_a_time(self) -> None:
        queue = MessageQueue()
        await queue.follow_up("task1")
        await queue.follow_up("task2")

        first = await queue.drain_follow_up()
        assert len(first) == 1
        assert first[0].content == "task1"

        second = await queue.drain_follow_up()
        assert len(second) == 1
        assert second[0].content == "task2"

        assert await queue.drain_follow_up() == []

    @pytest.mark.anyio
    async def test_drain_follow_up_all(self) -> None:
        queue = MessageQueue()
        await queue.follow_up("a", delivery_mode="all")
        await queue.follow_up("b")

        drained = await queue.drain_follow_up()
        assert len(drained) == 2
        assert [m.content for m in drained] == ["a", "b"]
        assert await queue.drain_follow_up() == []

    @pytest.mark.anyio
    async def test_drain_head_one_at_a_time_ignores_later_all(self) -> None:
        """delivery_mode is taken from the head only; later 'all' entries don't widen the batch."""
        queue = MessageQueue()
        await queue.steer("first", delivery_mode="one_at_a_time")
        await queue.steer("second", delivery_mode="all")

        drained = await queue.drain_steering()
        assert len(drained) == 1
        assert drained[0].content == "first"

        remaining = await queue.drain_steering()
        assert len(remaining) == 1
        assert remaining[0].content == "second"

    @pytest.mark.anyio
    async def test_has_follow_up_true(self) -> None:
        queue = MessageQueue()
        assert not queue.has_follow_up()
        await queue.follow_up("x")
        assert queue.has_follow_up()

    @pytest.mark.anyio
    async def test_has_follow_up_false_after_drain(self) -> None:
        queue = MessageQueue()
        await queue.follow_up("x")
        await queue.drain_follow_up()
        assert not queue.has_follow_up()

    @pytest.mark.anyio
    async def test_pending_count(self) -> None:
        queue = MessageQueue()
        assert queue.pending_count() == (0, 0)
        await queue.steer("a")
        await queue.steer("b")
        await queue.follow_up("c")
        assert queue.pending_count() == (2, 1)

    @pytest.mark.anyio
    async def test_steer_metadata(self) -> None:
        queue = MessageQueue()
        await queue.steer("msg", metadata={"source": "webhook"})
        drained = await queue.drain_steering()
        assert drained[0].metadata == {"source": "webhook"}

    @pytest.mark.anyio
    async def test_concurrent_steer_and_drain(self) -> None:
        queue = MessageQueue()

        async def _drain_all() -> list[QueuedMessage]:
            results: list[QueuedMessage] = []
            while True:
                batch = await queue.drain_steering()
                if not batch:
                    break
                results.extend(batch)
            return results

        # Add messages concurrently
        await asyncio.gather(
            queue.steer("concurrent-a"),
            queue.steer("concurrent-b"),
            queue.steer("concurrent-c"),
        )

        # All three should be present
        results = await _drain_all()
        assert len(results) == 3
        contents = {m.content for m in results}
        assert contents == {"concurrent-a", "concurrent-b", "concurrent-c"}

    @pytest.mark.anyio
    async def test_concurrent_producer_consumer(self) -> None:
        queue = MessageQueue()
        collected: list[QueuedMessage] = []

        async def producer() -> None:
            for i in range(5):
                await queue.steer(f"p{i}")
                await asyncio.sleep(0)

        async def consumer() -> None:
            for _ in range(5):
                while True:
                    batch = await queue.drain_steering()
                    if batch:
                        collected.extend(batch)
                        break
                    await asyncio.sleep(0)

        await asyncio.gather(producer(), consumer())
        assert len(collected) == 5


# ── Format helpers ────────────────────────────────────────────────────────────


class TestFormatHelpers:
    def test_format_steering_single(self) -> None:
        msg = QueuedMessage("stop that", "steering")
        result = format_steering([msg])
        assert result == "[steering] stop that"

    def test_format_steering_multiple(self) -> None:
        msgs = [
            QueuedMessage("first", "steering"),
            QueuedMessage("second", "steering"),
        ]
        result = format_steering(msgs)
        assert "[steering — multiple messages]" in result
        assert "- first" in result
        assert "- second" in result

    def test_format_steering_empty(self) -> None:
        assert format_steering([]) == ""

    def test_format_follow_up_single(self) -> None:
        msg = QueuedMessage("do this next", "follow_up")
        result = format_follow_up([msg])
        assert result == "do this next"

    def test_format_follow_up_multiple(self) -> None:
        msgs = [
            QueuedMessage("task A", "follow_up"),
            QueuedMessage("task B", "follow_up"),
        ]
        result = format_follow_up(msgs)
        assert "task A" in result
        assert "task B" in result
        assert "\n\n" in result


# ── MessageQueueCapability ────────────────────────────────────────────────────


class TestMessageQueueCapability:
    @pytest.mark.anyio
    async def test_noop_when_queues_empty(self) -> None:
        queue = MessageQueue()
        cap = MessageQueueCapability(queue=queue)
        messages: list[Any] = []
        rc = _fake_rc(messages)
        ctx = _fake_ctx()

        await cap.before_model_request(ctx, rc)

        assert messages == []

    @pytest.mark.anyio
    async def test_steer_injects_user_prompt_part_no_existing_request(self) -> None:
        """When there is no prior ModelRequest, a new one is appended (fallback path)."""
        queue = MessageQueue()
        await queue.steer("stop and try differently")
        cap = MessageQueueCapability(queue=queue)

        messages: list[Any] = []
        rc = _fake_rc(messages)
        ctx = _fake_ctx()

        await cap.before_model_request(ctx, rc)

        assert len(messages) == 1
        injected = messages[0]
        assert isinstance(injected, ModelRequest)
        assert len(injected.parts) == 1
        part = injected.parts[0]
        assert isinstance(part, UserPromptPart)
        assert "[steering]" in part.content
        assert "stop and try differently" in part.content

    @pytest.mark.anyio
    async def test_steer_merges_into_existing_model_request(self) -> None:
        """Steering is appended as a part inside the last ModelRequest (normal path).

        This prevents the "Processed history must end with a ModelRequest" error
        that was caused by downstream capabilities silently removing an extra
        trailing ModelRequest we used to append.
        """
        queue = MessageQueue()
        await queue.steer("only first line please")
        cap = MessageQueueCapability(queue=queue)

        existing = ModelRequest(
            parts=[ToolReturnPart(tool_name="execute", content="output", tool_call_id="c1")]
        )
        messages: list[Any] = [existing]
        rc = _fake_rc(messages)

        await cap.before_model_request(_fake_ctx(), rc)

        # Must NOT create a second ModelRequest — steering merges into the existing one
        assert len(messages) == 1
        merged = messages[0]
        assert isinstance(merged, ModelRequest)
        assert len(merged.parts) == 2  # ToolReturnPart + steering UserPromptPart
        assert isinstance(merged.parts[0], ToolReturnPart)
        assert isinstance(merged.parts[1], UserPromptPart)
        assert "[steering]" in merged.parts[1].content
        assert "only first line" in merged.parts[1].content

    @pytest.mark.anyio
    async def test_steer_merges_into_model_request_skipping_non_request(self) -> None:
        """Loop skips non-ModelRequest tail entries and merges into the earlier ModelRequest."""
        from pydantic_ai.messages import ModelResponse, TextPart

        queue = MessageQueue()
        await queue.steer("steer me")
        cap = MessageQueueCapability(queue=queue)

        model_req = ModelRequest(parts=[UserPromptPart(content="original")])
        model_resp = ModelResponse(parts=[TextPart(content="response")])
        messages: list[Any] = [model_req, model_resp]
        rc = _fake_rc(messages)

        await cap.before_model_request(_fake_ctx(), rc)

        # Still two messages — steering merged into model_req, not a new entry
        assert len(messages) == 2
        merged = messages[0]
        assert isinstance(merged, ModelRequest)
        assert isinstance(merged.parts[-1], UserPromptPart)
        assert "[steering]" in merged.parts[-1].content

    @pytest.mark.anyio
    async def test_steer_drains_after_injection(self) -> None:
        queue = MessageQueue()
        await queue.steer("once")
        cap = MessageQueueCapability(queue=queue)

        rc = _fake_rc([])
        await cap.before_model_request(_fake_ctx(), rc)

        # Queue should be empty after injection
        assert await queue.drain_steering() == []

    @pytest.mark.anyio
    async def test_multiple_steers_formatted_together(self) -> None:
        queue = MessageQueue()
        await queue.steer("first", delivery_mode="all")
        await queue.steer("second")

        cap = MessageQueueCapability(queue=queue)
        # Start with a ModelRequest so we exercise the merge path
        existing = ModelRequest(parts=[UserPromptPart(content="original")])
        messages: list[Any] = [existing]
        await cap.before_model_request(_fake_ctx(), _fake_rc(messages))

        # Steering is merged into the existing request, not a new one
        assert len(messages) == 1
        content = messages[0].parts[-1].content  # last part is the steering
        assert "multiple messages" in content
        assert "first" in content
        assert "second" in content

    @pytest.mark.anyio
    async def test_follow_up_not_injected(self) -> None:
        queue = MessageQueue()
        await queue.follow_up("later task")
        cap = MessageQueueCapability(queue=queue)

        messages: list[Any] = []
        await cap.before_model_request(_fake_ctx(), _fake_rc(messages))

        assert messages == []
        assert queue.has_follow_up()  # Still in queue

    @pytest.mark.anyio
    async def test_agent_integration_no_steering(self) -> None:
        queue = MessageQueue()
        cap = MessageQueueCapability(queue=queue)
        agent = Agent(_MODEL, capabilities=[cap])
        result = await agent.run("hello")
        # No steering was queued, so no [steering] part should appear in the messages
        steering_injected = any(
            isinstance(part, UserPromptPart)
            and isinstance(part.content, str)
            and "[steering]" in part.content
            for msg in result.all_messages()
            if isinstance(msg, ModelRequest)
            for part in msg.parts
        )
        assert not steering_injected

    @pytest.mark.anyio
    async def test_agent_integration_with_pre_populated_steering(self) -> None:
        queue = MessageQueue()
        await queue.steer("use a concise approach")
        cap = MessageQueueCapability(queue=queue)
        agent = Agent(_MODEL, capabilities=[cap])

        result = await agent.run("hello")
        # After run the steering queue should be drained — capability consumed it
        assert await queue.drain_steering() == []
        assert result.all_messages()  # run produced at least one message

    @pytest.mark.anyio
    async def test_drain_between_runs_prevents_stale_steering_bleed(self) -> None:
        """Draining the queue between runs — as chat.py does in the finally block —
        prevents stale steering from leaking into unrelated subsequent messages.
        """
        queue = MessageQueue()
        cap = MessageQueueCapability(queue=queue)
        agent = Agent(_MODEL, capabilities=[cap])

        # Run 1 — steering queue is empty
        result1 = await agent.run("task one")

        # Stale steering arrives after run 1 ends
        await queue.steer("stale: change direction")

        # ── chat.py finally block equivalent ──────────────────────────────────
        await queue.drain_steering()  # discard unconsumed steering
        # ─────────────────────────────────────────────────────────────────────

        # Run 2 — starts with a clean queue, no stale steering injected
        result2 = await agent.run("task two", message_history=result1.all_messages())

        stale_found = any(
            isinstance(part, UserPromptPart)
            and isinstance(part.content, str)
            and "[steering]" in part.content
            for msg in result2.new_messages()
            if isinstance(msg, ModelRequest)
            for part in msg.parts
        )
        assert not stale_found, "no stale steering should appear in run 2 after drain"
        assert await queue.drain_steering() == []  # queue still clean


# ── run_with_queue ────────────────────────────────────────────────────────────


class TestRunWithQueue:
    @pytest.mark.anyio
    async def test_single_run_no_follow_up(self) -> None:
        queue = MessageQueue()
        cap = MessageQueueCapability(queue=queue)
        agent = Agent(_MODEL, capabilities=[cap])
        deps = DeepAgentDeps()

        result = await run_with_queue(agent, "hello", deps=deps, queue=queue)
        # No follow-up was queued, so exactly one run's worth of messages should exist
        assert not queue.has_follow_up()
        assert await queue.drain_steering() == []
        assert len(result.all_messages()) == 2  # one ModelRequest + one ModelResponse

    @pytest.mark.anyio
    async def test_follow_up_triggers_second_run(self) -> None:
        queue = MessageQueue()
        cap = MessageQueueCapability(queue=queue)
        agent = Agent(_MODEL, capabilities=[cap])
        deps = DeepAgentDeps()

        await queue.follow_up("and also do this")

        result = await run_with_queue(agent, "first task", deps=deps, queue=queue)

        # The follow-up should have been consumed
        assert not queue.has_follow_up()
        # History should contain messages from both runs
        assert len(result.all_messages()) >= 4

    @pytest.mark.anyio
    async def test_multiple_follow_ups(self) -> None:
        queue = MessageQueue()
        cap = MessageQueueCapability(queue=queue)
        agent = Agent(_MODEL, capabilities=[cap])
        deps = DeepAgentDeps()

        await queue.follow_up("task 2")
        await queue.follow_up("task 3")

        result = await run_with_queue(agent, "task 1", deps=deps, queue=queue)

        assert not queue.has_follow_up()
        # 3 separate runs: task 1, task 2, task 3 (one at a time draining)
        assert len(result.all_messages()) >= 6

    @pytest.mark.anyio
    async def test_follow_up_not_delivered_by_plain_agent_run(self) -> None:
        queue = MessageQueue()
        cap = MessageQueueCapability(queue=queue)
        agent = Agent(_MODEL, capabilities=[cap])
        deps = DeepAgentDeps()

        await queue.follow_up("pending task")

        # Plain agent.run() does NOT consume follow-up messages
        await agent.run("hello", deps=deps)

        assert queue.has_follow_up()  # Still waiting

    @pytest.mark.anyio
    async def test_steering_during_follow_up_turn(self) -> None:
        queue = MessageQueue()
        await queue.follow_up("follow-up task")

        cap = MessageQueueCapability(queue=queue)
        agent = Agent(_MODEL, capabilities=[cap])
        deps = DeepAgentDeps()

        # Add steering before the follow-up run starts
        await queue.steer("be brief")

        await run_with_queue(agent, "initial", deps=deps, queue=queue)

        assert not queue.has_follow_up()
        # Steering should also be drained
        assert await queue.drain_steering() == []

    @pytest.mark.anyio
    async def test_message_history_passed_through(self) -> None:
        queue = MessageQueue()
        cap = MessageQueueCapability(queue=queue)
        agent = Agent(_MODEL, capabilities=[cap])
        deps = DeepAgentDeps()

        # First run establishes history
        first = await run_with_queue(agent, "first", deps=deps, queue=queue)
        initial_history = list(first.all_messages())

        await queue.follow_up("follow up")

        result = await run_with_queue(
            agent,
            "second start",
            deps=deps,
            queue=queue,
            message_history=initial_history,
        )

        # History from the first separate run + current run(s)
        assert len(result.all_messages()) > len(initial_history)


# ── DeepAgentDeps integration ─────────────────────────────────────────────────


class TestDeepAgentDepsIntegration:
    def test_clone_for_subagent_shares_queue(self) -> None:
        queue = MessageQueue()
        deps = DeepAgentDeps(message_queue=queue)
        sub = deps.clone_for_subagent()
        assert sub.message_queue is queue

    def test_clone_for_subagent_propagates_none(self) -> None:
        deps = DeepAgentDeps()
        sub = deps.clone_for_subagent()
        assert sub.message_queue is None

    @pytest.mark.anyio
    async def test_subagent_can_steer_parent(self) -> None:
        queue = MessageQueue()
        parent_deps = DeepAgentDeps(message_queue=queue)
        sub_deps = parent_deps.clone_for_subagent()

        # Subagent pushes via shared queue reference
        assert sub_deps.message_queue is not None
        await sub_deps.message_queue.steer("parent, change direction")

        # Parent sees the message
        drained = await queue.drain_steering()
        assert len(drained) == 1
        assert drained[0].content == "parent, change direction"
