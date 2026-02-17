"""Tests for conversation checkpointing, rewind, and session forking."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai_middleware import MiddlewareAgent

from pydantic_deep import create_deep_agent
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.checkpointing import (
    Checkpoint,
    CheckpointMiddleware,
    CheckpointToolset,
    FileCheckpointStore,
    InMemoryCheckpointStore,
    RewindRequested,
    _make_checkpoint,
    _resolve_toolset_store,
    _save_and_prune,
    fork_from_checkpoint,
)

TEST_MODEL = TestModel()


def _make_messages(n: int = 3) -> list[ModelMessage]:
    """Create a list of realistic model messages."""
    msgs: list[ModelMessage] = []
    for i in range(n):
        msgs.append(ModelRequest(parts=[UserPromptPart(content=f"User message {i}")]))
        msgs.append(ModelResponse(parts=[TextPart(content=f"Response {i}")]))
    return msgs


def _make_cp(
    label: str = "test",
    turn: int = 1,
    n_messages: int = 3,
    **kwargs: Any,
) -> Checkpoint:
    """Create a test checkpoint with optional overrides."""
    return _make_checkpoint(
        label=label,
        turn=turn,
        messages=_make_messages(n_messages),
        metadata=kwargs.get("metadata"),
    )


def _minimal_agent(**kwargs: Any) -> Any:
    """Create agent with minimal toolsets for fast tests."""
    defaults = {
        "model": TEST_MODEL,
        "include_subagents": False,
        "include_skills": False,
        "cost_tracking": False,
        "context_manager": False,
    }
    defaults.update(kwargs)
    return create_deep_agent(**defaults)


# ---------------------------------------------------------------------------
# Checkpoint dataclass
# ---------------------------------------------------------------------------


class TestCheckpoint:
    """Tests for the Checkpoint dataclass."""

    def test_create(self):
        """Checkpoint can be created with all fields."""
        msgs = _make_messages(2)
        now = datetime.now(timezone.utc)
        cp = Checkpoint(
            id="abc",
            label="test",
            turn=3,
            messages=msgs,
            message_count=len(msgs),
            created_at=now,
            metadata={"last_tool": "write_file"},
        )
        assert cp.id == "abc"
        assert cp.label == "test"
        assert cp.turn == 3
        assert cp.message_count == len(msgs)
        assert cp.metadata == {"last_tool": "write_file"}

    def test_default_metadata(self):
        """Default metadata is empty dict."""
        cp = Checkpoint(
            id="x",
            label="x",
            turn=1,
            messages=[],
            message_count=0,
            created_at=datetime.now(timezone.utc),
        )
        assert cp.metadata == {}


class TestMakeCheckpoint:
    """Tests for _make_checkpoint helper."""

    def test_auto_id_and_timestamp(self):
        """_make_checkpoint generates unique ID and current timestamp."""
        msgs = _make_messages(1)
        cp = _make_checkpoint("test", 1, msgs)
        assert len(cp.id) == 36  # uuid4 string
        assert cp.label == "test"
        assert cp.turn == 1
        assert cp.message_count == 2  # 1 request + 1 response
        assert cp.created_at <= datetime.now(timezone.utc)

    def test_shallow_copy(self):
        """Messages are shallow-copied."""
        msgs = _make_messages(1)
        cp = _make_checkpoint("test", 1, msgs)
        assert cp.messages is not msgs
        assert cp.messages == msgs

    def test_with_metadata(self):
        """Metadata is passed through."""
        cp = _make_checkpoint("test", 1, [], metadata={"tool": "execute"})
        assert cp.metadata == {"tool": "execute"}


# ---------------------------------------------------------------------------
# InMemoryCheckpointStore
# ---------------------------------------------------------------------------


class TestInMemoryCheckpointStore:
    """Tests for InMemoryCheckpointStore."""

    async def test_save_and_get(self):
        """Save and retrieve a checkpoint."""
        store = InMemoryCheckpointStore()
        cp = _make_cp()
        await store.save(cp)
        result = await store.get(cp.id)
        assert result is cp

    async def test_get_nonexistent(self):
        """Returns None for nonexistent checkpoint."""
        store = InMemoryCheckpointStore()
        assert await store.get("nonexistent") is None

    async def test_get_by_label(self):
        """Find checkpoint by label."""
        store = InMemoryCheckpointStore()
        cp = _make_cp(label="my-label")
        await store.save(cp)
        result = await store.get_by_label("my-label")
        assert result is cp

    async def test_get_by_label_skips_non_matching(self):
        """get_by_label iterates past non-matching checkpoints."""
        store = InMemoryCheckpointStore()
        await store.save(_make_cp(label="alpha"))
        target = _make_cp(label="beta")
        await store.save(target)
        result = await store.get_by_label("beta")
        assert result is target

    async def test_get_by_label_nonexistent(self):
        """Returns None for nonexistent label."""
        store = InMemoryCheckpointStore()
        assert await store.get_by_label("nope") is None

    async def test_list_all_empty(self):
        """Empty store returns empty list."""
        store = InMemoryCheckpointStore()
        assert await store.list_all() == []

    async def test_list_all_ordered(self):
        """Checkpoints are returned ordered by created_at."""
        store = InMemoryCheckpointStore()
        cp1 = _make_cp(label="first")
        cp2 = _make_cp(label="second")
        await store.save(cp1)
        await store.save(cp2)
        result = await store.list_all()
        assert len(result) == 2
        assert result[0].created_at <= result[1].created_at

    async def test_remove(self):
        """Remove existing checkpoint."""
        store = InMemoryCheckpointStore()
        cp = _make_cp()
        await store.save(cp)
        assert await store.remove(cp.id) is True
        assert await store.get(cp.id) is None

    async def test_remove_nonexistent(self):
        """Remove nonexistent returns False."""
        store = InMemoryCheckpointStore()
        assert await store.remove("nope") is False

    async def test_remove_oldest(self):
        """Remove oldest checkpoint (first inserted)."""
        store = InMemoryCheckpointStore()
        cp1 = _make_cp(label="old")
        cp2 = _make_cp(label="new")
        await store.save(cp1)
        await store.save(cp2)
        assert await store.remove_oldest() is True
        assert await store.get(cp1.id) is None
        assert await store.get(cp2.id) is not None

    async def test_remove_oldest_empty(self):
        """Remove oldest on empty store returns False."""
        store = InMemoryCheckpointStore()
        assert await store.remove_oldest() is False

    async def test_count(self):
        """Count returns number of checkpoints."""
        store = InMemoryCheckpointStore()
        assert await store.count() == 0
        await store.save(_make_cp(label="a"))
        assert await store.count() == 1
        await store.save(_make_cp(label="b"))
        assert await store.count() == 2

    async def test_clear(self):
        """Clear removes all checkpoints."""
        store = InMemoryCheckpointStore()
        await store.save(_make_cp(label="a"))
        await store.save(_make_cp(label="b"))
        await store.clear()
        assert await store.count() == 0

    async def test_save_overwrite(self):
        """Save with same ID overwrites."""
        store = InMemoryCheckpointStore()
        cp = _make_cp(label="original")
        await store.save(cp)
        updated = Checkpoint(
            id=cp.id,
            label="updated",
            turn=cp.turn,
            messages=cp.messages,
            message_count=cp.message_count,
            created_at=cp.created_at,
            metadata=cp.metadata,
        )
        await store.save(updated)
        result = await store.get(cp.id)
        assert result is not None
        assert result.label == "updated"
        assert await store.count() == 1


# ---------------------------------------------------------------------------
# FileCheckpointStore
# ---------------------------------------------------------------------------


class TestFileCheckpointStore:
    """Tests for FileCheckpointStore."""

    async def test_save_and_load(self, tmp_path: Any):
        """Save and load checkpoint with JSON serialization."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        cp = _make_cp(label="file-test")
        await store.save(cp)
        result = await store.get(cp.id)
        assert result is not None
        assert result.id == cp.id
        assert result.label == "file-test"
        assert result.turn == cp.turn
        assert result.message_count == cp.message_count
        assert len(result.messages) == len(cp.messages)

    async def test_get_nonexistent(self, tmp_path: Any):
        """Returns None for nonexistent checkpoint."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        assert await store.get("nonexistent") is None

    async def test_get_by_label(self, tmp_path: Any):
        """Find checkpoint by label."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        cp = _make_cp(label="labeled")
        await store.save(cp)
        result = await store.get_by_label("labeled")
        assert result is not None
        assert result.label == "labeled"

    async def test_get_by_label_skips_non_matching(self, tmp_path: Any):
        """get_by_label iterates past non-matching checkpoints."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        await store.save(_make_cp(label="first"))
        await store.save(_make_cp(label="second"))
        result = await store.get_by_label("second")
        assert result is not None
        assert result.label == "second"

    async def test_get_by_label_nonexistent(self, tmp_path: Any):
        """Returns None for nonexistent label."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        assert await store.get_by_label("nope") is None

    async def test_list_all(self, tmp_path: Any):
        """List all checkpoints ordered by creation time."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        cp1 = _make_cp(label="first")
        cp2 = _make_cp(label="second")
        await store.save(cp1)
        await store.save(cp2)
        result = await store.list_all()
        assert len(result) == 2
        assert result[0].created_at <= result[1].created_at

    async def test_list_all_empty(self, tmp_path: Any):
        """Empty store returns empty list."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        assert await store.list_all() == []

    async def test_remove(self, tmp_path: Any):
        """Remove checkpoint file."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        cp = _make_cp()
        await store.save(cp)
        assert await store.remove(cp.id) is True
        assert await store.get(cp.id) is None

    async def test_remove_nonexistent(self, tmp_path: Any):
        """Remove nonexistent returns False."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        assert await store.remove("nope") is False

    async def test_remove_oldest(self, tmp_path: Any):
        """Remove oldest checkpoint file."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        cp1 = _make_cp(label="old")
        cp2 = _make_cp(label="new")
        await store.save(cp1)
        await store.save(cp2)
        assert await store.remove_oldest() is True
        assert await store.count() == 1

    async def test_remove_oldest_empty(self, tmp_path: Any):
        """Remove oldest on empty store returns False."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        assert await store.remove_oldest() is False

    async def test_count(self, tmp_path: Any):
        """Count returns number of checkpoint files."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        assert await store.count() == 0
        await store.save(_make_cp())
        assert await store.count() == 1

    async def test_clear(self, tmp_path: Any):
        """Clear removes all checkpoint files."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        await store.save(_make_cp(label="a"))
        await store.save(_make_cp(label="b"))
        await store.clear()
        assert await store.count() == 0

    async def test_metadata_roundtrip(self, tmp_path: Any):
        """Metadata survives JSON serialization."""
        store = FileCheckpointStore(tmp_path / "checkpoints")
        cp = _make_cp(metadata={"last_tool": "execute", "extra": 42})
        await store.save(cp)
        result = await store.get(cp.id)
        assert result is not None
        assert result.metadata == {"last_tool": "execute", "extra": 42}

    async def test_creates_directory(self, tmp_path: Any):
        """Creates directory if it doesn't exist."""
        store = FileCheckpointStore(tmp_path / "nested" / "dir")
        cp = _make_cp()
        await store.save(cp)
        assert await store.count() == 1


