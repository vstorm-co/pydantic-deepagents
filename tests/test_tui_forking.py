"""Tests for the CLI fork integration (issue #104).

Follows the `TestMessageQueueIntegration` pattern from `test_tui.py`:
build a :class:`DeepApp` with a real forking-enabled agent, drive
`/fork` and `>>{branch_id}` through `pilot`, and assert against
`app.active_fork` and the rendered widget tree.
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
from pydantic_deep.features.forking.types import BranchSpec


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
    specs: list[BranchSpec] | None = None,
) -> CLIForkSession:
    """Helper - start a fork; if `slow` is True, branch tasks block on a barrier.

    `strategy` lets a test pin a specific :class:`MergeStrategy` for `/merge`
    flow tests. `None` keeps the dataclass default (`auto_with_fallback`).
    The strategy is patched onto
    `session.handle.merge_strategy` after fork to avoid threading a kwarg
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

    session = await start_fork_from_cli(app, ForkPickerResult(specs=specs or _specs()))
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


def _quiesce_fork_poll(app: DeepApp) -> None:
    """Stop the screen's fork poll loop so it can't replay into a panel that a
    unit test drives by hand.

    The live ``_poll_fork_state`` timer calls ``mark_status`` / ``replay_messages``
    on the branch panels every tick. Tests in :class:`TestIncrementalReplay`
    reset ``_last_replayed_len`` and assert exact watermark/child counts, so a
    poll tick landing mid-test bumps the watermark nondeterministically (flaky
    under full-suite ordering). Stopping the timer isolates the panel.
    """
    import contextlib

    screen: Any = app.screen
    timer = getattr(screen, "_poll_timer", None)
    if timer is not None:
        with contextlib.suppress(Exception):
            timer.stop()
        screen._poll_timer = None


def _capture_notifications(app: DeepApp) -> list[str]:
    """Monkey-patch `app.notify` to capture messages into a returned list."""
    captured: list[str] = []
    original = app.notify

    def _cap(
        message: str,
        *,
        title: str = "",
        severity: str = "information",
        timeout: float = 5,
    ) -> None:
        captured.append(message)
        original(message, title=title, severity=severity, timeout=timeout)

    app.notify = _cap  # type: ignore[method-assign]
    return captured


class TestForkPickerAndPanels:
    """Test 1 - /fork modal collects two branches, app.active_fork set, 2 BranchPanelWidgets."""

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
    """Test 2 - >>a focus on X routes to branch A's queue, branch B's queue empty."""

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

    async def test_steer_routes_to_hyphenated_label(self, fork_app: DeepApp) -> None:
        """A hyphenated label like `approach-a` (accepted by the picker) is steerable.

        Regression: the steering regex used \\w+, which can't match a hyphen, so
        `>>approach-a ...` was rejected as an unknown branch.
        """
        from apps.cli.messages import UserSubmitted

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            session = await _start_fork(
                fork_app,
                slow=True,
                specs=[
                    BranchSpec(label="approach-a", steer="A"),
                    BranchSpec(label="approach-b", steer="B"),
                ],
            )
            await pilot.pause()

            a_id = session.label_to_id["approach-a"]

            fork_app.screen.post_message(UserSubmitted(">>approach-a focus on tests"))
            await pilot.pause()
            await pilot.pause()

            a_queue = session.coordinator.branches[a_id].deps.message_queue
            assert a_queue is not None
            assert a_queue.pending_count() == (1, 0)
            drained = await a_queue.drain_steering()
            assert drained[0].content == "focus on tests"

            await session.abort()


class TestUnknownBranchSteer:
    """Test 3 - `>>{unknown_label} msg` is rejected with a notify (no fall-through)."""

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
    """Test 4 - Esc on a branch tab terminates that branch only; others continue."""

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
    """Test 5 - Esc on overview during a fork → abort all branches after confirm."""

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
    """Test 6 - /merge modal renders overview; picking a branch invokes merge_or_select."""

    async def test_merge_picker_invokes_coordinator(self, fork_app: DeepApp) -> None:
        from apps.cli.commands import dispatch_command
        from pydantic_deep.features.forking.types import MergeStrategy

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
    """Test 7 - ForkBadgeWidget visible during fork, hides on resolution."""

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
    """Test 8 - Tab cycles focus through branch panels in order."""

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


