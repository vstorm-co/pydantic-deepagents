"""Tests for CLI smart tool display formatting."""

from __future__ import annotations

from cli.tool_display import (
    _abbreviate_path,
    _truncate,
    format_tool_call,
    format_tool_result,
    render_tool_call,
    render_tool_result,
)


class TestAbbreviatePath:
    """Tests for _abbreviate_path()."""

    def test_short_relative_path(self) -> None:
        result = _abbreviate_path("test.py")
        assert result == "test.py"

    def test_basename_fallback(self) -> None:
        result = _abbreviate_path("/very/long/absolute/path/to/file.py", max_len=10)
        assert "file.py" in result

    def test_truncates_very_long_basename(self) -> None:
        long_name = "a" * 200 + ".py"
        result = _abbreviate_path(long_name, max_len=20)
        assert len(result) <= 20


class TestTruncate:
    """Tests for _truncate()."""

    def test_short_text(self) -> None:
        assert _truncate("hello") == "hello"

    def test_long_text(self) -> None:
        text = "x" * 200
        result = _truncate(text, 50)
        assert len(result) <= 50
        assert result.endswith("\u2026") or result.endswith("...")

    def test_exact_length(self) -> None:
        text = "x" * 120
        assert _truncate(text) == text


class TestFormatToolCall:
    """Tests for format_tool_call() per-tool formatters."""

    def test_read_file(self) -> None:
        result = format_tool_call("read_file", {"path": "/tmp/test.py"})
        assert "read_file" in result
        assert "test.py" in result

    def test_read_file_with_limit(self) -> None:
        result = format_tool_call("read_file", {"path": "/tmp/test.py", "limit": 50})
        assert "limit=50" in result

    def test_write_file(self) -> None:
        result = format_tool_call("write_file", {"path": "/tmp/test.py", "content": "a\nb\nc"})
        assert "write_file" in result
        assert "3 lines" in result

    def test_edit_file(self) -> None:
        result = format_tool_call("edit_file", {"path": "/tmp/test.py"})
        assert "edit_file" in result

    def test_execute(self) -> None:
        result = format_tool_call("execute", {"command": "python test.py"})
        assert "execute" in result
        assert "python test.py" in result

    def test_grep(self) -> None:
        result = format_tool_call("grep", {"pattern": "TODO", "path": "/src"})
        assert "grep" in result
        assert "TODO" in result

    def test_grep_no_path(self) -> None:
        result = format_tool_call("grep", {"pattern": "TODO"})
        assert 'grep("TODO")' == result

    def test_glob(self) -> None:
        result = format_tool_call("glob", {"pattern": "**/*.py"})
        assert "glob" in result
        assert "**/*.py" in result

    def test_ls(self) -> None:
        result = format_tool_call("ls", {"path": "."})
        assert "ls" in result

    def test_write_todos(self) -> None:
        result = format_tool_call("write_todos", {"todos": [1, 2, 3]})
        assert "3 items" in result

    def test_read_todos(self) -> None:
        result = format_tool_call("read_todos", {})
        assert "read_todos()" == result

    def test_web_search(self) -> None:
        result = format_tool_call("web_search", {"query": "python best practices"})
        assert "web_search" in result
        assert "python best practices" in result

    def test_save_checkpoint(self) -> None:
        result = format_tool_call("save_checkpoint", {"label": "milestone-1"})
        assert "milestone-1" in result

    def test_save_plan(self) -> None:
        result = format_tool_call("save_plan", {"name": "refactor-plan"})
        assert "refactor-plan" in result

    def test_ask_user(self) -> None:
        result = format_tool_call("ask_user", {"question": "Which approach?"})
        assert "ask_user" in result
        assert "Which approach?" in result

    def test_generic_fallback(self) -> None:
        result = format_tool_call("custom_tool", {"arg1": "val1", "arg2": "val2"})
        assert "custom_tool" in result
        assert "arg1=val1" in result

    def test_generic_truncates_many_args(self) -> None:
        result = format_tool_call("tool", {"a": "1", "b": "2", "c": "3", "d": "4", "e": "5"})
        assert "..." in result


class TestFormatToolResult:
    """Tests for format_tool_result()."""

    def test_read_file_lines(self) -> None:
        content = "line1\nline2\nline3"
        result = format_tool_result("read_file", content)
        assert "2 lines read" in result

    def test_execute_exit_code_0(self) -> None:
        result = format_tool_result("execute", "exit code 0")
        assert "exit code 0" in result

    def test_execute_nonzero_exit(self) -> None:
        result = format_tool_result("execute", "exit code 1: error occurred")
        assert "exit code" in result

    def test_grep_matches(self) -> None:
        content = "match1\nmatch2\nmatch3"
        result = format_tool_result("grep", content)
        assert "3 matches" in result

    def test_grep_no_matches(self) -> None:
        result = format_tool_result("grep", "")
        assert "0 matches" in result

    def test_write_file(self) -> None:
        result = format_tool_result("write_file", "ok")
        assert result == "done"

    def test_edit_file(self) -> None:
        result = format_tool_result("edit_file", "ok")
        assert result == "done"

    def test_write_todos(self) -> None:
        result = format_tool_result("write_todos", "ok")
        assert result == "updated"

    def test_read_todos(self) -> None:
        result = format_tool_result("read_todos", "Some todo content")
        assert "Some todo content" in result

    def test_unknown_tool(self) -> None:
        result = format_tool_result("custom", "some result text")
        assert "some result text" in result

    def test_long_result_truncated(self) -> None:
        result = format_tool_result("custom", "x" * 200)
        assert len(result) <= 60


class TestRenderToolCall:
    """Tests for render_tool_call() Rich markup output."""

    def test_returns_markup_string(self) -> None:
        result = render_tool_call("read_file", {"path": "/test.py"})
        assert "read_file" in result
        assert "[" in result  # Rich markup tags

    def test_with_custom_glyphs(self) -> None:
        from cli.theme import ASCII_GLYPHS

        result = render_tool_call("ls", {"path": "."}, glyphs=ASCII_GLYPHS)
        assert ASCII_GLYPHS.tool_prefix in result


class TestRenderToolResult:
    """Tests for render_tool_result() Rich markup output."""

    def test_returns_markup_string(self) -> None:
        result = render_tool_result("read_file", "content\nline2")
        # Now shows content preview instead of summary
        assert "content" in result
        assert "[" in result  # Rich markup tags

    def test_with_custom_glyphs(self) -> None:
        from cli.theme import ASCII_GLYPHS

        result = render_tool_result("write_file", "ok", glyphs=ASCII_GLYPHS)
        assert ASCII_GLYPHS.output_prefix in result
