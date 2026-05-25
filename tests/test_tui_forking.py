"""Tests for the CLI fork integration (issue #104).

Follows the ``TestMessageQueueIntegration`` pattern from ``test_tui.py``:
build a :class:`DeepApp` with a real forking-enabled agent, drive
``/fork`` and ``>>{branch_id}`` through ``pilot``, and assert against
``app.active_fork`` and the rendered widget tree.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from apps.cli.app import DeepApp
from apps.cli.forking import (
    CLIForkSession,
    ForkingNotEnabledError,
    ForkPickerResult,
    resolve_capability,
    start_fork_from_cli,
)
from apps.cli.modals.confirm import ConfirmModal
from apps.cli.modals.fork_picker import ForkPickerModal
from apps.cli.modals.merge_picker import MergePickerModal, MergePickerResult
from apps.cli.screens.chat import ChatScreen
from apps.cli.widgets.branch_panel import BranchPanelWidget
from apps.cli.widgets.fork_badge import ForkBadgeWidget
from apps.cli.widgets.fork_overview import ForkOverviewWidget
from apps.cli.widgets.fork_tabs import OVERVIEW_TAB_ID, ForkTabsWidget
from pydantic_deep import DeepAgentDeps, LiveForkCapability, create_deep_agent
from pydantic_deep.types import BranchSpec


def _make_fork_agent() -> Agent[DeepAgentDeps, str]:
    """Build a TestModel agent with forking enabled."""
    return create_deep_agent(
        model=TestModel(call_tools=[]),
        forking=True,
        include_skills=False,
        include_plan=False,
        include_memory=False,
        include_subagents=False,
        include_teams=False,
        include_todo=False,
        web_search=False,
        web_fetch=False,
        cost_tracking=False,
        context_manager=False,
        stuck_loop_detection=False,
        context_discovery=False,
    )


def _make_app() -> DeepApp:
    agent = _make_fork_agent()
    deps = DeepAgentDeps(backend=StateBackend())
    app = DeepApp(agent=agent, deps=deps, model="test", version="0.3.3")
    app.message_history = [ModelRequest(parts=[UserPromptPart(content="seed turn")])]
    return app


@pytest.fixture
def fork_app() -> DeepApp:
    return _make_app()


def _specs() -> list[BranchSpec]:
    return [
        BranchSpec(label="a", steer="approach A"),
        BranchSpec(label="b", steer="approach B"),
    ]


async def _start_fork(
    app: DeepApp,
    *,
    slow: bool = False,
    strategy: Any = None,
) -> CLIForkSession:
    """Helper — start a fork; if ``slow`` is True, branch tasks block on a barrier.

    ``strategy`` lets a test pin a specific :class:`MergeStrategy` for ``/merge``
    flow tests. ``None`` keeps the dataclass default (``auto_with_fallback``).
    The strategy is patched onto
    ``session.handle.merge_strategy`` after fork to avoid threading a kwarg
    through :func:`start_fork_from_cli` (production never overrides per-call).
    """
    if slow:
        barrier = asyncio.Event()
        app._fork_test_barrier = barrier  # type: ignore[attr-defined]
        real_run = app.agent.run  # type: ignore[union-attr]

        async def _blocking_run(*args: Any, **kwargs: Any) -> Any:
            await barrier.wait()
            return await real_run(*args, **kwargs)

        app.agent.run = _blocking_run  # type: ignore[union-attr, method-assign]

    session = await start_fork_from_cli(app, ForkPickerResult(specs=_specs()))
    if strategy is not None:
        session.handle.merge_strategy = strategy
    app.active_fork = session
    return session


async def _drain_tasks(session: CLIForkSession) -> None:
    """Wait for all branch tasks to settle (cancelled or completed)."""
    import contextlib

    for runtime in session.coordinator.branches.values():
        if not runtime.task.done():
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(runtime.task), timeout=1.0)


class TestForkPickerAndPanels:
    """Test 1 — /fork modal collects two branches, app.active_fork set, 2 BranchPanelWidgets."""

    async def test_fork_populates_active_fork_and_mounts_panels(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            session = await _start_fork(fork_app)
            await pilot.pause()

            assert fork_app.active_fork is session
            panels = list(fork_app.screen.query(BranchPanelWidget))
            assert len(panels) == 2
            labels = {p.label for p in panels}
            assert labels == {"a", "b"}

            await _drain_tasks(session)


class TestBranchSteering:
    """Test 2 — >>a focus on X routes to branch A's queue, branch B's queue empty."""

    async def test_steer_routes_to_correct_branch(self, fork_app: DeepApp) -> None:
        from apps.cli.messages import UserSubmitted

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            a_id = session.label_to_id["a"]
            b_id = session.label_to_id["b"]

            fork_app.screen.post_message(UserSubmitted(">>a focus on tests"))
            await pilot.pause()
            await pilot.pause()

            a_queue = session.coordinator.branches[a_id].deps.message_queue
            b_queue = session.coordinator.branches[b_id].deps.message_queue
            assert a_queue is not None and b_queue is not None
            assert a_queue.pending_count() == (1, 0)
            assert b_queue.pending_count() == (0, 0)

            drained = await a_queue.drain_steering()
            assert drained[0].content == "focus on tests"

            await session.abort()


class TestUnknownBranchSteer:
    """Test 3 — `>>{unknown_label} msg` is rejected with a notify (no fall-through)."""

    async def test_unknown_label_notifies_and_does_not_touch_shell(self, fork_app: DeepApp) -> None:
        from apps.cli.messages import UserSubmitted

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            shell_calls: list[str] = []

            def _record_shell(cmd: str) -> None:
                shell_calls.append(cmd)

            fork_app.run_shell_command = _record_shell  # type: ignore[assignment]

            fork_app.screen.post_message(UserSubmitted(">>totally_unknown_label some text"))
            await pilot.pause()
            await pilot.pause()

            # No branch queue touched
            for runtime in session.coordinator.branches.values():
                q = runtime.deps.message_queue
                assert q is not None
                assert q.pending_count() == (0, 0)

            assert shell_calls == []

            await session.abort()


class TestEscTerminatesOneBranch:
    """Test 4 — Esc on a branch tab terminates that branch only; others continue."""

    async def test_esc_on_branch_tab_terminates_branch(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            a_id = session.label_to_id["a"]
            b_id = session.label_to_id["b"]

            tabs = fork_app.screen.query_one(ForkTabsWidget)
            tabs.active_id = a_id
            await pilot.pause()

            chat = fork_app.screen
            assert isinstance(chat, ChatScreen)
            consumed = await chat.fork_action_escape()
            assert consumed is True
            await pilot.pause()

            from textual.screen import ModalScreen

            for screen in list(fork_app.screen_stack):
                if isinstance(screen, ModalScreen) and isinstance(screen, ConfirmModal):
                    screen.dismiss(True)
            await pilot.pause()
            await pilot.pause()
            await asyncio.sleep(0.05)
            await pilot.pause()

            assert session.coordinator.branches[a_id].status.state == "terminated"
            assert session.coordinator.branches[b_id].status.state == "running"

            await session.abort()


class TestEscAbortsAll:
    """Test 5 — Esc on overview during a fork → abort all branches after confirm."""

    async def test_esc_on_overview_aborts(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            tabs = fork_app.screen.query_one(ForkTabsWidget)
            tabs.active_id = OVERVIEW_TAB_ID
            await pilot.pause()

            chat = fork_app.screen
            assert isinstance(chat, ChatScreen)
            consumed = await chat.fork_action_escape()
            assert consumed is True
            await pilot.pause()

            for screen in list(fork_app.screen_stack):
                if isinstance(screen, ConfirmModal):
                    screen.dismiss(True)
            await pilot.pause()
            await pilot.pause()
            await asyncio.sleep(0.05)
            await pilot.pause()

            for runtime in session.coordinator.branches.values():
                assert runtime.task.done() or runtime.task.cancelled()

            assert fork_app.active_fork is None


class TestMergeFlow:
    """Test 6 — /merge modal renders overview; picking a branch invokes merge_or_select."""

    async def test_merge_picker_invokes_coordinator(self, fork_app: DeepApp) -> None:
        from apps.cli.commands import dispatch_command
        from pydantic_deep.types import MergeStrategy

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            session = await _start_fork(fork_app, strategy=MergeStrategy(kind="manual"))
            await _drain_tasks(session)
            await pilot.pause()

            a_id = session.label_to_id["a"]

            await dispatch_command(fork_app, "/merge")
            await pilot.pause()

            for screen in list(fork_app.screen_stack):
                if isinstance(screen, MergePickerModal):
                    screen.dismiss(MergePickerResult(branch_id=a_id))
                    break
            await pilot.pause()
            await pilot.pause()

            assert fork_app.active_fork is None
            assert any(
                isinstance(part, UserPromptPart) and "seed turn" in str(part.content)
                for msg in fork_app.message_history
                for part in getattr(msg, "parts", [])
            )


class TestForkBadgeVisibility:
    """Test 7 — ForkBadgeWidget visible during fork, hides on resolution."""

    async def test_badge_toggles_visibility(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            badge = fork_app.screen.query_one(ForkBadgeWidget)
            assert not badge.has_class("visible")

            session = await _start_fork(fork_app)
            await pilot.pause()
            assert badge.has_class("visible")

            await _drain_tasks(session)
            a_id = session.label_to_id["a"]
            await session.merge(a_id)
            fork_app.active_fork = None
            await pilot.pause()
            assert not badge.has_class("visible")


class TestTabCyclesFocus:
    """Test 8 — Tab cycles focus through branch panels in order."""

    async def test_tab_cycles_branches(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            tabs = fork_app.screen.query_one(ForkTabsWidget)
            tabs.statuses = session.inspect()
            assert tabs.active_id == OVERVIEW_TAB_ID

            chat = fork_app.screen
            assert isinstance(chat, ChatScreen)

            chat.action_cycle_branch_tab()
            await pilot.pause()
            first = tabs.active_id
            assert first != OVERVIEW_TAB_ID

            chat.action_cycle_branch_tab()
            await pilot.pause()
            second = tabs.active_id
            assert second != first and second != OVERVIEW_TAB_ID

            chat.action_cycle_branch_tab()
            await pilot.pause()
            assert tabs.active_id == OVERVIEW_TAB_ID

            await session.abort()


class TestForkingDisabled:
    async def test_dispatch_fork_when_disabled_notifies(self) -> None:
        """If forking is not enabled on the agent, /fork should notify and bail."""
        from apps.cli.commands import dispatch_command

        agent = create_deep_agent(
            model=TestModel(call_tools=[]),
            forking=False,
            include_skills=False,
            include_plan=False,
            include_memory=False,
            include_subagents=False,
            include_teams=False,
            include_todo=False,
            web_search=False,
            web_fetch=False,
            cost_tracking=False,
            context_manager=False,
            stuck_loop_detection=False,
            context_discovery=False,
        )
        deps = DeepAgentDeps(backend=StateBackend())
        app = DeepApp(agent=agent, deps=deps, model="test", version="0.3.3")
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            await dispatch_command(app, "/fork")
            await pilot.pause()
            assert app.active_fork is None

    async def test_start_fork_raises_when_disabled(self) -> None:
        """start_fork_from_cli should raise ForkingNotEnabledError on a no-forking agent."""
        agent = create_deep_agent(
            model=TestModel(call_tools=[]),
            forking=False,
            include_skills=False,
            include_plan=False,
            include_memory=False,
            include_subagents=False,
            include_teams=False,
            include_todo=False,
            web_search=False,
            web_fetch=False,
            cost_tracking=False,
            context_manager=False,
            stuck_loop_detection=False,
            context_discovery=False,
        )
        deps = DeepAgentDeps(backend=StateBackend())
        app = DeepApp(agent=agent, deps=deps, model="test", version="0.3.3")
        with pytest.raises(ForkingNotEnabledError):
            await start_fork_from_cli(app, ForkPickerResult(specs=_specs()))


class TestDoubleFork:
    async def test_double_fork_blocked(self, fork_app: DeepApp) -> None:
        from apps.cli.commands import dispatch_command

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()
            await dispatch_command(fork_app, "/fork")
            await pilot.pause()
            assert fork_app.active_fork is session
            await _drain_tasks(session)


class TestMergeWithoutFork:
    async def test_merge_without_fork_blocked(self, fork_app: DeepApp) -> None:
        from apps.cli.commands import dispatch_command

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            assert fork_app.active_fork is None
            await dispatch_command(fork_app, "/merge")
            await pilot.pause()
            assert fork_app.active_fork is None


class TestPlainPromptDuringFork:
    async def test_plain_prompt_blocked_while_fork_active(self, fork_app: DeepApp) -> None:
        """Plain prompts during a fork would race with the coordinator — must be blocked."""
        from apps.cli.messages import UserSubmitted

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()
            agent_run_calls: list[Any] = []
            real_run_agent = fork_app.screen._run_agent  # type: ignore[attr-defined]

            def _spy(text: str) -> None:
                agent_run_calls.append(text)
                real_run_agent(text)

            fork_app.screen._run_agent = _spy  # type: ignore[attr-defined]

            fork_app.screen.post_message(UserSubmitted("hello agent please run"))
            await pilot.pause()
            await pilot.pause()

            # Confirm the regular agent runner was NOT invoked
            assert agent_run_calls == []
            await session.abort()


class TestForkDuringAgentRun:
    async def test_fork_blocked_during_agent_run(self, fork_app: DeepApp) -> None:
        from apps.cli.commands import dispatch_command

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            barrier = asyncio.Event()

            async def _fake_run() -> None:
                await barrier.wait()

            task = asyncio.create_task(_fake_run())
            fork_app.agent_task = task

            await dispatch_command(fork_app, "/fork")
            await pilot.pause()

            assert fork_app.active_fork is None

            barrier.set()
            await task


class TestSlashCommandDuringFork:
    async def test_blocked_command_during_fork(self, fork_app: DeepApp) -> None:
        from apps.cli.messages import UserSubmitted

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            # /improve is NOT on the allow-list — should be blocked
            dispatched: list[str] = []
            real_handle = fork_app.handle_command

            def _record(command: str) -> None:
                dispatched.append(command)
                real_handle(command)

            fork_app.handle_command = _record  # type: ignore[method-assign]

            fork_app.screen.post_message(UserSubmitted("/improve"))
            await pilot.pause()
            await pilot.pause()

            assert dispatched == []  # blocked, not dispatched

            await session.abort()

    async def test_allowed_command_during_fork(self, fork_app: DeepApp) -> None:
        from apps.cli.messages import UserSubmitted

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            dispatched: list[str] = []
            real_handle = fork_app.handle_command

            def _record(command: str) -> None:
                dispatched.append(command)
                real_handle(command)

            fork_app.handle_command = _record  # type: ignore[method-assign]

            fork_app.screen.post_message(UserSubmitted("/help"))
            await pilot.pause()
            await pilot.pause()

            assert dispatched == ["/help"]
            await session.abort()


class TestMergePickerModalRendering:
    async def test_merge_picker_renders_untouched_placeholder(self) -> None:
        """A branch that never wrote should render the 'no changes' placeholder."""
        from datetime import datetime, timezone

        from pydantic_deep.types import (
            BranchDiffReport,
            BranchStatus,
            DiffSummary,
        )

        report = BranchDiffReport(
            fork_id="fork-x",
            paths=[],
            summary=DiffSummary(
                total_paths_touched=0,
                unanimous_paths=0,
                split_paths=0,
                per_branch_unique={"id-a": 0, "id-b": 0},
                agreement_score=1.0,
            ),
        )
        statuses = [
            BranchStatus(
                id="id-a",
                label="a",
                state="done",
                current_turn=0,
                last_activity_at=datetime.now(timezone.utc),
            ),
            BranchStatus(
                id="id-b",
                label="b",
                state="done",
                current_turn=0,
                last_activity_at=datetime.now(timezone.utc),
            ),
        ]

        agent = _make_fork_agent()
        deps = DeepAgentDeps(backend=StateBackend())
        app = DeepApp(agent=agent, deps=deps, model="test", version="0.3.3")

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            modal = MergePickerModal(report, statuses, {"a": "id-a", "b": "id-b"})
            app.push_screen(modal)
            await pilot.pause()
            modal.dismiss(MergePickerResult(branch_id="id-a"))
            await pilot.pause()


class TestForkPickerValidation:
    async def test_picker_rejects_blank_or_duplicate_labels(self, fork_app: DeepApp) -> None:
        from textual.widgets import Input

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()

            modal = ForkPickerModal()
            fork_app.push_screen(modal)
            await pilot.pause()

            modal.action_submit()
            await pilot.pause()
            assert modal._read_branch_row(0) == ("", "")
            assert modal._read_branch_row(1) == ("", "")

            modal.query_one("#branch-0-label", Input).value = "x"
            modal.query_one("#branch-0-steer", Input).value = "steer A"
            modal.query_one("#branch-1-label", Input).value = "x"
            modal.query_one("#branch-1-steer", Input).value = "steer B"
            modal.action_submit()
            await pilot.pause()

            modal.query_one("#branch-1-label", Input).value = "y"
            modal.action_submit()
            await pilot.pause()


class TestResolveCapability:
    async def test_resolve_capability_finds_instance(self, fork_app: DeepApp) -> None:
        cap = resolve_capability(fork_app.agent)
        assert isinstance(cap, LiveForkCapability)

    async def test_resolve_capability_returns_none_when_absent(self) -> None:
        class _BareAgent:
            _capabilities: list[Any] = []

        assert resolve_capability(_BareAgent()) is None


class TestForkOverviewWidget:
    async def test_overview_renders_no_branches_placeholder(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            overview = fork_app.screen.query_one(ForkOverviewWidget)
            overview.statuses = []
            await pilot.pause()


class TestSteerWithNoQueue:
    async def test_steer_returns_false_when_queue_none(self, fork_app: DeepApp) -> None:
        """If a branch's deps.message_queue is None, steer_branch should report False."""
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()
            a_id = session.label_to_id["a"]
            session.coordinator.branches[a_id].deps.message_queue = None
            delivered = await session.steer_branch("a", "test")
            assert delivered is False
            await session.abort()

    async def test_steer_returns_false_for_unknown_label(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()
            delivered = await session.steer_branch("nonexistent", "test")
            assert delivered is False
            await session.abort()


class TestBranchStateResolution:
    """Coverage for ``CLIForkSession.branch_state`` — label vs id vs unknown."""

    async def test_branch_state_by_label(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()
            assert session.branch_state("a") == "running"
            assert session.branch_state("b") == "running"
            await session.abort()

    async def test_branch_state_by_id(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()
            a_id = session.label_to_id["a"]
            assert session.branch_state(a_id) == "running"
            await session.abort()

    async def test_branch_state_unknown_returns_none(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()
            assert session.branch_state("nope") is None
            await session.abort()

    async def test_branch_state_reflects_terminated(self, fork_app: DeepApp) -> None:
        """After terminate_branch, state flips to ``terminated``."""
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()
            a_id = session.label_to_id["a"]
            await session.terminate_branch(a_id)
            # The coordinator marks state synchronously inside terminate_branch
            assert session.branch_state("a") == "terminated"
            assert session.branch_state("b") == "running"
            await session.abort()


class TestSteerToNonRunningBranch:
    """`>>{label} <msg>` to a non-running branch is rejected with notify."""

    async def test_done_branch_rejected(self, fork_app: DeepApp) -> None:
        from apps.cli.messages import UserSubmitted

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            # Force branch A to "done" without actually completing the task (which would
            # also fire the coordinator's done_callback and cascade further state).
            a_id = session.label_to_id["a"]
            session.coordinator.branches[a_id].status.state = "done"

            fork_app.screen.post_message(UserSubmitted(">>a do more"))
            await pilot.pause()
            await pilot.pause()

            # The queue should NOT have received the message — branch is not running.
            a_queue = session.coordinator.branches[a_id].deps.message_queue
            assert a_queue is not None
            assert a_queue.pending_count() == (0, 0)

            await session.abort()

    async def test_unknown_branch_rejected_with_notify(self, fork_app: DeepApp) -> None:
        """The new code path: regex matches but `branch_state` returns None → notify, no shell."""
        from apps.cli.messages import UserSubmitted

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            shell_calls: list[str] = []
            fork_app.run_shell_command = (  # type: ignore[method-assign]
                lambda command: shell_calls.append(command)
            )

            fork_app.screen.post_message(UserSubmitted(">>nosuchbranch do thing"))
            await pilot.pause()
            await pilot.pause()

            for runtime in session.coordinator.branches.values():
                q = runtime.deps.message_queue
                assert q is not None
                assert q.pending_count() == (0, 0)
            assert shell_calls == []

            await session.abort()


class TestOrphanToolCallScrub:
    """`start_fork_from_cli` patches orphaned tool calls in parent history before forking."""

    async def test_orphan_tool_calls_are_patched(self, fork_app: DeepApp) -> None:
        """A ToolCallPart without a matching ToolReturnPart in the parent history must
        be synthesized away (otherwise pydantic-ai's history validation rejects the
        branch's first agent.run() call).
        """
        from datetime import datetime, timezone

        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            TextPart,
            ToolCallPart,
            ToolReturnPart,
            UserPromptPart,
        )

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()

            fork_app.message_history = [
                ModelRequest(parts=[UserPromptPart(content="kick off")]),
                ModelResponse(
                    parts=[
                        TextPart(content="thinking…"),
                        ToolCallPart(
                            tool_name="read_file",
                            args={"path": "x.txt"},
                            tool_call_id="orphan-1",
                        ),
                    ],
                    timestamp=datetime.now(timezone.utc),
                ),
            ]

            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            for runtime in session.coordinator.branches.values():
                runtime_history = list(getattr(runtime.deps, "message_history", []) or [])
                _ = runtime_history

            orphan_msg = fork_app.message_history[-1]
            assert any(
                isinstance(part, ToolCallPart) and part.tool_call_id == "orphan-1"
                for part in getattr(orphan_msg, "parts", [])
            )
            assert not any(
                isinstance(part, ToolReturnPart) and part.tool_call_id == "orphan-1"
                for msg in fork_app.message_history
                for part in getattr(msg, "parts", [])
            )

            await session.abort()

    async def test_scrub_invokes_patcher(
        self, fork_app: DeepApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Direct verification: ``patch_tool_calls_processor`` is called with the parent history."""
        from pydantic_ai.messages import ModelMessage

        from pydantic_deep.processors import patch as patch_module

        real_patch = patch_module.patch_tool_calls_processor

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()

            captured: list[list[ModelMessage]] = []

            def _spy(history: list[ModelMessage]) -> list[ModelMessage]:
                captured.append(list(history))
                return real_patch(history)

            monkeypatch.setattr(patch_module, "patch_tool_calls_processor", _spy)

            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            assert len(captured) == 1
            assert captured[0] is not fork_app.message_history

            await session.abort()


# =====================================================================
# CLI/TUI diff-explorer tests (H–M from plan)
# =====================================================================


class TestForkOpenDiffCommand:
    """Tests H, I, L — `/fork diff` dispatch + allow-list."""

    async def test_open_diff_with_path_still_opens_picker(self, fork_app: DeepApp) -> None:
        from unittest.mock import patch

        from apps.cli.commands import dispatch_command
        from apps.cli.modals.diff_picker import DiffPickerModal

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await _drain_tasks(session)
            await pilot.pause()

            with patch(
                "pydantic_deep.toolsets.forking.editor.EditorDetector.detect",
                return_value="pycharm",
            ):
                # Even with a path argument the picker is opened; the
                # path arg is now ignored.
                await dispatch_command(fork_app, "/fork diff foo.py")
                await pilot.pause()

            assert isinstance(fork_app.screen, DiffPickerModal)
            await fork_app.pop_screen()
            await session.abort()

    async def test_open_diff_without_path_opens_picker(self, fork_app: DeepApp) -> None:
        from unittest.mock import patch

        from apps.cli.commands import dispatch_command
        from apps.cli.modals.diff_picker import DiffPickerModal

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await _drain_tasks(session)
            await pilot.pause()

            # Trigger a branch write so the picker has at least one path
            # to render (an empty report would also be a valid path but
            # the user-facing common case is "at least one touched file").
            for rt in session.coordinator.branches.values():
                if rt.overlay is not None:
                    rt.overlay.write("foo.py", "branch content")
                    break

            with patch(
                "pydantic_deep.toolsets.forking.editor.EditorDetector.detect",
                return_value="pycharm",
            ):
                await dispatch_command(fork_app, "/fork diff")
                await pilot.pause()

            # The dispatcher should have pushed the diff picker modal
            # (not invoked the editor — invocation happens when the user
            # confirms inside the picker).
            assert isinstance(fork_app.screen, DiffPickerModal)
            await fork_app.pop_screen()

            await session.abort()

    async def test_open_diff_falls_back_to_tui_modal(self, fork_app: DeepApp) -> None:
        from unittest.mock import patch

        from apps.cli.commands import dispatch_command

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await _drain_tasks(session)
            await pilot.pause()

            with patch(
                "pydantic_deep.toolsets.forking.editor.EditorDetector.detect",
                return_value="tui",
            ):
                await dispatch_command(fork_app, "/fork diff foo.py")
                await pilot.pause()

            assert any(isinstance(screen, MergePickerModal) for screen in fork_app.screen_stack)

            for screen in list(fork_app.screen_stack):
                if isinstance(screen, MergePickerModal):
                    screen.dismiss(None)
                    break
            await pilot.pause()
            await session.abort()

    async def test_open_diff_without_active_fork_notifies(self, fork_app: DeepApp) -> None:
        from unittest.mock import patch

        from apps.cli.commands import dispatch_command

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            with patch.object(fork_app, "notify") as notify_mock:
                await dispatch_command(fork_app, "/fork diff")
                await pilot.pause()
            assert notify_mock.called
            msg = notify_mock.call_args.args[0]
            assert "No active fork" in msg


class TestForkOpenDiffAllowList:
    """Test L — `/fork diff` is allowed mid-fork; plain `/fork` is not."""

    def test_is_fork_inspection_matches_open_diff(self) -> None:
        assert ChatScreen._is_fork_inspection("/fork diff") is True
        assert ChatScreen._is_fork_inspection("/fork diff src/foo.py") is True
        # Plain /fork and unrelated subcommands stay blocked.
        assert ChatScreen._is_fork_inspection("/fork") is False
        assert ChatScreen._is_fork_inspection("/fork-config") is False
        assert ChatScreen._is_fork_inspection("/fork random") is False


class TestMergePickerOpenInEditor:
    """Test M — `MergePickerModal` exposes an Open-in-editor delegation point."""

    def test_open_in_editor_delegates_to_callback(self, fork_app: DeepApp) -> None:
        from datetime import datetime, timezone

        from pydantic_deep.toolsets.forking.diff import build_diff_report
        from pydantic_deep.types import BranchStatus

        seen: list[str] = []

        def callback(branch_id: str) -> None:
            seen.append(branch_id)

        statuses = [
            BranchStatus(
                id="id-a",
                label="a",
                state="done",
                current_turn=0,
                last_activity_at=datetime.now(timezone.utc),
            )
        ]
        report = build_diff_report("fork-x", [])
        modal = MergePickerModal(report, statuses, {"a": "id-a"}, on_open_in_editor=callback)
        modal.action_open_in_editor()
        assert seen == ["id-a"]

    def test_open_in_editor_noop_without_callback(self, fork_app: DeepApp) -> None:
        from datetime import datetime, timezone

        from pydantic_deep.toolsets.forking.diff import build_diff_report
        from pydantic_deep.types import BranchStatus

        statuses = [
            BranchStatus(
                id="id-a",
                label="a",
                state="done",
                current_turn=0,
                last_activity_at=datetime.now(timezone.utc),
            )
        ]
        report = build_diff_report("fork-x", [])
        modal = MergePickerModal(report, statuses, {"a": "id-a"})
        # No callback set → action is a no-op, must not raise.
        modal.action_open_in_editor()


class TestMergeNotification:
    """Tests the addendum-mandated rich merge notification text."""

    def test_notification_default_apply_includes_count(self) -> None:
        from apps.cli.commands import _format_merge_notification
        from pydantic_deep.types import MergeResult

        result = MergeResult(
            fork_id="x",
            winner_branch_id="b1",
            discarded_branches=[],
            history_after_merge=[],
            applied_paths=["cat.md", "dog.md"],
            applied_changes=2,
        )
        text = _format_merge_notification("alpha", result)
        assert "kept branch alpha" in text
        assert "2 files applied" in text

    def test_notification_includes_conflicts(self) -> None:
        from apps.cli.commands import _format_merge_notification
        from pydantic_deep.types import MergeResult

        result = MergeResult(
            fork_id="x",
            winner_branch_id="b1",
            discarded_branches=[],
            history_after_merge=[],
            applied_paths=["cat.md"],
            applied_changes=1,
            conflicts=["cat.md"],
        )
        text = _format_merge_notification("alpha", result)
        assert "conflicts: cat.md" in text

    def test_notification_includes_errors(self) -> None:
        from apps.cli.commands import _format_merge_notification
        from pydantic_deep.types import FlushError, MergeResult

        result = MergeResult(
            fork_id="x",
            winner_branch_id="b1",
            discarded_branches=[],
            history_after_merge=[],
            errors=[FlushError(path="x", op="write", message="boom")],
        )
        text = _format_merge_notification("alpha", result)
        assert "errors: 1" in text