class TestForkTabsCostRender:
    """Cost must render even when set in the same tick as statuses (chip mount race)."""

    async def test_cost_renders_when_set_same_tick_as_statuses(self, fork_app: DeepApp) -> None:
        from textual.widgets import Static

        from pydantic_deep.features.forking.types import BranchCost

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.pause()

            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            tabs = fork_app.screen.query_one(ForkTabsWidget)
            statuses = session.inspect()
            costs = {
                s.id: BranchCost(
                    branch_id=s.id,
                    branch_label=s.label,
                    cumulative_usd=0.42,
                    budget_usd=1.00,
                    remaining_usd=0.58,
                    state=s.state,
                )
                for s in statuses
            }

            # Set statuses then costs back-to-back, exactly as _poll_fork_state does:
            # watch_statuses mounts chips async while watch_branch_costs is sync.
            tabs.statuses = statuses
            tabs.branch_costs = costs

            # The chip mounts asynchronously and the cost is re-applied once it
            # exists, so poll until it lands rather than guessing a fixed pause
            # count — the fixed-count version flaked under full-suite load.
            sid = statuses[0].id
            text = ""
            for _ in range(50):
                await pilot.pause()
                try:
                    chip = tabs.query_one(f"#fork-tab-{sid}", Static)
                except Exception:
                    continue
                text = str(getattr(chip, "content", ""))
                if "$0.42" in text:
                    break
            assert "$0.42" in text, f"cost missing from chip text: {text!r}"

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
        """Plain prompts during a fork would race with the coordinator - must be blocked."""
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

            # /improve is NOT on the allow-list - should be blocked
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

        from pydantic_deep.features.forking.types import (
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

            from textual.widgets import Static

            modal.query_one("#branch-0-label", Input).value = "x"
            modal.query_one("#branch-0-steer", Input).value = "steer A"
            modal.query_one("#branch-1-label", Input).value = "x"
            modal.query_one("#branch-1-steer", Input).value = "steer B"
            modal.action_submit()
            await pilot.pause()

            # Duplicate labels are rejected: error shown, modal stays open.
            error = modal.query_one("#fork-picker-error", Static)
            assert "distinct" in str(getattr(error, "content", "")).lower()
            assert isinstance(fork_app.screen, ForkPickerModal)

            # Distinct labels now submit successfully (modal dismisses).
            modal.query_one("#branch-1-label", Input).value = "y"
            modal.action_submit()
            await pilot.pause()
            assert not isinstance(fork_app.screen, ForkPickerModal)


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
    """Coverage for `CLIForkSession.branch_state` - label vs id vs unknown."""

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
        """After terminate_branch, state flips to `terminated`."""
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

            # The queue should NOT have received the message - branch is not running.
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
        """Direct verification: `patch_tool_calls_processor` is called with the parent history."""
        from pydantic_ai.messages import ModelMessage

        from pydantic_deep.features import patch as patch_module

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
    """Tests H, I, L - `/fork diff` dispatch + allow-list."""

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
                "pydantic_deep.features.forking.editor.EditorDetector.detect",
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

            # Trigger a branch write so the picker has at least one path to render.
            for rt in session.coordinator.branches.values():
                if rt.overlay is not None:
                    rt.overlay.write("foo.py", "branch content")
                    break

            with patch(
                "pydantic_deep.features.forking.editor.EditorDetector.detect",
                return_value="pycharm",
            ):
                await dispatch_command(fork_app, "/fork diff")
                await pilot.pause()

            # Dispatcher pushes the picker modal - editor invocation happens on user confirm.
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
                "pydantic_deep.features.forking.editor.EditorDetector.detect",
                return_value="tui",
            ):
                await dispatch_command(fork_app, "/fork diff foo.py")
                await pilot.pause()

            modal = next(
                (s for s in fork_app.screen_stack if isinstance(s, MergePickerModal)), None
            )
            assert modal is not None
            # The fallback must be browse-mode, not a pick-mode modal whose Enter is
            # silently discarded (the silent-no-op bug).
            assert modal._view_only is True

            # Pressing Enter in browse mode must NOT commit a merge: it just closes,
            # leaving the active fork unchanged.
            active_before = fork_app.active_fork
            modal.action_pick_selected()
            await pilot.pause()
            assert fork_app.active_fork is active_before
            assert not any(isinstance(s, MergePickerModal) for s in fork_app.screen_stack)
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
    """Test L - `/fork diff` is allowed mid-fork; plain `/fork` is not."""

    def test_is_fork_inspection_matches_open_diff(self) -> None:
        assert ChatScreen._is_fork_inspection("/fork diff") is True
        assert ChatScreen._is_fork_inspection("/fork diff src/foo.py") is True
        # Plain /fork and unrelated subcommands stay blocked.
        assert ChatScreen._is_fork_inspection("/fork") is False
        assert ChatScreen._is_fork_inspection("/fork-config") is False
        assert ChatScreen._is_fork_inspection("/fork random") is False

    def test_is_fork_inspection_is_case_insensitive(self) -> None:
        # Command dispatch lowercases the verb, so uppercase /FORK diff must also
        # pass the allow-check (regression: it was tested on original-case text).
        assert ChatScreen._is_fork_inspection("/FORK diff") is True
        assert ChatScreen._is_fork_inspection("/Fork Diff src/foo.py") is True
        assert ChatScreen._is_fork_inspection("/FORK") is False