# ---------------------------------------------------------------------------
# SaveAndPrune helper
# ---------------------------------------------------------------------------


class TestSaveAndPrune:
    """Tests for _save_and_prune helper."""

    async def test_saves_checkpoint(self):
        """Saves the checkpoint."""
        store = InMemoryCheckpointStore()
        cp = _make_cp()
        await _save_and_prune(store, cp, max_checkpoints=10)
        assert await store.count() == 1

    async def test_prunes_over_limit(self):
        """Prunes oldest when over max_checkpoints."""
        store = InMemoryCheckpointStore()
        cps = [_make_cp(label=f"cp-{i}") for i in range(5)]
        for cp in cps:
            await store.save(cp)
        # Add one more with max=5 — should prune to 5
        await _save_and_prune(store, _make_cp(label="extra"), max_checkpoints=5)
        assert await store.count() == 5


# ---------------------------------------------------------------------------
# RewindRequested
# ---------------------------------------------------------------------------


class TestRewindRequested:
    """Tests for the RewindRequested exception."""

    def test_attributes(self):
        """Exception stores checkpoint_id, label, messages."""
        msgs = _make_messages(2)
        exc = RewindRequested(checkpoint_id="abc", label="before-refactor", messages=msgs)
        assert exc.checkpoint_id == "abc"
        assert exc.label == "before-refactor"
        assert exc.messages is msgs

    def test_message_string(self):
        """Exception has descriptive message."""
        exc = RewindRequested(checkpoint_id="abc", label="test", messages=[])
        assert "test" in str(exc)
        assert "abc" in str(exc)

    def test_is_exception(self):
        """RewindRequested is a subclass of Exception."""
        assert issubclass(RewindRequested, Exception)


