"""Merge picker modal — opens on ``/merge`` to pick a winning branch.

Renders the :class:`BranchDiffReport` as a side-by-side per-branch
summary: status, list of touched paths, and the first few diff lines
per path. Two ways to pick:

- **Arrow navigation** — ``←`` / ``→`` (or ``h`` / ``l``) move the
  highlight between panels; ``Enter`` picks the highlighted one.
- **Number shortcut** — ``1``-``9`` pick the corresponding branch
  directly; the 10-branch case uses arrow nav.

Returns the chosen branch id or ``None`` on cancel.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from pydantic_deep.types import BranchChange, BranchDiffReport, BranchStatus

_DIFF_PREVIEW_LINES = 14


@dataclass(frozen=True)
class MergePickerResult:
    """Result of :class:`MergePickerModal` — the chosen branch id."""

    branch_id: str


class MergePickerModal(ModalScreen["MergePickerResult | None"]):
    """Pick the winner of an active fork.

    Bindings ``1``–``9`` pick the corresponding branch panel directly;
    for more than 9 branches, arrow navigation is the primary method.
    """

    DEFAULT_CSS = """
    MergePickerModal {
        align: center middle;
    }
    MergePickerModal > #merge-container {
        width: 100;
        max-height: 36;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    MergePickerModal > #merge-container > #merge-title {
        height: 1;
        text-style: bold;
    }
    MergePickerModal > #merge-container > #merge-meta {
        height: auto;
        color: $text-muted;
        margin: 0 0 1 0;
    }
    MergePickerModal > #merge-container > #merge-verdict {
        height: auto;
        color: $accent;
        margin: 0 0 1 0;
    }
    MergePickerModal > #merge-container > #merge-panels {
        height: 1fr;
    }
    MergePickerModal .merge-panel {
        width: 1fr;
        padding: 1;
        border: round $surface-lighten-2;
    }
    /* Focus ring — applied to the panel whose index matches
     * ``_selected_index``. ``$accent`` is the standard "this is what
     * Enter will pick" colour used elsewhere in the TUI. */
    MergePickerModal .merge-panel.selected {
        border: round $accent;
    }
    MergePickerModal .merge-panel-header {
        text-style: bold;
        height: 1;
    }
    MergePickerModal .merge-path {
        margin: 1 0 0 0;
    }
    MergePickerModal .merge-diff {
        color: $text-muted;
    }
    MergePickerModal .merge-empty {
        color: $text-disabled;
    }
    MergePickerModal > #merge-container > #merge-actions {
        height: 1;
        margin: 1 0 0 0;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("left,h", "move_prev", "Prev branch"),
        Binding("right,l", "move_next", "Next branch"),
        Binding("enter", "pick_selected", "Pick highlighted"),
        Binding("o", "open_in_editor", "Open in editor"),
        Binding("1", "pick_by_index(0)", "Pick 1", show=False),
        Binding("2", "pick_by_index(1)", "Pick 2", show=False),
        Binding("3", "pick_by_index(2)", "Pick 3", show=False),
        Binding("4", "pick_by_index(3)", "Pick 4", show=False),
        Binding("5", "pick_by_index(4)", "Pick 5", show=False),
        Binding("6", "pick_by_index(5)", "Pick 6", show=False),
        Binding("7", "pick_by_index(6)", "Pick 7", show=False),
        Binding("8", "pick_by_index(7)", "Pick 8", show=False),
        Binding("9", "pick_by_index(8)", "Pick 9", show=False),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        report: BranchDiffReport,
        branches: list[BranchStatus],
        label_to_id: dict[str, str],
        *,
        on_open_in_editor: Any = None,
        preselected_branch_id: str | None = None,
        verdict_subtitle: str | None = None,
        view_only: bool = False,
    ) -> None:
        super().__init__()
        self._report = report
        self._branches = branches
        self._id_to_label: dict[str, str] = {bid: label for label, bid in label_to_id.items()}
        ordered: list[str] = []
        for label, bid in label_to_id.items():
            ordered.append(bid)
            self._id_to_label.setdefault(bid, label)
        for status in branches:
            if status.id not in ordered:
                ordered.append(status.id)
                self._id_to_label.setdefault(status.id, status.label)
        self._ordered_ids = ordered
        if preselected_branch_id is not None and preselected_branch_id in self._ordered_ids:
            self._selected_index = self._ordered_ids.index(preselected_branch_id)
        else:
            self._selected_index = 0
        self._on_open_in_editor = on_open_in_editor
        self._verdict_subtitle = verdict_subtitle
        self._view_only = view_only

    def compose(self) -> ComposeResult:
        title = "Browse diff" if self._view_only else "Resolve fork"
        with Vertical(id="merge-container"):
            yield Static(
                f"[bold]{title}[/bold] · {self._report.fork_id}",
                id="merge-title",
            )
            yield Static(
                f"touched paths: {self._report.summary.total_paths_touched}",
                id="merge-meta",
            )
            if self._verdict_subtitle is not None:
                yield Static(self._verdict_subtitle, id="merge-verdict")
            with Horizontal(id="merge-panels"):
                for slot, branch_id in enumerate(self._ordered_ids, start=1):
                    yield self._render_branch_panel(slot, branch_id)
            yield Static(self._action_hint(), id="merge-actions")

    def _action_hint(self) -> str:
        if self._view_only:
            return "[dim]←/→ navigate  ·  Esc close[/dim]"
        selected_label = (
            self._id_to_label.get(self._ordered_ids[self._selected_index], "?")
            if self._ordered_ids
            else "—"
        )
        return (
            f"[dim]←/→ navigate  ·  [/dim]"
            f"[bold reverse] Enter [/] pick [bold]{selected_label}[/bold]  "
            f"·  [dim]Esc cancel[/dim]"
        )

    def _render_branch_panel(self, slot: int, branch_id: str) -> Vertical:
        status = next((s for s in self._branches if s.id == branch_id), None)
        label = self._id_to_label.get(branch_id, branch_id)
        header = f"[{slot}] [bold]{label}[/bold]  ·  {status.state if status else '?'}"

        panel = Vertical(classes="merge-panel", id=f"merge-panel-{slot - 1}")
        if slot - 1 == self._selected_index:
            panel.add_class("selected")
        items: list[Any] = [Static(header, classes="merge-panel-header")]

        touched_changes = self._touched_changes_for(branch_id)
        if not touched_changes:
            items.append(Static("[dim]no changes[/dim]", classes="merge-empty"))
        else:
            for path, change in touched_changes:
                added, removed = _count_changes(change.unified_diff_vs_parent)
                stats = f"  ·  [green]+{added}[/green] [red]-{removed}[/red]"
                items.append(
                    Static(
                        f"[bold]{path}[/bold]  ·  {change.operation}{stats}",
                        classes="merge-path",
                    )
                )
                if change.unified_diff_vs_parent.strip():
                    items.append(_DiffPreview(change.unified_diff_vs_parent))

        scroll = VerticalScroll(*items)
        panel.compose_add_child(scroll)
        return panel

    def _touched_changes_for(self, branch_id: str) -> list[tuple[str, BranchChange]]:
        results: list[tuple[str, BranchChange]] = []
        for path_diff in self._report.paths:
            change = path_diff.branches.get(branch_id)
            if change is None or change.operation == "untouched":
                continue
            results.append((path_diff.path, change))
        return results

    def action_pick_selected(self) -> None:
        if self._view_only:
            self.dismiss(None)
            return
        if not self._ordered_ids:
            return
        self._dismiss_with(self._ordered_ids[self._selected_index])

    def action_pick_by_index(self, index: int) -> None:
        """Power-user shortcut: pick branch at ``index`` (0-based)."""
        if self._view_only:
            return
        if 0 <= index < len(self._ordered_ids):
            self._dismiss_with(self._ordered_ids[index])

    def _dismiss_with(self, branch_id: str) -> None:
        self.dismiss(MergePickerResult(branch_id=branch_id))

    def action_open_in_editor(self) -> None:
        """Delegate to the optional ``on_open_in_editor`` callback.

        Wired by :func:`_dispatch_merge` to call
        :class:`EditorDetector` against the currently-selected branch's
        materialised path. The callback (when supplied) takes the branch
        id; the dispatcher resolves it to the materialised file path.
        """
        callback = self._on_open_in_editor
        if callback is None:
            return
        if not self._ordered_ids:  # pragma: no cover - defensive
            return
        branch_id = self._ordered_ids[self._selected_index]
        with contextlib.suppress(Exception):  # pragma: no cover - defensive
            callback(branch_id)

    def action_move_prev(self) -> None:
        if not self._ordered_ids:
            return
        self._selected_index = (self._selected_index - 1) % len(self._ordered_ids)
        self._refresh_selection()

    def action_move_next(self) -> None:
        if not self._ordered_ids:
            return
        self._selected_index = (self._selected_index + 1) % len(self._ordered_ids)
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        """Re-apply the ``selected`` class to the active panel + redraw hint."""
        for i in range(len(self._ordered_ids)):
            try:
                panel = self.query_one(f"#merge-panel-{i}", Vertical)
            except Exception:  # pragma: no cover - defensive
                continue
            if i == self._selected_index:
                panel.add_class("selected")
            else:
                panel.remove_class("selected")
        with contextlib.suppress(Exception):  # pragma: no cover - defensive
            self.query_one("#merge-actions", Static).update(self._action_hint())

    def action_cancel(self) -> None:
        self.dismiss(None)