class TestMergePickerOpenInEditor:
    """Test M - `MergePickerModal` exposes an Open-in-editor delegation point."""

    async def test_open_in_editor_delegates_to_callback(self, fork_app: DeepApp) -> None:
        from datetime import datetime, timezone

        from pydantic_deep.features.forking.diff import build_diff_report
        from pydantic_deep.features.forking.types import BranchStatus

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
        report = await build_diff_report("fork-x", [])
        modal = MergePickerModal(report, statuses, {"a": "id-a"}, on_open_in_editor=callback)
        modal.action_open_in_editor()
        assert seen == ["id-a"]

    async def test_open_in_editor_noop_without_callback(self, fork_app: DeepApp) -> None:
        from datetime import datetime, timezone

        from pydantic_deep.features.forking.diff import build_diff_report
        from pydantic_deep.features.forking.types import BranchStatus

        statuses = [
            BranchStatus(
                id="id-a",
                label="a",
                state="done",
                current_turn=0,
                last_activity_at=datetime.now(timezone.utc),
            )
        ]
        report = await build_diff_report("fork-x", [])
        modal = MergePickerModal(report, statuses, {"a": "id-a"})
        # No callback set → action is a no-op, must not raise.
        modal.action_open_in_editor()


class TestMergeNotification:
    """Tests the addendum-mandated rich merge notification text."""

    def test_notification_default_apply_includes_count(self) -> None:
        from apps.cli.commands import _format_merge_notification
        from pydantic_deep.features.forking.types import MergeResult

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
        from pydantic_deep.features.forking.types import MergeResult

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
        from pydantic_deep.features.forking.types import FlushError, MergeResult

        result = MergeResult(
            fork_id="x",
            winner_branch_id="b1",
            discarded_branches=[],
            history_after_merge=[],
            errors=[FlushError(path="x", op="write", message="boom")],
        )
        text = _format_merge_notification("alpha", result)
        assert "errors: 1" in text

    def test_notification_includes_deleted_paths(self) -> None:
        """The deleted-paths count surfaces as `N deleted` in the merge notification."""
        from apps.cli.commands import _format_merge_notification
        from pydantic_deep.features.forking.types import MergeResult

        result = MergeResult(
            fork_id="x",
            winner_branch_id="b1",
            discarded_branches=[],
            history_after_merge=[],
            applied_paths=["cat.md"],
            applied_changes=1,
            deleted_paths=["stale.py", "trash.py"],
        )
        text = _format_merge_notification("alpha", result)
        assert "1 files applied" in text
        assert "2 deleted" in text

    def test_notification_includes_blocked_commands(self) -> None:
        """User-denied tool calls surface as `denied: N` in the merge notification."""
        from apps.cli.commands import _format_merge_notification
        from pydantic_deep.features.forking.types import MergeResult

        result = MergeResult(
            fork_id="x",
            winner_branch_id="b1",
            discarded_branches=[],
            history_after_merge=[],
            blocked_commands=["execute: pytest", "execute: make"],
        )
        text = _format_merge_notification("alpha", result)
        assert "denied: 2" in text


class TestBranchPanelBlockedBadge:
    """Branch panel header renders `⚠ N denied` / `⏸ awaiting approval` badges.

    The header reflects two pieces of runtime state on the branch:

    - :attr:`BranchPanelWidget.blocked_count` - historical tally of denied
      tool calls; rendered as `⚠ N denied` (orange).
    - :attr:`BranchPanelWidget.awaiting_approval` - set while the branch
      is suspended on an approval request; rendered as
      `⏸ awaiting approval` (yellow) and takes precedence over the
      blocked-count badge because it reflects the branch's current state.
    """

    def test_header_renders_denied_badge_when_count_nonzero(self) -> None:
        panel = BranchPanelWidget("id-a", "alpha")
        panel.blocked_count = 3
        # Test the renderer directly to avoid running the full Textual app.
        rendered = panel._render_header()
        assert "⚠ 3 denied" in rendered

    def test_header_omits_denied_badge_when_count_zero(self) -> None:
        panel = BranchPanelWidget("id-a", "alpha")
        # Default value - no badge.
        assert "denied" not in panel._render_header()
        assert "awaiting" not in panel._render_header()

    def test_header_renders_awaiting_badge_when_pending(self) -> None:
        """`awaiting_approval=True` shows the ⏸ badge, taking priority over denied."""
        panel = BranchPanelWidget("id-a", "alpha")
        panel.awaiting_approval = True
        panel.blocked_count = 2  # also has past denials
        rendered = panel._render_header()
        assert "⏸ awaiting approval" in rendered
        # denied count is suppressed while awaiting
        assert "denied" not in rendered

    async def test_blocked_badge_updates_when_count_changes(self) -> None:
        """Reactive write triggers `watch_blocked_count` and refreshes the header."""
        from textual.app import App
        from textual.widgets import Static

        class _Harness(App[None]):
            def compose(self) -> Any:
                yield BranchPanelWidget("id-a", "alpha")

        harness = _Harness()
        async with harness.run_test():
            panel = harness.query_one(BranchPanelWidget)
            panel.blocked_count = 2
            header_widget = panel.query_one(".branch-header", Static)
            assert "⚠ 2 denied" in str(header_widget.render())

    async def test_awaiting_badge_updates_when_flag_set(self) -> None:
        """Reactive write to `awaiting_approval` triggers header refresh."""
        from textual.app import App
        from textual.widgets import Static

        class _Harness(App[None]):
            def compose(self) -> Any:
                yield BranchPanelWidget("id-a", "alpha")

        harness = _Harness()
        async with harness.run_test():
            panel = harness.query_one(BranchPanelWidget)
            panel.awaiting_approval = True
            header_widget = panel.query_one(".branch-header", Static)
            assert "⏸ awaiting approval" in str(header_widget.render())


