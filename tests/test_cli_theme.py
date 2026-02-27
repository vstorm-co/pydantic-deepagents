"""Tests for CLI theme and glyph system."""

from __future__ import annotations

import pytest

from cli.theme import (
    ASCII_GLYPHS,
    DEFAULT_THEME,
    MINIMAL_THEME,
    UNICODE_GLYPHS,
    detect_unicode_support,
    get_glyphs,
    get_theme,
)


class TestGetTheme:
    """Tests for get_theme()."""

    def test_default_theme(self) -> None:
        theme = get_theme("default")
        assert theme is DEFAULT_THEME
        assert theme.primary == "#10b981"

    def test_minimal_theme(self) -> None:
        theme = get_theme("minimal")
        assert theme is MINIMAL_THEME
        assert theme.primary == "blue"

    def test_unknown_falls_back_to_default(self) -> None:
        theme = get_theme("nonexistent")
        assert theme is DEFAULT_THEME

    def test_none_uses_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_THEME", "minimal")
        theme = get_theme()
        assert theme is MINIMAL_THEME

    def test_none_defaults_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PYDANTIC_DEEP_THEME", raising=False)
        theme = get_theme()
        assert theme is DEFAULT_THEME

    def test_theme_has_all_fields(self) -> None:
        theme = get_theme()
        assert theme.primary
        assert theme.accent
        assert theme.success
        assert theme.warning
        assert theme.error
        assert theme.info
        assert theme.text
        assert theme.muted


class TestDetectUnicodeSupport:
    """Tests for detect_unicode_support()."""

    def test_env_override_unicode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "unicode")
        assert detect_unicode_support() is True

    def test_env_override_ascii(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "ascii")
        assert detect_unicode_support() is False

    def test_utf8_encoding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "auto")
        import sys

        original = sys.stdout
        mock_stdout = type("FakeStdout", (), {"encoding": "utf-8"})()
        monkeypatch.setattr("sys.stdout", mock_stdout)
        try:
            assert detect_unicode_support() is True
        finally:
            monkeypatch.setattr("sys.stdout", original)

    def test_lang_var_utf8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "auto")

        mock_stdout = type("FakeStdout", (), {"encoding": "ascii"})()
        monkeypatch.setattr("sys.stdout", mock_stdout)
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        assert detect_unicode_support() is True

    def test_lc_all_utf8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "auto")

        mock_stdout = type("FakeStdout", (), {"encoding": "ascii"})()
        monkeypatch.setattr("sys.stdout", mock_stdout)
        monkeypatch.delenv("LANG", raising=False)
        monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
        assert detect_unicode_support() is True

    def test_lc_ctype_utf8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "auto")

        mock_stdout = type("FakeStdout", (), {"encoding": "ascii"})()
        monkeypatch.setattr("sys.stdout", mock_stdout)
        monkeypatch.delenv("LANG", raising=False)
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.setenv("LC_CTYPE", "en_US.UTF-8")
        assert detect_unicode_support() is True

    def test_no_unicode_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "auto")

        mock_stdout = type("FakeStdout", (), {"encoding": "ascii"})()
        monkeypatch.setattr("sys.stdout", mock_stdout)
        monkeypatch.delenv("LANG", raising=False)
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_CTYPE", raising=False)
        assert detect_unicode_support() is False

    def test_no_encoding_attribute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "auto")

        mock_stdout = type("FakeStdout", (), {})()
        monkeypatch.setattr("sys.stdout", mock_stdout)
        monkeypatch.delenv("LANG", raising=False)
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_CTYPE", raising=False)
        assert detect_unicode_support() is False


class TestGetGlyphs:
    """Tests for get_glyphs()."""

    def test_returns_unicode_when_supported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "unicode")
        assert get_glyphs() is UNICODE_GLYPHS

    def test_returns_ascii_when_not_supported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYDANTIC_DEEP_CHARSET", "ascii")
        assert get_glyphs() is ASCII_GLYPHS


class TestGlyphValues:
    """Tests for glyph set values."""

    def test_unicode_glyphs_have_values(self) -> None:
        assert UNICODE_GLYPHS.tool
        assert UNICODE_GLYPHS.arrow
        assert UNICODE_GLYPHS.success
        assert UNICODE_GLYPHS.error
        assert UNICODE_GLYPHS.ellipsis
        assert UNICODE_GLYPHS.tool_prefix
        assert UNICODE_GLYPHS.output_prefix
        assert len(UNICODE_GLYPHS.spinner_frames) >= 4

    def test_ascii_glyphs_have_values(self) -> None:
        assert ASCII_GLYPHS.tool
        assert ASCII_GLYPHS.arrow
        assert ASCII_GLYPHS.success
        assert ASCII_GLYPHS.error
        assert ASCII_GLYPHS.ellipsis == "..."
        assert ASCII_GLYPHS.tool_prefix == "(*)"
        assert ASCII_GLYPHS.output_prefix == "|"
        assert len(ASCII_GLYPHS.spinner_frames) >= 4
