"""Tests for AssistantMessage thinking display (apps/cli/widgets/assistant_message.py)."""

from __future__ import annotations

from apps.cli.widgets.assistant_message import (
    _THINKING_TAIL_LINES,
    AssistantMessage,
    _esc,
    _fmt_tokens,
    _linkify_bare_urls,
)


def test_esc_escapes_open_bracket() -> None:
    assert _esc("a [b] c") == r"a \[b] c"


def test_linkify_wraps_bare_urls_only() -> None:
    # Bare URL becomes a CommonMark autolink (renders as an OSC-8 hyperlink).
    assert _linkify_bare_urls("see https://x.com now") == "see <https://x.com> now"
    # Trailing sentence punctuation stays outside the link.
    assert _linkify_bare_urls("at https://x.com/p.") == "at <https://x.com/p>."
    # Existing markdown links and autolinks are left untouched.
    assert _linkify_bare_urls("[d](https://x.com)") == "[d](https://x.com)"
    assert _linkify_bare_urls("<https://x.com>") == "<https://x.com>"


def test_chat_screen_binds_copy_selection() -> None:
    from textual.binding import Binding

    from apps.cli.screens.chat import ChatScreen

    # BINDINGS items are typed as Binding | tuple; narrow to Binding before
    # reading .action/.key (they're all Binding(...) at runtime anyway).
    bindings = [b for b in ChatScreen.BINDINGS if isinstance(b, Binding)]
    actions = {b.action for b in bindings}
    keys = {b.key for b in bindings}
    assert "copy_text" in actions
    assert "ctrl+shift+c" in keys


def test_fmt_tokens_ranges() -> None:
    assert _fmt_tokens(500) == "500"
    assert _fmt_tokens(1200) == "1.2K"
    assert _fmt_tokens(150_000) == "150K"


def test_render_thinking_stream_empty_is_header_only() -> None:
    msg = AssistantMessage()
    assert msg._render_thinking_stream() == "[dim italic]💭 Thinking…[/dim italic]"


def test_render_thinking_stream_keeps_only_tail_lines() -> None:
    msg = AssistantMessage()
    msg._thinking = "\n".join(f"line {i}" for i in range(_THINKING_TAIL_LINES + 5))
    rendered = msg._render_thinking_stream()
    # The earliest lines are dropped; only the trailing window survives.
    assert "line 0" not in rendered
    assert f"line {_THINKING_TAIL_LINES + 4}" in rendered


def test_render_thinking_stream_skips_blank_lines_and_escapes() -> None:
    msg = AssistantMessage()
    msg._thinking = "first\n\n  \nweigh [option]"
    rendered = msg._render_thinking_stream()
    assert r"weigh \[option]" in rendered
    # The blank middle lines do not produce empty dim spans.
    assert rendered.count("💭") == 1


async def test_append_and_finalize_thinking_update_widget() -> None:
    from textual.app import App, ComposeResult

    captured: dict[str, AssistantMessage] = {}

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            m = AssistantMessage()
            captured["m"] = m
            yield m

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        m = captured["m"]
        assert m._thinking_widget is not None
        assert m._thinking_widget.display is False
        m.append_thinking("reasoning about the bug\n")
        m.append_thinking("checking the test")
        await pilot.pause()
        assert m._thinking_widget.display is True
        m.finalize_thinking()
        await pilot.pause()
        assert "Thought for 2 lines" in str(m._thinking_widget.render())


def test_finalize_thinking_singular_and_empty_noop() -> None:
    # No widget mounted → no-op, no error.
    msg = AssistantMessage()
    msg._thinking = "only one line"
    msg.finalize_thinking()
    # Empty thinking stays a no-op too.
    msg2 = AssistantMessage()
    msg2._thinking = "   "
    msg2.finalize_thinking()


async def test_finalize_thinking_singular_line_grammar() -> None:
    from textual.app import App, ComposeResult

    captured: dict[str, AssistantMessage] = {}

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            m = AssistantMessage()
            captured["m"] = m
            yield m

    app = _Harness()
    async with app.run_test() as pilot:
        await pilot.pause()
        m = captured["m"]
        m.append_thinking("single thought")
        await pilot.pause()
        m.finalize_thinking()
        await pilot.pause()
        assert m._thinking_widget is not None
        assert "Thought for 1 line" in str(m._thinking_widget.render())
