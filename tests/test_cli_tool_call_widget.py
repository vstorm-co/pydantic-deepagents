"""Tests for the ToolCallWidget rendering (apps/cli/widgets/tool_call.py)."""

from __future__ import annotations

from rich.console import Group
from rich.syntax import Syntax

from apps.cli.widgets.tool_call import (
    _diff_lines,
    _discovered_tool_names,
    _format_args_preview,
    _highlight,
    _lang_for_path,
    _tool_icon,
)


def test_discovered_tool_names_json_and_repr() -> None:
    json_form = '{"discovered_tools": [{"name": "task"}, {"name": "check_task"}]}'
    repr_form = "{'discovered_tools': [{'name': 'task'}, {'name': 'fork_run'}]}"
    assert _discovered_tool_names(json_form) == ["task", "check_task"]
    assert _discovered_tool_names(repr_form) == ["task", "fork_run"]
    assert _discovered_tool_names("not a discovery result") == []


def test_search_tools_args_preview_shows_queries() -> None:
    out = _format_args_preview("search_tools", {"queries": ["subagent delegation"]})
    assert out == '"subagent delegation"'
    assert _format_args_preview("search_tools", {}) == ""


async def test_search_tools_preview_renders_chips_not_json() -> None:
    from textual.app import App, ComposeResult

    from apps.cli.widgets.tool_call import ToolCallWidget

    captured: dict[str, ToolCallWidget] = {}

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            w = ToolCallWidget("search_tools", {"queries": ["x"]}, "s1")
            captured["w"] = w
            yield w

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        w = captured["w"]
        w.complete("{'discovered_tools': [{'name': 'task'}, {'name': 'check_task'}]}", 0.0)
        await pilot.pause()
        preview = w.result_preview
        assert isinstance(preview, str)
        assert "discovered 2 tools" in preview
        assert "task" in preview and "check_task" in preview
        assert "discovered_tools" not in preview  # raw JSON not shown


def test_tool_icon_known_and_default() -> None:
    # One monochrome marker for every tool (cohesive minimalist theme).
    assert _tool_icon("execute") == "›"
    assert _tool_icon("read_file") == "›"
    assert _tool_icon("totally_unknown") == "›"


def test_lang_for_path_by_extension_name_and_unknown() -> None:
    assert _lang_for_path("/a/b/main.py") == "python"
    assert _lang_for_path("Component.TSX") == "typescript"
    assert _lang_for_path("/srv/Dockerfile") == "docker"
    assert _lang_for_path("Makefile") == "make"
    assert _lang_for_path("/notes/readme") is None
    assert _lang_for_path("/data/archive.bin") is None


def test_highlight_returns_syntax_with_code() -> None:
    syntax = _highlight("print('hi')", "python")
    assert isinstance(syntax, Syntax)
    assert "print" in syntax.code


def test_diff_lines_counts_and_colors() -> None:
    lines, added, removed = _diff_lines("a\nb\nc", "a\nB\nc", "")
    assert added == 1
    assert removed == 1
    assert any("[$error]- b" in line for line in lines)
    assert any("[$success]+ B" in line for line in lines)


def test_diff_lines_pure_insert() -> None:
    lines, added, removed = _diff_lines("", "x\ny", "")
    assert (added, removed) == (2, 0)
    assert all("[$success]+" in line for line in lines)


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
        preview = w.result_preview
        assert isinstance(preview, str)
        assert "[$error]- foo" in preview
        assert "[$success]+ bar" in preview


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
        exec_preview = captured["exec"].result_preview
        assert isinstance(exec_preview, str)
        assert "$ ls -la /tmp" in exec_preview
        assert "total 0" in exec_preview
        assert captured["write"]._added == 2
        # A new .py file renders as a syntax-highlighted Group, not text.
        from rich.console import Group
        from rich.syntax import Syntax

        preview = captured["write"].result_preview
        assert isinstance(preview, Group)
        syntax = next(r for r in preview.renderables if isinstance(r, Syntax))
        assert "line1" in syntax.code


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
        preview = w.result_preview
        assert isinstance(preview, str)
        assert "[$error]- # Python" in preview
        assert "[$success]+ # JavaScript" in preview
        assert "updated" in preview


async def test_widget_write_file_highlight_truncates_long_content() -> None:
    """A long new file highlights the head lines and notes the remainder."""
    from textual.app import App, ComposeResult

    from apps.cli.widgets.tool_call import ToolCallWidget

    captured: dict[str, ToolCallWidget] = {}
    body = "\n".join(f"x = {i}" for i in range(40))

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            w = ToolCallWidget("write_file", {"file_path": "/big.py", "content": body}, "w1")
            captured["w"] = w
            yield w

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        w = captured["w"]
        w.complete("wrote", 0.1)
        await pilot.pause()
        assert w._added == 40
        preview = w.result_preview
        assert isinstance(preview, Group)
        # head + syntax + "more added" tail
        assert any("more added" in str(getattr(r, "plain", "")) for r in preview.renderables)


async def test_widget_write_file_unknown_ext_falls_back_to_text() -> None:
    """Unknown extensions keep the plain green-+ text path (no highlighting)."""
    from textual.app import App, ComposeResult

    from apps.cli.widgets.tool_call import ToolCallWidget

    captured: dict[str, ToolCallWidget] = {}

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            w = ToolCallWidget(
                "write_file", {"file_path": "/notes.unknownext", "content": "a\nb"}, "w1"
            )
            captured["w"] = w
            yield w

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        w = captured["w"]
        w.complete("wrote", 0.1)
        await pilot.pause()
        assert isinstance(w.result_preview, str)
        assert "[$success]+ a" in w.result_preview


async def test_widget_subagent_write_keeps_text_nesting() -> None:
    """Subagent writes keep the line-prefixed text form for the nesting bar."""
    from textual.app import App, ComposeResult

    from apps.cli.widgets.tool_call import ToolCallWidget

    captured: dict[str, ToolCallWidget] = {}

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            w = ToolCallWidget(
                "write_file",
                {"file_path": "/sub.py", "content": "x = 1"},
                "w1",
                is_subagent_tool=True,
            )
            captured["w"] = w
            yield w

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        w = captured["w"]
        w.complete("wrote", 0.1)
        await pilot.pause()
        assert isinstance(w.result_preview, str)
        assert "│" in w.result_preview
        assert "[$success]+ x = 1" in w.result_preview


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