# ---------------------------------------------------------------------------
# CheckpointMiddleware
# ---------------------------------------------------------------------------


class TestCheckpointMiddleware:
    """Tests for CheckpointMiddleware."""

    async def test_every_turn_saves_on_model_request(self):
        """every_turn frequency saves checkpoint in before_model_request."""
        store = InMemoryCheckpointStore()
        mw = CheckpointMiddleware(store=store, frequency="every_turn")
        msgs = _make_messages(2)
        result = await mw.before_model_request(msgs, None)
        assert result is msgs  # Messages passed through unmodified
        assert await store.count() == 1
        cps = await store.list_all()
        assert cps[0].label.startswith("turn-")

    async def test_every_tool_saves_on_tool_call(self):
        """every_tool frequency saves checkpoint in after_tool_call."""
        store = InMemoryCheckpointStore()
        mw = CheckpointMiddleware(store=store, frequency="every_tool")
        msgs = _make_messages(2)
        # First model request (sets _latest_messages)
        await mw.before_model_request(msgs, None)
        assert await store.count() == 0  # No save for every_tool on model request
        # Tool call triggers checkpoint
        result = await mw.after_tool_call("write_file", {"path": "/test"}, "ok", None)
        assert result == "ok"
        assert await store.count() == 1
        cps = await store.list_all()
        assert "write_file" in cps[0].label
        assert cps[0].metadata.get("last_tool") == "write_file"

    async def test_manual_only_no_auto_save(self):
        """manual_only frequency doesn't auto-save."""
        store = InMemoryCheckpointStore()
        mw = CheckpointMiddleware(store=store, frequency="manual_only")
        msgs = _make_messages(2)
        await mw.before_model_request(msgs, None)
        await mw.after_tool_call("write_file", {}, "ok", None)
        assert await store.count() == 0

    async def test_max_checkpoints_prunes(self):
        """Prunes oldest when max_checkpoints exceeded."""
        store = InMemoryCheckpointStore()
        mw = CheckpointMiddleware(store=store, frequency="every_turn", max_checkpoints=2)
        for _ in range(3):
            await mw.before_model_request(_make_messages(1), None)
        assert await store.count() == 2

    async def test_messages_not_modified(self):
        """Messages are returned unmodified from before_model_request."""
        store = InMemoryCheckpointStore()
        mw = CheckpointMiddleware(store=store, frequency="every_turn")
        msgs = _make_messages(2)
        result = await mw.before_model_request(msgs, None)
        assert result is msgs

    async def test_turn_counter_increments(self):
        """Turn counter increments on each before_model_request."""
        store = InMemoryCheckpointStore()
        mw = CheckpointMiddleware(store=store, frequency="every_turn")
        for _ in range(3):
            await mw.before_model_request([], None)
        assert mw._turn_counter == 3

    async def test_resolve_store_from_deps(self):
        """Store resolved from deps.checkpoint_store."""
        deps_store = InMemoryCheckpointStore()
        deps = DeepAgentDeps(checkpoint_store=deps_store)
        mw = CheckpointMiddleware(frequency="every_turn")  # No fallback store
        await mw.before_model_request(_make_messages(1), deps)
        assert await deps_store.count() == 1

    async def test_resolve_store_fallback(self):
        """Falls back to init store when deps has no checkpoint_store."""
        fallback_store = InMemoryCheckpointStore()
        deps = DeepAgentDeps()
        mw = CheckpointMiddleware(store=fallback_store, frequency="every_turn")
        await mw.before_model_request(_make_messages(1), deps)
        assert await fallback_store.count() == 1

    async def test_no_store_skips_silently(self):
        """No store available — skips checkpointing silently."""
        mw = CheckpointMiddleware(frequency="every_turn")  # No store at all
        result = await mw.before_model_request(_make_messages(1), None)
        assert result is not None  # Doesn't crash

    async def test_no_store_skips_after_tool_call(self):
        """No store available in after_tool_call — skips silently."""
        mw = CheckpointMiddleware(frequency="every_tool")
        mw._latest_messages = _make_messages(1)
        result = await mw.after_tool_call("test", {}, "ok", None)
        assert result == "ok"

    async def test_tool_result_passed_through(self):
        """after_tool_call returns the result unmodified."""
        store = InMemoryCheckpointStore()
        mw = CheckpointMiddleware(store=store, frequency="every_tool")
        mw._latest_messages = []
        result = await mw.after_tool_call("test", {}, {"data": 42}, None)
        assert result == {"data": 42}


