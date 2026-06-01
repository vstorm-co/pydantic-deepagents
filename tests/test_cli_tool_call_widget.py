"""Tests for the ToolCallWidget rendering (apps/cli/widgets/tool_call.py)."""

from __future__ import annotations

from apps.cli.widgets.tool_call import (
    _diff_lines,
    _format_args_preview,
    _tool_icon,
)


def test_tool_icon_known_and_default() -> None:
    assert _tool_icon("execute") == "⚡"
    assert _tool_icon("read_file") == "\U0001f4d6"
    assert _tool_icon("totally_unknown") == "◆"


def test_diff_lines_counts_and_colors() -> None:
    lines, added, removed = _diff_lines("a\nb\nc", "a\nB\nc", "")
    assert added == 1
    assert removed == 1
    assert any("[red]- b" in line for line in lines)
    assert any("[green]+ B" in line for line in lines)


def test_diff_lines_pure_insert() -> None:
    lines, added, removed = _diff_lines("", "x\ny", "")
    assert (added, removed) == (2, 0)
    assert all("[green]+" in line for line in lines)


def test_diff_lines_truncates_over_limit() -> None:
    old = "\n".join(f"old{i}" for i in range(30))
    new = "\n".join(f"new{i}" for i in range(30))
    lines, added, removed = _diff_lines(old, new, "", limit=12)
    assert added == 30
    assert removed == 30
    # 12 rendered + 1 truncation marker line.
    assert "more changed lines" in lines[-1]
    assert len(lines) == 13


def test_execute_preview_full_but_capped() -> None:
    short = _format_args_preview("execute", {"command": "pytest -q"})
    assert short == "pytest -q"
    long = _format_args_preview("execute", {"command": "echo " + "x" * 200})
    assert long.endswith("…")
    assert len(long) == 80


def test_execute_preview_collapses_newlines() -> None:
    out = _format_args_preview("execute", {"command": "echo a\n  echo b"})
    assert out == "echo a echo b"


async def test_widget_edit_diff_and_header_badge() -> None:
    """Mount a widget in a real app and verify diff + header badge render."""
    from textual.app import App, ComposeResult

    from apps.cli.widgets.tool_call import ToolCallWidget

    captured: dict[str, ToolCallWidget] = {}

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            w = ToolCallWidget(
                "edit_file",
                {"file_path": "/x.py", "old_string": "foo", "new_string": "bar\nbaz"},
                "c1",
            )
            captured["w"] = w
            yield w

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        w = captured["w"]
        w.complete("ok", 0.2, error=False)
        await pilot.pause()
        # difflib: 1 removed (foo) + 2 added (bar, baz)
        assert w._removed == 1
        assert w._added == 2
        assert "+2" in w._diff_badge()
        assert "-1" in w._diff_badge()
        assert "[red]- foo" in w.result_preview
        assert "[green]+ bar" in w.result_preview


async def test_widget_write_file_preview_and_execute_command() -> None:
    from textual.app import App, ComposeResult

    from apps.cli.widgets.tool_call import ToolCallWidget

    captured: dict[str, ToolCallWidget] = {}

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            wexec = ToolCallWidget("execute", {"command": "ls -la /tmp"}, "e1")
            wwrite = ToolCallWidget(
                "write_file", {"file_path": "/n.py", "content": "line1\nline2"}, "w1"
            )
            captured["exec"] = wexec
            captured["write"] = wwrite
            yield wexec
            yield wwrite

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        captured["exec"].complete("total 0\nfile.txt", 0.1)
        captured["write"].complete("wrote", 0.1)
        await pilot.pause()
        # Full command shown in body, not truncated.
        assert "$ ls -la /tmp" in captured["exec"].result_preview
        assert "total 0" in captured["exec"].result_preview
        assert captured["write"]._added == 2
        assert "[green]+ line1" in captured["write"].result_preview


async def test_widget_write_file_overwrite_shows_minus_diff() -> None:
    """Overwriting an existing file shows removed (-) and added (+) lines."""
    from textual.app import App, ComposeResult

    from apps.cli.widgets.tool_call import ToolCallWidget

    captured: dict[str, ToolCallWidget] = {}

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            w = ToolCallWidget(
                "write_file",
                {
                    "file_path": "/x.md",
                    "content": "# JavaScript\nnew line",
                    "_old_content": "# Python\nold line",
                },
                "w1",
            )
            captured["w"] = w
            yield w

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        w = captured["w"]
        w.complete("wrote", 0.1)
        await pilot.pause()
        assert w._removed >= 1
        assert w._added >= 1
        assert "[red]- # Python" in w.result_preview
        assert "[green]+ # JavaScript" in w.result_preview
        assert "updated" in w.result_preview


async def test_widget_mark_cancelling() -> None:
    from textual.app import App, ComposeResult

    from apps.cli.widgets.tool_call import ToolCallWidget

    captured: dict[str, ToolCallWidget] = {}

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            w = ToolCallWidget("execute", {"command": "sleep 10"}, "c1")
            captured["w"] = w
            yield w

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        w = captured["w"]
        assert w.status == "pending"
        w.mark_cancelling()
        await pilot.pause()
        assert w._cancelling is True
        # Completing afterwards still works.
        w.complete("interrupted", 0.1, error=True)
        await pilot.pause()
        assert w.status == "error"
        # mark_cancelling is a no-op once finished.
        w._cancelling = False
        w.mark_cancelling()
        assert w._cancelling is False
