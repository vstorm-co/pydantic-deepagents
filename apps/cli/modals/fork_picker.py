"""Fork picker modal — opens on ``/fork`` to collect N branch specs.

One row per branch with a bold header, a ``Model:`` line (resolved from
``app.fork_branch_models[i]`` or the agent default), a label input, and
a steer input. Branch count, per-branch models, default budget, and the
aggregate cap all live on the persisted ``app.fork_*`` reactive state
and are configured through ``/fork-config``. The picker turns the
collected label/steer pairs into :class:`BranchSpec` instances and
bundles them in a :class:`apps.cli.forking.ForkPickerResult`.

There is intentionally no budget Input here — each branch's
``budget_usd`` is read from ``app.fork_branch_budgets[i]`` (configured
via ``/fork-config``); an empty slot means "no cap".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from apps.cli.forking import ForkPickerResult
from pydantic_deep.types import BranchSpec

if TYPE_CHECKING:
    from apps.cli.app import DeepApp


class ForkPickerModal(ModalScreen["ForkPickerResult | None"]):
    """Collect labels + steer messages for N branches.

    The modal reads :attr:`DeepApp.fork_branch_count`,
    :attr:`DeepApp.fork_aggregate_budget_usd`,
    :attr:`DeepApp.fork_branch_models`, and
    :attr:`DeepApp.fork_branch_budgets` at compose time. The number of rows
    is fixed for the lifetime of the modal.

    Returns:
        :class:`ForkPickerResult` on submit, or ``None`` on cancel.
    """

    DEFAULT_CSS = """
    ForkPickerModal {
        align: center middle;
    }
    ForkPickerModal > #fork-picker-container {
        width: 76;
        max-height: 85%;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    ForkPickerModal .fork-branch-group {
        height: auto;
        margin: 1 0 0 0;
        padding: 1;
        border: round $surface-lighten-2;
    }
    ForkPickerModal .fork-branch-model {
        color: $text-muted;
        margin: 0;
    }
    ForkPickerModal #fork-picker-error {
        height: auto;
        color: $error;
        margin: 1 0 0 0;
        display: none;
    }
    ForkPickerModal #fork-picker-error.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._branch_count: int = 0
        self._aggregate_budget: float | None = None
        self._branch_models: list[str | None] = []
        self._branch_budgets: list[float | None] = []
        self._agent_model: str = ""

    def _snapshot_app_state(self) -> None:
        """Read fork knobs off :class:`DeepApp` once at compose time."""
        app: DeepApp = self.app  # type: ignore[assignment]
        self._branch_count = max(1, int(app.fork_branch_count))
        self._aggregate_budget = app.fork_aggregate_budget_usd
        models = list(app.fork_branch_models)
        budgets = list(app.fork_branch_budgets)
        models = (models + [None] * self._branch_count)[: self._branch_count]
        budgets = (budgets + [None] * self._branch_count)[: self._branch_count]
        self._branch_models = models
        self._branch_budgets = budgets
        self._agent_model = str(getattr(app, "model_name", "")) or "default"

    def compose(self) -> ComposeResult:
        self._snapshot_app_state()
        with VerticalScroll(id="fork-picker-container"):
            yield Static("[bold]Fork the run[/bold]")
            yield Static(
                f"Spawn {self._branch_count} branches that share the parent's "
                "history up to this point.\nPick a short label per branch "
                "(used by `>>{label} <msg>` steering) and a first message "
                "that differentiates each branch."
            )
            for i in range(self._branch_count):
                yield from self._compose_branch_row(i)
            yield Static("", id="fork-picker-error")
            yield Static(
                "\n[dim]Tab to move between fields  ·  Enter to submit  ·  Esc to cancel[/dim]"
            )

    def _compose_branch_row(self, i: int) -> ComposeResult:
        override = self._branch_models[i]
        model_label = override if override is not None else f"(default: {self._agent_model})"
        with Vertical(classes="fork-branch-group"):
            yield Static(f"[bold]Branch {i + 1}[/bold]")
            yield Static(f"Model: {model_label}", classes="fork-branch-model")
            yield Input(placeholder="label (e.g. 'a')", id=f"branch-{i}-label")
            yield Input(placeholder="steer message…", id=f"branch-{i}-steer")

    def on_mount(self) -> None:
        self.query_one("#branch-0-label", Input).focus()

    def _input(self, suffix: str) -> Input:
        return self.query_one(f"#{suffix}", Input)

    def _read_branch_row(self, i: int) -> tuple[str, str]:
        return (
            self._input(f"branch-{i}-label").value.strip(),
            self._input(f"branch-{i}-steer").value.strip(),
        )

    def _show_error(self, message: str) -> None:
        error = self.query_one("#fork-picker-error", Static)
        error.update(message)
        error.add_class("visible")

    def action_submit(self) -> None:
        rows = [self._read_branch_row(i) for i in range(self._branch_count)]
        labels = [r[0] for r in rows]
        if not all(labels):
            self._show_error("Every branch label is required.")
            return
        if any(not r[1] for r in rows):
            self._show_error("Every branch steer is required.")
            return
        if len(set(labels)) != len(labels):
            self._show_error("Branch labels must be distinct.")
            return

        specs: list[BranchSpec] = []
        for i, (label, steer) in enumerate(rows):
            specs.append(
                BranchSpec(
                    label=label,
                    steer=steer,
                    model=self._branch_models[i],
                    budget_usd=self._branch_budgets[i],
                )
            )
        self.dismiss(ForkPickerResult(specs=specs, aggregate_budget_usd=self._aggregate_budget))

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Input submitted callback."""
        self.action_submit()

    def action_cancel(self) -> None:
        """Cancel action."""
        self.dismiss(None)