def _diff_preview(unified_diff: str, limit: int | None = _DIFF_PREVIEW_LINES) -> str:
    """Render a colourised, header-stripped preview of a unified diff.

    Drops the ``---``/``+++`` file-name headers (they're already shown above
    the snippet via the ``path`` row) so the entire ``limit`` budget goes to
    actual changes. ``limit=None`` renders all lines (used by the expanded
    state of :class:`_DiffPreview`). Colours: green for ``+``, red for ``-``,
    cyan for ``@@`` hunk markers, dim for context.
    """
    from rich.markup import escape as _escape

    if not unified_diff.strip():
        return ""
    rendered: list[str] = []
    truncated = False
    for line in unified_diff.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        safe = _escape(line)
        if line.startswith("@@"):
            rendered.append(f"  [cyan]{safe}[/cyan]")
        elif line.startswith("+"):
            rendered.append(f"  [green]{safe}[/green]")
        elif line.startswith("-"):
            rendered.append(f"  [red]{safe}[/red]")
        else:
            rendered.append(f"  [dim]{safe}[/dim]")
        if limit is not None and len(rendered) >= limit:
            truncated = True
            break
    if truncated:
        rendered.append("  [dim]…[/dim]")
    return "\n".join(rendered)


def _meaningful_diff_lines(unified_diff: str) -> int:
    """Count diff lines that survive header stripping — used to decide expandability."""
    count = 0
    for line in unified_diff.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        count += 1
    return count


