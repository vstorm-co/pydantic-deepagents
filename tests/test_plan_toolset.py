"""Tests for the plan toolset helpers."""

from __future__ import annotations

from pydantic_deep.features.plan.toolset import _slugify_title


class TestSlugifyTitle:
    """Tests for _slugify_title used to build plan filenames."""

    def test_ascii_title(self) -> None:
        assert _slugify_title("Hello World!") == "hello-world"

    def test_non_latin_title_preserved(self) -> None:
        # Non-ASCII word characters must be kept rather than stripped to empty.
        result = _slugify_title("日本語のタイトル")
        assert result == "日本語のタイトル"
        assert result != "plan"

    def test_punctuation_only_falls_back_to_default(self) -> None:
        assert _slugify_title("!!!---") == "plan"

    def test_empty_title_falls_back_to_default(self) -> None:
        assert _slugify_title("") == "plan"

    def test_truncated_to_50_chars(self) -> None:
        assert _slugify_title("a" * 80) == "a" * 50