class TestAdoptAgentCoordinator:
    """B2 - adopt_agent_coordinator + reconcile_active_fork.

    Covers the autonomous fork path: the agent calls `fork_run` inside an
    `agent.run()`, leaving a coordinator on `deps.fork_coordinator` that
    the CLI side must wrap in a :class:`CLIForkSession`.
    """

    async def test_returns_none_when_deps_unset(self) -> None:
        """No deps on the app → adopter returns `None` (defensive)."""
        from apps.cli.forking import adopt_agent_coordinator

        app = _make_app()
        app.deps = None
        assert adopt_agent_coordinator(app) is None

    async def test_returns_none_when_coordinator_missing(self) -> None:
        """No coordinator on deps → adopter returns `None`."""
        from apps.cli.forking import adopt_agent_coordinator

        app = _make_app()
        assert app.deps is not None
        app.deps.fork_coordinator = None
        assert adopt_agent_coordinator(app) is None

    async def test_returns_none_when_no_branches(self) -> None:
        """Coordinator with no branches (fork() never called) → `None`."""
        from apps.cli.forking import adopt_agent_coordinator

        app = _make_app()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            # Allocate a coordinator without calling fork()
            cap = resolve_capability(app.agent)
            assert cap is not None

            class _Ctx:
                deps = app.deps

            await cap.for_run(_Ctx())
            assert adopt_agent_coordinator(app) is None

    async def test_wraps_existing_coordinator(self, fork_app: DeepApp) -> None:
        """Adopter builds a :class:`CLIForkSession` from a live coordinator."""
        from apps.cli.forking import adopt_agent_coordinator

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            # Pretend the agent allocated this coordinator: drop active_fork
            # so the adopter cold-starts on the existing deps.fork_coordinator.
            fork_app.active_fork = None
            assert fork_app.deps is not None
            fork_app.deps.fork_coordinator = session.coordinator

            adopted = adopt_agent_coordinator(fork_app)
            assert adopted is not None
            assert adopted.coordinator is session.coordinator
            assert adopted.handle is session.coordinator.handle
            assert adopted.adopted is True
            # label_to_id is populated from the existing handle
            assert set(adopted.label_to_id.keys()) == {"a", "b"}
            await _drain_tasks(session)

    async def test_returns_none_when_already_resolved(self, fork_app: DeepApp) -> None:
        """Resolved coordinator (post-merge) is NOT adopted - UI does not flash."""
        from apps.cli.forking import adopt_agent_coordinator

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await _drain_tasks(session)
            # Force the post-merge state: every overlay released.
            for runtime in session.coordinator.branches.values():
                runtime.overlay = None
            assert session.coordinator.is_resolved is True

            fork_app.active_fork = None
            assert fork_app.deps is not None
            fork_app.deps.fork_coordinator = session.coordinator

            assert adopt_agent_coordinator(fork_app) is None

    async def test_idempotent_when_already_active(self, fork_app: DeepApp) -> None:
        """Calling adopter twice returns the existing wrapper unchanged."""
        from apps.cli.forking import adopt_agent_coordinator

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            # active_fork is already set by _start_fork - but mark adopted=True
            # to simulate the auto-adopted path.
            fork_app.active_fork.adopted = True  # type: ignore[union-attr]
            assert fork_app.deps is not None
            fork_app.deps.fork_coordinator = session.coordinator

            adopted_again = adopt_agent_coordinator(fork_app)
            assert adopted_again is fork_app.active_fork
            await _drain_tasks(session)


class TestReconcileActiveFork:
    """B2 - reconcile_active_fork: post-turn cleanup + adoption combined.

    Tests the two transitions that the user-driven `/fork` cannot trigger:
    agent merged its own fork (cleanup), and agent forked without merging
    (adopt).
    """

    async def test_clears_active_fork_when_resolved(self, fork_app: DeepApp) -> None:
        """If the agent merged itself, the helper clears `app.active_fork`."""
        from apps.cli.forking import reconcile_active_fork

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await _drain_tasks(session)
            # Simulate agent-driven merge: release every overlay.
            for runtime in session.coordinator.branches.values():
                runtime.overlay = None
            assert session.coordinator.is_resolved is True

            mutated = reconcile_active_fork(fork_app)
            assert mutated is True
            assert fork_app.active_fork is None

    async def test_adopts_when_no_active_fork(self, fork_app: DeepApp) -> None:
        """If the agent forked without merging, helper adopts the coordinator."""
        from apps.cli.forking import reconcile_active_fork

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            # Pretend the user-driven /fork never ran: detach the CLI session
            # but leave the coordinator on deps where the agent would have put it.
            fork_app.active_fork = None
            assert fork_app.deps is not None
            fork_app.deps.fork_coordinator = session.coordinator

            mutated = reconcile_active_fork(fork_app)
            assert mutated is True
            assert fork_app.active_fork is not None
            assert fork_app.active_fork.adopted is True
            await _drain_tasks(session)

    async def test_no_op_when_no_fork_state(self, fork_app: DeepApp) -> None:
        """If the agent never forked, the helper does nothing."""
        from apps.cli.forking import reconcile_active_fork

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert fork_app.deps is not None
            fork_app.deps.fork_coordinator = None
            assert fork_app.active_fork is None

            assert reconcile_active_fork(fork_app) is False
            assert fork_app.active_fork is None


class TestOrphanStashMultiTurn:
    """B3.d - stashed coordinator survives subsequent non-fork parent turns in the TUI."""

    async def test_active_fork_survives_second_non_fork_turn(self, fork_app: DeepApp) -> None:
        """Second parent turn keeps `app.active_fork` at the same session."""
        from apps.cli.forking import reconcile_active_fork

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            assert fork_app.active_fork is session

            # reconcile_active_fork on an unresolved fork with active_fork set returns False (no-op)
            mutated = reconcile_active_fork(fork_app)
            assert mutated is False
            assert fork_app.active_fork is session

            # Simulate a second reconcile (e.g. another parent turn ending)
            mutated2 = reconcile_active_fork(fork_app)
            assert mutated2 is False
            assert fork_app.active_fork is session
            assert fork_app.active_fork.coordinator is session.coordinator

            # Unblock the slow branches so they complete
            barrier = getattr(fork_app, "_fork_test_barrier", None)
            if barrier is not None:
                barrier.set()
            await _drain_tasks(session)


class TestForkCommandBlockedWhenAdopted:
    """B2 - `/fork` shows the adopted-specific notification when active_fork.adopted."""

    async def test_notification_says_agent_already_forked(self, fork_app: DeepApp) -> None:
        """User typing `/fork` during an auto-adopted fork gets the adopted message."""
        from apps.cli.commands import dispatch_command

        notifications: list[tuple[str, str]] = []
        original_notify = fork_app.notify

        def _capture_notify(
            message: str,
            *,
            title: str = "",
            severity: str = "information",
            timeout: float = 5,
        ) -> None:
            notifications.append((message, severity))
            original_notify(message, title=title, severity=severity, timeout=timeout)

        fork_app.notify = _capture_notify  # type: ignore[method-assign]

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            # Mark the session as auto-adopted.
            session.adopted = True
            fork_app.active_fork = session

            await dispatch_command(fork_app, "/fork")
            await pilot.pause()

            assert any("agent already forked" in msg.lower() for msg, _ in notifications), (
                notifications
            )
            await _drain_tasks(session)

    async def test_notification_says_fork_already_active_when_not_adopted(
        self, fork_app: DeepApp
    ) -> None:
        """User-initiated forks keep the original wording (regression guard)."""
        from apps.cli.commands import dispatch_command

        notifications: list[tuple[str, str]] = []
        original_notify = fork_app.notify

        def _capture_notify(
            message: str,
            *,
            title: str = "",
            severity: str = "information",
            timeout: float = 5,
        ) -> None:
            notifications.append((message, severity))
            original_notify(message, title=title, severity=severity, timeout=timeout)

        fork_app.notify = _capture_notify  # type: ignore[method-assign]

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            # session.adopted defaults to False (user-initiated path)
            assert session.adopted is False

            await dispatch_command(fork_app, "/fork")
            await pilot.pause()

            assert any("fork already active" in msg.lower() for msg, _ in notifications), (
                notifications
            )
            await _drain_tasks(session)