# ---------------------------------------------------------------------------
# CheckpointToolset
# ---------------------------------------------------------------------------


class TestCheckpointToolset:
    """Tests for CheckpointToolset agent tools."""

    def _make_ctx(self, store: InMemoryCheckpointStore | None = None) -> Any:
        """Create a mock RunContext."""
        deps = DeepAgentDeps(checkpoint_store=store)
        ctx = type("MockCtx", (), {"deps": deps})()
        return ctx

    async def test_save_checkpoint_labels_latest(self):
        """save_checkpoint labels the most recent checkpoint."""
        store = InMemoryCheckpointStore()
        cp = _make_cp(label="auto-1")
        await store.save(cp)

        toolset = CheckpointToolset(store=store)
        ctx = self._make_ctx(store)

        result = await toolset.tools["save_checkpoint"].function(ctx, "before-refactor")
        assert "before-refactor" in result

        # Verify the checkpoint was relabeled
        updated = await store.get(cp.id)
        assert updated is not None
        assert updated.label == "before-refactor"

    async def test_save_checkpoint_no_checkpoints(self):
        """save_checkpoint returns message when no checkpoints exist."""
        store = InMemoryCheckpointStore()
        toolset = CheckpointToolset(store=store)
        ctx = self._make_ctx(store)
        result = await toolset.tools["save_checkpoint"].function(ctx, "test")
        assert "No checkpoint" in result

    async def test_save_checkpoint_no_store(self):
        """save_checkpoint returns message when no store available."""
        toolset = CheckpointToolset()
        ctx = self._make_ctx(None)
        result = await toolset.tools["save_checkpoint"].function(ctx, "test")
        assert "not enabled" in result

    async def test_list_checkpoints_empty(self):
        """list_checkpoints returns message when no checkpoints."""
        store = InMemoryCheckpointStore()
        toolset = CheckpointToolset(store=store)
        ctx = self._make_ctx(store)
        result = await toolset.tools["list_checkpoints"].function(ctx)
        assert "No checkpoints" in result

    async def test_list_checkpoints_with_data(self):
        """list_checkpoints returns formatted list."""
        store = InMemoryCheckpointStore()
        await store.save(_make_cp(label="cp-1", metadata={"last_tool": "execute"}))
        await store.save(_make_cp(label="cp-2"))
        toolset = CheckpointToolset(store=store)
        ctx = self._make_ctx(store)
        result = await toolset.tools["list_checkpoints"].function(ctx)
        assert "cp-1" in result
        assert "cp-2" in result
        assert "execute" in result

    async def test_list_checkpoints_no_store(self):
        """list_checkpoints returns message when no store."""
        toolset = CheckpointToolset()
        ctx = self._make_ctx(None)
        result = await toolset.tools["list_checkpoints"].function(ctx)
        assert "not enabled" in result

    async def test_rewind_to_raises_exception(self):
        """rewind_to raises RewindRequested with checkpoint data."""
        store = InMemoryCheckpointStore()
        cp = _make_cp(label="target")
        await store.save(cp)
        toolset = CheckpointToolset(store=store)
        ctx = self._make_ctx(store)
        with pytest.raises(RewindRequested) as exc_info:
            await toolset.tools["rewind_to"].function(ctx, cp.id)
        assert exc_info.value.checkpoint_id == cp.id
        assert exc_info.value.label == "target"
        assert len(exc_info.value.messages) > 0

    async def test_rewind_to_nonexistent(self):
        """rewind_to returns error message for nonexistent checkpoint."""
        store = InMemoryCheckpointStore()
        toolset = CheckpointToolset(store=store)
        ctx = self._make_ctx(store)
        result = await toolset.tools["rewind_to"].function(ctx, "nope")
        assert "not found" in result

    async def test_rewind_to_no_store(self):
        """rewind_to returns message when no store."""
        toolset = CheckpointToolset()
        ctx = self._make_ctx(None)
        result = await toolset.tools["rewind_to"].function(ctx, "nope")
        assert "not enabled" in result

    async def test_resolve_from_deps(self):
        """Toolset resolves store from ctx.deps.checkpoint_store."""
        deps_store = InMemoryCheckpointStore()
        await deps_store.save(_make_cp(label="via-deps"))

        toolset = CheckpointToolset()  # No fallback store
        ctx = self._make_ctx(deps_store)
        result = await toolset.tools["list_checkpoints"].function(ctx)
        assert "via-deps" in result


