"""Fork configuration modal — opens on `/fork-config`.

A settings modal that mutates :class:`apps.cli.app.DeepApp`'s `fork_*`
reactive state and writes the new values to `.pydantic-deep/config.toml`.
It does **not** spawn a fork — that's still :class:`ForkPickerModal`'s job,
opened via `/fork`.

The branch-count Input is the resizable anchor: committing a new value
(Enter on that Input) remounts the per-branch model rows, preserving the
typed values for slots that survive the resize and surfacing a
non-fatal warning if shrinking dropped any non-empty values.

On Save the modal validates everything, mutates the four `app.fork_*`
reactives, persists each via :func:`apps.cli.config.set_config_value`,
notifies success, and dismisses. Persistence failures are notified but
do not block dismissal — the in-memory reactive is the source of truth
for the rest of the session.

Per-branch budget overrides are NOT in this modal — the only budget
knobs are the *default per-branch budget* and the *aggregate cap*. If
a user wants to override a specific branch's budget for a single fork
they do it in the spawn picker (`/fork`) on a session-only basis.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from apps.cli.config import DEFAULT_CONFIG_PATH, set_config_value
from apps.cli.forking import resolve_capability
from apps.cli.modals.model_picker import ModelPickerModal
from pydantic_deep.models import DEFAULT_JUDGE_MODEL

if TYPE_CHECKING:
    from apps.cli.app import DeepApp


logger = logging.getLogger(__name__)

_DEFAULT_MAX_BRANCHES_FALLBACK = 10


def _resolve_ceiling(app: DeepApp) -> int:
    """Live `max_branches` cap; falls back to `10` without a capability."""

    cap = resolve_capability(app.agent) if app.agent is not None else None
    if cap is None:
        return _DEFAULT_MAX_BRANCHES_FALLBACK
    return cap.max_branches


def _persist(app: DeepApp, key: str, value: str) -> bool:
    """Write one fork CLI knob to `config.toml`; `notify` on error.

    Returns `True` on success, `False` on a swallowed exception. Mirrors
    the model-persistence pattern in `apps/cli/app.py:243`. The modal
    treats persistence failures as best-effort — the user's in-memory
    reactive state is already correct by the time we call this.
    """

    try:
        set_config_value(DEFAULT_CONFIG_PATH, key, value)
        return True
    except Exception as e:
        logger.warning("set_config_value(%s=%r) failed", key, value, exc_info=True)
        app.notify(f"Failed to save {key}: {e}", severity="warning")
        return False


class ForkConfigModal(ModalScreen[None]):
    """Form-style settings modal for `/fork` knobs.

    Reads :attr:`DeepApp.fork_branch_count`,
    :attr:`DeepApp.fork_default_budget_usd`,
    :attr:`DeepApp.fork_aggregate_budget_usd`, and
    :attr:`DeepApp.fork_branch_models` at compose time. On save, mutates
    each reactive and writes through to `.pydantic-deep/config.toml` via
    :func:`apps.cli.config.set_config_value`.

    Cancellation (`Esc`) dismisses without mutating any state.
    """

    DEFAULT_CSS = """
    ForkConfigModal {
        align: center middle;
    }
    ForkConfigModal > #fork-config-container {
        width: 80;
        max-height: 85%;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    ForkConfigModal .fork-config-field {
        height: auto;
        margin: 1 0 0 0;
    }
    /* `Vertical` defaults to `height: 1fr` which would eat the
     * outer `VerticalScroll`'s overflow. Force `auto` so children
     * stack to their natural height and the outer scroll engages. */
    ForkConfigModal #fork-config-rows {
        height: auto;
    }
    ForkConfigModal .fork-config-row {
        height: auto;
        margin: 1 0 0 0;
        padding: 1;
        border: round $surface-lighten-2;
    }
    ForkConfigModal .fork-config-model-btn {
        width: 100%;
        margin: 0;
    }
    ForkConfigModal #fork-config-error {
        height: auto;
        color: $error;
        margin: 1 0 0 0;
        display: none;
    }
    ForkConfigModal #fork-config-error.visible {
        display: block;
    }
    ForkConfigModal #fork-config-hint {
        height: auto;
        margin: 1 0 0 0;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    _STRATEGY_OPTIONS: list[tuple[str, str]] = [
        (
            "auto_with_fallback — judge picks; you confirm above threshold (default)",
            "auto_with_fallback",
        ),
        ("manual — always open the picker", "manual"),
        ("auto — judge picks and commits immediately", "auto"),
        ("vote — three judges vote, majority wins", "vote"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._branch_count: int = 1
        self._aggregate_budget: float | None = None
        self._branch_models: list[str | None] = []
        self._branch_budgets: list[float | None] = []
        self._agent_model: str = ""
        self._merge_strategy: str = "auto_with_fallback"
        self._judge_model: str = "anthropic:claude-haiku-4-5-20251001"
        self._confidence_threshold: float = 0.80

    def _snapshot_app_state(self) -> None:
        """Snapshot fork knobs off :class:`DeepApp` once at compose time."""
        app: DeepApp = self.app  # type: ignore[assignment]
        self._branch_count = max(1, int(app.fork_branch_count))
        self._aggregate_budget = app.fork_aggregate_budget_usd
        self._branch_models = self._pad(list(app.fork_branch_models), None)
        self._branch_budgets = self._pad(list(app.fork_branch_budgets), None)
        self._agent_model = str(getattr(app, "model_name", "")) or "default"
        self._merge_strategy = str(getattr(app, "fork_merge_strategy", "auto_with_fallback"))
        self._judge_model = str(getattr(app, "fork_judge_model", DEFAULT_JUDGE_MODEL))
        self._confidence_threshold = float(getattr(app, "fork_confidence_threshold", 0.80))

    def _pad(self, items: list, fill: object) -> list:
        """Pad/truncate `items` to `self._branch_count` slots."""
        if len(items) < self._branch_count:
            return items + [fill] * (self._branch_count - len(items))
        return items[: self._branch_count]

    # compose

    def compose(self) -> ComposeResult:
        self._snapshot_app_state()
        with VerticalScroll(id="fork-config-container"):
            yield Static("[bold]Fork configuration[/bold]")
            with Vertical(classes="fork-config-field"):
                yield Static("Branches (Enter on this field resizes rows)")
                yield Input(
                    placeholder="N (1–max)",
                    value=str(self._branch_count),
                    id="fork-config-count",
                )
            with Vertical(classes="fork-config-field"):
                yield Static("Aggregate cap (USD)")
                yield Input(
                    placeholder="(unset)",
                    value=self._fmt_float(self._aggregate_budget),
                    id="fork-config-aggregate",
                )
            with Vertical(classes="fork-config-field"):
                yield Static("Merge strategy")
                yield Select(
                    [(label, value) for label, value in self._STRATEGY_OPTIONS],
                    value=self._merge_strategy,
                    id="fork-config-strategy",
                )
            with Vertical(classes="fork-config-field"):
                yield Static("Judge model  [dim](for auto / auto_with_fallback)[/dim]")
                yield Button(
                    self._judge_model,
                    id="fork-config-judge-model-btn",
                    classes="fork-config-model-btn",
                )
            with Vertical(classes="fork-config-field"):
                yield Static("Confidence threshold  [dim](auto_with_fallback: 0.0–1.0)[/dim]")
                yield Input(
                    placeholder="0.80",
                    value=str(self._confidence_threshold),
                    id="fork-config-threshold",
                )
            with Vertical(id="fork-config-rows"):
                for i in range(self._branch_count):
                    yield self._build_branch_row(i, self._branch_models[i], self._branch_budgets[i])
            yield Static("", id="fork-config-error")
            yield Static(
                "[dim]Tab to move · Enter on a field saves · "
                "Enter on Branches resizes · Esc to cancel[/dim]",
                id="fork-config-hint",
            )

    def _build_branch_row(self, i: int, model: str | None, budget: float | None) -> Vertical:
        """Build one branch's model + budget row as a single widget tree.

        Returns a fully-constructed :class:`Vertical` (not a generator) so the
        same builder works both inside `compose()` and for dynamic
        `mount()` calls from :meth:`_maybe_resize_rows` — Textual's
        `with Container():` context manager requires the live compose
        stack, which only exists during the initial `compose()` pass.
        """
        return Vertical(
            Static(f"[bold]Branch {i + 1}[/bold]"),
            Static("Model"),
            Button(
                self._format_model_label(model),
                id=f"fork-config-model-btn-{i}",
                classes="fork-config-model-btn",
            ),
            Static("Budget (USD)"),
            Input(
                placeholder="(no cap)",
                value=self._fmt_float(budget),
                id=f"fork-config-budget-{i}",
            ),
            classes="fork-config-row",
        )

    def _format_model_label(self, model: str | None) -> str:
        return model if model else f"(default: {self._agent_model})"

    @staticmethod
    def _fmt_float(value: float | None) -> str:
        return "" if value is None else f"{value}"

    # focus management

    def on_mount(self) -> None:
        self.query_one("#fork-config-count", Input).focus()

    # input helpers

    def _input(self, suffix: str) -> Input:
        return self.query_one(f"#{suffix}", Input)

    def _input_or_none(self, suffix: str) -> Input | None:
        """Like :meth:`_input` but returns `None` instead of raising `NoMatches`.

        Per-branch rows mount asynchronously, so a row may not be present yet
        when Save fires — callers surface a friendly error rather than crashing.
        """
        with contextlib.suppress(NoMatches):
            return self.query_one(f"#{suffix}", Input)
        return None

    def _show_error(self, message: str) -> None:
        error = self.query_one("#fork-config-error", Static)
        error.update(message)
        error.add_class("visible")

    def _clear_error(self) -> None:
        error = self.query_one("#fork-config-error", Static)
        error.update("")
        error.remove_class("visible")

    def _parse_positive_float(self, raw: str) -> float | str:
        """Return `float` on success or an error message on failure."""
        try:
            value = float(raw)
        except ValueError:
            return f"Invalid number: {raw!r}"
        if value <= 0:
            return f"Must be positive, got {value}"
        return value

    # resize

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "fork-config-count":
            await self._maybe_resize_rows(event.input.value)
            return
        await self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Open the model picker for branch rows or the judge model button."""
        btn_id = event.button.id or ""
        if btn_id == "fork-config-judge-model-btn":
            self._open_judge_model_picker()
            return
        prefix = "fork-config-model-btn-"
        if not btn_id.startswith(prefix):
            return
        try:
            idx = int(btn_id[len(prefix) :])
        except ValueError:  # pragma: no cover - defensive
            return
        if idx < 0 or idx >= len(self._branch_models):  # pragma: no cover - defensive
            return
        self._open_model_picker_for(idx)

    def _open_judge_model_picker(self) -> None:
        """Push :class:`ModelPickerModal` and write the result back to the judge model button."""

        btn = self.query_one("#fork-config-judge-model-btn", Button)
        current = str(btn.label)

        def _on_pick(picked: str | None) -> None:
            if not picked:
                return
            btn.label = picked
            self._judge_model = picked

        self.app.push_screen(ModelPickerModal(current), _on_pick)

    def _open_model_picker_for(self, idx: int) -> None:
        """Push :class:`ModelPickerModal` and write the result back to slot `idx`."""

        current = self._branch_models[idx] or ""

        def _on_pick(picked: str | None) -> None:
            if not picked:
                return
            self._branch_models[idx] = picked
            btn = self.query_one(f"#fork-config-model-btn-{idx}", Button)
            btn.label = self._format_model_label(picked)

        self.app.push_screen(ModelPickerModal(current), _on_pick)

    async def _maybe_resize_rows(self, raw: str) -> None:
        try:
            new_n = int(raw)
        except ValueError:
            self._show_error(f"Invalid count: {raw!r}")
            return
        ceiling = _resolve_ceiling(self._app())
        if new_n < 1 or new_n > ceiling:
            self._show_error(f"N must be in [1, {ceiling}]")
            return

        old_n = self._branch_count
        keep_n = min(old_n, new_n)
        kept_models = list(self._branch_models[:keep_n])
        kept_budgets: list[float | None] = []
        for i in range(keep_n):
            raw_budget = self._input(f"fork-config-budget-{i}").value.strip()
            parsed = self._parse_positive_float(raw_budget) if raw_budget else None
            kept_budgets.append(parsed if isinstance(parsed, float) else None)

        truncated_models = sum(1 for m in self._branch_models[keep_n:old_n] if m)
        truncated_budgets = 0
        for i in range(keep_n, old_n):
            raw_b = self._input(f"fork-config-budget-{i}").value.strip()
            if raw_b:
                truncated_budgets += 1

        rows = self.query_one("#fork-config-rows", Vertical)
        await rows.remove_children()
        new_models: list[str | None] = []
        new_budgets: list[float | None] = []
        for i in range(new_n):
            model = kept_models[i] if i < keep_n else None
            budget = kept_budgets[i] if i < keep_n else None
            new_models.append(model)
            new_budgets.append(budget)
            await rows.mount(self._build_branch_row(i, model, budget))
        self._branch_count = new_n
        self._branch_models = new_models
        self._branch_budgets = new_budgets

        if truncated_models or truncated_budgets:
            self._show_error(
                f"Truncated {truncated_models} model override(s) and {truncated_budgets} budget(s)."
            )
        else:
            self._clear_error()

    def _read_judge_settings(self) -> tuple[str, str, float] | None:
        """Validate and return `(strategy, judge_model, threshold)` or `None` on error."""
        strategy_widget = self.query_one("#fork-config-strategy", Select)
        strategy_value = strategy_widget.value
        strategy = "auto_with_fallback" if strategy_value is Select.BLANK else str(strategy_value)

        judge_model = str(self.query_one("#fork-config-judge-model-btn", Button).label).strip()
        if not judge_model:
            judge_model = "anthropic:claude-haiku-4-5-20251001"
        if ":" not in judge_model:
            self._show_error(
                f"Judge model {judge_model!r} missing provider prefix "
                "(e.g. 'anthropic:claude-haiku-4-5' or 'openrouter:anthropic/claude-haiku-4-5')"
            )
            return None

        threshold_raw = self._input("fork-config-threshold").value.strip()
        threshold: float = 0.80
        if threshold_raw:
            try:
                threshold = float(threshold_raw)
            except ValueError:
                self._show_error(f"Confidence threshold: invalid number {threshold_raw!r}")
                return None
            if not 0.0 <= threshold <= 1.0:
                self._show_error("Confidence threshold must be in [0.0, 1.0]")
                return None
        return strategy, judge_model, threshold

    async def action_save(self) -> None:
        count_raw = self._input("fork-config-count").value.strip()
        ceiling = _resolve_ceiling(self._app())
        try:
            count = int(count_raw)
        except ValueError:
            self._show_error(f"Invalid count: {count_raw!r}")
            return
        if count < 1 or count > ceiling:
            self._show_error(f"N must be in [1, {ceiling}]")
            return
        if count != self._branch_count:
            await self._maybe_resize_rows(count_raw)
            if self._branch_count != count:
                return

        aggregate_raw = self._input("fork-config-aggregate").value.strip()
        aggregate_budget: float | None = None
        if aggregate_raw:
            parsed_agg = self._parse_positive_float(aggregate_raw)
            if isinstance(parsed_agg, str):
                self._show_error(f"Aggregate cap: {parsed_agg}")
                return
            aggregate_budget = parsed_agg

        models: list[str | None] = []
        for i in range(count):
            slot = self._branch_models[i] if i < len(self._branch_models) else None
            if not slot:
                models.append(None)
                continue
            if ":" not in slot:
                self._show_error(
                    f"Branch {i + 1} model {slot!r} missing provider prefix "
                    "(e.g. 'anthropic:claude-opus-4-6')"
                )
                return
            models.append(slot)

        budgets: list[float | None] = []
        for i in range(count):
            budget_input = self._input_or_none(f"fork-config-budget-{i}")
            if budget_input is None:
                # Row hasn't finished mounting (async mount race) — surface a
                # friendly error and abort Save instead of crashing on NoMatches.
                self._show_error(f"Branch {i + 1} row is still loading — try Save again.")
                return
            raw = budget_input.value.strip()
            if not raw:
                budgets.append(None)
                continue
            parsed_b = self._parse_positive_float(raw)
            if isinstance(parsed_b, str):
                self._show_error(f"Branch {i + 1} budget: {parsed_b}")
                return
            budgets.append(parsed_b)

        judge_settings = self._read_judge_settings()
        if judge_settings is None:
            return
        strategy, judge_model_raw, threshold = judge_settings

        app = self._app()
        app.fork_branch_count = count
        app.fork_aggregate_budget_usd = aggregate_budget
        app.fork_branch_models = models
        app.fork_branch_budgets = budgets
        app.fork_merge_strategy = strategy  # type: ignore[assignment]
        app.fork_judge_model = judge_model_raw
        app.fork_confidence_threshold = threshold

        _persist(app, "fork_branch_count", str(count))
        _persist(
            app,
            "fork_aggregate_budget_usd",
            "" if aggregate_budget is None else str(aggregate_budget),
        )
        _persist(
            app,
            "fork_branch_models",
            ",".join(m or "" for m in models),
        )
        _persist(
            app,
            "fork_branch_budgets",
            ",".join("" if b is None else str(b) for b in budgets),
        )
        _persist(app, "fork_merge_strategy", strategy)
        _persist(app, "fork_judge_model", judge_model_raw)
        _persist(app, "fork_confidence_threshold", str(threshold))
        app.notify("Fork config saved")
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    # helpers

    def _app(self) -> DeepApp:
        return self.app  # type: ignore[return-value]


__all__ = ["ForkConfigModal"]
