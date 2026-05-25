"""Diff picker modal — choose which file + branches to send to the external diff tool.

Replaces the "type the path manually" UX of ``/fork diff <path>``: opens
a modal listing every touched path from :class:`BranchDiffReport` and lets
the user toggle which branches to include in the diff invocation. On
confirm, returns a :class:`DiffPickerResult` that the dispatcher feeds to
:meth:`EditorDetector.invoke`.

Navigation:

- ``↑`` / ``↓`` (or ``k`` / ``j``) move the path selection.
- ``←`` / ``→`` (or ``h`` / ``l``) move the branch selection.
- ``Space`` toggles the currently-selected branch.
- ``Enter`` confirms; ``Esc`` cancels.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from pydantic_deep.types import BranchDiffReport, BranchStatus


@dataclass(frozen=True)
class DiffPickerResult:
    """User choice from :class:`DiffPickerModal`.

    Attributes:
        path: Relative path to diff (one of the report's touched paths).
        branch_ids: Branch ids the user wants in the diff invocation,
            in the original ``label_to_id`` order. At least one entry
            (the modal forbids confirming with everything unchecked).
        include_parent: When ``True`` (default), the parent snapshot is
            passed to the editor alongside the branch files.  When
            ``False``, only the selected branch files are opened so the
            user sees a direct branch-vs-branch diff.
    """

    path: str
    branch_ids: list[str]
    include_parent: bool = True


class DiffPickerModal(ModalScreen["DiffPickerResult | None"]):
    """Pick a touched path + branches to feed into the external diff tool."""

    DEFAULT_CSS = """
    DiffPickerModal {
        align: center middle;
    }
    DiffPickerModal > #diff-container {
        width: 90;
        max-height: 30;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    DiffPickerModal #diff-title {
        height: 1;
        text-style: bold;
    }
    DiffPickerModal #diff-meta {
        height: auto;
        color: $text-muted;
        margin: 0 0 1 0;
    }
    DiffPickerModal #diff-paths {
        height: 1fr;
        border: round $surface-lighten-2;
        padding: 0 1;
    }
    DiffPickerModal .diff-path-row {
        height: 1;
    }
    DiffPickerModal .diff-path-row.selected {
        background: $accent 25%;
        color: $text;
    }
    DiffPickerModal #diff-branches {
        height: auto;
        margin: 1 0 0 0;
    }
    DiffPickerModal .diff-branch-chip {
        height: 1;
        width: auto;
        margin: 0 2 0 0;
    }
    DiffPickerModal .diff-branch-chip.focused {
        background: $accent 25%;
    }
    DiffPickerModal #diff-parent {
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
    }
    DiffPickerModal #diff-actions {
        height: 1;
        margin: 0 0 0 0;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("up,k", "move_path_up", "Prev file"),
        Binding("down,j", "move_path_down", "Next file"),
        Binding("left,h", "move_branch_prev", "Prev branch"),
        Binding("right,l", "move_branch_next", "Next branch"),
        Binding("space", "toggle_branch", "Toggle branch"),
        Binding("p", "toggle_parent", "Toggle parent"),
        Binding("m", "browse_merge_view", "Browse diff"),
        Binding("enter", "confirm", "Open diff"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        report: BranchDiffReport,
        branches: list[BranchStatus],
        label_to_id: dict[str, str],
        *,
        initial_branch_id: str | None = None,
    ) -> None:
        """Construct the modal.

        Args:
            report: Diff over the active fork — its ``paths`` list drives
                the path selector.
            branches: Branch statuses from ``CLIForkSession.inspect()`` —
                used to derive labels for branches missing from
                ``label_to_id``.
            label_to_id: Maps user-facing branch labels to coordinator
                branch ids; preserves the user's preferred branch order.
            initial_branch_id: When supplied (e.g. when launched from the
                merge picker's "Open in editor" button), only that branch
                is checked by default; otherwise every branch is checked.
        """
        super().__init__()
        self._report = report
        self._branches = branches
        self._id_to_label: dict[str, str] = {bid: label for label, bid in label_to_id.items()}
        ordered: list[str] = []
        for _label, bid in label_to_id.items():
            ordered.append(bid)
        for status in branches:
            if status.id not in ordered:
                ordered.append(status.id)
                self._id_to_label.setdefault(status.id, status.label)
        self._ordered_branch_ids = ordered

        self._paths: list[str] = [
            pd.path
            for pd in report.paths
            if any(c.operation != "untouched" for c in pd.branches.values())
        ]
        self._path_index = 0
        self._branch_index = 0
        if initial_branch_id is not None and initial_branch_id in ordered:
            self._enabled: dict[str, bool] = {bid: (bid == initial_branch_id) for bid in ordered}
        else:
            self._enabled = {bid: True for bid in ordered}
        self._include_parent: bool = True

    # ── Composition ───────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="diff-container"):
            yield Static(
                f"[bold]Open diff[/bold] · {self._report.fork_id}",
                id="diff-title",
            )
            yield Static(
                f"{len(self._paths)} touched path"
                f"{'s' if len(self._paths) != 1 else ''}  ·  "
                f"{len(self._ordered_branch_ids)} branch"
                f"{'es' if len(self._ordered_branch_ids) != 1 else ''}",
                id="diff-meta",
            )
            yield VerticalScroll(*self._render_path_rows(), id="diff-paths")
            with Horizontal(id="diff-branches"):
                for slot, bid in enumerate(self._ordered_branch_ids):
                    yield Static(
                        self._render_branch_chip(bid, slot == self._branch_index),
                        classes="diff-branch-chip",
                        id=f"diff-branch-{slot}",
                    )
            yield Static(self._render_parent_chip(), id="diff-parent")
            yield Static(self._render_action_hint(), id="diff-actions")

    def _render_path_rows(self) -> list[Static]:
        if not self._paths:
            return [Static("[dim]No touched paths — nothing to diff.[/dim]")]
        rows: list[Static] = []
        for i, path in enumerate(self._paths):
            row = Static(
                self._render_path_row(path),
                classes="diff-path-row",
                id=f"diff-path-{i}",
            )
            if i == self._path_index:
                row.add_class("selected")
            rows.append(row)
        return rows

    @staticmethod
    def _display_path(path: str) -> str:
        """Return a short, human-readable version of ``path``.

        Absolute paths under the current working directory are made
        relative; absolute paths outside CWD fall back to the basename.
        Relative paths are returned unchanged.
        """
        p = Path(path)
        if p.is_absolute():
            try:
                return str(p.relative_to(Path.cwd()))
            except ValueError:
                return p.name
        return path

    def _render_path_row(self, path: str) -> str:
        chunks: list[str] = []
        for path_diff in self._report.paths:
            if path_diff.path != path:
                continue
            for bid, change in path_diff.branches.items():
                if change.operation == "untouched":
                    continue
                label = self._id_to_label.get(bid, bid)
                chunks.append(f"[cyan]{label}[/cyan]({change.operation})")
        suffix = "  ·  " + " ".join(chunks) if chunks else ""
        return f"[bold]{self._display_path(path)}[/bold]{suffix}"

    def _render_branch_chip(self, bid: str, focused: bool) -> str:
        label = self._id_to_label.get(bid, bid)
        prefix = "" if self._enabled[bid] else "[red]✗[/red] "
        text = f"{prefix}{label}"
        return f"[bold reverse] {text} [/]" if focused else text

    def _render_parent_chip(self) -> str:
        if self._include_parent:
            return "[dim]parent: include  (p)[/dim]"
        return "[red]✗[/red][dim] parent: excluded  (p)[/dim]"

    def _render_action_hint(self) -> str:
        return (
            "[dim]↑/↓ file  ·  ←/→ branch  ·  Space toggle  ·  p parent  ·  "
            "m browse  ·  [/dim][bold reverse] Enter [/] open diff  "
            "[dim]·  Esc cancel[/dim]"
        )

    # ── Actions ───────────────────────────────────────────────────

    def action_move_path_up(self) -> None:
        if not self._paths:
            return
        self._path_index = (self._path_index - 1) % len(self._paths)
        self._refresh_paths()

    def action_move_path_down(self) -> None:
        if not self._paths:
            return
        self._path_index = (self._path_index + 1) % len(self._paths)
        self._refresh_paths()

    def action_move_branch_prev(self) -> None:
        if not self._ordered_branch_ids:
            return
        self._branch_index = (self._branch_index - 1) % len(self._ordered_branch_ids)
        self._refresh_branches()

    def action_move_branch_next(self) -> None:
        if not self._ordered_branch_ids:
            return
        self._branch_index = (self._branch_index + 1) % len(self._ordered_branch_ids)
        self._refresh_branches()

    def action_toggle_branch(self) -> None:
        if not self._ordered_branch_ids:
            return
        bid = self._ordered_branch_ids[self._branch_index]
        self._enabled[bid] = not self._enabled[bid]
        self._refresh_branches()

    def action_toggle_parent(self) -> None:
        self._include_parent = not self._include_parent
        self._refresh_parent_chip()

    def action_confirm(self) -> None:
        if not self._paths:
            self.dismiss(None)
            return
        chosen_branches = [bid for bid in self._ordered_branch_ids if self._enabled[bid]]
        if not chosen_branches:
            self._flash_actions("[red]Pick at least one branch (Space to toggle)[/red]")
            return
        self.dismiss(
            DiffPickerResult(
                path=self._paths[self._path_index],
                branch_ids=chosen_branches,
                include_parent=self._include_parent,
            )
        )

    def action_browse_merge_view(self) -> None:
        """Open :class:`MergePickerModal` in view-only mode for this fork."""
        from apps.cli.modals.merge_picker import MergePickerModal

        label_to_id = {label: bid for bid, label in self._id_to_label.items()}
        self.app.push_screen(
            MergePickerModal(
                self._report,
                self._branches,
                label_to_id,
                view_only=True,
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    # ── Internal helpers ──────────────────────────────────────────

    def _refresh_paths(self) -> None:
        for i in range(len(self._paths)):
            with contextlib.suppress(Exception):  # pragma: no cover - defensive
                row = self.query_one(f"#diff-path-{i}", Static)
                if i == self._path_index:
                    row.add_class("selected")
                else:
                    row.remove_class("selected")

    def _refresh_branches(self) -> None:
        for slot, bid in enumerate(self._ordered_branch_ids):
            with contextlib.suppress(Exception):  # pragma: no cover - defensive
                chip = self.query_one(f"#diff-branch-{slot}", Static)
                chip.update(self._render_branch_chip(bid, slot == self._branch_index))

    def _refresh_parent_chip(self) -> None:
        with contextlib.suppress(Exception):  # pragma: no cover - defensive
            chip = self.query_one("#diff-parent", Static)
            chip.update(self._render_parent_chip())

    def _flash_actions(self, text: str) -> None:
        """Temporarily replace the action hint with a warning."""
        with contextlib.suppress(Exception):  # pragma: no cover - defensive
            actions = self.query_one("#diff-actions", Static)
            actions.update(text)
            self.set_timer(2.0, lambda: actions.update(self._render_action_hint()))

    # ── Testing helpers ───────────────────────────────────────────

    @property
    def selected_path(self) -> str | None:
        """Path that ``Enter`` would currently confirm (or ``None`` if empty)."""
        return self._paths[self._path_index] if self._paths else None

    @property
    def enabled_branch_ids(self) -> list[str]:
        """Branch ids currently checked, preserving the original order."""
        return [bid for bid in self._ordered_branch_ids if self._enabled[bid]]

    @property
    def parent_included(self) -> bool:
        """Whether the parent file will be passed to the editor."""
        return self._include_parent


__all__ = ["DiffPickerModal", "DiffPickerResult"]