# ---------------------------------------------------------------------------
# _resolve_toolset_store
# ---------------------------------------------------------------------------


class TestResolveToolsetStore:
    """Tests for _resolve_toolset_store helper."""

    def test_from_deps(self):
        """Returns store from ctx.deps."""
        store = InMemoryCheckpointStore()
        deps = DeepAgentDeps(checkpoint_store=store)
        ctx = type("MockCtx", (), {"deps": deps})()
        assert _resolve_toolset_store(ctx, None) is store

    def test_fallback(self):
        """Falls back to provided fallback."""
        fallback = InMemoryCheckpointStore()
        deps = DeepAgentDeps()
        ctx = type("MockCtx", (), {"deps": deps})()
        assert _resolve_toolset_store(ctx, fallback) is fallback

    def test_none_when_no_store(self):
        """Returns None when no store available."""
        deps = DeepAgentDeps()
        ctx = type("MockCtx", (), {"deps": deps})()
        assert _resolve_toolset_store(ctx, None) is None


# ---------------------------------------------------------------------------
# fork_from_checkpoint
# ---------------------------------------------------------------------------


class TestForkFromCheckpoint:
    """Tests for fork_from_checkpoint utility."""

    async def test_returns_messages_copy(self):
        """Returns a copy of checkpoint messages."""
        store = InMemoryCheckpointStore()
        cp = _make_cp(label="fork-source")
        await store.save(cp)
        result = await fork_from_checkpoint(store, cp.id)
        assert result is not cp.messages  # Different list object
        assert len(result) == len(cp.messages)

    async def test_nonexistent_raises(self):
        """Raises ValueError for nonexistent checkpoint."""
        store = InMemoryCheckpointStore()
        with pytest.raises(ValueError, match="not found"):
            await fork_from_checkpoint(store, "nonexistent")