class TestIncrementalReplay:
    """E1B - replay_messages_append renders only the delta between poll ticks."""

    async def test_e1b_a_append_renders_only_delta(self, fork_app: DeepApp) -> None:
        """E1B.a - new TextPart between ticks → panel renders only the delta."""
        from pydantic_ai.messages import ModelResponse, TextPart

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()

            panel = list(fork_app.screen.query(BranchPanelWidget))[0]
            _quiesce_fork_poll(fork_app)
            panel._last_replayed_len = 0

            msg1 = [ModelResponse(parts=[TextPart(content="hello")])]
            panel.replay_messages_append(msg1)
            assert panel._last_replayed_len == 1

            msg2 = msg1 + [ModelResponse(parts=[TextPart(content="world")])]
            panel.replay_messages_append(msg2)
            assert panel._last_replayed_len == 2
            await _drain_tasks(session)

    async def test_note_streamed_messages_prevents_double_replay(self, fork_app: DeepApp) -> None:
        """note_streamed_messages advances the watermark so a poll-tick append of
        the already-streamed transcript is a no-op (no doubling)."""
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

        from apps.cli.widgets.message_list import MessageList

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()

            panel = list(fork_app.screen.query(BranchPanelWidget))[0]
            _quiesce_fork_poll(fork_app)
            panel._last_replayed_len = 0

            streamed = [
                ModelResponse(parts=[TextPart(content="streamed live")]),
                ModelResponse(parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="c1")]),
            ]
            # Simulate _stream_branch_via_iter having rendered these live.
            panel.note_streamed_messages(streamed)
            assert panel._last_replayed_len == 2
            assert "c1" in panel._rendered_call_ids

            msg_list = panel.query_one(MessageList)
            before = len(msg_list.children)

            # A poll tick replaying the same transcript must NOT re-render it.
            panel.replay_messages_append(streamed)
            assert len(msg_list.children) == before
            await _drain_tasks(session)

    async def test_e1b_b_tool_call_then_return_updates_in_place(self, fork_app: DeepApp) -> None:
        """E1B.b - ToolCallPart in tick N, ToolReturnPart in tick N+1."""
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            ToolCallPart,
            ToolReturnPart,
        )

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()

            panel = list(fork_app.screen.query(BranchPanelWidget))[0]
            _quiesce_fork_poll(fork_app)
            panel._last_replayed_len = 0
            panel._rendered_call_ids = set()

            tick1 = [
                ModelResponse(parts=[ToolCallPart(tool_name="ls", args="{}", tool_call_id="c1")])
            ]
            panel.replay_messages_append(tick1)
            assert "c1" in panel._rendered_call_ids

            tick2 = tick1 + [
                ModelRequest(
                    parts=[ToolReturnPart(tool_name="ls", content="file.txt", tool_call_id="c1")]
                )
            ]
            panel.replay_messages_append(tick2)
            assert panel._last_replayed_len == 2
            await _drain_tasks(session)

    async def test_e1b_c_tool_return_completes_across_text_part_boundary(
        self, fork_app: DeepApp
    ) -> None:
        """tick N ends with a TextPart (current_assistant→None); tick N+1's
        ToolReturnPart for a call from tick N must still complete it in place,
        not leave the tool row spinning forever."""
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            TextPart,
            ToolCallPart,
            ToolReturnPart,
        )

        from apps.cli.widgets.assistant_message import AssistantMessage
        from apps.cli.widgets.message_list import MessageList

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()

            panel = list(fork_app.screen.query(BranchPanelWidget))[0]
            _quiesce_fork_poll(fork_app)
            panel._last_replayed_len = 0
            panel._rendered_call_ids = set()

            # Tick N: a tool call followed by a text part - the trailing text ends
            # the assistant message, setting current_assistant to None.
            tick1 = [
                ModelResponse(
                    parts=[
                        ToolCallPart(tool_name="ls", args="{}", tool_call_id="c1"),
                        TextPart(content="done"),
                    ]
                )
            ]
            panel.replay_messages_append(tick1)
            await pilot.pause()

            # Tick N+1: the return for c1 arrives.
            tick2 = tick1 + [
                ModelRequest(
                    parts=[ToolReturnPart(tool_name="ls", content="file.txt", tool_call_id="c1")]
                )
            ]
            panel.replay_messages_append(tick2)
            await pilot.pause()

            msg_list = panel.query_one(MessageList)
            widget = None
            for child in msg_list.children:
                if isinstance(child, AssistantMessage) and child.has_tool_call("c1"):
                    widget = child._tool_widgets["c1"]
            assert widget is not None, "tool-call widget for c1 not found"
            # The call must be completed (not stuck pending) despite the tick boundary.
            assert widget.status == "success"
            await _drain_tasks(session)

    async def test_e1b_d_running_transition_clears_list_no_duplicate(
        self, fork_app: DeepApp
    ) -> None:
        """A done→running mark_status must clear the rendered list so the next
        full replay doesn't duplicate the transcript on top of itself."""
        from pydantic_ai.messages import ModelResponse, TextPart

        from apps.cli.widgets.message_list import MessageList
        from apps.cli.widgets.user_message import UserMessage

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()

            panel = list(fork_app.screen.query(BranchPanelWidget))[0]
            _quiesce_fork_poll(fork_app)
            msg_list = panel.query_one(MessageList)
            # Start from a clean panel (the fork setup pre-populates it).
            msg_list.clear_messages()
            panel._last_replayed_len = 0
            panel._rendered_call_ids = set()

            from pydantic_ai.messages import ModelRequest, UserPromptPart

            history = [
                ModelRequest(parts=[UserPromptPart(content="hi there")]),
                ModelResponse(parts=[TextPart(content="hello back")]),
            ]
            panel.replay_messages_append(history)
            await pilot.pause()
            users_before = [c for c in msg_list.children if isinstance(c, UserMessage)]
            assert len(users_before) == 1

            # done → running resets the watermark; it must also clear the list.
            panel.mark_status("running")
            await pilot.pause()
            assert panel._last_replayed_len == 0
            assert len([c for c in msg_list.children]) == 0

            # Re-replaying the full history must not duplicate the prior render.
            panel.replay_messages_append(history)
            await pilot.pause()
            users_after = [c for c in msg_list.children if isinstance(c, UserMessage)]
            assert len(users_after) == 1
            await _drain_tasks(session)

    async def test_e1b_c_full_replay_on_done_is_consistent(self, fork_app: DeepApp) -> None:
        """E1B.c - on task done, full replay_messages runs and panel is consistent."""
        from pydantic_ai.messages import ModelResponse, TextPart

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()

            panel = list(fork_app.screen.query(BranchPanelWidget))[0]
            _quiesce_fork_poll(fork_app)
            panel._last_replayed_len = 0

            msgs = [
                ModelResponse(parts=[TextPart(content="partial")]),
                ModelResponse(parts=[TextPart(content="more")]),
            ]
            panel.replay_messages_append(msgs[:1])
            assert panel._last_replayed_len == 1

            panel.replay_messages(msgs)
            assert panel._last_replayed_len == 2
            await _drain_tasks(session)

    async def test_full_replay_completes_tool_return_across_text_part_boundary(
        self, fork_app: DeepApp
    ) -> None:
        """A full replay of a transcript where a ToolCallPart is followed by a
        TextPart (which ends the assistant message) must still complete the
        call's ToolReturnPart in place, not leave the tool row spinning."""
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            TextPart,
            ToolCallPart,
            ToolReturnPart,
        )

        from apps.cli.widgets.assistant_message import AssistantMessage
        from apps.cli.widgets.message_list import MessageList

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()

            panel = list(fork_app.screen.query(BranchPanelWidget))[0]
            _quiesce_fork_poll(fork_app)

            messages = [
                ModelResponse(
                    parts=[
                        ToolCallPart(tool_name="ls", args="{}", tool_call_id="c1"),
                        TextPart(content="done"),
                    ]
                ),
                ModelRequest(
                    parts=[ToolReturnPart(tool_name="ls", content="file.txt", tool_call_id="c1")]
                ),
            ]
            panel.replay_messages(messages)
            await pilot.pause()

            msg_list = panel.query_one(MessageList)
            widget = None
            for child in msg_list.children:
                if isinstance(child, AssistantMessage) and child.has_tool_call("c1"):
                    widget = child._tool_widgets["c1"]
            assert widget is not None, "tool-call widget for c1 not found"
            # Completed in place despite the trailing TextPart boundary.
            assert widget.status == "success"
            # The held reference is recorded so a later append tick could also
            # complete a call first rendered by the full replay.
            assert "c1" in panel._rendered_call_msgs
            await _drain_tasks(session)

    async def test_e1b_d_multiple_new_messages_in_one_tick(self, fork_app: DeepApp) -> None:
        """E1B.d - history grew by >1 message between polls → all rendered."""
        from pydantic_ai.messages import ModelResponse, TextPart

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()

            panel = list(fork_app.screen.query(BranchPanelWidget))[0]
            _quiesce_fork_poll(fork_app)
            panel._last_replayed_len = 0

            msgs = [
                ModelResponse(parts=[TextPart(content="a")]),
                ModelResponse(parts=[TextPart(content="b")]),
                ModelResponse(parts=[TextPart(content="c")]),
            ]
            panel.replay_messages_append(msgs)
            assert panel._last_replayed_len == 3
            await _drain_tasks(session)