class _DiffPreview(Static):
    """Per-file diff snippet with click-to-expand toggle.

    Collapsed by default — shows ``_DIFF_PREVIEW_LINES`` meaningful lines and
    a ``(click to expand)`` hint when the underlying diff has more. Clicking
    swaps to the full diff with a ``(click to collapse)`` hint. Diffs that
    fit in the preview budget have no hint and ignore clicks.
    """

    DEFAULT_CSS = """
    _DiffPreview {
        color: $text-muted;
    }
    _DiffPreview.expandable {
        link-color: $accent;
    }
    """

    def __init__(self, unified_diff: str) -> None:
        self._diff = unified_diff
        self._expanded = False
        self._expandable = _meaningful_diff_lines(unified_diff) > _DIFF_PREVIEW_LINES
        super().__init__(self._compose_content(), classes="merge-diff")
        if self._expandable:
            self.add_class("expandable")

    def _compose_content(self) -> str:
        if self._expanded:
            body = _diff_preview(self._diff, limit=None)
            hint = "  [dim](click to collapse)[/dim]"
        else:
            body = _diff_preview(self._diff, limit=_DIFF_PREVIEW_LINES)
            hint = "  [dim](click to expand)[/dim]" if self._expandable else ""
        return body + ("\n" + hint if hint else "")

    def on_click(self) -> None:
        if not self._expandable:
            return
        self._expanded = not self._expanded
        self.update(self._compose_content())


def _count_changes(unified_diff: str) -> tuple[int, int]:
    """Count `+`/`-` lines (excluding the `+++`/`---` headers)."""
    added = removed = 0
    for line in unified_diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed
