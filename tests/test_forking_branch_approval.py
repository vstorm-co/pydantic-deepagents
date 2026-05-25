"""Tests for branch-level tool-approval routing.

When a branch agent produces ``DeferredToolRequests`` output, the branch
suspends on :attr:`BranchRuntime.pending_approval` (a
:class:`~pydantic_deep.types.PendingApprovalRequest` carrying an
:class:`asyncio.Queue`). The TUI poll loop detects this, surfaces an
approval modal, and puts ``True`` (approve) or ``False`` (deny) into the
queue to unblock the branch.

These tests simulate the TUI by polling ``pending_approval`` and feeding
the queue directly, then asserting on the branch's outcome — what reaches
:attr:`BranchRuntime.blocked_commands`, what surfaces in the post-merge
:class:`~pydantic_deep.types.MergeResult`, and that ``pending_approval``
is correctly cleared on completion and cancellation. Also covers the
unit-level :func:`_describe_blocked_call` helper that formats a
``ToolCallPart`` into the ``"tool_name: arg"`` string shown in the modal.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai_backends import BackendProtocol, StateBackend

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.forking.coordinator import (
    ForkCoordinator,
    _describe_blocked_call,
)
from pydantic_deep.toolsets.forking.store import InMemoryForkStateStore
from pydantic_deep.types import BranchIsolation, BranchSpec


class _NormalResult:
    """Stand-in for a clean ``AgentRunResult`` with no deferred tools."""

    output = "ok"

    def all_messages(self) -> list[Any]:
        return []


class _DeferredResult:
    """Stand-in for an ``AgentRunResult`` whose output is a ``DeferredToolRequests``."""

    def __init__(self, calls: list[ToolCallPart]) -> None:
        self.output = DeferredToolRequests(calls=[], approvals=calls)

    def all_messages(self) -> list[Any]:
        return []


class _DeferringAgent:
    """Agent stub: first ``run()`` returns deferred, second returns clean.

    Mirrors the real pydantic-ai contract: when an approval-required tool
    is invoked the run ends with ``output=DeferredToolRequests(...)``; the
    coordinator's helper continues with ``deferred_tool_results`` and the
    next run returns a normal result.
    """

    model = "anthropic:claude-sonnet-4-6"
    _root_capability = None

    def __init__(self, calls_to_defer: list[ToolCallPart]) -> None:
        self._calls = calls_to_defer
        self.run_invocations: int = 0
        self.last_deferred_results: Any | None = None

    async def run(
        self,
        prompt: str | None,
        *,
        message_history: Any = None,
        deps: Any = None,
        deferred_tool_results: Any = None,
    ) -> Any:
        self.run_invocations += 1
        if deferred_tool_results is not None:
            self.last_deferred_results = deferred_tool_results
            return _NormalResult()
        return _DeferredResult(self._calls)


class _NoDeferAgent:
    """Control: never defers."""

    model = "anthropic:claude-sonnet-4-6"
    _root_capability = None

    async def run(
        self,
        prompt: str | None,
        *,
        message_history: Any = None,
        deps: Any = None,
        deferred_tool_results: Any = None,
    ) -> Any:
        return _NormalResult()


def _make_coord(
    agent: Any,
    parent: BackendProtocol,
    tmp_path: Path,
) -> ForkCoordinator:
    deps = DeepAgentDeps(backend=parent)
    return ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        materializer_root=tmp_path / "forks",
    )


async def _feed_approval(coord: ForkCoordinator, bid: str, approved: bool) -> None:
    """Simulate the TUI: poll until the branch suspends, then respond."""
    rt = coord.branches[bid]
    for _ in range(200):
        if rt.pending_approval is not None:
            rt.pending_approval.response.put_nowait(approved)
            return
        await asyncio.sleep(0.005)
    raise AssertionError(  # pragma: no cover
        f"branch {bid!r} never set pending_approval (timed out after 1 s)"
    )


async def test_branch_deny_records_blocked_command(tmp_path: Path) -> None:
    """Denying the approval modal records the call in ``blocked_commands``."""
    deferred_call = ToolCallPart(
        tool_name="execute",
        args={"command": "pytest -q"},
        tool_call_id="call-1",
    )
    agent = _DeferringAgent([deferred_call])
    coord = _make_coord(agent, StateBackend(), tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    bid = handle.branches[0]

    await asyncio.gather(
        coord.branches[bid].task,
        _feed_approval(coord, bid, False),  # user denies
    )

    rt = coord.branches[bid]
    assert rt.blocked_commands == ["execute: pytest -q"]
    assert rt.status.state == "done"
    # Two agent.run() calls: initial + continuation after denial.
    assert agent.run_invocations == 2


async def test_branch_approve_does_not_record_blocked(tmp_path: Path) -> None:
    """Approving the approval modal leaves ``blocked_commands`` empty."""
    deferred_call = ToolCallPart(
        tool_name="execute",
        args={"command": "pytest -q"},
        tool_call_id="call-2",
    )
    agent = _DeferringAgent([deferred_call])
    coord = _make_coord(agent, StateBackend(), tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    bid = handle.branches[0]

    await asyncio.gather(
        coord.branches[bid].task,
        _feed_approval(coord, bid, True),  # user approves
    )

    rt = coord.branches[bid]
    assert rt.blocked_commands == []
    assert rt.status.state == "done"
    # Approved call forwarded as True in DeferredToolResults.approvals.
    assert agent.last_deferred_results is not None
    assert agent.last_deferred_results.approvals == {"call-2": True}


async def test_branch_denied_commands_surface_in_merge_result(tmp_path: Path) -> None:
    """Denied calls reach ``MergeResult.blocked_commands`` after merge."""
    deferred_call = ToolCallPart(
        tool_name="execute",
        args={"command": "make"},
        tool_call_id="call-3",
    )
    agent = _DeferringAgent([deferred_call])
    coord = _make_coord(agent, StateBackend(), tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    bid = handle.branches[0]

    await asyncio.gather(
        coord.branches[bid].task,
        _feed_approval(coord, bid, False),
    )
    result = await coord.merge_or_select(f"pick:{bid}")

    assert result.blocked_commands == ["execute: make"]


async def test_branch_without_deferrals_keeps_blocked_empty(tmp_path: Path) -> None:
    """A branch that never triggers approval has empty ``blocked_commands``."""
    coord = _make_coord(_NoDeferAgent(), StateBackend(), tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])
    rt = coord.branches[handle.branches[0]]
    assert rt.blocked_commands == []

    result = await coord.merge_or_select(f"pick:{handle.branches[0]}")
    assert result.blocked_commands == []


async def test_pending_approval_cleared_after_response(tmp_path: Path) -> None:
    """``pending_approval`` is reset to ``None`` once the branch unblocks."""
    deferred_call = ToolCallPart(
        tool_name="execute",
        args={"command": "ls"},
        tool_call_id="call-4",
    )
    agent = _DeferringAgent([deferred_call])
    coord = _make_coord(agent, StateBackend(), tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    bid = handle.branches[0]

    await asyncio.gather(
        coord.branches[bid].task,
        _feed_approval(coord, bid, True),
    )

    # After the branch finishes the field must be cleared.
    assert coord.branches[bid].pending_approval is None


async def test_pending_approval_cleared_after_cancellation(tmp_path: Path) -> None:
    """Cancelling a branch while it's suspended on approval clears ``pending_approval``.

    The finally block in ``_run_branch_with_approval`` must run on
    ``asyncio.CancelledError`` so the next branch's modal can fire
    without being shadowed by an orphaned request from the cancelled
    branch.  Regression guard against a coordination deadlock.
    """
    deferred_call = ToolCallPart(
        tool_name="execute",
        args={"command": "ls"},
        tool_call_id="call-cancel",
    )
    agent = _DeferringAgent([deferred_call])
    coord = _make_coord(agent, StateBackend(), tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    bid = handle.branches[0]

    # Wait until the branch suspends on pending_approval.
    rt = coord.branches[bid]
    for _ in range(200):
        if rt.pending_approval is not None:
            break
        await asyncio.sleep(0.005)
    assert rt.pending_approval is not None, "branch never suspended on approval"

    # Cancel mid-suspend; finally must clear pending_approval.
    rt.task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await rt.task
    assert rt.pending_approval is None


async def test_approval_helper_denies_when_runtime_missing(tmp_path: Path) -> None:
    """Unknown ``branch_id`` → deny the deferred call (no path to user consent).

    Defensive path: in production the runtime is always present (fork()
    inserts it before scheduling).  When the runtime is missing the
    helper has no way to surface the modal, so the safe default is to
    deny — auto-approving a gated tool would be a permissions hole.
    """
    deferred_call = ToolCallPart(
        tool_name="execute",
        args={"command": "ls"},
        tool_call_id="call-x",
    )
    agent = _DeferringAgent([deferred_call])
    coord = _make_coord(agent, StateBackend(), tmp_path)
    spec = BranchSpec(label="alpha", steer="alpha")
    deps = DeepAgentDeps(backend=StateBackend())

    result = await coord._run_branch_with_approval("never-inserted", spec, [], deps)

    # Branch still completes in two invocations (one denial doesn't hang),
    # and the denial is passed through to pydantic-ai.
    assert isinstance(result, _NormalResult)
    assert agent.run_invocations == 2
    assert agent.last_deferred_results is not None
    assert agent.last_deferred_results.approvals == {"call-x": False}


# ---------------------------------------------------------------------------
# _describe_blocked_call — unit tests for the modal description formatter
# ---------------------------------------------------------------------------


def test_describe_blocked_call_with_command_arg() -> None:
    call = ToolCallPart(tool_name="execute", args={"command": "pytest -q"}, tool_call_id="x")
    assert _describe_blocked_call(call) == "execute: pytest -q"


def test_describe_blocked_call_without_command_arg() -> None:
    call = ToolCallPart(tool_name="write_file", args={"path": "/x"}, tool_call_id="x")
    assert _describe_blocked_call(call) == "write_file"


def test_describe_blocked_call_with_non_dict_args() -> None:
    """Non-dict ``args`` fall back to the tool name only."""

    class _Stub:
        tool_name = "weird_tool"
        args = "raw-string-args"

    assert _describe_blocked_call(_Stub()) == "weird_tool"


def test_describe_blocked_call_with_args_as_dict_fallback() -> None:
    """When ``args`` is not a dict but ``args_as_dict()`` returns one, use it."""

    class _Stub:
        tool_name = "execute"
        args = '{"command": "make"}'

        def args_as_dict(self) -> dict[str, Any]:
            return {"command": "make"}

    assert _describe_blocked_call(_Stub()) == "execute: make"


def test_describe_blocked_call_with_args_as_dict_raising() -> None:
    """A raising ``args_as_dict()`` returns the tool-name fallback."""

    class _Stub:
        tool_name = "execute"
        args = "not-a-dict"

        def args_as_dict(self) -> dict[str, Any]:
            raise ValueError("parse error")

    assert _describe_blocked_call(_Stub()) == "execute"


def test_describe_blocked_call_with_args_as_dict_returning_non_dict() -> None:
    """``args_as_dict()`` returning a non-dict falls back to tool name."""

    class _Stub:
        tool_name = "execute"
        args = "not-a-dict"

        def args_as_dict(self) -> Any:
            return "still-not-a-dict"

    assert _describe_blocked_call(_Stub()) == "execute"


def test_describe_blocked_call_with_empty_command_arg() -> None:
    """An empty string command falls back to tool name only."""
    call = ToolCallPart(tool_name="execute", args={"command": ""}, tool_call_id="x")
    assert _describe_blocked_call(call) == "execute"


def test_describe_blocked_call_with_unknown_object() -> None:
    """Calls missing ``tool_name`` show as ``<unknown>``."""

    class _Empty:
        pass

    assert _describe_blocked_call(_Empty()) == "<unknown>"