# ---------------------------------------------------------------------------
# create_deep_agent integration
# ---------------------------------------------------------------------------


class TestCreateDeepAgentCheckpoints:
    """Tests for create_deep_agent with checkpointing params."""

    def test_default_disabled(self):
        """Checkpointing is disabled by default."""
        from pydantic_ai import Agent

        agent = _minimal_agent()
        assert isinstance(agent, Agent)

    def test_include_checkpoints_adds_middleware_and_toolset(self):
        """include_checkpoints=True adds middleware and toolset."""
        agent = _minimal_agent(include_checkpoints=True)
        # Should be wrapped in MiddlewareAgent due to checkpoint middleware
        assert isinstance(agent, MiddlewareAgent)
        # Should have checkpoint middleware
        assert any(isinstance(m, CheckpointMiddleware) for m in agent.middleware)
        # Wrapped agent should have checkpoint toolset
        toolset_names = [getattr(t, "_id", "") for t in agent.wrapped.toolsets]
        assert "deep-checkpoints" in toolset_names

    def test_custom_checkpoint_store(self):
        """Custom checkpoint store is passed through."""
        custom_store = InMemoryCheckpointStore()
        agent = _minimal_agent(include_checkpoints=True, checkpoint_store=custom_store)
        assert isinstance(agent, MiddlewareAgent)
        cp_mw = next(m for m in agent.middleware if isinstance(m, CheckpointMiddleware))
        assert cp_mw._fallback_store is custom_store

    def test_checkpoint_frequency_every_turn(self):
        """checkpoint_frequency is passed to middleware."""
        agent = _minimal_agent(include_checkpoints=True, checkpoint_frequency="every_turn")
        cp_mw = next(m for m in agent.middleware if isinstance(m, CheckpointMiddleware))
        assert cp_mw.frequency == "every_turn"

    def test_checkpoint_frequency_manual_only(self):
        """manual_only frequency is passed to middleware."""
        agent = _minimal_agent(include_checkpoints=True, checkpoint_frequency="manual_only")
        cp_mw = next(m for m in agent.middleware if isinstance(m, CheckpointMiddleware))
        assert cp_mw.frequency == "manual_only"

    def test_max_checkpoints_custom(self):
        """max_checkpoints is passed to middleware."""
        agent = _minimal_agent(include_checkpoints=True, max_checkpoints=5)
        cp_mw = next(m for m in agent.middleware if isinstance(m, CheckpointMiddleware))
        assert cp_mw.max_checkpoints == 5

    def test_checkpoints_with_existing_middleware(self):
        """Checkpoints work alongside other middleware."""
        from pydantic_ai_middleware import AgentMiddleware

        class DummyMiddleware(AgentMiddleware[DeepAgentDeps]):
            pass

        agent = _minimal_agent(
            include_checkpoints=True,
            middleware=[DummyMiddleware()],
        )
        assert isinstance(agent, MiddlewareAgent)
        assert any(isinstance(m, DummyMiddleware) for m in agent.middleware)
        assert any(isinstance(m, CheckpointMiddleware) for m in agent.middleware)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestCheckpointExports:
    """Tests for checkpointing types exported from pydantic_deep."""

    def test_checkpoint_importable(self):
        from pydantic_deep import Checkpoint

        assert Checkpoint is not None

    def test_checkpoint_store_importable(self):
        from pydantic_deep import CheckpointStore

        assert CheckpointStore is not None

    def test_in_memory_store_importable(self):
        from pydantic_deep import InMemoryCheckpointStore

        assert InMemoryCheckpointStore is not None

    def test_file_store_importable(self):
        from pydantic_deep import FileCheckpointStore

        assert FileCheckpointStore is not None

    def test_checkpoint_middleware_importable(self):
        from pydantic_deep import CheckpointMiddleware

        assert CheckpointMiddleware is not None

    def test_checkpoint_toolset_importable(self):
        from pydantic_deep import CheckpointToolset

        assert CheckpointToolset is not None

    def test_rewind_requested_importable(self):
        from pydantic_deep import RewindRequested

        assert RewindRequested is not None

    def test_fork_from_checkpoint_importable(self):
        from pydantic_deep import fork_from_checkpoint

        assert callable(fork_from_checkpoint)
