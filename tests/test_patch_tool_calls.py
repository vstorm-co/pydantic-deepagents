"""Tests for PatchToolCallsProcessor."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel

from pydantic_deep import (
    CANCELLED_MESSAGE,
    create_deep_agent,
    patch_tool_calls_processor,
)

TEST_MODEL = TestModel()


class TestPatchToolCallsProcessor:
    def test_empty_messages(self):
        result = patch_tool_calls_processor([])
        assert result == []

    def test_no_orphans(self):
        """Normal history with matched tool calls passes through unchanged."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="t", args={}, tool_call_id="c1")]),
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="t", content="result", tool_call_id="c1"),
                ]
            ),
            ModelResponse(parts=[TextPart(content="done")]),
        ]
        result = patch_tool_calls_processor(messages)
        assert result is messages  # same object, no changes

    def test_no_tool_calls(self):
        """Messages with no tool calls pass through unchanged."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[TextPart(content="hi")]),
        ]
        result = patch_tool_calls_processor(messages)
        assert result is messages

    def test_single_orphan_at_end(self):
        """Tool call at the end with no following ModelRequest."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="execute", args={}, tool_call_id="c1")]),
        ]
        result = patch_tool_calls_processor(messages)
        assert len(result) == 3
        # New ModelRequest with synthetic ToolReturnPart
        patched = result[2]
        assert isinstance(patched, ModelRequest)
        assert len(patched.parts) == 1
        assert isinstance(patched.parts[0], ToolReturnPart)
        assert patched.parts[0].tool_name == "execute"
        assert patched.parts[0].content == CANCELLED_MESSAGE
        assert patched.parts[0].tool_call_id == "c1"

    def test_orphan_with_existing_next_request(self):
        """Orphan when next message is a ModelRequest with other parts."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_file", args={}, tool_call_id="c1"),
                    ToolCallPart(tool_name="write_file", args={}, tool_call_id="c2"),
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="read_file", content="data", tool_call_id="c1"),
                    # c2 is missing!
                ]
            ),
            ModelResponse(parts=[TextPart(content="done")]),
        ]
        result = patch_tool_calls_processor(messages)
        assert len(result) == 4
        # The ModelRequest at index 2 should now have synthetic part prepended
        patched = result[2]
        assert isinstance(patched, ModelRequest)
        # Synthetic c2 + original c1
        assert len(patched.parts) == 2
        synthetic = patched.parts[0]
        assert isinstance(synthetic, ToolReturnPart)
        assert synthetic.tool_name == "write_file"
        assert synthetic.tool_call_id == "c2"
        assert synthetic.content == CANCELLED_MESSAGE
        # Original part preserved
        original = patched.parts[1]
        assert isinstance(original, ToolReturnPart)
        assert original.tool_call_id == "c1"

    def test_multiple_orphans_across_messages(self):
        """Multiple orphaned tool calls in different positions."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="t1", args={}, tool_call_id="c1")]),
            # No response for c1 — next is another response
            ModelResponse(parts=[ToolCallPart(tool_name="t2", args={}, tool_call_id="c2")]),
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="t2", content="ok", tool_call_id="c2"),
                ]
            ),
        ]
        result = patch_tool_calls_processor(messages)
        # c1 orphan: index 1, next message is ModelResponse (not ModelRequest)
        # So a new ModelRequest should be inserted after index 1
        assert len(result) == 5
        synthetic_req = result[2]
        assert isinstance(synthetic_req, ModelRequest)
        assert len(synthetic_req.parts) == 1
        assert isinstance(synthetic_req.parts[0], ToolReturnPart)
        assert synthetic_req.parts[0].tool_call_id == "c1"

    def test_all_calls_orphaned(self):
        """All tool calls in a response are orphaned."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="a", args={}, tool_call_id="c1"),
                    ToolCallPart(tool_name="b", args={}, tool_call_id="c2"),
                ]
            ),
        ]
        result = patch_tool_calls_processor(messages)
        assert len(result) == 3
        patched = result[2]
        assert isinstance(patched, ModelRequest)
        assert len(patched.parts) == 2
        tool_names = {p.tool_name for p in patched.parts if isinstance(p, ToolReturnPart)}
        assert tool_names == {"a", "b"}

    def test_deterministic_order(self):
        """Synthetic parts are in sorted order by tool_call_id."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="go")]),
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="z", args={}, tool_call_id="zzz"),
                    ToolCallPart(tool_name="a", args={}, tool_call_id="aaa"),
                    ToolCallPart(tool_name="m", args={}, tool_call_id="mmm"),
                ]
            ),
        ]
        result = patch_tool_calls_processor(messages)
        patched = result[2]
        assert isinstance(patched, ModelRequest)
        ids = [p.tool_call_id for p in patched.parts if isinstance(p, ToolReturnPart)]
        assert ids == ["aaa", "mmm", "zzz"]

    def test_response_with_only_text_parts(self):
        """ModelResponse with only TextParts is not affected."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[TextPart(content="just text")]),
        ]
        result = patch_tool_calls_processor(messages)
        assert result is messages

    def test_next_request_has_no_tool_returns(self):
        """Next ModelRequest exists but has no ToolReturnParts at all."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[ToolCallPart(tool_name="t", args={}, tool_call_id="c1")]),
            ModelRequest(parts=[UserPromptPart(content="followup")]),
        ]
        result = patch_tool_calls_processor(messages)
        assert len(result) == 3
        # The ModelRequest at index 2 should have synthetic part prepended
        patched = result[2]
        assert isinstance(patched, ModelRequest)
        assert len(patched.parts) == 2
        assert isinstance(patched.parts[0], ToolReturnPart)
        assert patched.parts[0].tool_call_id == "c1"
        # Original UserPromptPart preserved
        assert isinstance(patched.parts[1], UserPromptPart)

    def test_cancelled_message_constant(self):
        assert CANCELLED_MESSAGE == "Tool call was cancelled."

    # --- Phase 2: orphaned tool results (missing calls) ---

    def test_orphaned_tool_result_stripped(self):
        """ToolReturnPart without matching ToolCallPart in preceding response is removed."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[TextPart(content="summary")]),
            # This ModelRequest has a ToolReturnPart but the preceding
            # ModelResponse has no ToolCallParts — orphaned result
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="read_file", content="data", tool_call_id="c1"),
                    UserPromptPart(content="next"),
                ]
            ),
            ModelResponse(parts=[TextPart(content="done")]),
        ]
        result = patch_tool_calls_processor(messages)
        assert len(result) == 4
        # The orphaned ToolReturnPart should be stripped, keeping UserPromptPart
        patched = result[2]
        assert isinstance(patched, ModelRequest)
        assert len(patched.parts) == 1
        assert isinstance(patched.parts[0], UserPromptPart)

    def test_orphaned_tool_result_all_stripped(self):
        """ModelRequest with only orphaned ToolReturnParts is removed entirely."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(parts=[TextPart(content="no tool calls here")]),
            # Only orphaned tool results — entire message should be removed
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="t1", content="r1", tool_call_id="c1"),
                    ToolReturnPart(tool_name="t2", content="r2", tool_call_id="c2"),
                ]
            ),
            ModelResponse(parts=[TextPart(content="done")]),
        ]
        result = patch_tool_calls_processor(messages)
        # The empty ModelRequest should be removed
        assert len(result) == 3
        assert isinstance(result[0], ModelRequest)
        assert isinstance(result[1], ModelResponse)
        assert isinstance(result[2], ModelResponse)

    def test_mixed_valid_and_orphaned_results(self):
        """Some ToolReturnParts have matching calls, some don't."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name="t1", args={}, tool_call_id="c1"),
                    # No c2 call!
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="t1", content="ok", tool_call_id="c1"),
                    ToolReturnPart(tool_name="t2", content="orphaned", tool_call_id="c2"),
                ]
            ),
            ModelResponse(parts=[TextPart(content="done")]),
        ]
        result = patch_tool_calls_processor(messages)
        assert len(result) == 4
        patched = result[2]
        assert isinstance(patched, ModelRequest)
        # Only c1 should remain
        assert len(patched.parts) == 1
        assert isinstance(patched.parts[0], ToolReturnPart)
        assert patched.parts[0].tool_call_id == "c1"

    def test_orphaned_result_at_start(self):
        """ToolReturnPart at the very start (no preceding message) is orphaned."""
        messages = [
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="t", content="data", tool_call_id="c1"),
                    UserPromptPart(content="hello"),
                ]
            ),
            ModelResponse(parts=[TextPart(content="hi")]),
        ]
        result = patch_tool_calls_processor(messages)
        assert len(result) == 2
        patched = result[0]
        assert isinstance(patched, ModelRequest)
        assert len(patched.parts) == 1
        assert isinstance(patched.parts[0], UserPromptPart)

    def test_both_orphaned_calls_and_results(self):
        """Both orphaned calls and orphaned results in the same history."""
        messages = [
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            # Orphaned call (c1 has no result)
            ModelResponse(parts=[ToolCallPart(tool_name="t1", args={}, tool_call_id="c1")]),
            # Next response (no ModelRequest between them)
            ModelResponse(parts=[TextPart(content="text")]),
            # Orphaned result (c2 has no matching call in prev response)
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="t2", content="orphaned", tool_call_id="c2"),
                    UserPromptPart(content="next"),
                ]
            ),
        ]
        result = patch_tool_calls_processor(messages)
        # After phase 1: synthetic result for c1 injected
        # After phase 2: orphaned c2 stripped
        # Check c1 was patched
        has_c1_synthetic = False
        for msg in result:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart) and part.tool_call_id == "c1":
                        has_c1_synthetic = True
                        assert part.content == CANCELLED_MESSAGE
        assert has_c1_synthetic
        # Check c2 was stripped
        for msg in result:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart) and part.tool_call_id == "c2":
                        raise AssertionError(
                            "Orphaned c2 should have been stripped"
                        )  # pragma: no cover


# --- Integration with create_deep_agent ---


class TestCreateDeepAgentPatchToolCalls:
    def test_patch_tool_calls_true(self):
        """Agent with patch_tool_calls=True has the processor."""
        agent = create_deep_agent(model=TEST_MODEL, patch_tool_calls=True, cost_tracking=False)
        # The agent should have history_processors containing our processor
        # We check indirectly via the agent's internal graph state
        from pydantic_deep.processors.patch import patch_tool_calls_processor as ptp

        # Access the processors from the agent's graph
        assert any(
            p is ptp
            for p in agent.history_processors
        )

    def test_patch_tool_calls_false(self):
        """Agent with patch_tool_calls=False (default) doesn't have the processor."""
        agent = create_deep_agent(model=TEST_MODEL, cost_tracking=False)
        from pydantic_deep.processors.patch import patch_tool_calls_processor as ptp

        processors = agent.history_processors
        assert all(p is not ptp for p in processors)

    def test_patch_tool_calls_with_other_processors(self):
        """patch_tool_calls works alongside other history processors."""
        from pydantic_deep import create_sliding_window_processor

        window = create_sliding_window_processor(
            trigger=("messages", 100),
            keep=("messages", 50),
        )
        agent = create_deep_agent(
            model=TEST_MODEL,
            patch_tool_calls=True,
            history_processors=[window],
            cost_tracking=False,
        )
        from pydantic_deep.processors.patch import patch_tool_calls_processor as ptp

        processors = agent.history_processors
        # patch_tool_calls_processor should be first
        assert processors[0] is ptp


# --- Exports ---


class TestPatchExports:
    def test_importable_from_pydantic_deep(self):
        from pydantic_deep import CANCELLED_MESSAGE, patch_tool_calls_processor

        assert patch_tool_calls_processor is not None
        assert CANCELLED_MESSAGE == "Tool call was cancelled."