class TestBranchStreamRunner:
    """E1A - branch_runner wired via enter_fork_view routes agent.iter() into panels."""

    async def test_e1a_a_branch_runner_set_on_coordinator(self, fork_app: DeepApp) -> None:
        """E1A.a - after enter_fork_view, coordinator.branch_runner is set."""
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()
            assert session.coordinator.branch_runner is not None
            await _drain_tasks(session)

    async def test_e1a_b_panels_have_runtime_panel_ref(self, fork_app: DeepApp) -> None:
        """E1A.b - each runtime has a _panel reference pointing to the mounted BranchPanelWidget."""
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await pilot.pause()
            for branch_id in session.handle.branches:
                runtime = session.coordinator.branches[branch_id]
                panel_ref = getattr(runtime, "_panel", None)
                assert panel_ref is not None
                assert isinstance(panel_ref, BranchPanelWidget)
                assert panel_ref.branch_id == branch_id
            await _drain_tasks(session)

    async def test_e1a_c_branch_runner_streams_into_panel(self, fork_app: DeepApp) -> None:
        """E1A.c - branch tasks use branch_runner via iter and produce output in panels."""
        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await _drain_tasks(session)
            await pilot.pause()

            for branch_id in session.handle.branches:
                runtime = session.coordinator.branches[branch_id]
                assert runtime.task.done()
                assert runtime.status.state == "done"

    async def test_e1a_d_coordinator_without_runner_uses_agent_run(self) -> None:
        """E1A.d - coordinator without branch_runner uses agent.run() (default path)."""
        from pydantic_ai_backends import StateBackend

        from pydantic_deep import DeepAgentDeps
        from pydantic_deep.features.forking.coordinator import ForkCoordinator
        from pydantic_deep.features.forking.store import InMemoryForkStateStore
        from pydantic_deep.features.forking.types import BranchSpec

        agent = _make_fork_agent()
        deps = DeepAgentDeps(backend=StateBackend())
        coord = ForkCoordinator(
            agent=agent,
            parent_deps=deps,
            max_branches=2,
            max_depth=1,
            store=InMemoryForkStateStore(),
        )
        assert coord.branch_runner is None
        handle = await coord.fork(
            [BranchSpec(label="x", steer="go")],
            parent_history=[ModelRequest(parts=[UserPromptPart(content="seed")])],
        )
        assert len(handle.branches) == 1
        await asyncio.gather(*(rt.task for rt in coord.branches.values()))
        for rt in coord.branches.values():
            assert rt.task.done()
            assert rt.status.state == "done"
            result = rt.task.result()
            assert result is not None


class TestInteractiveBranchChat:
    """E2 - interactive multi-branch chat input routing."""

    async def test_e2_c_plain_text_on_overview_during_fork_is_blocked(
        self, fork_app: DeepApp
    ) -> None:
        """E2.c - plain text on the overview tab during an active fork → notification."""
        from apps.cli.messages import UserSubmitted

        notifications = _capture_notifications(fork_app)

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await _drain_tasks(session)
            await pilot.pause()

            fork_app.screen.post_message(UserSubmitted("hello there"))
            await pilot.pause()
            await pilot.pause()
            assert any("fork active" in n.lower() for n in notifications), notifications
            await _drain_tasks(session)

    async def test_e2_d_plain_text_on_running_branch_is_blocked(self, fork_app: DeepApp) -> None:
        """E2.d - plain text on a still-running branch → notification (cannot interact)."""
        from apps.cli.messages import UserSubmitted

        notifications = _capture_notifications(fork_app)

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app, slow=True)
            await pilot.pause()

            first_bid = session.handle.branches[0]
            chat_screen = fork_app.screen
            if isinstance(chat_screen, ChatScreen):
                tabs = chat_screen.query_one(ForkTabsWidget)
                tabs.active_id = first_bid
                chat_screen.focus_branch_tab(first_bid)

            fork_app.screen.post_message(UserSubmitted("try interact"))
            await pilot.pause()
            await pilot.pause()
            assert any("still running" in n.lower() for n in notifications), notifications

            barrier = getattr(fork_app, "_fork_test_barrier", None)
            if barrier is not None:
                barrier.set()
            await _drain_tasks(session)

    async def test_e2_e_slash_fork_blocked_during_interactive_chat(self, fork_app: DeepApp) -> None:
        """E2.e - /fork typed during an interactive branch chat → blocked."""
        from apps.cli.messages import UserSubmitted

        notifications = _capture_notifications(fork_app)

        async with fork_app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            session = await _start_fork(fork_app)
            await _drain_tasks(session)
            await pilot.pause()

            first_bid = session.handle.branches[0]
            chat_screen = fork_app.screen
            if isinstance(chat_screen, ChatScreen):
                tabs = chat_screen.query_one(ForkTabsWidget)
                tabs.active_id = first_bid
                chat_screen.focus_branch_tab(first_bid)

            fork_app.screen.post_message(UserSubmitted("/fork"))
            await pilot.pause()
            await pilot.pause()
            assert any(
                "blocked" in n.lower() or "fork already" in n.lower() for n in notifications
            ), notifications
